"""
Environmental context per upload (Q5, t-1026-1; docs/specs/q5_environmental_sources.md).

Flow:
  1. POST /uploads stores an upload with latitude/longitude + collected_at and
     schedules `run_lookup(upload_id)` as a FastAPI background task (runs after
     the response is sent; never blocks or fails the upload).
  2. run_lookup marks `environment_contexts[upload_id]` pending, then checks the
     coarse shared cache (`environment_cache`, keyed by lat/lon rounded to 2
     decimals + UTC date + depth). On a miss it asks the providers in Q5 order
     (providers.PROVIDER_ORDER), each with a per-request timeout, bounded
     retries and an overall deadline.
  3. The public values (with source, dataset, query URL, grid cell, retrieved_at)
     are written to the per-upload doc and, when no attempt failed transiently,
     to the shared cache.
  4. GET /environment/uploads/{id} merges that doc with the upload's own
     DO/pH/temperature/salinity at read time: a user value wins and is labelled
     user_provided; the public value is returned alongside, never overwritten.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import get_settings
from ..db import get_db
from .http import HttpClientFactory, ProviderUnavailable, default_client_factory
from .models import (
    VARIABLES, USER_FIELDS, EnvironmentContextResponse, EnvironmentQuery, ProviderAttempt,
    PublicValue, PublicVariableResult, SourceInfo, UserValue, VariableContext,
)
from .providers import ALL_PROVIDERS, PROVIDER_ORDER, LookupQuery, ProviderContext

logger = logging.getLogger("app.environment")

CONTEXTS = "environment_contexts"
CACHE = "environment_cache"
CACHE_VERSION = "v1"
# Values for dates this recent can still change (CMEMS forecast -> analysis,
# ERA5T -> ERA5), so their shared-cache entries expire; older ones do not.
RECENT_DAYS = 14
RECENT_CACHE_TTL = timedelta(hours=24)
# A lookup still "pending" after this long died with its process; GET re-runs it.
STALE_PENDING = timedelta(minutes=10)

# Tests swap this for an httpx.MockTransport-backed client.
_client_factory: HttpClientFactory = default_client_factory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    # Naive timestamps (as sent, or as returned by Mongo) are UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def missing_inputs(upload: dict[str, Any]) -> list[str]:
    return [f for f in ("latitude", "longitude", "collected_at") if upload.get(f) is None]


def build_query(upload: dict[str, Any]) -> Optional[tuple[LookupQuery, EnvironmentQuery]]:
    if missing_inputs(upload):
        return None
    collected = upload["collected_at"]
    if isinstance(collected, str):
        collected = datetime.fromisoformat(collected)
    collected = _as_utc(collected)
    lat, lon = float(upload["latitude"]), float(upload["longitude"])
    depth = upload.get("depth_meters")
    depth = float(depth) if depth is not None else None
    lq = LookupQuery(latitude=round(lat, 2), longitude=round(lon, 2), collected_at=collected,
                     day=collected.date(), depth_m=round(depth) if depth is not None else None)
    eq = EnvironmentQuery(
        latitude=lat, longitude=lon, lookup_latitude=lq.latitude, lookup_longitude=lq.longitude,
        collected_at=collected, date=lq.day.isoformat(), depth_m=depth,
        target_level="sample_depth" if depth is not None else "surface",
    )
    return lq, eq


def cache_key(lq: LookupQuery) -> str:
    depth = "surface" if lq.depth_m is None else f"{int(lq.depth_m)}m"
    return f"{CACHE_VERSION}:{lq.latitude:.2f}:{lq.longitude:.2f}:{lq.day.isoformat()}:{depth}"


def _cache_expiry(lq: LookupQuery, now: datetime) -> Optional[datetime]:
    if (now.date() - lq.day).days > RECENT_DAYS:
        return None
    return now + RECENT_CACHE_TTL


async def fetch_public(lq: LookupQuery, *, client_factory: Optional[HttpClientFactory] = None
                       ) -> tuple[dict[str, PublicVariableResult], bool]:
    """Ask the providers for every variable. Returns (results, any_transient)."""
    settings = get_settings()
    timeout = float(settings.environment_provider_timeout_s)
    # Overall cap per provider call: a CMEMS read is up to ~5 requests.
    deadline = timeout * 4
    factory = client_factory or _client_factory
    async with factory(timeout) as client:
        ctx = ProviderContext(
            client=client,
            retries=max(0, int(settings.environment_provider_retries)),
            max_distance_km=float(settings.environment_max_cell_distance_km),
            copernicus_username=settings.copernicus_marine_username,
            copernicus_password=settings.copernicus_marine_password,
        )

        async def one(variable: str) -> tuple[str, PublicVariableResult, bool]:
            attempts: list[ProviderAttempt] = []
            transient = False
            for provider in PROVIDER_ORDER[variable]:
                try:
                    value = await asyncio.wait_for(provider.fetch(variable, lq, ctx), timeout=deadline)
                except ProviderUnavailable as exc:
                    attempts.append(ProviderAttempt(provider=provider.name, ok=False,
                                                    reason=exc.reason, transient=exc.transient))
                    transient = transient or exc.transient
                    logger.warning("env lookup %s via %s unavailable: %s", variable, provider.name, exc.reason)
                    continue
                except asyncio.TimeoutError:
                    reason = f"no answer within {deadline:g} s"
                    attempts.append(ProviderAttempt(provider=provider.name, ok=False, reason=reason, transient=True))
                    transient = True
                    logger.error("ENV LOOKUP TIMEOUT %s via %s: %s", variable, provider.name, reason)
                    continue
                except Exception as exc:  # a provider bug must not sink the other variables
                    reason = f"provider error ({type(exc).__name__}: {exc})"
                    attempts.append(ProviderAttempt(provider=provider.name, ok=False, reason=reason, transient=True))
                    transient = True
                    logger.exception("ENV LOOKUP PROVIDER CRASH %s via %s", variable, provider.name)
                    continue
                attempts.append(ProviderAttempt(provider=provider.name, ok=True))
                return variable, PublicVariableResult(status="ok", value=value, attempts=attempts), transient
            reason = "; ".join(f"{a.provider}: {a.reason}" for a in attempts) or "no provider configured"
            return variable, PublicVariableResult(status="unavailable", reason=reason, attempts=attempts), transient

        done = await asyncio.gather(*(one(v) for v in VARIABLES))
    results = {v: r for v, r, _ in done}
    return results, any(t for _, _, t in done)


def _dump(results: dict[str, PublicVariableResult]) -> dict[str, Any]:
    return {k: r.model_dump(mode="json") for k, r in results.items()}


async def run_lookup(upload_id: str, *, force: bool = False,
                     client_factory: Optional[HttpClientFactory] = None) -> None:
    """Background entry point. Never raises: failures end up in the doc and the log."""
    try:
        await _run_lookup(upload_id, force=force, client_factory=client_factory)
    except Exception as exc:
        logger.exception("ENV LOOKUP FAILED for upload %s", upload_id)
        try:
            await get_db()[CONTEXTS].update_one(
                {"upload_id": upload_id},
                {"$set": {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                          "completed_at": _utcnow()}},
                upsert=True,
            )
        except Exception:
            logger.exception("ENV LOOKUP: could not record the failure for upload %s", upload_id)


async def _run_lookup(upload_id: str, *, force: bool, client_factory: Optional[HttpClientFactory]) -> None:
    db = get_db()
    upload = await db["uploads"].find_one({"upload_id": upload_id})
    if not upload:
        logger.warning("env lookup: upload %s not found", upload_id)
        return
    built = build_query(upload)
    if built is None:
        return
    lq, eq = built
    key = cache_key(lq)
    now = _utcnow()
    await db[CONTEXTS].update_one(
        {"upload_id": upload_id},
        {"$set": {"upload_id": upload_id, "user_id": upload.get("user_id"), "status": "pending",
                  "query": eq.model_dump(mode="json"), "cache_key": key, "requested_at": now,
                  "error": None}},
        upsert=True,
    )

    results: Optional[dict[str, Any]] = None
    cache_hit = False
    retrieved_at = None
    if not force:
        cached = await db[CACHE].find_one({"cache_key": key})
        if cached:
            exp = cached.get("expires_at")
            if exp is None or _as_utc(exp) > now:
                results = cached["public"]
                retrieved_at = cached.get("retrieved_at")
                cache_hit = True

    if results is None:
        fetched, transient = await fetch_public(lq, client_factory=client_factory)
        results = _dump(fetched)
        retrieved_at = _utcnow()
        if transient:
            logger.warning("env lookup %s: transient provider failure, not writing shared cache %s", upload_id, key)
        else:
            await db[CACHE].update_one(
                {"cache_key": key},
                {"$set": {"cache_key": key, "public": results, "retrieved_at": retrieved_at,
                          "created_at": retrieved_at, "expires_at": _cache_expiry(lq, retrieved_at),
                          "lookup": {"latitude": lq.latitude, "longitude": lq.longitude,
                                     "date": lq.day.isoformat(), "depth_m": lq.depth_m}}},
                upsert=True,
            )

    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    status = "complete" if ok == len(VARIABLES) else "partial"
    await db[CONTEXTS].update_one(
        {"upload_id": upload_id},
        {"$set": {"status": status, "public": results, "cache_hit": cache_hit,
                  "retrieved_at": retrieved_at, "completed_at": _utcnow()}},
    )
    logger.info("env lookup %s: %s (%d/%d variables, cache %s)", upload_id, status, ok,
                len(VARIABLES), "hit" if cache_hit else "miss")


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------

def _user_value(upload: dict[str, Any], variable: str) -> Optional[UserValue]:
    spec = USER_FIELDS.get(variable)
    if not spec:
        return None
    field, unit = spec
    val = upload.get(field)
    if val is None:
        return None
    return UserValue(value=float(val), unit=unit, field=field)


def query_matches(doc: dict[str, Any], eq: EnvironmentQuery) -> bool:
    q = doc.get("query") or {}
    return (q.get("lookup_latitude") == eq.lookup_latitude
            and q.get("lookup_longitude") == eq.lookup_longitude
            and q.get("date") == eq.date
            and q.get("depth_m") == eq.depth_m)


def needs_lookup(doc: Optional[dict[str, Any]], eq: EnvironmentQuery, now: Optional[datetime] = None) -> bool:
    if doc is None or not query_matches(doc, eq):
        return True
    if doc.get("status") == "pending":
        req = doc.get("requested_at")
        return req is None or _as_utc(req) < (now or _utcnow()) - STALE_PENDING
    return False


def build_response(upload: dict[str, Any], doc: Optional[dict[str, Any]], *,
                   pending_reason: Optional[str] = None) -> EnvironmentContextResponse:
    upload_id = upload["upload_id"]
    built = build_query(upload)
    missing = missing_inputs(upload)

    if built is None:
        status, reason = "not_applicable", (
            f"No public environmental lookup: {', '.join(missing)} not recorded on the upload "
            "(it needs latitude, longitude and collected_at)."
        )
        public_state, public_reason, public = "not_applicable", reason, {}
        query = None
    else:
        query = built[1]
        if doc is None or doc.get("status") == "pending" or not query_matches(doc, query):
            status = "pending"
            reason = pending_reason or "Public environmental lookup is queued or running."
            public_state, public_reason, public = "pending", reason, {}
        elif doc.get("status") == "failed":
            status = "failed"
            reason = f"Public environmental lookup failed: {doc.get('error')}"
            public_state, public_reason, public = "unavailable", reason, {}
        else:
            status, reason = doc.get("status", "partial"), None
            public_state, public_reason, public = None, None, doc.get("public") or {}

    variables: dict[str, VariableContext] = {}
    sources: dict[str, SourceInfo] = {}
    for var, unit in VARIABLES.items():
        user = _user_value(upload, var)
        pv: Optional[PublicValue] = None
        attempts: list[ProviderAttempt] = []
        if public_state is None:
            raw = public.get(var) or {"status": "unavailable", "reason": "not looked up"}
            res = PublicVariableResult.model_validate(raw)
            p_status = res.status
            p_reason = res.reason
            pv = res.value
            attempts = res.attempts
            if pv is not None and pv.provider in ALL_PROVIDERS:
                sources[pv.provider] = ALL_PROVIDERS[pv.provider].info
        else:
            p_status, p_reason = public_state, public_reason

        if user is not None:
            variables[var] = VariableContext(
                status="user_provided", value=user.value, unit=user.unit, value_source="user",
                user_value=user, public_status=p_status, public=pv, public_reason=p_reason, attempts=attempts,
            )
        elif pv is not None:
            variables[var] = VariableContext(
                status="ok", value=pv.value, unit=pv.unit, value_source="public",
                public_status=p_status, public=pv, attempts=attempts,
            )
        else:
            variables[var] = VariableContext(
                status="unavailable", unit=unit, reason=p_reason, public_status=p_status,
                public_reason=p_reason, attempts=attempts,
            )

    return EnvironmentContextResponse(
        upload_id=upload_id, status=status, reason=reason, query=query, variables=variables,
        sources=list(sources.values()),
        requested_at=(doc or {}).get("requested_at"),
        retrieved_at=(doc or {}).get("retrieved_at"),
        cache_hit=(doc or {}).get("cache_hit") if status not in ("pending", "not_applicable") else None,
        cache_key=(doc or {}).get("cache_key"),
    )
