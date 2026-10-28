"""
Environmental context per upload (Q5, t-1026-1; docs/specs/q5_environmental_sources.md).

Every HTTP response here is a recorded fixture
(tests/fixtures/environment/bay_of_bengal/, recorded live on 2026-10-18 by
tests/fixtures/environment/record_fixtures.py for 15.6 N, 82.3 E, 2026-10-01).
The transport raises ConnectError for any URL without a fixture, so the suite
can never reach the network.

Covers: each provider against its recorded response, cache miss/hit and
refresh, user-value precedence, unavailable paths (land cell, date outside
the dataset, network failure, provider crash), Copernicus credentials, the
POST /uploads trigger and the access rules on GET /environment/uploads/{id}.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import blosc
import httpx
import numpy as np
import pytest

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.config import get_settings
from app.environment import http as env_http
from app.environment import providers, service, zarr_point
from app.environment.http import ProviderUnavailable
from app.environment.providers import LookupQuery, ProviderContext
from app.models.user import UserRole

FIXTURES = Path(__file__).parent / "fixtures" / "environment" / "bay_of_bengal"
OWNER = "usr_test_001"  # researcher_token (conftest)
WHEN = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
THETAO_SURFACE_CHUNK = (
    "https://s3.waw3-1.cloudferro.com/mdl-arco-geo-012/arco/GLOBAL_ANALYSISFORECAST_PHY_001_024/"
    "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406/geoChunked.zarr/thetao/11.24.35.49"
)


# ---------------------------------------------------------------------------
# Recorded-fixture transport
# ---------------------------------------------------------------------------

def _strip_cop(url: str) -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("x-cop-")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def _load_fixtures() -> dict[str, tuple[int, str, bytes]]:
    index = json.loads((FIXTURES / "index.json").read_text())
    return {
        e["url"]: (e["status"], e["content_type"], (FIXTURES / e["file"]).read_bytes())
        for e in index["responses"]
    }


_RECORDED = _load_fixtures()


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self, override: Optional[Callable[[httpx.Request], Optional[httpx.Response]]] = None):
        self.override = override
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.override is not None:
            resp = self.override(request)
            if resp is not None:
                return resp
        key = _strip_cop(str(request.url))
        if request.method == "GET" and key in _RECORDED:
            status, ctype, body = _RECORDED[key]
            return httpx.Response(status, headers={"content-type": ctype}, content=body)
        raise httpx.ConnectError(f"no recorded fixture for {request.method} {key}", request=request)


def _factory(transport: FixtureTransport):
    return lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout)


def _fail_hosts(*hosts: str):
    def override(request: httpx.Request):
        if request.url.host in hosts:
            raise httpx.ConnectError("simulated outage", request=request)
        return None
    return override


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    providers.clear_caches()
    s = get_settings()
    monkeypatch.setattr(s, "environment_provider_retries", 0)
    monkeypatch.setattr(s, "copernicus_marine_username", "")
    monkeypatch.setattr(s, "copernicus_marine_password", "")
    monkeypatch.setattr(env_http.asyncio, "sleep", AsyncMock())  # no real back-off waits
    yield
    providers.clear_caches()


@pytest.fixture
def transport(monkeypatch):
    t = FixtureTransport()
    monkeypatch.setattr(service, "_client_factory", _factory(t))
    return t


def _query(depth=None, day=None) -> LookupQuery:
    return LookupQuery(latitude=15.6, longitude=82.3, collected_at=WHEN,
                       day=day or WHEN.date(), depth_m=depth)


def _ctx(transport: FixtureTransport, **kw) -> tuple[httpx.AsyncClient, ProviderContext]:
    client = httpx.AsyncClient(transport=transport, timeout=15)
    return client, ProviderContext(client=client, retries=0, max_distance_km=30, **kw)


# ---------------------------------------------------------------------------
# In-memory Mongo ($set / $setOnInsert / upsert; equality filters)
# ---------------------------------------------------------------------------

class _Collection:
    def __init__(self):
        self.docs: list[dict] = []

    @staticmethod
    def _match(doc, flt):
        return all(doc.get(k) == v for k, v in flt.items())

    async def find_one(self, flt):
        for d in self.docs:
            if self._match(d, flt):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if self._match(d, flt):
                d.update(copy.deepcopy(update.get("$set", {})))
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        new = {k: v for k, v in flt.items()}
        new.update(copy.deepcopy(update.get("$setOnInsert", {})))
        new.update(copy.deepcopy(update.get("$set", {})))
        self.docs.append(new)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id="new")


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def fake_db():
    db = _FakeDb()
    with patch.object(_mongo_module, "_db", db):
        yield db


def _upload(upload_id="upl_env1", user_id=OWNER, lat=15.6012, lon=82.2987, **extra):
    doc = {
        "upload_id": upload_id, "user_id": user_id, "original_filename": "s.fasta",
        "file_size_bytes": 10, "status": "stored",
        "collected_at": datetime(2026, 10, 1, 6, 0),  # naive UTC, as Mongo returns it
        "latitude": lat, "longitude": lon, "depth_meters": None,
    }
    doc.update(extra)
    return doc


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Providers against recorded responses
# ---------------------------------------------------------------------------

class TestCopernicusMarine:
    async def test_surface_values_match_the_live_recording(self):
        t = FixtureTransport()
        client, ctx = _ctx(t)
        async with client:
            temp = await providers.COPERNICUS.fetch("temperature", _query(), ctx)
            sal = await providers.COPERNICUS.fetch("salinity", _query(), ctx)
            do = await providers.COPERNICUS.fetch("dissolved_oxygen", _query(), ctx)
            ph = await providers.COPERNICUS.fetch("ph", _query(), ctx)
            cur = await providers.COPERNICUS.fetch("current", _query(), ctx)

        # Same numbers as docs/specs/q5_environmental_sources.md V2, V4-V7.
        assert (temp.value, temp.unit) == (30.2808, "°C")
        assert temp.dataset_id == "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406"
        assert temp.product_id == "GLOBAL_ANALYSISFORECAST_PHY_001_024"
        assert temp.query_url == THETAO_SURFACE_CHUNK
        gp = temp.grid_point
        assert (gp.latitude, gp.longitude, gp.depth_m, gp.time) == (15.58334, 82.33334, 0.494, "2026-10-01T00:00:00Z")
        assert gp.distance_km == pytest.approx(4.02, abs=0.01)
        assert temp.access == "anonymous_arco" and "undocumented" in temp.note
        assert temp.retrieved_at.tzinfo is not None
        assert temp.attribution == "E.U. Copernicus Marine Service Information"

        assert (sal.value, sal.unit, sal.source_variable) == (30.787, "PSU", "so")
        assert (do.value, do.unit) == (6.6309, "mg/L")
        assert (do.raw_value, do.raw_unit) == (207.2282, "mmol m-3")
        assert (do.grid_point.latitude, do.grid_point.longitude) == (15.5, 82.25)  # 0.25° BGC grid
        assert ph.value == 8.0317

        assert (cur.value, cur.unit, cur.source_variable) == (0.3516, "m/s", "uo,vo")
        assert cur.details["uo_m_s"] == -0.3439 and cur.details["vo_m_s"] == -0.0728
        assert cur.details["direction_deg"] == 258.1  # heading WSW
        assert [s["date"] for s in cur.series] == [f"2026-09-{d}" for d in range(25, 31)] + ["2026-10-01"]
        assert cur.series[-1]["speed"] == 0.3516

    async def test_sample_depth_and_temperature_profile(self):
        t = FixtureTransport()
        client, ctx = _ctx(t)
        async with client:
            temp = await providers.COPERNICUS.fetch("temperature", _query(depth=50), ctx)
            do = await providers.COPERNICUS.fetch("dissolved_oxygen", _query(depth=50), ctx)
        assert temp.value == 23.6626 and temp.grid_point.depth_m == 47.374
        assert [(p["level"], p["depth_m"], p["value"]) for p in temp.details["profile"]] == [
            ("surface", 0.494, 30.2808), ("mid", 25.211, 27.7152), ("sample_depth", 47.374, 23.6626),
        ]
        assert do.value == 3.7294 and do.raw_value == 116.5501

    async def test_land_cell_is_unavailable_never_estimated(self):
        def override(request):
            if _strip_cop(str(request.url)) == THETAO_SURFACE_CHUNK:
                return httpx.Response(404)  # Zarr: missing chunk = all fill
            return None
        client, ctx = _ctx(FixtureTransport(override))
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.COPERNICUS.fetch("temperature", _query(), ctx)
        assert exc.value.reason.startswith("no valid model cell within 30 km")
        assert exc.value.transient is False

    async def test_nearest_ocean_cell_is_used_when_the_exact_cell_is_land(self):
        status, ctype, body = _RECORDED[THETAO_SURFACE_CHUNK]
        t = FixtureTransport()
        client, ctx = _ctx(t)
        async with client:
            href = await providers.resolve_geo_href(ctx, providers.PHY_THETAO_ANFC)
            ds = await zarr_point.load_dataset(client, href, retries=0)
        zarray = ds.meta["thetao/.zarray"]
        arr = np.frombuffer(blosc.decompress(body), dtype="<f4").reshape(zarray["chunks"]).copy()
        target = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
        ti = int(np.argmin(np.abs(ds.times - target))) % 134
        yi = int(np.argmin(np.abs(ds.lat - 15.6))) % 32
        xi = int(np.argmin(np.abs(ds.lon - 82.3))) % 64
        arr[ti, 1, yi, xi] = np.nan  # level index 49 is local index 1 in its 2-level chunk
        land_body = blosc.compress(arr.tobytes(), typesize=4, cname="lz4", clevel=5, shuffle=1)

        def override(request):
            if _strip_cop(str(request.url)) == THETAO_SURFACE_CHUNK:
                return httpx.Response(200, content=land_body)
            return None
        providers.clear_caches()
        client, ctx = _ctx(FixtureTransport(override))
        async with client:
            temp = await providers.COPERNICUS.fetch("temperature", _query(), ctx)
        assert (temp.grid_point.latitude, temp.grid_point.longitude) != (15.58334, 82.33334)
        assert 4.02 < temp.grid_point.distance_km <= 30
        assert 25 < temp.value < 35  # a real neighbouring cell value, not a fill

    async def test_date_outside_every_dataset(self):
        client, ctx = _ctx(FixtureTransport())
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.COPERNICUS.fetch("ph", _query(day=date(2019, 1, 1)), ctx)
        assert "outside the dataset time axis (2021-11-01 to" in exc.value.reason
        assert exc.value.transient is False  # safe to cache: the answer will not change

    async def test_network_failure_is_transient_and_named(self):
        client, ctx = _ctx(FixtureTransport(_fail_hosts("s3.waw3-1.cloudferro.com")))
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.COPERNICUS.fetch("salinity", _query(), ctx)
        assert exc.value.transient is True
        assert "network error (ConnectError" in exc.value.reason

    async def test_verified_credentials_tag_reads_like_the_toolbox(self):
        def override(request):
            if request.url.host == "auth.marine.copernicus.eu":
                if request.method == "POST":
                    assert b"grant_type=password" in request.content
                    return httpx.Response(200, json={"access_token": "tok"})
                assert request.headers["Authorization"] == "Bearer tok"
                return httpx.Response(200, json={"preferred_username": "alice"})
            return None
        t = FixtureTransport(override)
        client, ctx = _ctx(t, copernicus_username="alice", copernicus_password="s3cret")
        async with client:
            temp = await providers.COPERNICUS.fetch("temperature", _query(), ctx)
        assert temp.access == "authenticated_arco" and temp.note is None
        chunk_reqs = [r for r in t.requests if r.url.path.endswith("thetao/11.24.35.49")]
        assert chunk_reqs and chunk_reqs[0].url.params["x-cop-user"] == "alice"
        dumped = temp.model_dump_json()
        assert "s3cret" not in dumped and "x-cop-user" not in temp.query_url

    async def test_rejected_credentials_fall_back_to_anonymous_with_a_note(self):
        def override(request):
            if request.url.host == "auth.marine.copernicus.eu":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return None
        client, ctx = _ctx(FixtureTransport(override), copernicus_username="bob", copernicus_password="x")
        async with client:
            temp = await providers.COPERNICUS.fetch("temperature", _query(), ctx)
        assert temp.access == "anonymous_arco"
        assert "rejected" in temp.note
        assert temp.value == 30.2808


class TestOtherProviders:
    async def test_oisst_on_ncei_erddap(self):
        client, ctx = _ctx(FixtureTransport())
        async with client:
            v = await providers.OISST.fetch("temperature", _query(), ctx)
        assert (v.value, v.unit, v.provider) == (29.86, "°C", "noaa_erddap")
        assert v.dataset_id == "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon"
        assert v.query_url.startswith("https://www.ncei.noaa.gov/erddap/griddap/")
        assert (v.grid_point.latitude, v.grid_point.longitude) == (15.625, 82.375)
        assert v.grid_point.time == "2026-10-01T12:00:00Z"

    async def test_oisst_refuses_a_deep_sample(self):
        t = FixtureTransport()
        client, ctx = _ctx(t)
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.OISST.fetch("temperature", _query(depth=50), ctx)
        assert "sea-surface only" in exc.value.reason
        assert t.requests == []

    async def test_era5_wind_via_open_meteo(self):
        client, ctx = _ctx(FixtureTransport())
        async with client:
            v = await providers.ERA5_WIND.fetch("wind", _query(), ctx)
        assert (v.value, v.unit, v.kind) == (1.85, "m/s", "reanalysis")
        assert v.details["direction_deg"] == 177
        assert v.grid_point.time == "2026-10-01T06:00:00Z"  # hour nearest collected_at
        assert len(v.series) == 7 and v.series[-1] == {"date": "2026-10-01", "mean": 1.763, "max": 2.34, "hours": 24}
        assert "non-commercial" in v.note
        assert "archive-api.open-meteo.com/v1/era5" in v.query_url

    async def test_open_meteo_marine_current_fallback(self):
        client, ctx = _ctx(FixtureTransport())
        async with client:
            v = await providers.MARINE_CURRENT.fetch("current", _query(), ctx)
        assert (v.value, v.unit) == (0.4167, "m/s")
        assert (v.raw_value, v.raw_unit) == (1.5, "km/h")

    async def test_open_meteo_error_payload(self):
        def override(request):
            if request.url.host == "archive-api.open-meteo.com":
                return httpx.Response(200, json={"error": True, "reason": "Latitude must be in range"})
            return None
        client, ctx = _ctx(FixtureTransport(override))
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.ERA5_WIND.fetch("wind", _query(), ctx)
        assert "Latitude must be in range" in exc.value.reason

    async def test_retries_are_bounded(self):
        calls = []

        def override(request):
            if request.url.host == "archive-api.open-meteo.com":
                calls.append(1)
                return httpx.Response(503)
            return None
        client = httpx.AsyncClient(transport=FixtureTransport(override), timeout=15)
        ctx = ProviderContext(client=client, retries=2, max_distance_km=30)
        async with client:
            with pytest.raises(ProviderUnavailable) as exc:
                await providers.ERA5_WIND.fetch("wind", _query(), ctx)
        assert len(calls) == 3 and exc.value.transient is True
        assert "HTTP 503 after 3 attempt(s)" in exc.value.reason


# ---------------------------------------------------------------------------
# Service: fallbacks, cache, precedence
# ---------------------------------------------------------------------------

class TestLookupService:
    async def test_cache_miss_then_hit_for_a_nearby_upload(self, fake_db, transport):
        fake_db["uploads"].docs += [_upload("upl_a"), _upload("upl_b", lat=15.6049, lon=82.3021)]

        await service.run_lookup("upl_a")
        doc_a = fake_db[service.CONTEXTS].docs[0]
        assert doc_a["status"] == "complete" and doc_a["cache_hit"] is False
        assert doc_a["cache_key"] == "v1:15.60:82.30:2026-10-01:surface"
        cached = fake_db[service.CACHE].docs
        assert len(cached) == 1 and cached[0]["expires_at"] is None  # date > 14 days old: permanent
        n_requests = len(transport.requests)
        assert n_requests > 0

        await service.run_lookup("upl_b")  # rounds to the same 15.60/82.30 key
        doc_b = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_b"})
        assert doc_b["cache_hit"] is True and doc_b["status"] == "complete"
        assert len(transport.requests) == n_requests  # no API was hit again
        assert doc_b["public"] == doc_a["public"]

    async def test_force_refresh_bypasses_the_shared_cache(self, fake_db, transport):
        fake_db["uploads"].docs.append(_upload("upl_a"))
        await service.run_lookup("upl_a")
        n = len(transport.requests)
        await service.run_lookup("upl_a", force=True)
        assert len(transport.requests) > n
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        assert doc["cache_hit"] is False

    async def test_expired_cache_entry_is_ignored(self, fake_db, transport):
        fake_db["uploads"].docs.append(_upload("upl_a"))
        fake_db[service.CACHE].docs.append({
            "cache_key": "v1:15.60:82.30:2026-10-01:surface", "public": {"stale": True},
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        })
        await service.run_lookup("upl_a")
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        assert doc["cache_hit"] is False and "stale" not in doc["public"]

    def test_cache_expiry_rule(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        recent = LookupQuery(15.6, 82.3, WHEN, date(2026, 10, 10), None)  # forecast/ERA5T may still change
        assert service._cache_expiry(recent, now) == now + timedelta(hours=24)
        old = LookupQuery(15.6, 82.3, WHEN, date(2026, 10, 1), None)  # > 14 days: kept for good
        assert service._cache_expiry(old, now) is None

    async def test_fallbacks_and_transient_failures(self, fake_db, monkeypatch):
        # Copernicus and Open-Meteo archive down: temperature falls back to
        # OISST, current to Open-Meteo Marine; salinity/DO/pH/wind unavailable.
        t = FixtureTransport(_fail_hosts("s3.waw3-1.cloudferro.com", "archive-api.open-meteo.com"))
        monkeypatch.setattr(service, "_client_factory", _factory(t))
        fake_db["uploads"].docs.append(_upload("upl_a"))
        await service.run_lookup("upl_a")

        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        pub = doc["public"]
        assert doc["status"] == "partial"
        assert pub["temperature"]["value"]["provider"] == "noaa_erddap"
        assert [a["provider"] for a in pub["temperature"]["attempts"]] == ["copernicus_marine", "noaa_erddap"]
        assert pub["current"]["value"]["provider"] == "open_meteo_marine"
        for var in ("salinity", "dissolved_oxygen", "ph", "wind"):
            assert pub[var]["status"] == "unavailable" and pub[var]["value"] is None
            assert "network error" in pub[var]["reason"]
        assert fake_db[service.CACHE].docs == []  # transient: not cached

    async def test_provider_crash_is_contained(self, fake_db, transport, monkeypatch):
        async def boom(*a, **k):
            raise ZeroDivisionError("bug")
        monkeypatch.setattr(providers.ERA5_WIND, "fetch", boom)
        fake_db["uploads"].docs.append(_upload("upl_a"))
        await service.run_lookup("upl_a")
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        assert doc["status"] == "partial"
        assert doc["public"]["wind"]["reason"].startswith("open_meteo: provider error (ZeroDivisionError")
        assert doc["public"]["temperature"]["status"] == "ok"

    async def test_run_lookup_never_raises(self, fake_db, monkeypatch):
        monkeypatch.setattr(service, "fetch_public", AsyncMock(side_effect=RuntimeError("db gone")))
        fake_db["uploads"].docs.append(_upload("upl_a"))
        await service.run_lookup("upl_a")  # must not raise
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        assert doc["status"] == "failed" and "RuntimeError: db gone" in doc["error"]

    async def test_user_values_take_precedence_public_kept_alongside(self, fake_db, transport):
        up = _upload("upl_a", dissolved_oxygen_mg_l=6.8, ph=8.1)
        fake_db["uploads"].docs.append(up)
        await service.run_lookup("upl_a")
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": "upl_a"})
        resp = service.build_response(up, doc)

        do = resp.variables["dissolved_oxygen"]
        assert (do.status, do.value, do.unit, do.value_source) == ("user_provided", 6.8, "mg/L", "user")
        assert do.user_value.field == "dissolved_oxygen_mg_l"
        assert do.public_status == "ok" and do.public.value == 6.6309
        ph = resp.variables["ph"]
        assert (ph.status, ph.value, ph.public.value) == ("user_provided", 8.1, 8.0317)
        temp = resp.variables["temperature"]
        assert (temp.status, temp.value, temp.value_source) == ("ok", 30.2808, "public")
        # The stored public values were not overwritten by the user's.
        assert doc["public"]["dissolved_oxygen"]["value"]["value"] == 6.6309
        assert {s.provider for s in resp.sources} == {"copernicus_marine", "open_meteo"}
        assert resp.status == "complete" and resp.cache_hit is False

    async def test_upload_without_coordinates_is_not_applicable(self, fake_db, transport):
        up = _upload("upl_a", latitude=None, longitude=None, ph=7.9)
        fake_db["uploads"].docs.append(up)
        await service.run_lookup("upl_a")
        assert transport.requests == [] and fake_db[service.CONTEXTS].docs == []
        resp = service.build_response(up, None)
        assert resp.status == "not_applicable" and "latitude, longitude" in resp.reason
        assert resp.variables["ph"].status == "user_provided"
        assert resp.variables["salinity"].status == "unavailable"
        assert resp.variables["salinity"].public_status == "not_applicable"


# ---------------------------------------------------------------------------
# Endpoints and the upload trigger
# ---------------------------------------------------------------------------

@pytest.fixture
def other_token():
    return create_access_token("usr_other", {"email": "o@example.com", "role": UserRole.researcher})


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment_context_enabled", True)


class TestEndpoints:
    async def _seed_complete(self, fake_db, transport, **extra):
        fake_db["uploads"].docs.append(_upload("upl_a", **extra))
        await service.run_lookup("upl_a")

    async def test_owner_gets_the_cached_context(self, client, fake_db, transport, researcher_token):
        await self._seed_complete(fake_db, transport, ph=8.1)
        r = await client.get("/environment/uploads/upl_a", headers=_auth(researcher_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "complete"
        assert body["variables"]["temperature"]["public"]["query_url"] == THETAO_SURFACE_CHUNK
        assert body["variables"]["ph"]["status"] == "user_provided"
        assert body["variables"]["wind"]["value"] == 1.85
        assert body["query"]["lookup_latitude"] == 15.6 and body["query"]["latitude"] == 15.6012

    async def test_access_rules_match_get_upload(self, client, fake_db, transport, researcher_token,
                                                 other_token, admin_token):
        await self._seed_complete(fake_db, transport)
        url = "/environment/uploads/upl_a"
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=_auth(other_token))).status_code == 403
        assert (await client.get(url, headers=_auth(admin_token))).status_code == 200
        r = await client.get("/environment/uploads/upl_nope", headers=_auth(researcher_token))
        assert r.status_code == 404

    async def test_missing_context_schedules_one_lookup(self, client, fake_db, researcher_token,
                                                        enabled, monkeypatch):
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        fake_db["uploads"].docs.append(_upload("upl_a"))
        r1 = await client.get("/environment/uploads/upl_a", headers=_auth(researcher_token))
        r2 = await client.get("/environment/uploads/upl_a", headers=_auth(researcher_token))
        assert r1.json()["status"] == "pending" and r2.json()["status"] == "pending"
        assert r1.json()["variables"]["temperature"]["public_status"] == "pending"
        run.assert_awaited_once_with("upl_a")

    async def test_stale_pending_or_moved_upload_is_looked_up_again(self, client, fake_db, transport,
                                                                    researcher_token, enabled, monkeypatch):
        await self._seed_complete(fake_db, transport)
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        url = "/environment/uploads/upl_a"
        assert (await client.get(url, headers=_auth(researcher_token))).json()["status"] == "complete"
        run.assert_not_awaited()

        # Coordinates corrected after the lookup: the cached context no longer applies.
        fake_db["uploads"].docs[0]["latitude"] = 16.2
        assert (await client.get(url, headers=_auth(researcher_token))).json()["status"] == "pending"
        assert run.await_count == 1

        # A lookup left "pending" by a dead process is re-run after STALE_PENDING.
        ctx_doc = fake_db[service.CONTEXTS].docs[0]
        ctx_doc["requested_at"] = datetime.now(timezone.utc) - timedelta(minutes=11)
        await client.get(url, headers=_auth(researcher_token))
        assert run.await_count == 2

    async def test_disabled_server_says_so(self, client, fake_db, researcher_token, monkeypatch):
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        fake_db["uploads"].docs.append(_upload("upl_a"))
        r = await client.get("/environment/uploads/upl_a", headers=_auth(researcher_token))
        assert r.json()["status"] == "pending" and "disabled" in r.json()["reason"]
        run.assert_not_awaited()

    async def test_refresh_is_admin_only(self, client, fake_db, researcher_token, admin_token, monkeypatch):
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        fake_db["uploads"].docs += [_upload("upl_a"), _upload("upl_nocoord", latitude=None, longitude=None)]
        url = "/environment/uploads/upl_a/refresh"
        assert (await client.post(url, headers=_auth(researcher_token))).status_code == 403
        r = await client.post(url, headers=_auth(admin_token))
        assert r.status_code == 202 and r.json()["status"] == "pending"
        run.assert_awaited_once_with("upl_a", force=True)
        r = await client.post("/environment/uploads/upl_nocoord/refresh", headers=_auth(admin_token))
        assert r.status_code == 422


class TestUploadTrigger:
    FORM = {"latitude": "15.6012", "longitude": "82.2987", "collected_at": "2026-10-01T06:00:00Z"}

    async def _post(self, client, token, data):
        return await client.post(
            "/uploads", files={"file": ("s.fasta", BytesIO(b">a\nACGT\n"), "text/plain")},
            data=data, headers=_auth(token),
        )

    @pytest.fixture
    def storage_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(get_settings(), "upload_storage_dir", str(tmp_path))

    async def test_upload_with_coordinates_and_date_schedules_the_lookup(
            self, client, fake_db, storage_dir, researcher_token, enabled, monkeypatch):
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        r = await self._post(client, researcher_token, self.FORM)
        assert r.status_code == 201
        run.assert_awaited_once_with(r.json()["upload_id"])

    @pytest.mark.parametrize("drop", ["latitude", "collected_at"])
    async def test_no_lookup_without_coordinates_or_date(
            self, client, fake_db, storage_dir, researcher_token, enabled, monkeypatch, drop):
        run = AsyncMock()
        monkeypatch.setattr(service, "run_lookup", run)
        form = {k: v for k, v in self.FORM.items() if k != drop and not (drop == "latitude" and k == "longitude")}
        assert (await self._post(client, researcher_token, form)).status_code == 201
        run.assert_not_awaited()

    async def test_end_to_end_upload_then_get(self, client, fake_db, storage_dir, transport,
                                              researcher_token, enabled):
        r = await self._post(client, researcher_token, {**self.FORM, "dissolved_oxygen_mg_l": "6.1"})
        assert r.status_code == 201
        upload_id = r.json()["upload_id"]
        # ASGITransport waits for the background task, so the lookup is done.
        g = await client.get(f"/environment/uploads/{upload_id}", headers=_auth(researcher_token))
        body = g.json()
        assert body["status"] == "complete", body
        assert body["variables"]["dissolved_oxygen"]["status"] == "user_provided"
        assert body["variables"]["dissolved_oxygen"]["public"]["value"] == 6.6309
        assert body["variables"]["salinity"]["value"] == 30.787
        assert body["variables"]["current"]["public"]["details"]["direction_deg"] == 258.1

    async def test_lookup_failure_never_fails_the_upload(
            self, client, fake_db, storage_dir, researcher_token, enabled, monkeypatch):
        monkeypatch.setattr(service, "fetch_public", AsyncMock(side_effect=OSError("network down")))
        r = await self._post(client, researcher_token, self.FORM)
        assert r.status_code == 201
        doc = await fake_db[service.CONTEXTS].find_one({"upload_id": r.json()["upload_id"]})
        assert doc["status"] == "failed"
