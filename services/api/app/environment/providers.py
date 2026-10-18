"""
Public-data providers for the environmental-context service (Q5, t-1026-1).

Sources, URLs and the fallback order follow docs/specs/q5_environmental_sources.md
(verified 2026-10-18):

  temperature       Copernicus Marine thetao (V2/V3)  -> NOAA OISST on NCEI ERDDAP (V1, surface only)
  salinity          Copernicus Marine so (V7)
  dissolved_oxygen  Copernicus Marine o2 (V5), mmol m-3 -> mg/L
  ph                Copernicus Marine ph (V6)
  current           Copernicus Marine uo/vo (V4)      -> Open-Meteo Marine (V11)
  wind              ECMWF ERA5 via Open-Meteo (V8)

Each provider either returns a PublicValue (value + unit + source + dataset +
exact query URL + grid cell used + retrieved_at) or raises
ProviderUnavailable with a reason. Nothing is ever estimated.
"""
from __future__ import annotations

import logging
import math
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Protocol
from urllib.parse import quote, urlencode

import httpx

from .http import ProviderUnavailable, get_with_retry
from .models import GridPoint, PublicValue, SourceInfo
from . import zarr_point

logger = logging.getLogger("app.environment")

# By-day panels (A6 wind, A7 current) show the 7 days ending at collected_at.
SERIES_DAYS = 7
# OISST is a sea-surface product: never use it for a sample deeper than this.
SURFACE_MAX_DEPTH_M = 5.0
# mmol m-3 of O2 -> mg/L (molar mass of O2 = 31.998 g/mol). Q5 A1.
O2_MMOL_M3_TO_MG_L = 0.031998


@dataclass
class LookupQuery:
    latitude: float
    longitude: float
    collected_at: datetime  # UTC-aware
    day: date
    depth_m: Optional[float]  # None -> surface


@dataclass
class ProviderContext:
    client: httpx.AsyncClient
    retries: int
    max_distance_km: float
    copernicus_username: str = ""
    copernicus_password: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Provider(Protocol):
    name: str
    variables: frozenset[str]
    info: SourceInfo

    async def fetch(self, variable: str, q: LookupQuery, ctx: ProviderContext) -> PublicValue: ...


# ---------------------------------------------------------------------------
# Copernicus Marine (ARCO Zarr)
# ---------------------------------------------------------------------------

STAC_ROOT = "https://stac.marine.copernicus.eu/metadata"
CAS_TOKEN_URL = "https://auth.marine.copernicus.eu/realms/MIS/protocol/openid-connect/token"
CAS_USERINFO_URL = "https://auth.marine.copernicus.eu/realms/MIS/protocol/openid-connect/userinfo"
_ARCO = "https://s3.waw3-1.cloudferro.com"


@dataclass(frozen=True)
class CmemsDataset:
    product_id: str
    dataset_id: str
    # geoChunked href as listed by STAC on 2026-10-18; used only when the STAC
    # lookup itself fails (the bucket number changes between dataset versions).
    fallback_href: str
    kind: str = "modelled"


def _ds(product, dataset, bucket):
    return CmemsDataset(product, dataset, f"{_ARCO}/{bucket}/arco/{product}/{dataset}/geoChunked.zarr")


PHY_THETAO_ANFC = _ds("GLOBAL_ANALYSISFORECAST_PHY_001_024", "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406", "mdl-arco-geo-012")
PHY_SO_ANFC = _ds("GLOBAL_ANALYSISFORECAST_PHY_001_024", "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m_202406", "mdl-arco-geo-010")
PHY_CUR_ANFC = _ds("GLOBAL_ANALYSISFORECAST_PHY_001_024", "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406", "mdl-arco-geo-007")
BGC_BIO_ANFC = _ds("GLOBAL_ANALYSISFORECAST_BGC_001_028", "cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m_202311", "mdl-arco-geo-006")
BGC_CAR_ANFC = _ds("GLOBAL_ANALYSISFORECAST_BGC_001_028", "cmems_mod_glo_bgc-car_anfc_0.25deg_P1D-m_202311", "mdl-arco-geo-006")
# Reanalysis for dates before the analysis/forecast axes start (PHY 2022-06-01,
# BGC 2021-11-01). The multiyear BGC daily dataset has no pH.
PHY_MY = _ds("GLOBAL_MULTIYEAR_PHY_001_030", "cmems_mod_glo_phy_my_0.083deg_P1D-m_202311", "mdl-arco-geo-025")
BGC_MY = _ds("GLOBAL_MULTIYEAR_BGC_001_029", "cmems_mod_glo_bgc_my_0.25deg_P1D-m_202406", "mdl-arco-geo-018")

# variable -> [(source variable(s), dataset)], tried in order.
CMEMS_CANDIDATES: dict[str, list[tuple[tuple[str, ...], CmemsDataset]]] = {
    "temperature": [(("thetao",), PHY_THETAO_ANFC), (("thetao",), PHY_MY)],
    "salinity": [(("so",), PHY_SO_ANFC), (("so",), PHY_MY)],
    "dissolved_oxygen": [(("o2",), BGC_BIO_ANFC), (("o2",), BGC_MY)],
    "ph": [(("ph",), BGC_CAR_ANFC)],
    "current": [(("uo", "vo"), PHY_CUR_ANFC), (("uo", "vo"), PHY_MY)],
}

_STAC_TTL_S = 24 * 3600
_stac_cache: dict[str, tuple[float, str]] = {}
_CAS_TTL_S = 12 * 3600
_cas_cache: dict[str, tuple[float, Optional[str], str]] = {}


def clear_caches() -> None:
    _stac_cache.clear()
    _cas_cache.clear()
    zarr_point.clear_caches()


async def resolve_geo_href(ctx: ProviderContext, ds: CmemsDataset) -> str:
    """geoChunked Zarr URL from the dataset's STAC item; hard-coded fallback."""
    cached = _stac_cache.get(ds.dataset_id)
    if cached and _time.monotonic() - cached[0] < _STAC_TTL_S:
        return cached[1]
    url = f"{STAC_ROOT}/{ds.product_id}/{ds.dataset_id}/dataset.stac.json"
    try:
        resp = await get_with_retry(ctx.client, url, retries=ctx.retries, what="Copernicus Marine STAC")
        href = resp.json()["assets"]["geoChunked"]["href"]
    except (ProviderUnavailable, KeyError, ValueError, TypeError) as exc:
        logger.warning("Copernicus Marine STAC lookup failed for %s (%s); using the href recorded on 2026-10-18",
                       ds.dataset_id, getattr(exc, "reason", exc))
        return ds.fallback_href
    _stac_cache[ds.dataset_id] = (_time.monotonic(), href)
    return href


async def copernicus_access(ctx: ProviderContext) -> tuple[dict[str, str], str, Optional[str]]:
    """(query params for ARCO reads, access label, note).

    Mirrors the official `copernicusmarine` toolbox (v2.5.0,
    core_functions/credentials_utils.py and utils.py): credentials are checked
    against the Copernicus Marine auth server, and data reads carry
    x-cop-client / x-cop-user query parameters. The ARCO bytes are the same
    either way. Without credentials (or if they are rejected) the read is
    anonymous, which worked on 2026-10-18 but is undocumented (Q5 V2).
    """
    base = {"x-cop-client": "synth-veda-api"}
    user, pwd = ctx.copernicus_username, ctx.copernicus_password
    if not (user and pwd):
        return base, "anonymous_arco", "Anonymous read of the public ARCO store (undocumented access path, Q5 V2)."

    cached = _cas_cache.get(user)
    if cached and _time.monotonic() - cached[0] < _CAS_TTL_S:
        verified, note = cached[1], cached[2]
    else:
        verified, note = None, ""
        try:
            resp = await ctx.client.post(CAS_TOKEN_URL, data={
                "client_id": "toolbox", "grant_type": "password",
                "username": user, "password": pwd, "scope": "openid profile email",
            })
            if resp.status_code == 200:
                token = resp.json()["access_token"]
                info = await ctx.client.get(CAS_USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
                info.raise_for_status()
                verified = info.json().get("preferred_username") or user
            elif resp.status_code == 400 and "invalid_grant" in resp.text:
                note = "COPERNICUS_MARINE credentials were rejected by auth.marine.copernicus.eu"
                logger.error("ENV LOOKUP: %s; reading ARCO anonymously", note)
            else:
                note = f"Copernicus Marine auth check returned HTTP {resp.status_code}"
                logger.error("ENV LOOKUP: %s; reading ARCO anonymously", note)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            note = f"Copernicus Marine auth check failed ({type(exc).__name__})"
            logger.error("ENV LOOKUP NETWORK ERROR: %s; reading ARCO anonymously", note)
        _cas_cache[user] = (_time.monotonic(), verified, note)

    if verified:
        return {**base, "x-cop-user": verified}, "authenticated_arco", None
    return base, "anonymous_arco", f"{note}; anonymous read of the public ARCO store (undocumented, Q5 V2)."


class CopernicusMarineProvider:
    name = "copernicus_marine"
    variables = frozenset(CMEMS_CANDIDATES)
    info = SourceInfo(
        provider=name,
        source="Copernicus Marine Service",
        licence="Copernicus Marine Service licence: free of charge, attribution required",
        attribution="E.U. Copernicus Marine Service Information",
        terms_note="Supported access needs a free Copernicus Marine account (COPERNICUS_MARINE_USERNAME/PASSWORD).",
    )

    async def fetch(self, variable: str, q: LookupQuery, ctx: ProviderContext) -> PublicValue:
        params, access, access_note = await copernicus_access(ctx)
        reasons: list[str] = []
        transient = False
        for src_vars, ds in CMEMS_CANDIDATES[variable]:
            try:
                return await self._fetch_from(variable, src_vars, ds, q, ctx, params, access, access_note)
            except ProviderUnavailable as exc:
                if exc.reason.startswith("no valid model cell"):
                    raise  # same grid in the other dataset; do not paper over it
                reasons.append(f"{ds.dataset_id}: {exc.reason}")
                transient = transient or exc.transient
        raise ProviderUnavailable("; ".join(reasons), transient=transient)

    async def _fetch_from(self, variable, src_vars, ds, q, ctx, params, access, access_note) -> PublicValue:
        href = await resolve_geo_href(ctx, ds)
        meta = await zarr_point.load_dataset(ctx.client, href, params=params, retries=ctx.retries)
        window = SERIES_DAYS if variable == "current" else 1
        depth = None if variable == "current" else q.depth_m

        async def read(v, d, win=1):
            return await zarr_point.read_point(
                ctx.client, meta, v, latitude=q.latitude, longitude=q.longitude, day=q.day,
                depth_m=d, max_distance_km=ctx.max_distance_km, window_days=win,
                params=params, retries=ctx.retries,
            )

        def no_cell(p):
            where = f"{p.depth_m} m" if p.depth_m is not None else "the surface"
            return ProviderUnavailable(
                f"no valid model cell within {ctx.max_distance_km:g} km at {where} on {q.day.isoformat()} "
                f"(nearest cell {p.latitude}, {p.longitude} is land or below the model seafloor)"
            )

        common = dict(
            provider=self.name, source=self.info.source, product_id=ds.product_id,
            dataset_id=ds.dataset_id, retrieved_at=_now(), access=access, kind=ds.kind,
            licence=self.info.licence, attribution=self.info.attribution, note=access_note,
        )

        if variable == "current":
            pu = await read("uo", None, window)
            pv = await read("vo", None, window)
            if pu.value is None or pv.value is None:
                raise no_cell(pu)
            speed = math.hypot(pu.value, pv.value)
            series = []
            vseries = dict(pv.series)
            for day_iso, u in pu.series:
                v = vseries.get(day_iso)
                series.append({"date": day_iso,
                               "speed": round(math.hypot(u, v), 4) if u is not None and v is not None else None})
            return PublicValue(
                value=round(speed, 4), unit="m/s", source_variable="uo,vo", query_url=pu.chunk_url,
                grid_point=_grid(pu),
                details={"uo_m_s": round(pu.value, 4), "vo_m_s": round(pv.value, 4),
                         "direction_deg": round(_bearing_toward(pu.value, pv.value), 1),
                         "direction_convention": "toward (oceanographic)",
                         "query_urls": [pu.chunk_url, pv.chunk_url]},
                series=series, **common,
            )

        (src,) = src_vars
        p = await read(src, depth)
        if p.value is None:
            raise no_cell(p)
        details: dict = {}
        raw_value = raw_unit = None
        value, unit = p.value, p.units
        if variable == "temperature":
            unit = "°C"
            if q.depth_m is not None:
                details["profile"] = await self._profile(read, q.depth_m)
        elif variable == "salinity":
            unit = "PSU"  # CMEMS units "1e-3" (practical salinity)
            raw_unit = p.units
        elif variable == "dissolved_oxygen":
            raw_value, raw_unit = p.value, p.units or "mmol m-3"
            value, unit = p.value * O2_MMOL_M3_TO_MG_L, "mg/L"
            details["conversion"] = f"mg/L = mmol m-3 x {O2_MMOL_M3_TO_MG_L}"
        elif variable == "ph":
            unit = "pH"
            raw_unit = p.units or None
        return PublicValue(
            value=round(value, 4), unit=unit, source_variable=src, query_url=p.chunk_url,
            grid_point=_grid(p), raw_value=round(raw_value, 4) if raw_value is not None else None,
            raw_unit=raw_unit, details=details, **common,
        )

    async def _profile(self, read, depth_m: float) -> list[dict]:
        """Surface, mid and sample-depth levels (Q5 A3); null where no data."""
        levels = []
        for label, d in (("surface", None), ("mid", depth_m / 2), ("sample_depth", depth_m)):
            try:
                p = await read("thetao", d)
            except ProviderUnavailable as exc:
                levels.append({"level": label, "depth_m": None, "value": None, "reason": exc.reason})
                continue
            levels.append({"level": label, "depth_m": p.depth_m,
                           "value": round(p.value, 4) if p.value is not None else None,
                           "latitude": p.latitude, "longitude": p.longitude})
        return levels


def _grid(p: zarr_point.PointRead) -> GridPoint:
    return GridPoint(latitude=p.latitude, longitude=p.longitude, depth_m=p.depth_m,
                     time=p.time, distance_km=p.distance_km)


def _bearing_toward(u: float, v: float) -> float:
    """Compass bearing (deg) the flow heads toward, from east (u) and north (v)."""
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


# ---------------------------------------------------------------------------
# NOAA OISST v2.1 on the NCEI ERDDAP (surface temperature fallback)
# ---------------------------------------------------------------------------

NCEI_ERDDAP = "https://www.ncei.noaa.gov/erddap/griddap"
# Final first (lags ~2 weeks), then preliminary (lags ~2 days). Q5 V1.
OISST_DATASETS = ("ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon", "ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon")


class NoaaErddapOisstProvider:
    name = "noaa_erddap"
    variables = frozenset({"temperature"})
    info = SourceInfo(
        provider=name,
        source="NOAA NCEI ERDDAP (OISST v2.1)",
        licence="US public domain (NOAA)",
        attribution="NOAA NCEI Optimum Interpolation SST v2.1, via www.ncei.noaa.gov/erddap",
        terms_note="Sea-surface temperature only, 0.25°, daily.",
    )

    async def fetch(self, variable: str, q: LookupQuery, ctx: ProviderContext) -> PublicValue:
        if q.depth_m is not None and q.depth_m > SURFACE_MAX_DEPTH_M:
            raise ProviderUnavailable(
                f"OISST is sea-surface only and the sample depth is {q.depth_m:g} m")
        lon360 = q.longitude % 360.0
        stamp = f"{q.day.isoformat()}T12:00:00Z"
        constraint = f"sst[({stamp})][(0.0)][({q.latitude})][({lon360})]"
        reasons = []
        transient = False
        for dataset in OISST_DATASETS:
            url = f"{NCEI_ERDDAP}/{dataset}.json?{quote(constraint, safe='():.,-')}"
            try:
                resp = await get_with_retry(ctx.client, url, retries=ctx.retries,
                                            what="NOAA ERDDAP OISST", allow_404=True)
            except ProviderUnavailable as exc:
                reasons.append(f"{dataset}: {exc.reason}")
                transient = transient or exc.transient
                continue
            if resp.status_code == 404:
                reasons.append(f"{dataset}: no data for {q.day.isoformat()} ({_erddap_message(resp)})")
                continue
            try:
                table = resp.json()["table"]
                cols = table["columnNames"]
                row = table["rows"][0]
                rec = dict(zip(cols, row))
            except (KeyError, IndexError, ValueError) as exc:
                reasons.append(f"{dataset}: unreadable ERDDAP response ({exc})")
                continue
            if not str(rec.get("time", "")).startswith(q.day.isoformat()):
                reasons.append(f"{dataset}: nearest time step {rec.get('time')} is not {q.day.isoformat()}")
                continue
            sst = rec.get("sst")
            if sst is None or (isinstance(sst, float) and math.isnan(sst)):
                raise ProviderUnavailable(
                    f"OISST cell {rec.get('latitude')}, {rec.get('longitude')} has no SST (land or ice)")
            lon = float(rec["longitude"])
            return PublicValue(
                value=round(float(sst), 4), unit="°C", provider=self.name, source=self.info.source,
                product_id="NOAA OISST v2.1", dataset_id=dataset, source_variable="sst", query_url=url,
                grid_point=GridPoint(latitude=float(rec["latitude"]), longitude=lon - 360 if lon > 180 else lon,
                                     depth_m=0.0, time=str(rec["time"])),
                retrieved_at=_now(), access="public_api", kind="satellite_analysis",
                licence=self.info.licence, attribution=self.info.attribution,
                note="Sea-surface temperature (fallback after Copernicus Marine).",
            )
        raise ProviderUnavailable("; ".join(reasons) or "no OISST dataset answered", transient=transient)


def _erddap_message(resp: httpx.Response) -> str:
    text = " ".join(resp.text.split())
    start = text.find("message=")
    return (text[start + 8:] if start >= 0 else text)[:200]


# ---------------------------------------------------------------------------
# Open-Meteo: ERA5 wind (V8) and Marine currents fallback (V11)
# ---------------------------------------------------------------------------

OPEN_METEO_TERMS = "Open-Meteo free API: non-commercial use only (data CC BY 4.0)."


def _series_window(q: LookupQuery) -> tuple[str, str]:
    return (q.day - timedelta(days=SERIES_DAYS - 1)).isoformat(), q.day.isoformat()


def _nearest_hour_index(times: list[str], when: datetime) -> int:
    target = when.astimezone(timezone.utc).replace(tzinfo=None)
    best, best_d = 0, None
    for i, t in enumerate(times):
        d = abs((datetime.fromisoformat(t) - target).total_seconds())
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _daily(times: list[str], values: list[Optional[float]]) -> list[dict]:
    by_day: dict[str, list[float]] = {}
    for t, v in zip(times, values):
        by_day.setdefault(t[:10], [])
        if v is not None:
            by_day[t[:10]].append(float(v))
    out = []
    for d, vs in by_day.items():
        out.append({"date": d,
                    "mean": round(sum(vs) / len(vs), 3) if vs else None,
                    "max": round(max(vs), 3) if vs else None,
                    "hours": len(vs)})
    return out


async def _open_meteo_get(ctx: ProviderContext, url: str, what: str) -> dict:
    resp = await get_with_retry(ctx.client, url, retries=ctx.retries, what=what)
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderUnavailable(f"{what}: response is not JSON") from exc
    if data.get("error"):
        raise ProviderUnavailable(f"{what}: {data.get('reason', 'error')}")
    return data


class OpenMeteoEra5WindProvider:
    name = "open_meteo"
    variables = frozenset({"wind"})
    info = SourceInfo(
        provider=name,
        source="Open-Meteo (ECMWF ERA5)",
        licence="CC BY 4.0 (data); Open-Meteo free API terms",
        attribution="Weather data by Open-Meteo.com, ECMWF ERA5 reanalysis",
        terms_note=OPEN_METEO_TERMS + " Commercial deployment: Copernicus CDS ERA5 or a paid key (Q5 user action 2).",
    )
    BASE = "https://archive-api.open-meteo.com/v1/era5"

    async def fetch(self, variable: str, q: LookupQuery, ctx: ProviderContext) -> PublicValue:
        start, end = _series_window(q)
        url = f"{self.BASE}?" + urlencode({
            "latitude": q.latitude, "longitude": q.longitude, "start_date": start, "end_date": end,
            "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "ms", "timezone": "UTC",
        })
        data = await _open_meteo_get(ctx, url, "Open-Meteo ERA5")
        try:
            hourly = data["hourly"]
            times, speeds, dirs = hourly["time"], hourly["wind_speed_10m"], hourly["wind_direction_10m"]
        except KeyError as exc:
            raise ProviderUnavailable(f"Open-Meteo ERA5: missing {exc} in response") from exc
        if not times:
            raise ProviderUnavailable("Open-Meteo ERA5: no hourly values returned")
        i = _nearest_hour_index(times, q.collected_at)
        if speeds[i] is None:
            # ERA5 lags real time; the value may exist later. Not cached.
            raise ProviderUnavailable(f"Open-Meteo ERA5 has no wind value for {times[i]} UTC yet", transient=True)
        return PublicValue(
            value=float(speeds[i]), unit="m/s", provider=self.name, source=self.info.source,
            product_id="ECMWF ERA5", dataset_id="open-meteo era5 hourly", source_variable="wind_speed_10m,wind_direction_10m",
            query_url=url,
            grid_point=GridPoint(latitude=float(data["latitude"]), longitude=float(data["longitude"]),
                                 depth_m=None, time=times[i] + ":00Z"),
            retrieved_at=_now(), access="public_api", kind="reanalysis",
            details={"direction_deg": dirs[i], "direction_convention": "from (meteorological)",
                     "height_m": 10, "units_hourly": data.get("hourly_units", {})},
            series=_daily(times, speeds),
            licence=self.info.licence, attribution=self.info.attribution, note=OPEN_METEO_TERMS,
        )


class OpenMeteoMarineCurrentProvider:
    name = "open_meteo_marine"
    variables = frozenset({"current"})
    info = SourceInfo(
        provider=name,
        source="Open-Meteo Marine",
        licence="CC BY 4.0 (data); Open-Meteo free API terms",
        attribution="Marine data by Open-Meteo.com",
        terms_note=OPEN_METEO_TERMS,
    )
    BASE = "https://marine-api.open-meteo.com/v1/marine"

    async def fetch(self, variable: str, q: LookupQuery, ctx: ProviderContext) -> PublicValue:
        start, end = _series_window(q)
        url = f"{self.BASE}?" + urlencode({
            "latitude": q.latitude, "longitude": q.longitude, "start_date": start, "end_date": end,
            "hourly": "ocean_current_velocity,ocean_current_direction", "timezone": "UTC",
        })
        data = await _open_meteo_get(ctx, url, "Open-Meteo Marine")
        try:
            hourly = data["hourly"]
            times, vel, dirs = hourly["time"], hourly["ocean_current_velocity"], hourly["ocean_current_direction"]
            vel_unit = data.get("hourly_units", {}).get("ocean_current_velocity", "km/h")
        except KeyError as exc:
            raise ProviderUnavailable(f"Open-Meteo Marine: missing {exc} in response") from exc
        if not times:
            raise ProviderUnavailable("Open-Meteo Marine: no hourly values returned")
        factor = {"km/h": 1 / 3.6, "m/s": 1.0}.get(vel_unit)
        if factor is None:
            raise ProviderUnavailable(f"Open-Meteo Marine: unexpected velocity unit {vel_unit!r}")
        i = _nearest_hour_index(times, q.collected_at)
        if vel[i] is None:
            raise ProviderUnavailable(f"Open-Meteo Marine has no current value at {times[i]} UTC (land cell?)")
        ms = [v * factor if v is not None else None for v in vel]
        return PublicValue(
            value=round(ms[i], 4), unit="m/s", provider=self.name, source=self.info.source,
            product_id="Open-Meteo Marine", dataset_id="open-meteo marine hourly",
            source_variable="ocean_current_velocity,ocean_current_direction", query_url=url,
            grid_point=GridPoint(latitude=float(data["latitude"]), longitude=float(data["longitude"]),
                                 depth_m=0.0, time=times[i] + ":00Z"),
            retrieved_at=_now(), access="public_api", kind="modelled",
            raw_value=vel[i], raw_unit=vel_unit,
            details={"direction_deg": dirs[i], "direction_convention": "toward (as reported by Open-Meteo)"},
            series=[{"date": d["date"], "speed": d["mean"], "max": d["max"]} for d in _daily(times, ms)],
            licence=self.info.licence, attribution=self.info.attribution,
            note=OPEN_METEO_TERMS + " Fallback after Copernicus Marine.",
        )


COPERNICUS = CopernicusMarineProvider()
OISST = NoaaErddapOisstProvider()
ERA5_WIND = OpenMeteoEra5WindProvider()
MARINE_CURRENT = OpenMeteoMarineCurrentProvider()

# Q5 provider order per variable.
PROVIDER_ORDER: dict[str, list[Provider]] = {
    "temperature": [COPERNICUS, OISST],
    "salinity": [COPERNICUS],
    "dissolved_oxygen": [COPERNICUS],
    "ph": [COPERNICUS],
    "current": [COPERNICUS, MARINE_CURRENT],
    "wind": [ERA5_WIND],
}

ALL_PROVIDERS: dict[str, Provider] = {p.name: p for p in (COPERNICUS, OISST, ERA5_WIND, MARINE_CURRENT)}
