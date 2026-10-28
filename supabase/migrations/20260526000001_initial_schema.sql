-- Migration: 001 initial schema
-- Creates all Synth Veda structured tables in Supabase/Postgres.
-- MongoDB handles raw analysis documents. This schema handles:
--   auth, roles, reviews, curation, training batches, model versions, audit.

-- -----------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------
create extension if not exists "pgcrypto";

-- -----------------------------------------------------------------------
-- Enums
-- -----------------------------------------------------------------------
create type user_role as enum (
  'viewer',
  'researcher',
  'expert_contributor',
  'curator',
  'admin',
  'company_owner',
  'expedition_operator'
);

create type review_state as enum (
  'submitted',
  'triaged',
  'needs_evidence',
  'accepted',
  'rejected',
  'duplicate',
  'company_verified',
  'included_in_training_batch'
);

create type review_decision as enum (
  'accept',
  'reject',
  'needs_evidence',
  'mark_duplicate',
  'company_verify'
);

create type model_status as enum (
  'experimental',
  'staging',
  'production',
  'retired'
);

create type batch_status as enum (
  'assembling',
  'frozen',
  'training',
  'evaluated',
  'promoted',
  'rejected'
);

-- -----------------------------------------------------------------------
-- user_profiles
-- Mirrors auth.users — one row per Supabase auth user.
-- -----------------------------------------------------------------------
create table if not exists user_profiles (
  id              uuid primary key references auth.users(id) on delete cascade,
  email           text not null,
  display_name    text,
  role            user_role not null default 'researcher',
  created_at      timestamptz not null default now(),
  last_login      timestamptz
);

-- Auto-create profile on new auth signup via trigger
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.user_profiles (id, email, display_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name'),
    'researcher'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure handle_new_user();

-- -----------------------------------------------------------------------
-- admin_invite_keys
-- Company-issued 8-char alphanumeric keys hashed as SHA-256.
-- Never store plaintext keys. Rate-limiting enforced at API layer.
-- -----------------------------------------------------------------------
create table if not exists admin_invite_keys (
  id              uuid primary key default gen_random_uuid(),
  key_hash        text not null unique,   -- SHA-256 of raw 8-char key
  role_to_grant   user_role not null,
  created_by      uuid not null references user_profiles(id),
  max_uses        int not null default 1,
  uses_count      int not null default 0,
  expires_at      timestamptz not null,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now()
);

create index if not exists invite_keys_hash on admin_invite_keys(key_hash) where is_active = true;
create index if not exists invite_keys_created_by on admin_invite_keys(created_by);

-- RPC: consume an invite key atomically (avoids race on uses_count)
create or replace function consume_invite_key(p_key_id uuid, p_user_id uuid)
returns boolean language plpgsql security definer as $$
declare
  v_key admin_invite_keys;
begin
  select * into v_key
  from admin_invite_keys
  where id = p_key_id
    and is_active = true
    and expires_at > now()
    and uses_count < max_uses
  for update;

  if not found then
    return false;
  end if;

  update admin_invite_keys
  set uses_count = uses_count + 1,
      is_active  = (uses_count + 1 < max_uses)
  where id = p_key_id;

  return true;
end;
$$;

-- -----------------------------------------------------------------------
-- role_assignments
-- Full audit trail of every role grant/revoke.
-- -----------------------------------------------------------------------
create table if not exists role_assignments (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references user_profiles(id),
  role            user_role not null,
  granted_by      uuid not null references user_profiles(id),
  invite_key_id   uuid references admin_invite_keys(id),
  granted_at      timestamptz not null default now(),
  revoked_at      timestamptz,
  is_active       boolean not null default true
);

create index if not exists role_assignments_user_id on role_assignments(user_id) where is_active = true;

-- -----------------------------------------------------------------------
-- expert_reviews
-- Server-authoritative mirror of MongoDB reviews collection.
-- MongoDB stores the raw doc; Postgres stores the structured state for
-- queuing, RLS, and curation workflows.
-- -----------------------------------------------------------------------
create table if not exists expert_reviews (
  id                  uuid primary key default gen_random_uuid(),
  review_id           text not null unique,    -- matches MongoDB review_id (e.g. "rev_abc123")
  analysis_id         text not null,
  sequence_id         text not null,
  submitted_by        uuid not null references user_profiles(id),
  correction_type     text not null,
  proposed_taxon      text,
  is_novelty          boolean,
  is_contamination    boolean,
  is_low_quality      boolean,
  evidence_notes      text,
  state               review_state not null default 'submitted',
  decided_by          uuid references user_profiles(id),
  decision_notes      text,
  decided_at          timestamptz,
  created_at          timestamptz not null default now()
);

create index if not exists expert_reviews_analysis_id on expert_reviews(analysis_id);
create index if not exists expert_reviews_submitted_by on expert_reviews(submitted_by);
create index if not exists expert_reviews_state on expert_reviews(state);
create index if not exists expert_reviews_queue on expert_reviews(state, created_at asc)
  where state in ('submitted', 'triaged', 'needs_evidence');

-- -----------------------------------------------------------------------
-- review_evidence
-- Files, references, or URLs attached to a review by expert/contributor.
-- -----------------------------------------------------------------------
create table if not exists review_evidence (
  id              uuid primary key default gen_random_uuid(),
  review_id       uuid not null references expert_reviews(id) on delete cascade,
  submitted_by    uuid not null references user_profiles(id),
  evidence_type   text not null check (evidence_type in ('file', 'reference', 'url', 'text')),
  content         text,        -- URL or text content
  storage_key     text,        -- object storage key for uploaded files
  created_at      timestamptz not null default now()
);

create index if not exists review_evidence_review_id on review_evidence(review_id);

-- -----------------------------------------------------------------------
-- curation_decisions
-- Full log of every curator/admin decision on a review.
-- -----------------------------------------------------------------------
create table if not exists curation_decisions (
  id              uuid primary key default gen_random_uuid(),
  review_id       uuid not null references expert_reviews(id),
  curator_id      uuid not null references user_profiles(id),
  decision        review_decision not null,
  notes           text,
  decided_at      timestamptz not null default now()
);

create index if not exists curation_decisions_review_id on curation_decisions(review_id);
create index if not exists curation_decisions_curator_id on curation_decisions(curator_id);

-- -----------------------------------------------------------------------
-- curated_sequences
-- Clean, deduplicated sequences accepted for monthly training batches.
-- -----------------------------------------------------------------------
create table if not exists curated_sequences (
  id                  uuid primary key default gen_random_uuid(),
  sequence_id         text not null,          -- original FASTA sequence ID
  sequence            text not null,
  taxon               text not null,
  taxon_rank          text check (taxon_rank in ('species', 'genus', 'family', 'order', 'class', 'phylum')),
  ncbi_taxon_id       text,
  route               text not null,          -- fish / plant / bacteria_pathogen / etc.
  source              text not null check (source in ('expert_correction', 'reference_db', 'manual_curation')),
  quality_score       float check (quality_score between 0.0 and 1.0),
  curated_by          uuid not null references user_profiles(id),
  training_batch_id   uuid,                   -- set when included in a batch
  curated_at          timestamptz not null default now()
);

create index if not exists curated_sequences_route on curated_sequences(route);
create index if not exists curated_sequences_taxon on curated_sequences(taxon);
create index if not exists curated_sequences_batch on curated_sequences(training_batch_id) where training_batch_id is not null;

-- -----------------------------------------------------------------------
-- training_batches
-- Monthly training batch metadata. Actual sequence data in curated_sequences.
-- -----------------------------------------------------------------------
create table if not exists training_batches (
  id              uuid primary key default gen_random_uuid(),
  batch_id        text not null unique,       -- e.g. "batch_fish_2026_05"
  month_year      text not null,              -- "2026-05"
  route           text not null,
  status          batch_status not null default 'assembling',
  sequence_count  int not null default 0,
  created_by      uuid not null references user_profiles(id),
  frozen_at       timestamptz,
  created_at      timestamptz not null default now()
);

create index if not exists training_batches_route on training_batches(route);
create index if not exists training_batches_status on training_batches(status);
create index if not exists training_batches_month on training_batches(month_year);

-- Add FK from curated_sequences now that training_batches exists
alter table curated_sequences
  add constraint curated_sequences_batch_fk
  foreign key (training_batch_id) references training_batches(id)
  not valid;

-- -----------------------------------------------------------------------
-- training_batch_items
-- Junction table: which curated sequences are in which batch and split.
-- -----------------------------------------------------------------------
create table if not exists training_batch_items (
  id                    uuid primary key default gen_random_uuid(),
  batch_id              uuid not null references training_batches(id),
  curated_sequence_id   uuid not null references curated_sequences(id),
  split                 text not null check (split in ('train', 'val', 'test')),
  added_at              timestamptz not null default now(),
  unique (batch_id, curated_sequence_id)
);

create index if not exists batch_items_batch_id on training_batch_items(batch_id);
create index if not exists batch_items_split on training_batch_items(batch_id, split);

-- -----------------------------------------------------------------------
-- model_versions
-- Registry of every model version ever built. Immutable after insert.
-- -----------------------------------------------------------------------
create table if not exists model_versions (
  id                      uuid primary key default gen_random_uuid(),
  model_id                text not null unique,   -- e.g. "sv_fish_v3"
  route                   text not null,
  base_model              text not null,
  training_batch_id       uuid references training_batches(id),
  artifact_uri            text,
  checksum                text,
  metrics                 jsonb not null default '{}',
  thresholds              jsonb not null default '{}',
  status                  model_status not null default 'experimental',
  promoted_by             uuid references user_profiles(id),
  promoted_at             timestamptz,
  created_at              timestamptz not null default now()
);

create index if not exists model_versions_route on model_versions(route);
create index if not exists model_versions_status on model_versions(status);
create index if not exists model_versions_production on model_versions(route, status)
  where status = 'production';

-- -----------------------------------------------------------------------
-- model_eval_metrics
-- Per-eval-set metrics for each model version.
-- -----------------------------------------------------------------------
create table if not exists model_eval_metrics (
  id                      uuid primary key default gen_random_uuid(),
  model_version_id        uuid not null references model_versions(id),
  eval_set                text not null check (eval_set in ('val', 'test', 'regression')),
  f1                      float,
  precision               float,
  recall                  float,
  novelty_fpr             float,   -- false positive rate for novelty detection
  contamination_recall    float,
  latency_ms_p95          float,
  evaluated_at            timestamptz not null default now(),
  unique (model_version_id, eval_set)
);

create index if not exists eval_metrics_model on model_eval_metrics(model_version_id);

-- -----------------------------------------------------------------------
-- audit_logs
-- Append-only. Every privileged mutation writes here.
-- Service role only — never exposed directly to users via RLS.
-- -----------------------------------------------------------------------
create table if not exists audit_logs (
  id              uuid primary key default gen_random_uuid(),
  actor_id        uuid references user_profiles(id),
  actor_role      text not null,
  action          text not null,
  target_type     text not null,
  target_id       text not null,
  payload         jsonb not null default '{}',
  created_at      timestamptz not null default now()
);

create index if not exists audit_logs_actor on audit_logs(actor_id);
create index if not exists audit_logs_action on audit_logs(action);
create index if not exists audit_logs_target on audit_logs(target_type, target_id);
create index if not exists audit_logs_created_at on audit_logs(created_at desc);
