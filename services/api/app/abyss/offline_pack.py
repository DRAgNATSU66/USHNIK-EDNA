"""
Offline pack services — Phase 10.

Responsibilities:
  - Generate signed offline licenses (JWT) for expeditions
  - Build offline pack manifests describing available components
  - Validate offline licenses submitted with abyss analysis requests

Offline license:
  A short-lived JWT signed with the server's jwt_secret. It contains the
  expedition_id, user_id, and expiry. The offline device checks this token
  before running any analysis. When the device is offline, it cannot contact
  the server — expiry enforcement is the only protection. Licenses are issued
  for the planned expedition duration plus a 48-hour buffer.

Security notes:
  - The license cannot be revoked once issued (offline, no revocation check).
  - If an expedition is compromised, issue a new expedition and cancel
    by not accepting the old expedition_id during sync.
  - License duration is capped at 90 days.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .models import (
    ExpeditionDoc,
    OfflinePackComponent,
    OfflinePackManifest,
    ABYSS_DISCLAIMER,
)


_MAX_LICENSE_DAYS = 90
_BUFFER_HOURS = 48


def generate_offline_license(
    expedition: ExpeditionDoc,
    user_id: str,
    duration_days: int = 14,
) -> tuple[str, datetime]:
    """
    Generate a signed offline license JWT for an expedition.

    Returns (token, expires_at). The token is a standard JWT signed
    with the server's jwt_secret — same key as user access tokens, but
    with a different 'type' claim so they cannot be interchanged.

    Duration is capped at _MAX_LICENSE_DAYS to prevent indefinite licenses.
    """
    from ..auth.jwt import create_access_token as _create_token
    import jwt as _jwt
    from ..config import get_settings

    actual_days = min(duration_days, _MAX_LICENSE_DAYS)
    expires_at = datetime.now(timezone.utc) + timedelta(days=actual_days, hours=_BUFFER_HOURS)

    settings = get_settings()
    payload: dict[str, Any] = {
        "type": "offline_license",
        "expedition_id": expedition.expedition_id,
        "sub": user_id,
        "exp": expires_at,
    }
    token = _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def validate_offline_license(token: str) -> dict[str, Any] | None:
    """
    Validate an offline license token.

    Returns the decoded payload if valid, or None if expired/invalid.
    Does NOT check if the expedition still exists — offline devices cannot do
    network calls. Caller is responsible for checking expedition validity.
    """
    from ..auth.jwt import decode_access_token
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "offline_license":
            return None
        return payload
    except Exception:
        return None


def build_pack_manifest(expedition: ExpeditionDoc) -> OfflinePackManifest:
    """
    Build an offline pack manifest for an expedition.

    The manifest describes what is available for download. Phase 10 defines
    the contract; actual model artifact bundling happens in Phase 15 when
    trained model weights exist.

    Components:
      1. offline_license  — issued by this call (always available)
      2. route_models     — quantized/compressed specialist model heads
                            (not_yet_trained until Phase 14 completes)
      3. reference_pack   — curated species reference signatures
                            (not_yet_available until Phase 14 curates data)
      4. contaminant_pack — known contaminant motifs (available: hardcoded list)
      5. metadata_pack    — local species/depth metadata stubs (available)
    """
    components = [
        OfflinePackComponent(
            name="offline_license",
            component_type="license",
            status="available",
            size_mb_estimate=0.001,
            description="Signed JWT credential for offline sessions.",
        ),
        OfflinePackComponent(
            name="route_models_quantized",
            component_type="model_pack",
            status="not_yet_trained",
            size_mb_estimate=0.0,
            description=(
                "Quantized/INT8 specialist model heads for each taxonomic route. "
                "Available after Phase 14 training cycle completes."
            ),
            artifact_uri=None,
        ),
        OfflinePackComponent(
            name="reference_pack_v1",
            component_type="reference_pack",
            status="not_yet_available",
            size_mb_estimate=0.0,
            description=(
                "Curated k-mer reference signatures for fish, plant, bacteria, "
                "animal, and misc routes. Available after Phase 14."
            ),
            artifact_uri=None,
        ),
        OfflinePackComponent(
            name="contaminant_pack_v1",
            component_type="contaminant_pack",
            status="available",
            size_mb_estimate=0.05,
            description=(
                "Known lab reagent motifs, Illumina adapters, PhiX control "
                "sequences, and human GC/CpG profile for contamination detection."
            ),
        ),
        OfflinePackComponent(
            name="metadata_pack_v1",
            component_type="metadata_pack",
            status="available",
            size_mb_estimate=1.2,
            description=(
                "Taxonomic route priors, habitat metadata, depth profiles, "
                "and species name stubs for offline result annotation."
            ),
        ),
    ]

    total_mb = sum(c.size_mb_estimate for c in components if c.status == "available")

    instructions = (
        "Before departure: download all 'available' components to your field device. "
        "'not_yet_trained' components will be added automatically once Phase 14 "
        "model training completes. "
        "After returning: run POST /abyss/sync to upload offline logs, "
        "analyses, and trigger full online re-analysis. "
        f"{ABYSS_DISCLAIMER}"
    )

    return OfflinePackManifest(
        expedition_id=expedition.expedition_id,
        components=components,
        total_size_mb_estimate=round(total_mb, 3),
        instructions=instructions,
    )
