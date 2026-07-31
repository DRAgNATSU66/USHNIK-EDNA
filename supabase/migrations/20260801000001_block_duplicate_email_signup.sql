-- Migration: 004 block password signup for an email already linked to Google
--
-- Without this, someone who already has a Google-linked account could sign
-- up again with email/password using the same address and end up with a
-- second, disconnected user_profiles row — their uploads/analyses/reviews
-- would silently split between two identities depending on which method
-- they used to log in.
--
-- The Google -> existing-password-account direction is handled in
-- application code (services/api/app/auth/router.py, google_exchange):
-- when no google_sub match exists yet, it looks up the email and attaches
-- google_sub to the existing password row instead of inserting a new one.
--
-- The password -> existing-Google-account direction can't be intercepted
-- in application code, because supabase.auth.signUp() creates the
-- auth.users row directly against Supabase, before our backend is ever
-- called. So it's blocked here, at the trigger that fires on that insert:
-- if a user_profiles row already exists for this email with a non-null
-- google_sub, raise an exception. Postgres trigger exceptions roll back
-- the whole transaction, so the auth.users insert itself fails and
-- signUp() returns an error — no duplicate row is ever created.

create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
declare
  v_existing_google_sub text;
begin
  select google_sub into v_existing_google_sub
  from public.user_profiles
  where lower(email) = lower(new.email) and google_sub is not null
  limit 1;

  if v_existing_google_sub is not null then
    raise exception 'EMAIL_LINKED_TO_GOOGLE: This email is already registered with Google sign-in. Please continue with Google instead.';
  end if;

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
