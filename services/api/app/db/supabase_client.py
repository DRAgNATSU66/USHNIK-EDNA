"""
Supabase client wrapper.

Used for Postgres-backed structured data: user_profiles, admin_invite_keys,
role_assignments, expert_reviews, curation_decisions, curated_sequences,
training_batches, model_versions, audit_logs.

The service-role key is NEVER exposed to frontend. It is only used server-side.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import AsyncClient

_client: "AsyncClient | None" = None


async def init_supabase() -> None:
    global _client
    from supabase import create_async_client
    from ..config import get_settings

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return  # Supabase not configured — skip (local dev without Supabase is fine)

    _client = await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )


async def close_supabase() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class SupabaseClient:
    """
    Thin wrapper around the Supabase async client.
    Raises RuntimeError if Supabase is not configured (dev shortcut).
    """

    @staticmethod
    def _get() -> "AsyncClient":
        if _client is None:
            raise RuntimeError(
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        return _client

    # ------------------------------------------------------------------
    # user_profiles
    # ------------------------------------------------------------------

    @staticmethod
    async def upsert_user_by_google_sub(
        google_sub: str, email: str, display_name: str | None, role: str
    ) -> dict:
        """Insert or update a user_profiles row keyed by Google `sub`.

        id is NOT set here — Postgres generates it (gen_random_uuid() default).
        Callers must use the returned row's `id` for the JWT subject and for
        any downstream user_profiles(id) foreign keys.
        """
        client = SupabaseClient._get()
        res = await (
            client.table("user_profiles")
            .upsert(
                {
                    "google_sub": google_sub,
                    "email": email,
                    "display_name": display_name,
                    "role": role,
                },
                on_conflict="google_sub",
            )
            .execute()
        )
        return res.data[0] if res.data else {}

    @staticmethod
    async def get_user_by_google_sub(google_sub: str) -> dict | None:
        client = SupabaseClient._get()
        res = (
            await client.table("user_profiles")
            .select("*")
            .eq("google_sub", google_sub)
            .maybe_single()
            .execute()
        )
        return res.data if res else None

    @staticmethod
    async def update_last_login(user_id: str) -> None:
        from datetime import datetime, timezone
        client = SupabaseClient._get()
        await (
            client.table("user_profiles")
            .update({"last_login": datetime.now(timezone.utc).isoformat()})
            .eq("id", user_id)
            .execute()
        )

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

    # ------------------------------------------------------------------
    # admin_invite_keys
    # ------------------------------------------------------------------

    @staticmethod
    async def get_invite_key(key_hash: str) -> dict | None:
        client = SupabaseClient._get()
        res = (
            await client.table("admin_invite_keys")
            .select("*")
            .eq("key_hash", key_hash)
            .eq("is_active", True)
            .single()
            .execute()
        )
        return res.data

    @staticmethod
    async def consume_invite_key(key_id: str, user_id: str) -> bool:
        """
        Atomically increment uses_count. Deactivate when max_uses reached.
        Returns True if key was successfully consumed.
        """
        client = SupabaseClient._get()
        # Use RPC to avoid race condition on uses_count
        res = await client.rpc(
            "consume_invite_key",
            {"p_key_id": key_id, "p_user_id": user_id},
        ).execute()
        return bool(res.data)

    @staticmethod
    async def create_invite_key(
        key_hash: str,
        role_to_grant: str,
        created_by: str,
        max_uses: int = 1,
        expires_hours: int = 72,
    ) -> dict:
        from datetime import datetime, timedelta, timezone
        client = SupabaseClient._get()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).isoformat()
        res = await (
            client.table("admin_invite_keys")
            .insert({
                "key_hash": key_hash,
                "role_to_grant": role_to_grant,
                "created_by": created_by,
                "max_uses": max_uses,
                "uses_count": 0,
                "expires_at": expires_at,
                "is_active": True,
            })
            .execute()
        )
        return res.data[0] if res.data else {}

    # ------------------------------------------------------------------
    # role_assignments
    # ------------------------------------------------------------------

    @staticmethod
    async def assign_role(user_id: str, role: str, granted_by: str, invite_key_id: str | None = None) -> dict:
        client = SupabaseClient._get()
        res = await (
            client.table("role_assignments")
            .insert({
                "user_id": user_id,
                "role": role,
                "granted_by": granted_by,
                "invite_key_id": invite_key_id,
                "is_active": True,
            })
            .execute()
        )
        # Also update user_profiles.role
        await (
            client.table("user_profiles")
            .update({"role": role})
            .eq("id", user_id)
            .execute()
        )
        return res.data[0] if res.data else {}

    # ------------------------------------------------------------------
    # expert_reviews (Supabase mirror of MongoDB reviews)
    # ------------------------------------------------------------------

    @staticmethod
    async def upsert_review(review_data: dict) -> dict:
        client = SupabaseClient._get()
        res = await (
            client.table("expert_reviews")
            .upsert(review_data, on_conflict="review_id")
            .execute()
        )
        return res.data[0] if res.data else {}

    @staticmethod
    async def update_review_state(review_id: str, state: str, decided_by: str, notes: str | None) -> None:
        from datetime import datetime, timezone
        client = SupabaseClient._get()
        await (
            client.table("expert_reviews")
            .update({
                "state": state,
                "decided_by": decided_by,
                "decision_notes": notes,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("review_id", review_id)
            .execute()
        )

    # ------------------------------------------------------------------
    # curated_sequences
    # ------------------------------------------------------------------

    @staticmethod
    async def insert_curated_sequence(seq_data: dict) -> dict:
        client = SupabaseClient._get()
        res = await client.table("curated_sequences").insert(seq_data).execute()
        return res.data[0] if res.data else {}

    # ------------------------------------------------------------------
    # training_batches
    # ------------------------------------------------------------------

    @staticmethod
    async def get_or_create_training_batch(batch_id: str, month_year: str, route: str, created_by: str) -> dict:
        client = SupabaseClient._get()
        res = await client.table("training_batches").select("*").eq("batch_id", batch_id).execute()
        if res.data:
            return res.data[0]
        res = await (
            client.table("training_batches")
            .insert({
                "batch_id": batch_id,
                "month_year": month_year,
                "route": route,
                "status": "assembling",
                "sequence_count": 0,
                "created_by": created_by,
            })
            .execute()
        )
        return res.data[0] if res.data else {}

    @staticmethod
    async def freeze_training_batch(batch_id: str) -> None:
        from datetime import datetime, timezone
        client = SupabaseClient._get()
        await (
            client.table("training_batches")
            .update({"status": "frozen", "frozen_at": datetime.now(timezone.utc).isoformat()})
            .eq("batch_id", batch_id)
            .execute()
        )

    # ------------------------------------------------------------------
    # model_versions
    # ------------------------------------------------------------------

    @staticmethod
    async def register_model_version(model_data: dict) -> dict:
        client = SupabaseClient._get()
        res = await client.table("model_versions").insert(model_data).execute()
        return res.data[0] if res.data else {}

    @staticmethod
    async def promote_model(model_id: str, promoted_by: str) -> None:
        from datetime import datetime, timezone
        client = SupabaseClient._get()
        # Retire previous production model for same route first
        model_res = await client.table("model_versions").select("route").eq("model_id", model_id).single().execute()
        if model_res.data:
            await (
                client.table("model_versions")
                .update({"status": "retired"})
                .eq("route", model_res.data["route"])
                .eq("status", "production")
                .execute()
            )
        await (
            client.table("model_versions")
            .update({
                "status": "production",
                "promoted_by": promoted_by,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("model_id", model_id)
            .execute()
        )

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------

    @staticmethod
    async def log_action(
        action: str,
        target_type: str,
        target_id: str,
        actor_id: str | None,
        actor_role: str,
        payload: dict | None = None,
    ) -> None:
        from datetime import datetime, timezone
        client = SupabaseClient._get()
        await (
            client.table("audit_logs")
            .insert({
                "actor_id": actor_id,
                "actor_role": actor_role,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "payload": payload or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            .execute()
        )


def get_supabase() -> SupabaseClient:
    return SupabaseClient()
