-- Migration: 002 Row Level Security policies
-- Enforces that users can only access data they are authorized to see.
-- Authorization source of truth is user_profiles.role — never user-editable metadata.

-- -----------------------------------------------------------------------
-- Helper: get the role of the current authenticated user
-- -----------------------------------------------------------------------
create or replace function current_user_role()
returns text language sql security definer stable as $$
  select role::text from public.user_profiles where id = auth.uid()
$$;

create or replace function is_admin_or_owner()
returns boolean language sql security definer stable as $$
  select current_user_role() in ('admin', 'company_owner')
$$;

create or replace function is_curator_or_above()
returns boolean language sql security definer stable as $$
  select current_user_role() in ('curator', 'admin', 'company_owner')
$$;

-- -----------------------------------------------------------------------
-- user_profiles
-- Users can read and update their own row.
-- Admins can read all rows. No one can insert directly (trigger handles it).
-- -----------------------------------------------------------------------
alter table user_profiles enable row level security;

create policy "users_read_own_profile"
  on user_profiles for select
  using (id = auth.uid() or is_admin_or_owner());

create policy "users_update_own_profile"
  on user_profiles for update
  using (id = auth.uid())
  with check (
    -- Users cannot escalate their own role
    role = (select role from user_profiles where id = auth.uid())
  );

create policy "admins_update_any_profile"
  on user_profiles for update
  using (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- admin_invite_keys
-- Only admins can read, create, or deactivate keys.
-- -----------------------------------------------------------------------
alter table admin_invite_keys enable row level security;

create policy "admins_manage_invite_keys"
  on admin_invite_keys for all
  using (is_admin_or_owner())
  with check (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- role_assignments
-- Only admins can read or write.
-- -----------------------------------------------------------------------
alter table role_assignments enable row level security;

create policy "admins_manage_role_assignments"
  on role_assignments for all
  using (is_admin_or_owner())
  with check (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- expert_reviews
-- Submitters can read their own reviews.
-- Curators and admins can read all and update state.
-- Anyone authenticated can insert (submit a review).
-- -----------------------------------------------------------------------
alter table expert_reviews enable row level security;

create policy "authenticated_submit_review"
  on expert_reviews for insert
  with check (auth.uid() is not null and submitted_by = auth.uid());

create policy "submitter_read_own_reviews"
  on expert_reviews for select
  using (submitted_by = auth.uid() or is_curator_or_above());

create policy "curators_update_review_state"
  on expert_reviews for update
  using (is_curator_or_above());

-- -----------------------------------------------------------------------
-- review_evidence
-- Submitter of the parent review can insert evidence.
-- Curators/admins can read all evidence.
-- -----------------------------------------------------------------------
alter table review_evidence enable row level security;

create policy "submitter_add_evidence"
  on review_evidence for insert
  with check (
    auth.uid() is not null
    and submitted_by = auth.uid()
    and exists (
      select 1 from expert_reviews er
      where er.id = review_evidence.review_id and er.submitted_by = auth.uid()
    )
  );

create policy "submitter_or_curator_read_evidence"
  on review_evidence for select
  using (
    submitted_by = auth.uid() or is_curator_or_above()
  );

-- -----------------------------------------------------------------------
-- curation_decisions
-- Only curators and admins can read or write.
-- -----------------------------------------------------------------------
alter table curation_decisions enable row level security;

create policy "curators_manage_decisions"
  on curation_decisions for all
  using (is_curator_or_above())
  with check (is_curator_or_above());

-- -----------------------------------------------------------------------
-- curated_sequences
-- Curators/admins can insert and update.
-- All authenticated users can read (needed for training export visibility).
-- -----------------------------------------------------------------------
alter table curated_sequences enable row level security;

create policy "authenticated_read_curated_sequences"
  on curated_sequences for select
  using (auth.uid() is not null);

create policy "curators_write_curated_sequences"
  on curated_sequences for insert
  with check (is_curator_or_above());

create policy "curators_update_curated_sequences"
  on curated_sequences for update
  using (is_curator_or_above());

-- -----------------------------------------------------------------------
-- training_batches
-- Admins can create and update batches.
-- Curators can read. Researchers cannot see batch internals.
-- -----------------------------------------------------------------------
alter table training_batches enable row level security;

create policy "curators_read_training_batches"
  on training_batches for select
  using (is_curator_or_above());

create policy "admins_manage_training_batches"
  on training_batches for insert
  with check (is_admin_or_owner());

create policy "admins_update_training_batches"
  on training_batches for update
  using (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- training_batch_items
-- Same as training_batches — curators read, admins write.
-- -----------------------------------------------------------------------
alter table training_batch_items enable row level security;

create policy "curators_read_batch_items"
  on training_batch_items for select
  using (is_curator_or_above());

create policy "admins_manage_batch_items"
  on training_batch_items for all
  using (is_admin_or_owner())
  with check (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- model_versions
-- All authenticated users can read (models are public within the platform).
-- Only admins can register or promote models.
-- -----------------------------------------------------------------------
alter table model_versions enable row level security;

create policy "authenticated_read_model_versions"
  on model_versions for select
  using (auth.uid() is not null);

create policy "admins_manage_model_versions"
  on model_versions for insert
  with check (is_admin_or_owner());

create policy "admins_update_model_versions"
  on model_versions for update
  using (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- model_eval_metrics
-- All authenticated users can read.
-- Only admins can write (inserted by training pipeline via service role).
-- -----------------------------------------------------------------------
alter table model_eval_metrics enable row level security;

create policy "authenticated_read_eval_metrics"
  on model_eval_metrics for select
  using (auth.uid() is not null);

create policy "admins_write_eval_metrics"
  on model_eval_metrics for insert
  with check (is_admin_or_owner());

-- -----------------------------------------------------------------------
-- audit_logs
-- No direct user access. Service role writes. Admins can read via service role.
-- Regular auth users have no access.
-- -----------------------------------------------------------------------
alter table audit_logs enable row level security;

create policy "admins_read_audit_logs"
  on audit_logs for select
  using (is_admin_or_owner());

-- No insert policy for regular users — service role bypasses RLS.
