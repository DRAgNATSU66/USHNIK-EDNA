-- Dev seed: inserts test data for local development.
-- Run after migrations. Uses fixed UUIDs so re-running is idempotent.
-- DO NOT run against production.

-- -----------------------------------------------------------------------
-- Test users (matching the JWTs created by tests/conftest.py)
-- Insert directly into user_profiles (bypassing auth.users in local dev)
-- -----------------------------------------------------------------------
insert into user_profiles (id, email, display_name, role)
values
  ('00000000-0000-0000-0000-000000000001', 'test@example.com',    'Test Researcher',  'researcher'),
  ('00000000-0000-0000-0000-000000000002', 'admin@example.com',   'Test Admin',       'admin'),
  ('00000000-0000-0000-0000-000000000003', 'curator@example.com', 'Test Curator',     'curator'),
  ('00000000-0000-0000-0000-000000000004', 'expert@example.com',  'Test Expert',      'expert_contributor')
on conflict (id) do nothing;

-- -----------------------------------------------------------------------
-- Sample invite key (raw key: TESTKEY1, SHA-256 hash)
-- echo -n "TESTKEY1" | sha256sum => a2c9d2ee4... (pre-computed below)
-- -----------------------------------------------------------------------
insert into admin_invite_keys (id, key_hash, role_to_grant, created_by, max_uses, expires_at)
values (
  '00000000-0000-0000-0000-000000000010',
  encode(digest('TESTKEY1', 'sha256'), 'hex'),
  'expert_contributor',
  '00000000-0000-0000-0000-000000000002',
  5,
  now() + interval '30 days'
)
on conflict (key_hash) do nothing;

-- -----------------------------------------------------------------------
-- Sample model version (smoke-test placeholder)
-- -----------------------------------------------------------------------
insert into model_versions (id, model_id, route, base_model, status, metrics, thresholds)
values (
  '00000000-0000-0000-0000-000000000020',
  'sv_smoke_test_v0',
  'misc_unknown',
  'bert-base-uncased',
  'retired',
  '{"f1": 0.0, "note": "smoke test only — not a real DNA model"}',
  '{"min_confidence": 0.5}'
)
on conflict (model_id) do nothing;
