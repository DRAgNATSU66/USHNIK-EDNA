-- Migration: 003 decouple user_profiles from Supabase Auth
--
-- The API verifies Google ID tokens itself and mints its own JWTs — it never
-- creates rows in auth.users. The original user_profiles.id FK to auth.users
-- made every login crash (Google's `sub` claim is a numeric string, not a
-- uuid, and no matching auth.users row exists anyway). Decouple: id becomes
-- a normal generated uuid, and google_sub is the lookup key for a Google
-- account.

alter table user_profiles drop constraint if exists user_profiles_id_fkey;
alter table user_profiles alter column id set default gen_random_uuid();

alter table user_profiles add column if not exists google_sub text unique;

create index if not exists user_profiles_google_sub on user_profiles(google_sub) where google_sub is not null;
