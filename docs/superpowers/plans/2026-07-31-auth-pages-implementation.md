# Auth Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/login`, `/signup`, `/forgot-password`, and `/reset-password` pages — ported near-pixel-exact from the provided `Auth Login.dc.html` design (dark-recolored) — backed by Supabase Auth for email/password while keeping the existing Google OAuth flow unchanged.

**Architecture:** Backend adds one new endpoint, `POST /auth/supabase/exchange`, that verifies a Supabase Auth session token and mints the app's existing JWT — reusing the dormant `handle_new_user` Postgres trigger, no new tables. Frontend adds a shared `AuthLayout`/`HelixCanvas` shell (ported from the design) plus four pages, all driving auth through extended `AuthContext` methods that end in the same JWT-persistence path as the existing Google flow.

**Tech Stack:** React 18 + Vite + react-router-dom v6 (frontend), FastAPI + Supabase (Python `supabase` client, already a dependency) (backend), `@supabase/supabase-js` (new frontend dependency).

## Global Constraints

- No new database tables or migrations — reuse `user_profiles` and the existing `handle_new_user` trigger.
- The Google OAuth flow (`loginWithGoogle`, `/auth/google/exchange`) must not change behavior.
- Every auth path (Google, email/password login, signup, password reset) must end by producing the same `TokenResponse` shape (`{ access_token, token_type, user }`) so `ProtectedRoute` and every existing protected page keep working unchanged.
- Supabase project's "Confirm email" setting must be OFF, so `supabase.auth.signUp()` returns a session immediately (per the design spec's decision to not gate first login on email verification).
- No backend code for password reset — `resetPasswordForEmail` / `updateUser` are client-side Supabase calls only.
- Source design file: `frontend_zips_claude_design/_extracted_login/Auth Login.dc.html` — layout, spacing, typography (Instrument Sans), and the canvas helix animation are ported as-is; only the right panel's light background is recolored to dark.
- No frontend automated test framework exists in this repo (`web_frontend/package.json` has no vitest/jest) — frontend tasks are verified manually via `npm run dev`, matching existing project convention. Backend tasks follow the existing pytest + `unittest.mock` convention (see `services/api/tests/test_auth_phase3.py`).

---

## Task 1: Backend — SupabaseClient auth-lookup methods

**Files:**
- Modify: `services/api/app/db/supabase_client.py`
- Test: `services/api/tests/test_supabase_client.py`

**Interfaces:**
- Produces: `SupabaseClient.get_user_by_id(user_id: str) -> dict | None` — fetches a `user_profiles` row by `id`.
- Produces: `SupabaseClient.get_auth_user(access_token: str) -> object | None` — verifies a Supabase Auth access token via Supabase itself and returns the resulting user object (has `.id` and `.email` attributes), or `None` if the token is invalid/expired.

- [ ] **Step 1: Write the failing tests**

Add to `services/api/tests/test_supabase_client.py` (after the existing `test_get_user_returns_none_on_empty` test):

```python
@pytest.mark.anyio
async def test_get_user_by_id_returns_profile():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.execute = AsyncMock(return_value=MagicMock(data={"id": "u1", "role": "researcher"}))

    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=chain)

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_user_by_id("u1")
    mock_client.table.assert_called_with("user_profiles")
    assert result == {"id": "u1", "role": "researcher"}


@pytest.mark.anyio
async def test_get_user_by_id_returns_none_on_empty():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.execute = AsyncMock(return_value=MagicMock(data=None))

    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=chain)

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_user_by_id("missing")
    assert result is None


@pytest.mark.anyio
async def test_get_auth_user_returns_user_on_success():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    fake_user = MagicMock(id="u1", email="a@b.com")
    mock_client = MagicMock()
    mock_client.auth = MagicMock()
    mock_client.auth.get_user = AsyncMock(return_value=MagicMock(user=fake_user))

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_auth_user("valid-token")
    assert result is fake_user


@pytest.mark.anyio
async def test_get_auth_user_returns_none_on_invalid_token():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    mock_client = MagicMock()
    mock_client.auth = MagicMock()
    mock_client.auth.get_user = AsyncMock(side_effect=Exception("invalid JWT"))

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_auth_user("bad-token")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/api && python -m pytest tests/test_supabase_client.py -v`
Expected: the four new tests FAIL with `AttributeError: get_user_by_id`/`get_auth_user`.

- [ ] **Step 3: Implement the methods**

In `services/api/app/db/supabase_client.py`, add these two methods to the `SupabaseClient` class, directly after the existing `update_last_login` method (after line 106, before the `# admin_invite_keys` section comment on line 108):

```python
    @staticmethod
    async def get_user_by_id(user_id: str) -> dict | None:
        client = SupabaseClient._get()
        res = (
            await client.table("user_profiles")
            .select("*")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return res.data if res else None

    @staticmethod
    async def get_auth_user(access_token: str):
        """
        Verify a Supabase Auth access token via Supabase's own /auth/v1/user
        endpoint and return the resulting user object (has .id and .email),
        or None if the token is invalid or expired.
        """
        client = SupabaseClient._get()
        try:
            res = await client.auth.get_user(access_token)
        except Exception:
            return None
        return res.user if res else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/api && python -m pytest tests/test_supabase_client.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/db/supabase_client.py services/api/tests/test_supabase_client.py
git commit -m "feat(auth): add SupabaseClient.get_user_by_id and get_auth_user"
```

---

## Task 2: Backend — Supabase Auth token verification

**Files:**
- Create: `services/api/app/auth/supabase_auth.py`
- Test: `services/api/tests/test_auth_supabase.py`

**Interfaces:**
- Consumes: `SupabaseClient.get_auth_user(access_token: str) -> object | None` (Task 1).
- Produces: `SupabaseAuthClaims` dataclass with fields `user_id: str`, `email: str`.
- Produces: `async def verify_supabase_access_token(access_token: str) -> SupabaseAuthClaims`, raises `ValueError` if the token is invalid/expired or Supabase is not configured.

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_auth_supabase.py`:

```python
"""
Tests for Supabase Auth access-token verification.
All external I/O (Supabase) is mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.anyio
async def test_verify_supabase_access_token_returns_claims():
    from app.auth.supabase_auth import verify_supabase_access_token

    fake_user = MagicMock(id="00000000-0000-0000-0000-000000000099", email="bob@example.com")
    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user", AsyncMock(return_value=fake_user)):
        claims = await verify_supabase_access_token("valid-token")

    assert claims.user_id == "00000000-0000-0000-0000-000000000099"
    assert claims.email == "bob@example.com"


@pytest.mark.anyio
async def test_verify_supabase_access_token_invalid_raises():
    from app.auth.supabase_auth import verify_supabase_access_token

    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="verification failed"):
            await verify_supabase_access_token("bad-token")


@pytest.mark.anyio
async def test_verify_supabase_access_token_not_configured_raises():
    from app.auth.supabase_auth import verify_supabase_access_token

    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        with pytest.raises(ValueError, match="not configured"):
            await verify_supabase_access_token("any-token")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/api && python -m pytest tests/test_auth_supabase.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.supabase_auth'`.

- [ ] **Step 3: Implement `supabase_auth.py`**

Create `services/api/app/auth/supabase_auth.py`:

```python
"""
Supabase Auth access-token verification.

Delegates to Supabase's own auth endpoint via the server-side client
(already configured with the service-role key) rather than verifying the
JWT signature locally — this avoids managing a second signing secret and
stays correct if Supabase rotates its signing key.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..db.supabase_client import SupabaseClient


@dataclass
class SupabaseAuthClaims:
    user_id: str   # auth.users.id (uuid) — same value as user_profiles.id
    email: str


async def verify_supabase_access_token(access_token: str) -> SupabaseAuthClaims:
    """
    Verify a Supabase Auth access token and return the extracted claims.

    Raises ValueError if the token is invalid, expired, or Supabase is not
    configured.
    """
    try:
        user = await SupabaseClient.get_auth_user(access_token)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    if user is None:
        raise ValueError("Supabase access token verification failed")

    return SupabaseAuthClaims(user_id=user.id, email=user.email)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/api && python -m pytest tests/test_auth_supabase.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/auth/supabase_auth.py services/api/tests/test_auth_supabase.py
git commit -m "feat(auth): add Supabase Auth access-token verification"
```

---

## Task 3: Backend — `/auth/supabase/exchange` endpoint

**Files:**
- Modify: `services/api/app/auth/router.py`
- Test: `services/api/tests/test_auth_supabase.py`

**Interfaces:**
- Consumes: `verify_supabase_access_token` and `SupabaseAuthClaims` (Task 2), `SupabaseClient.get_user_by_id` (Task 1), existing `SupabaseClient.update_last_login`, `create_access_token`, `TokenResponse`, `UserProfile`, `UserRole`.
- Produces: `POST /auth/supabase/exchange` — body `{ access_token: str }` → `TokenResponse` (same shape as `/auth/google/exchange`).

- [ ] **Step 1: Write the failing tests**

Append to `services/api/tests/test_auth_supabase.py`:

```python
from app.auth.supabase_auth import SupabaseAuthClaims


# ---------------------------------------------------------------------------
# /auth/supabase/exchange endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_supabase_exchange_with_valid_token(client):
    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000010", email="alice@example.com")
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id",
               AsyncMock(return_value={"id": fake_claims.user_id, "role": "researcher", "display_name": "Alice"})), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["role"] == "researcher"
    assert data["user"]["display_name"] == "Alice"


@pytest.mark.anyio
async def test_supabase_exchange_retries_once_if_profile_missing(client):
    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000011", email="new@example.com")
    profile_lookup = AsyncMock(side_effect=[None, {"id": fake_claims.user_id, "role": "researcher", "display_name": None}])
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id", profile_lookup), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()), \
         patch("app.auth.router.asyncio.sleep", AsyncMock()):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    assert profile_lookup.await_count == 2
    assert resp.json()["user"]["role"] == "researcher"


@pytest.mark.anyio
async def test_supabase_exchange_invalid_token_returns_401(client):
    with patch("app.auth.router.verify_supabase_access_token",
               AsyncMock(side_effect=ValueError("Supabase access token verification failed"))):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "bad-token"})

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_supabase_exchange_supabase_unavailable_still_works(client):
    """If the profile lookup is down, exchange still succeeds with default researcher role."""
    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000012", email="offline@example.com")
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "researcher"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/api && python -m pytest tests/test_auth_supabase.py -v`
Expected: the four new tests FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

In `services/api/app/auth/router.py`:

Add `import asyncio` as the first line of the file (before `import hashlib`), and add the import of the new verify function after the existing `from .google import verify_google_id_token` line:

```python
from .supabase_auth import verify_supabase_access_token
```

Add a new request model after `GoogleExchangeRequest` (after line 24):

```python
class SupabaseExchangeRequest(BaseModel):
    access_token: str
```

Add the new endpoint after the `google_exchange` function ends (after line 119, before the `# POST /auth/admin-key/redeem` comment block):

```python
# ---------------------------------------------------------------------------
# POST /auth/supabase/exchange
# ---------------------------------------------------------------------------

@router.post("/supabase/exchange", response_model=TokenResponse)
async def supabase_exchange(body: SupabaseExchangeRequest):
    """
    Exchange a Supabase Auth session access token (from client-side
    supabase-js signUp/signInWithPassword/updateUser) for a Synth Veda JWT.

    The `handle_new_user` Postgres trigger auto-creates the user_profiles
    row when Supabase Auth creates the underlying auth.users row, so by the
    time this runs the profile usually already exists. If it hasn't landed
    yet (trigger race on the very first request right after signup), retry
    once after a short delay before falling back to default researcher
    values — mirroring how /auth/google/exchange tolerates Supabase being
    unavailable.
    """
    try:
        claims = await verify_supabase_access_token(body.access_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    role = UserRole.researcher
    display_name = None
    try:
        profile = await SupabaseClient.get_user_by_id(claims.user_id)
        if profile is None:
            await asyncio.sleep(0.5)
            profile = await SupabaseClient.get_user_by_id(claims.user_id)
        if profile:
            role = UserRole(profile.get("role", UserRole.researcher))
            display_name = profile.get("display_name")
        await SupabaseClient.update_last_login(claims.user_id)
    except RuntimeError:
        pass

    user = UserProfile(
        user_id=claims.user_id,
        email=claims.email,
        display_name=display_name,
        role=role,
    )
    token = create_access_token(
        subject=user.user_id,
        extra={"email": user.email, "role": user.role, "name": user.display_name},
    )
    return TokenResponse(access_token=token, user=user)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/api && python -m pytest tests/test_auth_supabase.py tests/test_auth_phase3.py -v`
Expected: all tests PASS (including the pre-existing Google-flow tests, confirming no regression).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/auth/router.py services/api/tests/test_auth_supabase.py
git commit -m "feat(auth): add POST /auth/supabase/exchange endpoint"
```

---

## Task 4: Frontend — Supabase client setup

**Files:**
- Modify: `web_frontend/package.json`
- Create: `web_frontend/src/lib/supabaseClient.js`
- Modify: `web_frontend/.env.example`

**Interfaces:**
- Produces: `web_frontend/src/lib/supabaseClient.js` exports `supabase` — a configured `@supabase/supabase-js` client, or `null` if `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` are unset.

- [ ] **Step 1: Add the dependency**

In `web_frontend/package.json`, add this line to `dependencies`, alphabetically after `"@react-three/fiber": "^8.15.12",` and before `"axios": "^1.11.0",`:

```json
    "@supabase/supabase-js": "^2.45.4",
```

Run:
```bash
cd web_frontend && npm install
```
Expected: install completes, `@supabase/supabase-js` appears in `web_frontend/package-lock.json`.

- [ ] **Step 2: Create the Supabase client**

Create `web_frontend/src/lib/supabaseClient.js`:

```js
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env?.VITE_SUPABASE_URL || "";
const supabaseAnonKey = import.meta.env?.VITE_SUPABASE_ANON_KEY || "";

/**
 * Client-side Supabase instance, used only for Auth (signUp,
 * signInWithPassword, resetPasswordForEmail, updateUser). Never used for
 * direct table access — that stays server-side with the service-role key.
 * `null` when env vars are unset, so callers can show a clear "not
 * configured" error instead of crashing.
 */
export const supabase =
  supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null;
```

- [ ] **Step 3: Document the new env vars**

In `web_frontend/.env.example`, append after the existing `VITE_GOOGLE_CLIENT_ID=` line:

```
# Supabase project URL and anon (public) key, from Supabase dashboard →
# Project Settings → API. The anon key is safe to expose client-side.
# Leave blank to see a "Supabase is not configured" error on password
# sign-in/sign-up (Google OAuth still works without these).
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
```

- [ ] **Step 4: Verify it loads without error**

Run: `cd web_frontend && npm run build`
Expected: build succeeds (confirms `supabaseClient.js` has no syntax errors and the new dependency resolves).

- [ ] **Step 5: Commit**

```bash
git add web_frontend/package.json web_frontend/package-lock.json web_frontend/src/lib/supabaseClient.js web_frontend/.env.example
git commit -m "feat(auth): add Supabase client for email/password auth"
```

---

## Task 5: Frontend — AuthContext + api.js additions

**Files:**
- Modify: `web_frontend/src/lib/api.js`
- Modify: `web_frontend/src/contexts/AuthContext.jsx`

**Interfaces:**
- Consumes: `supabase` (Task 4).
- Produces (added to `useAuth()` return value): `loginWithPassword(email, password) -> Promise<user>`, `signUpWithPassword(email, password, displayName) -> Promise<user>`, `requestPasswordReset(email) -> Promise<void>`, `confirmPasswordReset(newPassword) -> Promise<user>`.
- Produces: `authSupabaseExchange(access_token: string) -> Promise<{access_token, token_type, user}>` in `lib/api.js`.

- [ ] **Step 1: Add `authSupabaseExchange` to `lib/api.js`**

In `web_frontend/src/lib/api.js`, add this line directly after the existing `authMe` export (after line 79):

```js
/** Exchange a Supabase Auth session access token for a Synth Veda JWT + user profile. */
export const authSupabaseExchange = (access_token) =>
  request("POST", "/auth/supabase/exchange", { body: { access_token } });
```

- [ ] **Step 2: Extend `AuthContext.jsx`**

In `web_frontend/src/contexts/AuthContext.jsx`, replace line 1-2:

```js
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { authGoogleExchange, authMe } from "../lib/api";
```

with:

```js
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { authGoogleExchange, authMe, authSupabaseExchange } from "../lib/api";
import { supabase } from "../lib/supabaseClient";
```

Insert the following after the existing `loginWithGoogle` function ends (after line 58, `}, []);`, before the `// On mount:` comment on line 60):

```js
  const _exchangeSupabaseSession = useCallback(async (session) => {
    if (!session) {
      throw new Error("No active session. Please try again.");
    }
    const data = await authSupabaseExchange(session.access_token);
    _persist(data.access_token, data.user);
    return data.user;
  }, []);

  /**
   * Sign in with email + password via Supabase Auth, then exchange the
   * resulting session for a Synth Veda JWT.
   */
  const loginWithPassword = useCallback(async (email, password) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message);
    return _exchangeSupabaseSession(data.session);
  }, [_exchangeSupabaseSession]);

  /**
   * Create an account with email + password via Supabase Auth. Throws a
   * "check your email" message (not a hard failure) if the project ever
   * requires email confirmation and no session comes back.
   */
  const signUpWithPassword = useCallback(async (email, password, displayName) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: displayName } },
    });
    if (error) throw new Error(error.message);
    if (!data.session) {
      throw new Error("Check your email to confirm your account, then sign in.");
    }
    return _exchangeSupabaseSession(data.session);
  }, [_exchangeSupabaseSession]);

  /** Request a password-reset email via Supabase Auth. */
  const requestPasswordReset = useCallback(async (email) => {
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    if (error) throw new Error(error.message);
  }, []);

  /**
   * Set a new password using the recovery session Supabase established
   * from the reset-link URL, then exchange it for a Synth Veda JWT.
   */
  const confirmPasswordReset = useCallback(async (newPassword) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
    if (updateError) throw new Error(updateError.message);
    const { data: sessionData } = await supabase.auth.getSession();
    if (!sessionData.session) {
      throw new Error("Reset link expired. Please request a new one.");
    }
    return _exchangeSupabaseSession(sessionData.session);
  }, [_exchangeSupabaseSession]);
```

Replace the provider's `value={{...}}` block (lines 86-99):

```js
      value={{
        user,
        token,
        loading,
        authError,
        isAuthenticated,
        isAdmin,
        isCurator,
        isExpeditionOp,
        loginWithGoogle,
        logout,
        setAuthError,
      }}
```

with:

```js
      value={{
        user,
        token,
        loading,
        authError,
        isAuthenticated,
        isAdmin,
        isCurator,
        isExpeditionOp,
        loginWithGoogle,
        loginWithPassword,
        signUpWithPassword,
        requestPasswordReset,
        confirmPasswordReset,
        logout,
        setAuthError,
      }}
```

- [ ] **Step 3: Verify it builds**

Run: `cd web_frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add web_frontend/src/lib/api.js web_frontend/src/contexts/AuthContext.jsx
git commit -m "feat(auth): add email/password auth methods to AuthContext"
```

---

## Task 6: Frontend — Shared auth shell + Login page

**Files:**
- Modify: `web_frontend/src/index.css`
- Create: `web_frontend/src/components/auth/authStyles.js`
- Create: `web_frontend/src/components/auth/HelixCanvas.jsx`
- Create: `web_frontend/src/components/auth/AuthLayout.jsx`
- Create: `web_frontend/src/pages/Login.jsx`
- Modify: `web_frontend/src/main.jsx`

**Interfaces:**
- Consumes: `loginWithGoogle`, `loginWithPassword` from `useAuth()` (Task 5).
- Produces: `authColors`, `authInputStyle`, `authLabelStyle`, `authLabelTextStyle`, `authPrimaryButtonStyle`, `authDividerStyle`, `authErrorStyle`, `authInfoStyle` (named exports from `authStyles.js`).
- Produces: `HelixCanvas` (default export, no props) — animated canvas DNA helix.
- Produces: `AuthLayout` (default export) — props `topRightPrompt: string`, `topRightLabel: string`, `topRightHref: string`, `children`.
- Produces: `/login` route.

- [ ] **Step 1: Add the font and animation keyframe**

In `web_frontend/src/index.css`, append after the existing content:

```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400..700;1,400&display=swap');

@keyframes sv-helix-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}
```

- [ ] **Step 2: Create shared auth styles**

Create `web_frontend/src/components/auth/authStyles.js`:

```js
export const authColors = {
  pageBg: "#05070C",
  cardBg: "#12141C",
  leftBg: "#0C1220",
  textPrimary: "#F5F5F3",
  textSecondary: "rgba(245,245,243,0.62)",
  textMuted: "rgba(245,245,243,0.45)",
  border: "rgba(245,245,243,0.14)",
  inputBg: "rgba(255,255,255,0.04)",
  accentPurple: "#8B7BE0",
  accentAmber: "#F59E0B",
  errorBg: "rgba(255,80,80,0.08)",
  errorBorder: "rgba(255,80,80,0.2)",
  errorText: "#FF9B9B",
  infoBg: "rgba(139,123,224,0.12)",
  infoBorder: "rgba(139,123,224,0.3)",
};

export const authInputStyle = {
  padding: "13px 16px",
  border: `1px solid ${authColors.border}`,
  borderRadius: 12,
  background: authColors.inputBg,
  fontFamily: "inherit",
  fontSize: "14.5px",
  color: authColors.textPrimary,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

export const authLabelStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 7,
};

export const authLabelTextStyle = {
  fontSize: 13,
  fontWeight: 500,
  color: authColors.textSecondary,
};

export const authPrimaryButtonStyle = {
  marginTop: 8,
  width: "100%",
  padding: "14px 0",
  border: "none",
  borderRadius: 999,
  background: authColors.textPrimary,
  color: authColors.leftBg,
  fontFamily: "inherit",
  fontSize: 15,
  fontWeight: 500,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
};

export const authDividerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  color: authColors.textMuted,
  fontSize: 12,
  letterSpacing: "0.08em",
};

export const authErrorStyle = {
  marginTop: 12,
  padding: "10px 14px",
  borderRadius: 8,
  fontSize: 13,
  textAlign: "center",
  background: authColors.errorBg,
  border: `1px solid ${authColors.errorBorder}`,
  color: authColors.errorText,
};

export const authInfoStyle = {
  marginTop: 12,
  padding: "10px 14px",
  borderRadius: 8,
  fontSize: 13,
  textAlign: "center",
  background: authColors.infoBg,
  border: `1px solid ${authColors.infoBorder}`,
  color: authColors.accentPurple,
};
```

- [ ] **Step 3: Port the helix canvas animation**

Create `web_frontend/src/components/auth/HelixCanvas.jsx` (ported verbatim from `Auth Login.dc.html`'s `initHelix` script, converted to a React component):

```jsx
import { useEffect, useRef } from "react";

const WIDTH = 430;
const HEIGHT = 500;

function rnd(i) {
  const x = Math.sin(i * 127.1) * 43758.5453;
  return x - Math.floor(x);
}

export default function HelixCanvas() {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    cv.width = WIDTH * dpr;
    cv.height = HEIGHT * dpr;
    ctx.scale(dpr, dpr);

    const N = 170, R = 100, cx = WIDTH / 2, coils = 2.6, PER = 0.55;
    const WEB = [];
    for (let i = 0; i < 46; i++) {
      WEB.push({ h: rnd(i * 3), ang: rnd(i * 5 + 1) * Math.PI * 2, rad: 1.15 + rnd(i * 7 + 2) * 0.75, seed: i });
    }
    const SAT = 4;

    const draw = (t) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.translate(WIDTH / 2, HEIGHT / 2);
      ctx.rotate(Math.PI / 6);
      ctx.scale(0.86, 0.86);
      ctx.translate(-WIDTH / 2, -HEIGHT / 2);
      ctx.globalCompositeOperation = "lighter";
      const rot = t * 0.00085;

      const pt = (i, phase, roff, yoff) => {
        const y = 20 + (i / (N - 1)) * (HEIGHT - 40) + (yoff || 0);
        const a = (i / (N - 1)) * coils * Math.PI * 2 + rot + phase;
        const rr = R * (1 + (roff || 0));
        const z = Math.cos(a);
        const persp = 1 + z * 0.001 * PER * 220;
        return { x: cx + Math.sin(a) * rr * (0.9 + 0.1 * persp), y, z, s: 0.75 + ((z + 1) / 2) * 0.55 };
      };

      for (let i = 3; i < N - 3; i += 5) {
        const p1 = pt(i, 0), p2 = pt(i, Math.PI);
        const d = (p1.z + p2.z + 2) / 4;
        ctx.strokeStyle = `rgba(70,180,225,${0.05 + 0.14 * d})`;
        ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
        const steps = 5;
        for (let k = 1; k < steps; k++) {
          const fx = p1.x + (p2.x - p1.x) * (k / steps), fy = p1.y + (p2.y - p1.y) * (k / steps);
          const a = 0.10 + 0.30 * d * (0.5 + rnd(i * 11 + k) * 0.5);
          ctx.fillStyle = `rgba(110,205,240,${a})`;
          ctx.beginPath(); ctx.arc(fx, fy, 0.9 + d * 0.9, 0, 7); ctx.fill();
        }
      }

      ctx.lineWidth = 0.5;
      for (let i = 0; i < N - 8; i += 4) {
        const s = rnd(i * 5) > 0.5 ? 0 : Math.PI;
        const p1 = pt(i, s), p2 = pt(i + 5 + Math.floor(rnd(i) * 6), s);
        const d = (p1.z + p2.z + 2) / 4;
        if (d < 0.45) continue;
        ctx.strokeStyle = `rgba(120,215,250,${0.05 + 0.10 * d})`;
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
      }

      const webP = WEB.map((w) => {
        const y = 20 + w.h * (HEIGHT - 40);
        const a = w.h * coils * Math.PI * 2 + rot + w.ang;
        const z = Math.cos(a) * Math.min(w.rad, 1.4);
        return { x: cx + Math.sin(a) * R * w.rad, y, z, seed: w.seed };
      });
      for (let i = 0; i < webP.length; i++) {
        const w1 = webP[i];
        const d1 = (w1.z + 1.4) / 2.8;
        let links = 0;
        for (let j = 0; j < webP.length && links < 2; j++) {
          if (j === i) continue;
          const w2 = webP[j];
          const dx = w1.x - w2.x, dy = w1.y - w2.y;
          const dist = Math.hypot(dx, dy);
          if (dist < 95) {
            const a = (0.03 + 0.09 * d1) * (1 - dist / 95);
            ctx.strokeStyle = `rgba(140,220,250,${a})`;
            ctx.lineWidth = 0.5;
            ctx.beginPath(); ctx.moveTo(w1.x, w1.y); ctx.lineTo(w2.x, w2.y); ctx.stroke();
            links++;
          }
        }
        const si = Math.round(((w1.y - 20) / (HEIGHT - 40)) * (N - 1));
        const sp = pt(Math.max(0, Math.min(N - 1, si)), rnd(w1.seed) > 0.5 ? 0 : Math.PI);
        const td = Math.hypot(w1.x - sp.x, w1.y - sp.y);
        if (td < 130) {
          ctx.strokeStyle = `rgba(110,205,245,${0.04 + 0.10 * d1 * (1 - td / 130)})`;
          ctx.lineWidth = 0.45;
          ctx.beginPath(); ctx.moveTo(w1.x, w1.y); ctx.lineTo(sp.x, sp.y); ctx.stroke();
        }
        const deep = rnd(w1.seed * 9) > 0.6;
        const col = deep ? "60,110,235" : "120,215,250";
        const nr = (deep ? 1.6 : 1.0) * (0.5 + d1);
        const ng = ctx.createRadialGradient(w1.x, w1.y, 0, w1.x, w1.y, nr * 3);
        ng.addColorStop(0, `rgba(${col},${0.25 + d1 * 0.55})`);
        ng.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = ng;
        ctx.beginPath(); ctx.arc(w1.x, w1.y, nr * 3, 0, 7); ctx.fill();
      }
      for (let i = 0; i < webP.length - 2; i += 5) {
        const a1 = webP[i], a2 = webP[i + 1], a3 = webP[i + 2];
        const dAvg = (a1.z + a2.z + a3.z + 4.2) / 8.4;
        if (dAvg < 0.55) continue;
        if (Math.hypot(a1.x - a2.x, a1.y - a2.y) > 110 || Math.hypot(a1.x - a3.x, a1.y - a3.y) > 110) continue;
        ctx.fillStyle = `rgba(100,200,245,${0.025 + 0.035 * dAvg})`;
        ctx.beginPath(); ctx.moveTo(a1.x, a1.y); ctx.lineTo(a2.x, a2.y); ctx.lineTo(a3.x, a3.y); ctx.closePath(); ctx.fill();
      }

      for (let s = 0; s < 2; s++) {
        const phase = s * Math.PI;
        for (let pass = 0; pass < 2; pass++) {
          for (let i = 0; i < N; i++) {
            const p = pt(i, phase);
            const depth = (p.z + 1) / 2;
            if (pass === 0 ? depth > 0.5 : depth <= 0.5) continue;
            const hue = s === 0 ? "155,228,255" : "75,195,245";
            const r = (1.0 + depth * 2.4) * p.s;
            const alpha = 0.16 + depth * 0.8;
            const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.4);
            g.addColorStop(0, `rgba(${hue},${alpha})`);
            g.addColorStop(0.35, `rgba(${hue},${alpha * 0.4})`);
            g.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(p.x, p.y, r * 3.4, 0, 7); ctx.fill();
            ctx.fillStyle = `rgba(225,248,255,${alpha * 0.9})`;
            ctx.beginPath(); ctx.arc(p.x, p.y, r * 0.5, 0, 7); ctx.fill();
            for (let k = 0; k < SAT; k++) {
              const seed = i * 13 + k * 31 + s * 97;
              const ox = (rnd(seed) - 0.5) * 26 * (0.4 + depth);
              const oy = (rnd(seed + 1) - 0.5) * 14;
              const sa = (0.05 + rnd(seed + 2) * 0.3) * (0.3 + depth * 0.7);
              ctx.fillStyle = `rgba(${hue},${sa})`;
              ctx.beginPath(); ctx.arc(p.x + ox, p.y + oy, 0.5 + rnd(seed + 3) * 1.3 * p.s, 0, 7); ctx.fill();
            }
            if (rnd(i * 3 + s * 7) > 0.94 && depth > 0.6) {
              const fr = 20 + rnd(i) * 14;
              const pulse = 0.7 + 0.3 * Math.sin(t * 0.002 + i);
              const fg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, fr);
              fg.addColorStop(0, `rgba(210,245,255,${0.6 * depth * pulse})`);
              fg.addColorStop(0.25, `rgba(90,200,250,${0.28 * depth * pulse})`);
              fg.addColorStop(1, "rgba(0,0,0,0)");
              ctx.fillStyle = fg;
              ctx.beginPath(); ctx.arc(p.x, p.y, fr, 0, 7); ctx.fill();
              ctx.strokeStyle = `rgba(230,250,255,${0.5 * depth * pulse})`;
              ctx.lineWidth = 0.7;
              const sl = 7 * pulse;
              ctx.beginPath();
              ctx.moveTo(p.x - sl, p.y); ctx.lineTo(p.x + sl, p.y);
              ctx.moveTo(p.x, p.y - sl); ctx.lineTo(p.x, p.y + sl);
              ctx.stroke();
            }
          }
        }
      }

      for (let i = 0; i < 110; i++) {
        const layer = i < 60 ? 0.4 : 1;
        const dx = (rnd(i) * WIDTH + t * 0.002 * layer * (rnd(i + 7) - 0.5) * 10 + WIDTH) % WIDTH;
        const dy = (rnd(i + 60) * HEIGHT + t * 0.005 * layer * (4 + rnd(i) * 10)) % HEIGHT;
        const tw = 0.5 + 0.5 * Math.sin(t * 0.003 + i * 2.7);
        const a = (0.04 + rnd(i + 120) * 0.2) * layer * tw;
        ctx.fillStyle = `rgba(130,215,245,${a})`;
        ctx.beginPath(); ctx.arc(dx, dy, (0.5 + rnd(i + 30) * 1.2) * layer, 0, 7); ctx.fill();
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: `${WIDTH}px`, height: `${HEIGHT}px`, display: "block", margin: "-30px 0", maxWidth: "100%" }}
    />
  );
}
```

- [ ] **Step 4: Build the shared layout shell**

Create `web_frontend/src/components/auth/AuthLayout.jsx`:

```jsx
import { Link } from "react-router-dom";
import HelixCanvas from "./HelixCanvas";
import { authColors } from "./authStyles";

export default function AuthLayout({ topRightPrompt, topRightLabel, topRightHref, children }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        boxSizing: "border-box",
        background: authColors.pageBg,
        fontFamily: "'Instrument Sans', system-ui, sans-serif",
      }}
    >
      <div
        style={{
          width: 1240,
          maxWidth: "100%",
          minHeight: 720,
          background: authColors.cardBg,
          borderRadius: 20,
          display: "grid",
          gridTemplateColumns: "minmax(320px,500px) minmax(0,1fr)",
          overflow: "hidden",
          boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
        }}
      >
        {/* Left: dark DNA panel */}
        <div
          style={{
            position: "relative",
            background: authColors.leftBg,
            color: authColors.textPrimary,
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "44px 44px 40px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "radial-gradient(90% 70% at 15% 100%, rgba(41,171,226,0.20) 0%, rgba(12,18,32,0) 60%), radial-gradient(70% 50% at 90% 8%, rgba(109,91,208,0.22) 0%, rgba(12,18,32,0) 55%)",
            }}
          />
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={authColors.accentAmber} strokeWidth="2" strokeLinecap="round" />
              <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={authColors.accentPurple} strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span style={{ fontWeight: 600, letterSpacing: "0.22em", fontSize: 13 }}>SYNTH VEDA</span>
          </div>
          <div style={{ position: "relative", alignSelf: "center", animation: "sv-helix-float 7s ease-in-out infinite" }}>
            <HelixCanvas />
          </div>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 14 }}>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: 1.18, fontWeight: 500, letterSpacing: "-0.02em" }}>
              Unravel the intricacies of your genetic code.
            </h1>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "rgba(245,245,243,0.62)", maxWidth: "36ch" }}>
              Precision eDNA sequencing and AI-driven analysis, from sample to insight.
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <span style={{ width: 22, height: 4, borderRadius: 2, background: authColors.accentPurple }} />
              <span style={{ width: 8, height: 4, borderRadius: 2, background: "rgba(245,245,243,0.25)" }} />
              <span style={{ width: 8, height: 4, borderRadius: 2, background: "rgba(245,245,243,0.25)" }} />
            </div>
          </div>
        </div>

        {/* Right: form */}
        <div style={{ display: "flex", flexDirection: "column", padding: "44px clamp(32px,7vw,96px) 36px", boxSizing: "border-box", minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, fontSize: 13, color: authColors.textMuted }}>
            <span>{topRightPrompt}</span>
            <Link
              to={topRightHref}
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "9px 20px",
                border: `1px solid ${authColors.border}`,
                borderRadius: 999,
                color: authColors.textPrimary,
                fontWeight: 500,
                textDecoration: "none",
              }}
            >
              {topRightLabel}
            </Link>
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 400, width: "100%", alignSelf: "center" }}>
            {children}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: authColors.textMuted }}>
            <span>© 2026 Synth Veda Labs</span>
            <div style={{ display: "flex", gap: 18 }}>
              <a href="#" style={{ color: authColors.textMuted }}>Privacy</a>
              <a href="#" style={{ color: authColors.textMuted }}>Terms</a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Build the Login page**

Create `web_frontend/src/pages/Login.jsx`:

```jsx
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authDividerStyle,
  authErrorStyle,
} from "../components/auth/authStyles";

const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || "";

function LoginForm() {
  const { loginWithGoogle, loginWithPassword } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleGoogleSuccess = async (credentialResponse) => {
    setSubmitting(true);
    setError("");
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-in failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleError = () => {
    setError("Google sign-in was cancelled or failed. Please try again.");
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await loginWithPassword(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-in failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Welcome back
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Sign in to access your <span style={{ color: authColors.accentPurple }}>analysis workspace</span>.
      </p>

      {GOOGLE_CLIENT_ID && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, marginBottom: 24 }}>
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
            theme="outline"
            shape="pill"
            size="large"
            text="continue_with"
            width={400}
          />
          <div style={authDividerStyle}>
            <span style={{ flex: 1, height: 1, background: authColors.border }} />
            OR
            <span style={{ flex: 1, height: 1, background: authColors.border }} />
          </div>
        </div>
      )}

      <form onSubmit={handlePasswordSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Email address</span>
          <input
            type="email"
            required
            placeholder="you@institution.org"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={authLabelTextStyle}>Password</span>
            <Link to="/forgot-password" style={{ fontSize: "12.5px", color: authColors.accentPurple }}>
              Forgot password?
            </Link>
          </div>
          <input
            type="password"
            required
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Signing in..." : "Sign in"}
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>

      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

export default function Login() {
  const content = (
    <AuthLayout topRightPrompt="New to Synth Veda?" topRightLabel="Create account" topRightHref="/signup">
      <LoginForm />
    </AuthLayout>
  );

  if (!GOOGLE_CLIENT_ID) return content;
  return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{content}</GoogleOAuthProvider>;
}
```

Note: the design's mockup Google button was a static SVG (non-functional). For a working Google OAuth button we use `@react-oauth/google`'s real `GoogleLogin` widget (already used elsewhere in this app) — its exact pixel rendering is controlled by Google, not fully custom, but `theme="outline"` + `shape="pill"` gets as close as possible to the mockup's white pill button.

- [ ] **Step 6: Wire the `/login` route**

In `web_frontend/src/main.jsx`, add the import after the existing `import Landing from "./pages/Landing";` line:

```js
import Login from "./pages/Login";
```

Add the route inside `<Routes>`, directly after the `/* Public */` `<Route path="/" element={<Landing />} />` line:

```jsx
      <Route path="/login" element={<Login />} />
```

- [ ] **Step 7: Manual verification**

Run: `cd web_frontend && npm run dev`

Open `http://localhost:5173/login` in a browser and confirm:
- The split-screen card renders: dark left panel with an animating particle DNA helix, "SYNTH VEDA" wordmark, headline, tagline, progress dots.
- The right panel is dark (not the original design's light/cream), with "Welcome back", email + password fields, "Forgot password?" link, and a "Sign in" button.
- If `VITE_GOOGLE_CLIENT_ID` is set in `web_frontend/.env`, a Google button + "OR" divider appear above the form.
- Submitting the email/password form with a test Supabase account (once Task 10's dashboard config is done) successfully redirects to `/dashboard`; submitting with bad credentials shows an inline error.
- No errors in the browser console.

- [ ] **Step 8: Commit**

```bash
git add web_frontend/src/index.css web_frontend/src/components/auth web_frontend/src/pages/Login.jsx web_frontend/src/main.jsx
git commit -m "feat(auth): add shared auth shell and Login page"
```

---

## Task 7: Frontend — Signup page

**Files:**
- Create: `web_frontend/src/pages/Signup.jsx`
- Modify: `web_frontend/src/main.jsx`

**Interfaces:**
- Consumes: `AuthLayout`, `authColors`, `authInputStyle`, `authLabelStyle`, `authLabelTextStyle`, `authPrimaryButtonStyle`, `authDividerStyle`, `authErrorStyle`, `authInfoStyle` (Task 6); `loginWithGoogle`, `signUpWithPassword` from `useAuth()` (Task 5).
- Produces: `/signup` route.

- [ ] **Step 1: Build the Signup page**

Create `web_frontend/src/pages/Signup.jsx`:

```jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authDividerStyle,
  authErrorStyle,
  authInfoStyle,
} from "../components/auth/authStyles";

const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || "";

function SignupForm() {
  const { loginWithGoogle, signUpWithPassword } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleGoogleSuccess = async (credentialResponse) => {
    setSubmitting(true);
    setError("");
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-up failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleError = () => {
    setError("Google sign-up was cancelled or failed. Please try again.");
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await signUpWithPassword(email, password, displayName);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const msg = err.message || "Sign-up failed. Please try again.";
      if (msg.toLowerCase().startsWith("check your email")) {
        setInfo(msg);
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Create your account
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Start building your <span style={{ color: authColors.accentPurple }}>analysis workspace</span>.
      </p>

      {GOOGLE_CLIENT_ID && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, marginBottom: 24 }}>
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
            theme="outline"
            shape="pill"
            size="large"
            text="signup_with"
            width={400}
          />
          <div style={authDividerStyle}>
            <span style={{ flex: 1, height: 1, background: authColors.border }} />
            OR
            <span style={{ flex: 1, height: 1, background: authColors.border }} />
          </div>
        </div>
      )}

      <form onSubmit={handlePasswordSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Full name</span>
          <input
            type="text"
            required
            placeholder="Ada Lovelace"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Email address</span>
          <input
            type="email"
            required
            placeholder="you@institution.org"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Password</span>
          <input
            type="password"
            required
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Confirm password</span>
          <input
            type="password"
            required
            placeholder="Re-enter your password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Creating account..." : "Create account"}
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>

      {info && <div style={authInfoStyle}>{info}</div>}
      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

export default function Signup() {
  const content = (
    <AuthLayout topRightPrompt="Already have an account?" topRightLabel="Sign in" topRightHref="/login">
      <SignupForm />
    </AuthLayout>
  );

  if (!GOOGLE_CLIENT_ID) return content;
  return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{content}</GoogleOAuthProvider>;
}
```

- [ ] **Step 2: Wire the `/signup` route**

In `web_frontend/src/main.jsx`, add the import after `import Login from "./pages/Login";`:

```js
import Signup from "./pages/Signup";
```

Add the route directly after the `/login` route:

```jsx
      <Route path="/signup" element={<Signup />} />
```

- [ ] **Step 3: Manual verification**

Run: `cd web_frontend && npm run dev` (if not already running)

Open `http://localhost:5173/signup` and confirm:
- Same dark split-screen shell as `/login`, with "Create your account" heading and full name / email / password / confirm password fields.
- Submitting with mismatched passwords shows "Passwords do not match." without calling the backend.
- Submitting with a valid new email/password (once Task 10's dashboard config is done) redirects to `/dashboard`.
- The "Already have an account? Sign in" link navigates to `/login`, and `/login`'s "Create account" link navigates back to `/signup`.

- [ ] **Step 4: Commit**

```bash
git add web_frontend/src/pages/Signup.jsx web_frontend/src/main.jsx
git commit -m "feat(auth): add Signup page"
```

---

## Task 8: Frontend — Forgot/Reset password pages

**Files:**
- Create: `web_frontend/src/pages/ForgotPassword.jsx`
- Create: `web_frontend/src/pages/ResetPassword.jsx`
- Modify: `web_frontend/src/main.jsx`

**Interfaces:**
- Consumes: `AuthLayout`, `authColors`, `authInputStyle`, `authLabelStyle`, `authLabelTextStyle`, `authPrimaryButtonStyle`, `authErrorStyle`, `authInfoStyle` (Task 6); `requestPasswordReset`, `confirmPasswordReset` from `useAuth()` (Task 5).
- Produces: `/forgot-password` and `/reset-password` routes.

- [ ] **Step 1: Build the Forgot Password page**

Create `web_frontend/src/pages/ForgotPassword.jsx`:

```jsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authErrorStyle,
  authInfoStyle,
} from "../components/auth/authStyles";

function ForgotPasswordForm() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Reset your password
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Enter your email and we'll send you a link to get back into your <span style={{ color: authColors.accentPurple }}>analysis workspace</span>.
      </p>

      {sent ? (
        <div style={{ ...authInfoStyle, textAlign: "left" }}>
          If that email is registered, a reset link is on its way. Check your inbox.
        </div>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <label style={authLabelStyle}>
            <span style={authLabelTextStyle}>Email address</span>
            <input
              type="email"
              required
              placeholder="you@institution.org"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={authInputStyle}
            />
          </label>
          <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
            {submitting ? "Sending..." : "Send reset link"}
          </button>
        </form>
      )}

      {error && <div style={authErrorStyle}>{error}</div>}

      <p style={{ marginTop: 24, fontSize: 13, color: authColors.textMuted, textAlign: "center" }}>
        <Link to="/login" style={{ color: authColors.accentPurple }}>Back to sign in</Link>
      </p>
    </>
  );
}

export default function ForgotPassword() {
  return (
    <AuthLayout topRightPrompt="Remembered it?" topRightLabel="Sign in" topRightHref="/login">
      <ForgotPasswordForm />
    </AuthLayout>
  );
}
```

- [ ] **Step 2: Build the Reset Password page**

Create `web_frontend/src/pages/ResetPassword.jsx`:

```jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authErrorStyle,
} from "../components/auth/authStyles";

function ResetPasswordForm() {
  const { confirmPasswordReset } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmPasswordReset(password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Could not reset password. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Set a new password
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Choose a new password for your <span style={{ color: authColors.accentPurple }}>analysis workspace</span>.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>New password</span>
          <input
            type="password"
            required
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Confirm new password</span>
          <input
            type="password"
            required
            placeholder="Re-enter your new password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Saving..." : "Save new password"}
        </button>
      </form>

      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

export default function ResetPassword() {
  return (
    <AuthLayout topRightPrompt="Remembered it?" topRightLabel="Sign in" topRightHref="/login">
      <ResetPasswordForm />
    </AuthLayout>
  );
}
```

- [ ] **Step 3: Wire the routes**

In `web_frontend/src/main.jsx`, add the imports after `import Signup from "./pages/Signup";`:

```js
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
```

Add the routes directly after the `/signup` route:

```jsx
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
```

- [ ] **Step 4: Manual verification**

Run: `cd web_frontend && npm run dev` (if not already running)

Open `http://localhost:5173/forgot-password` and confirm:
- The form takes an email and, on submit, replaces itself with the "reset link is on its way" message (regardless of whether the email is real — confirms the anti-enumeration behavior).
- "Back to sign in" navigates to `/login`.

Full reset-link verification (`/reset-password`) happens in Task 10 once Supabase's redirect URL is configured and a real reset email can be sent.

- [ ] **Step 5: Commit**

```bash
git add web_frontend/src/pages/ForgotPassword.jsx web_frontend/src/pages/ResetPassword.jsx web_frontend/src/main.jsx
git commit -m "feat(auth): add Forgot/Reset password pages"
```

---

## Task 9: Frontend — Landing page cleanup

**Files:**
- Modify: `web_frontend/src/pages/Landing.jsx`

**Interfaces:**
- Consumes: `/login` and `/signup` routes (Tasks 6-7).
- Produces: `Landing` page with no embedded Google sign-in; links to `/login` and `/signup` instead.

- [ ] **Step 1: Replace the file**

Replace the full contents of `web_frontend/src/pages/Landing.jsx` with:

```jsx
import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { healthCheck } from "../lib/api";

const css = `
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--gradient-primary:linear-gradient(135deg,#0066ff 0%,#00d4ff 100%);--gradient-bg:radial-gradient(ellipse at center,#002266 0%,#001133 100%);}
*{box-sizing:border-box;margin:0;padding:0;}
html,body,#root{height:100%;width:100%;overflow:hidden !important;background:var(--gradient-bg) !important;}
body{font-family:'Inter',system-ui,Segoe UI,Roboto;color:var(--text-primary);}
.app-scroll{height:100vh;overflow:auto;-webkit-overflow-scrolling:touch;position:relative;scroll-behavior:smooth;}
#landing-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;}
.sv-container{position:relative;z-index:10;min-height:100vh;padding:2rem;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:1.5rem;}
.sv-header{width:100%;text-align:center;margin-bottom:1rem;}
.sv-logo{font-size:clamp(2rem,5vw,3.2rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.25rem;line-height:1.05;}
.sv-subtitle{color:var(--text-muted);max-width:840px;margin:0 auto;font-size:14px;line-height:1.4;}
.sv-card{width:100%;max-width:520px;background:rgba(255,255,255,0.04);border-radius:20px;padding:32px;border:1px solid var(--glass-border);backdrop-filter:blur(15px);box-shadow:0 25px 80px rgba(0,17,51,0.5);}
.sv-status-bar{position:fixed;top:18px;right:18px;display:flex;align-items:center;gap:12px;padding:8px 12px;border-radius:40px;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);backdrop-filter:blur(8px);z-index:20;}
.sv-dot{width:8px;height:8px;border-radius:50%;background:var(--accent-green);animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.sv-divider{border:none;border-top:1px solid rgba(255,255,255,0.08);margin:1.25rem 0;}
.sv-footer{margin-top:1.5rem;color:var(--text-muted);font-size:13px;text-align:center;}
.sv-cta-row{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;}
.sv-btn{display:inline-flex;align-items:center;justify-content:center;padding:12px 28px;border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;transition:transform 0.2s ease;}
.sv-btn:hover{transform:translateY(-2px);text-decoration:none;}
.sv-btn-primary{background:var(--gradient-primary);color:#ffffff;box-shadow:0 10px 30px rgba(0,102,255,0.4);}
.sv-btn-secondary{background:rgba(255,255,255,0.06);color:var(--text-primary);border:1px solid var(--glass-border);}
.app-scroll::-webkit-scrollbar{width:12px;}
.app-scroll::-webkit-scrollbar-track{background:transparent;}
.app-scroll::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#00d4ff 0%,#0066ff 100%);border-radius:999px;min-height:28px;}
.app-scroll{scrollbar-width:thin;scrollbar-color:#00d4ff transparent;}
`;

export default function Landing() {
  const { isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();
  const bgCanvasRef = useRef(null);
  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    if (!loading && isAuthenticated) navigate("/dashboard", { replace: true });
  }, [isAuthenticated, loading, navigate]);

  useEffect(() => {
    const on = () => setIsOnline(true);
    const off = () => setIsOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  useEffect(() => {
    healthCheck()
      .then(() => setBackendStatus("Connected"))
      .catch(() => setBackendStatus("Unreachable"));
  }, []);

  useEffect(() => {
    const canvas = bgCanvasRef.current;
    if (!canvas) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 2.6;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    const palette = [
      new THREE.Color(0x00ffaa), new THREE.Color(0x00d4ff),
      new THREE.Color(0x0066ff), new THREE.Color(0x00ff88),
    ];
    const particlesCount = 10000;
    const sphereGeom = new THREE.SphereGeometry(1, 64, 64);
    const srcPos = sphereGeom.attributes.position.array;
    const positions = new Float32Array(particlesCount * 3);
    for (let i = 0; i < particlesCount; i++) {
      const i3 = i * 3;
      const vIdx = i3 % srcPos.length;
      positions[i3] = srcPos[vIdx] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 1] = srcPos[(vIdx + 1) % srcPos.length] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 2] = srcPos[(vIdx + 2) % srcPos.length] * (1.05 + (Math.random() - 0.5) * 0.02);
    }
    const pGeom = new THREE.BufferGeometry();
    pGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const pMat = new THREE.PointsMaterial({
      size: 0.012, color: palette[0].clone(), transparent: true,
      opacity: 0.55, depthTest: false, blending: THREE.AdditiveBlending,
    });
    const sphere = new THREE.Points(pGeom, pMat);
    scene.add(sphere);

    const totalCycle = 14, minScale = 0.6, maxScale = 12.0;
    let rafId;
    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const t = performance.now() * 0.001;
      const norm = 0.5 * (Math.sin((2 * Math.PI * t) / totalCycle - Math.PI / 2) + 1);
      const scale = minScale + (maxScale - minScale) * norm;
      sphere.scale.set(scale, scale, scale);
      const cycle = t * 0.12;
      const idx = Math.floor(cycle) % palette.length;
      pMat.color.copy(palette[idx]).lerp(palette[(idx + 1) % palette.length], cycle - Math.floor(cycle));
      pMat.opacity = 0.45 + 0.12 * (0.5 + 0.5 * Math.sin(t * 0.9));
      sphere.rotation.x += 0.0003;
      sphere.rotation.y += 0.0005;
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafId);
      try { pGeom.dispose(); pMat.dispose(); renderer.dispose(); } catch {}
    };
  }, []);

  return (
    <>
      <style>{css}</style>
      <div className="app-scroll">
        <canvas id="landing-canvas" ref={bgCanvasRef} />
        <div className="sv-status-bar">
          <div className="sv-dot" style={{ background: isOnline ? "var(--accent-green)" : "#ff6b6b" }} />
          <span style={{ color: "var(--text-secondary)", fontSize: 13, fontWeight: 600 }}>
            {isOnline ? "Online" : "Offline"} • Backend: {backendStatus}
          </span>
        </div>

        <div className="sv-container">
          <header className="sv-header">
            <div className="sv-logo">Synth Veda</div>
            <div className="sv-subtitle">
              eDNA Biodiversity Analysis Platform — AI-powered species identification
              and biodiversity assessment from environmental DNA samples
            </div>
          </header>

          <div className="sv-card">
            <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6, color: "var(--text-primary)" }}>
              Get started
            </h2>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
              Sign in or create an account to submit samples and view results.
            </p>

            <div className="sv-cta-row">
              <Link to="/login" className="sv-btn sv-btn-primary">Sign in</Link>
              <Link to="/signup" className="sv-btn sv-btn-secondary">Create account</Link>
            </div>

            <hr className="sv-divider" />

            <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", lineHeight: 1.6 }}>
              By signing in you agree that all analysis results are preliminary
              and require expert confirmation before use in scientific publications.
            </div>
          </div>

          <div className="sv-footer">
            Synth Veda · eDNA Biodiversity Analysis Platform
          </div>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Manual verification**

Run: `cd web_frontend && npm run dev` (if not already running)

Open `http://localhost:5173/` and confirm:
- The existing dark blue/cyan Landing page still renders (particle sphere background, status bar, header) — unchanged except the card now shows "Sign in" / "Create account" buttons instead of a Google button.
- Both buttons navigate to `/login` and `/signup` respectively.
- No console errors about missing `GoogleLogin`/`GoogleOAuthProvider` imports.

- [ ] **Step 3: Commit**

```bash
git add web_frontend/src/pages/Landing.jsx
git commit -m "refactor(auth): remove embedded Google sign-in from Landing, link to /login and /signup"
```

---

## Task 10: Supabase dashboard configuration + end-to-end verification

**Files:** none (configuration + manual verification only)

**Interfaces:**
- Consumes: all of Tasks 1-9.

- [ ] **Step 1: Configure Supabase Auth settings**

In the Supabase dashboard for this project:

1. **Authentication → Providers → Email**: ensure "Enable Email provider" is ON, and toggle **"Confirm email" OFF** (per the Global Constraints — signup must return a session immediately).
2. **Authentication → URL Configuration**: set **Site URL** to the frontend's dev URL (`http://localhost:5173`) and add `http://localhost:5173/reset-password` to **Redirect URLs**. Add the production frontend URL + `/reset-password` here too once deployed.

- [ ] **Step 2: Set local env vars**

In `web_frontend/.env` (create from `.env.example` if it doesn't exist), set:

```
VITE_SUPABASE_URL=<your Supabase project URL>
VITE_SUPABASE_ANON_KEY=<your Supabase anon key>
```

Confirm `services/api/.env` already has `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` set (these were required before this project; unchanged by this plan).

- [ ] **Step 3: Run the full backend test suite**

Run: `cd services/api && python -m pytest -v`
Expected: all tests pass, including the new `test_auth_supabase.py` and the extended `test_supabase_client.py`, with no regressions in `test_auth_phase3.py` or any other existing test file.

- [ ] **Step 4: End-to-end manual verification**

With the backend running (`uvicorn app.main:app --reload` from `services/api`, or the project's usual dev command) and the frontend running (`npm run dev` from `web_frontend`):

1. Visit `/signup`, create an account with a real-format test email and an 8+ character password. Confirm redirect to `/dashboard` and that `ProtectedRoute`-gated pages are now accessible.
2. Log out (existing logout flow), visit `/login`, sign back in with the same email/password. Confirm redirect to `/dashboard`.
3. Visit `/login` with a wrong password. Confirm an inline error appears and no redirect happens.
4. Visit `/forgot-password`, submit the test account's email. Confirm the "reset link is on its way" message appears, and that a real email arrives (from Supabase) with a link back to `/reset-password`.
5. Open that link, set a new password on `/reset-password`. Confirm redirect to `/dashboard`.
6. Log out and log back in with the new password to confirm the reset took effect.
7. Confirm Google OAuth sign-in from `/login` still works end-to-end exactly as it did before this plan (unchanged flow).

- [ ] **Step 5: Commit**

No code changes in this task — if any issues were found and fixed during verification, ensure those fixes were committed in their respective earlier tasks. If not, commit them now with an appropriate message referencing the fix.
