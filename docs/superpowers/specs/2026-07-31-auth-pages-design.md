# Auth Pages Rebuild (Login / Signup / Password Reset)

## Overview

Replace the current Google-only sign-in embedded inside `Landing.jsx` with a
dedicated auth system: `/login`, `/signup`, `/forgot-password`, and
`/reset-password` pages, built from a provided visual design
(`frontend_zips_claude_design/EDNA Login Page Design.zip`, extracted design
file `Auth Login.dc.html`), ported near-pixel-exact into React and recolored
from its original light theme to a dark theme. Both Google OAuth (existing)
and email/password (new, via Supabase Auth) are supported.

This dark-recolored version of the provided design is intended to become the
base visual language for the rest of the app in later, separate passes —
this spec covers only the auth pages.

## In scope

- `AuthLayout` shared shell + `HelixCanvas` animated background, ported from
  the `.dc.html` design almost exactly (same layout, spacing, typography,
  animation), background recolored from light/cream to dark.
- `/login` — Google OAuth + email/password sign-in.
- `/signup` — Google OAuth + email/password account creation.
- `/forgot-password` — request a password reset email.
- `/reset-password` — set a new password from the emailed link.
- Backend: one new endpoint to exchange a Supabase Auth session for the
  app's existing JWT, reusing the dormant `user_profiles` auto-create
  trigger.
- `Landing.jsx` loses its embedded `GoogleLogin` block, replaced with links
  to `/login` and `/signup`.

## Out of scope (separate specs later)

- Redesigning Landing, Dashboard, Upload, or any other existing page.
- Enforcing email verification before first login (Supabase sends the
  verification email; sign-in is not blocked on it yet).
- Reconciling the app-wide color palette / design system across all pages —
  explicitly deferred; pages will be built separately and unified later.

## Current state (for context)

- `web_frontend/src/pages/Landing.jsx` embeds a `GoogleLogin` button and
  calls `useAuth().loginWithGoogle`.
- `web_frontend/src/contexts/AuthContext.jsx` stores `sv_access_token` /
  `sv_user_profile` in `localStorage`, exposes `loginWithGoogle`, `logout`.
- `web_frontend/src/lib/api.js` is a thin fetch wrapper; `authGoogleExchange`
  hits `POST /auth/google/exchange`.
- Backend auth lives in `services/api/app/auth/` (`router.py`, `google.py`,
  `jwt.py`, `deps.py`, `session.py`) — **not** the legacy
  `src/web_api/main.py`, which is an older, unrelated Mongo/Beanie stub.
- `services/api/app/models/user.py` — `UserProfile` has no password field.
- Supabase migration `20260731000001_decouple_user_profiles_from_auth.sql`
  deliberately decoupled `user_profiles.id` from `auth.users` **for the
  Google flow only**, because Google's `sub` isn't a UUID and no matching
  `auth.users` row exists for Google logins. The original
  `handle_new_user()` trigger (auto-inserts a `user_profiles` row when a
  real `auth.users` row is created) still exists and fires correctly for
  any real Supabase Auth signup — it has simply been unused because nothing
  has created real `auth.users` rows yet. Email/password signups will use
  this trigger as originally intended.
- No transactional email service is configured anywhere in the project.

## Architecture decision: Supabase Auth for email/password

Email/password auth is implemented using Supabase's built-in Auth (password
hashing, session issuance, email verification, password-reset emails) rather
than a hand-rolled `password_hash` column + custom email integration.
Rationale: no email-sending integration exists in this project today, and
Supabase Auth removes the need to write or security-review password storage
code. Google OAuth continues to use its existing custom-JWT flow unchanged;
the two paths converge on the same `user_profiles` table and the same app
JWT shape, so every existing protected route keeps working without change.

## Visual design

Source: `Auth Login.dc.html` (extracted from the provided zip). Ported
near-pixel-exact:

- Split-screen shell, `grid-template-columns: minmax(320px,500px) minmax(0,1fr)`,
  rounded 20px card, `Instrument Sans` font (Google Fonts import).
- **Left panel**: fixed across Login/Signup. Dark navy background with radial
  gradient accents, animated 2D `<canvas>` DNA helix (particle/web
  animation — ported verbatim from the design's inline script, no Three.js
  needed), "SYNTH VEDA" wordmark, headline + tagline (props-driven so Signup
  can show different copy), progress dots.
- **Right panel**: form content, swapped per page. Recolored from the
  design's light cream/white to a dark background consistent with the left
  panel — same pill-shaped buttons, soft borders, spacing, and the purple
  (`#6D5BD0`) / amber (`#F59E0B`) accents, just adapted for dark surfaces
  (light text, subtle light-on-dark borders/inputs instead of dark-on-white).
- Forgot/Reset password reuse `AuthLayout` with a simpler single-field form
  (no Google button, no OR divider).

## Frontend structure

New files:

- `web_frontend/src/components/auth/AuthLayout.jsx` — shared split-screen
  shell (left `HelixCanvas` + copy, right `children`).
- `web_frontend/src/components/auth/HelixCanvas.jsx` — canvas particle
  animation ported from the design's inline script into a
  `useRef`/`useEffect` React component.
- `web_frontend/src/pages/Login.jsx`
- `web_frontend/src/pages/Signup.jsx`
- `web_frontend/src/pages/ForgotPassword.jsx`
- `web_frontend/src/pages/ResetPassword.jsx`
- `web_frontend/src/lib/supabaseClient.js` — `@supabase/supabase-js` client
  using `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`.

Modified files:

- `web_frontend/src/contexts/AuthContext.jsx` — add `signUpWithPassword`,
  `loginWithPassword`, alongside existing `loginWithGoogle`. All three end
  by exchanging a token for the app JWT and persisting it the same way.
- `web_frontend/src/lib/api.js` — add
  `authSupabaseExchange(supabase_access_token)` → `POST /auth/supabase/exchange`.
- `web_frontend/src/main.jsx` — add public routes `/login`, `/signup`,
  `/forgot-password`, `/reset-password`.
- `web_frontend/src/pages/Landing.jsx` — remove embedded `GoogleLogin`
  block; add "Sign in" / "Get started" links to `/login` / `/signup`.
- `web_frontend/package.json` — add `@supabase/supabase-js`.
- `web_frontend/.env.example` — add `VITE_SUPABASE_URL`,
  `VITE_SUPABASE_ANON_KEY`.

## Backend structure

No new database tables — reuses `user_profiles` and the existing
`handle_new_user` trigger.

New:

- `services/api/app/auth/supabase_auth.py` — verifies a Supabase Auth access
  token via `client.auth.get_user(token)` on the existing server-side
  Supabase client (service-role key already configured; no new secret
  needed).
- `POST /auth/supabase/exchange` in `auth/router.py` — body
  `{ access_token: str }`. Verifies the token, looks up the
  trigger-created `user_profiles` row by id (small defensive retry if the
  trigger hasn't landed yet, mirroring the Google flow's tolerance for
  Supabase being unconfigured), mints the app JWT via the existing
  `create_access_token`, returns the same `TokenResponse` shape as
  `/auth/google/exchange`.

Modified:

- `services/api/app/db/supabase_client.py` — add `get_user_by_id(user_id)`.

Not needed:

- Any backend code for signup or password reset — both happen client-side
  via `supabase-js` (`signUp`, `signInWithPassword`,
  `resetPasswordForEmail`, `updateUser`). The service-role key stays
  server-only; client-side Supabase calls use the anon key, which is
  standard Supabase practice.
- Supabase dashboard config (not code, but required): set the password
  recovery redirect URL to `<frontend-url>/reset-password`.

## Flows

**Signup:** display name + email + password → `supabase.auth.signUp()` →
`handle_new_user` trigger creates `user_profiles` row → frontend calls
`authSupabaseExchange` with the session's access token → app JWT stored
(`sv_access_token`, same key as today) → redirect to `/dashboard`. The
Supabase project's "Confirm email" setting is left **off**, so `signUp()`
returns a session immediately — signup has the same one-step, no-friction
feel as the Google flow. Supabase still sends its standard welcome/
confirmation email in the background; it's just not a gate on first login,
matching the "no verification enforcement yet" decision above.

**Login (password):** `supabase.auth.signInWithPassword()` → exchange →
redirect to `/dashboard`. Invalid credentials surface Supabase's generic
"Invalid login credentials" message inline under the form — never reveal
whether the email exists.

**Login (Google):** unchanged; `loginWithGoogle` continues to call
`/auth/google/exchange` directly.

**Forgot password:** email → `resetPasswordForEmail()` → always show the
same "if that email exists, a reset link is on its way" message regardless
of whether the account exists, to avoid account enumeration.

**Reset password:** page loads with a recovery session established by
Supabase's client-side URL token detection → new-password form →
`updateUser({ password })` → exchange the now-active session for an app JWT
→ redirect to `/dashboard`.

**Error handling:** all flows reuse `AuthContext`'s existing `authError`
state and the app's existing inline error message styling. Backend
unreachable errors follow the same pattern already used elsewhere (e.g.
`Landing.jsx`'s existing Google-login error handling).

## Testing

- Backend: `services/api/tests/test_auth_supabase.py` (new) — mirrors
  `test_auth_phase3.py`'s style. Cases: valid token exchange mints a JWT
  with correct subject/role; invalid/expired token → 401; profile row
  missing at exchange time is tolerated (retry path).
- Frontend: manual verification via dev server — signup, login (both
  methods), forgot/reset password, and confirming `ProtectedRoute` still
  gates `/dashboard` etc. identically regardless of login method used.
