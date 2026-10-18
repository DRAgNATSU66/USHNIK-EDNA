"""
Point reads from Copernicus Marine ARCO Zarr stores (Q5, t-1026-1).

Copernicus Marine publishes every dataset as consolidated Zarr v2 on public
S3 (the "ARCO" stores). The official `copernicusmarine` toolbox reads the same
stores through xarray; pulling in xarray/zarr/dask for one grid cell per
upload is not worth it, so this module reads exactly what a point lookup
needs:

  1. `.zmetadata` (consolidated array metadata),
  2. the 1-D coordinate arrays (latitude, longitude, elevation, time),
  3. the one data chunk that holds the nearest cell.

We use the `geoChunked` layout: its chunks are [134 days, 2 levels, 32 lat,
64 lon], about 1.2 MB compressed, the same size as a `timeChunked` chunk but
holding a ~4-month daily series for the cell, which the by-day panels use.

Only the blosc compressor is supported (every CMEMS ARCO array checked on
2026-10-18 uses blosc/lz4 with byte shuffle). Anything else raises
ProviderUnavailable instead of guessing.
"""
from __future__ import annotations

import math
import re
import time as _time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
import numpy as np

from .http import ProviderUnavailable, get_with_retry

try:  # blosc is in requirements.txt; keep the import failure explicit.
    import blosc  # type: ignore
except ImportError:  # pragma: no cover - exercised only on a broken install
    blosc = None

# Coordinate arrays and metadata change at most daily (the forecast axis
# grows); re-read them after this long.
METADATA_TTL_S = 6 * 3600
_CHUNK_CACHE_MAX = 6

_meta_cache: dict[str, tuple[float, "DatasetMeta"]] = {}
_chunk_cache: "OrderedDict[str, np.ndarray]" = OrderedDict()


def clear_caches() -> None:
    """Tests use this to make sure every read goes through the transport."""
    _meta_cache.clear()
    _chunk_cache.clear()


@dataclass
class DatasetMeta:
    base_url: str
    meta: dict[str, Any]
    lat: np.ndarray
    lon: np.ndarray
    # Positive-down depth in metres for each vertical index (None: 2-D data).
    depth: Optional[np.ndarray]
    # Each time step as seconds since the Unix epoch (UTC).
    times: np.ndarray
    attrs: dict[str, Any] = field(default_factory=dict)

    def time_range(self) -> tuple[str, str]:
        return (_iso_date(self.times[0]), _iso_date(self.times[-1]))


@dataclass
class PointRead:
    value: Optional[float]  # None: no valid cell within reach at that level/time
    latitude: float  # grid cell actually used
    longitude: float
    depth_m: Optional[float]
    time: str  # ISO timestamp of the time step used
    distance_km: float
    chunk_url: str
    units: str
    # [(ISO date, value or None)] for the window ending at the target date,
    # limited to the time steps inside the fetched chunk.
    series: list[tuple[str, Optional[float]]]


def _iso_date(epoch_s: float) -> str:
    return datetime.fromtimestamp(float(epoch_s), tz=timezone.utc).date().isoformat()


def _iso_ts(epoch_s: float) -> str:
    return datetime.fromtimestamp(float(epoch_s), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_UNIT_SECONDS = {"seconds": 1, "second": 1, "minutes": 60, "minute": 60,
                 "hours": 3600, "hour": 3600, "days": 86400, "day": 86400}


def decode_cf_time(values: np.ndarray, units: str) -> np.ndarray:
    """CF "<unit> since <date>" -> seconds since 1970-01-01 UTC."""
    m = re.match(r"\s*(\w+)\s+since\s+(\d{4}-\d{1,2}-\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", units)
    if not m or m.group(1).lower() not in _UNIT_SECONDS:
        raise ProviderUnavailable(f"unsupported time units {units!r}")
    y, mo, d = (int(p) for p in m.group(2).split("-"))
    hh, mm, ss = (int(m.group(i) or 0) for i in (3, 4, 5))
    origin = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc).timestamp()
    return origin + values.astype("float64") * _UNIT_SECONDS[m.group(1).lower()]


def _decode_chunk(raw: bytes, zarray: dict[str, Any]) -> np.ndarray:
    comp = zarray.get("compressor")
    if comp is None:
        buf = raw
    elif comp.get("id") == "blosc":
        if blosc is None:
            raise ProviderUnavailable("python-blosc is not installed (services/api/requirements.txt)")
        buf = blosc.decompress(raw)
    else:
        raise ProviderUnavailable(f"unsupported Zarr compressor {comp.get('id')!r}")
    if zarray.get("filters"):
        raise ProviderUnavailable("Zarr filters are not supported")
    arr = np.frombuffer(buf, dtype=np.dtype(zarray["dtype"]))
    order = zarray.get("order", "C")
    return arr.reshape(zarray["chunks"], order=order)


async def _read_full_array(client, base_url, name, meta, params, retries) -> np.ndarray:
    zarray = meta[f"{name}/.zarray"]
    shape, chunks = zarray["shape"], zarray["chunks"]
    if len(shape) != 1:
        raise ProviderUnavailable(f"coordinate {name} is not 1-D")
    parts = []
    for i in range(math.ceil(shape[0] / chunks[0])):
        resp = await get_with_retry(client, f"{base_url}/{name}/{i}", params=params,
                                    retries=retries, what=f"Copernicus Marine {name} coordinate")
        parts.append(_decode_chunk(resp.content, zarray).astype("float64"))
    return np.concatenate(parts)[: shape[0]]


async def load_dataset(client: httpx.AsyncClient, base_url: str, *, params=None, retries=1) -> DatasetMeta:
    cached = _meta_cache.get(base_url)
    if cached and _time.monotonic() - cached[0] < METADATA_TTL_S:
        return cached[1]

    resp = await get_with_retry(client, f"{base_url}/.zmetadata", params=params,
                                retries=retries, what="Copernicus Marine .zmetadata")
    try:
        meta = resp.json()["metadata"]
    except Exception as exc:
        raise ProviderUnavailable(f"unreadable .zmetadata at {base_url}: {exc}") from exc

    def has(name):
        return f"{name}/.zarray" in meta

    lat_name = "latitude" if has("latitude") else "lat"
    lon_name = "longitude" if has("longitude") else "lon"
    if not (has(lat_name) and has(lon_name) and has("time")):
        raise ProviderUnavailable(f"{base_url} lacks latitude/longitude/time coordinates")

    lat = await _read_full_array(client, base_url, lat_name, meta, params, retries)
    lon = await _read_full_array(client, base_url, lon_name, meta, params, retries)
    raw_t = await _read_full_array(client, base_url, "time", meta, params, retries)
    times = decode_cf_time(raw_t, meta.get("time/.zattrs", {}).get("units", ""))

    depth = None
    if has("elevation"):  # ARCO convention: metres, positive up
        depth = -await _read_full_array(client, base_url, "elevation", meta, params, retries)
    elif has("depth"):
        depth = await _read_full_array(client, base_url, "depth", meta, params, retries)

    ds = DatasetMeta(base_url=base_url, meta=meta, lat=lat, lon=lon, depth=depth, times=times,
                     attrs=meta.get(".zattrs", {}))
    _meta_cache[base_url] = (_time.monotonic(), ds)
    return ds


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.minimum(1.0, a)))


def _valid_mask(values: np.ndarray, zarray: dict, attrs: dict) -> np.ndarray:
    v = values.astype("float64")
    mask = np.isfinite(v)
    fill = zarray.get("fill_value")
    if isinstance(fill, (int, float)) and not (isinstance(fill, float) and math.isnan(fill)):
        mask &= v != float(fill)
    if "_FillValue" in attrs and isinstance(attrs["_FillValue"], (int, float)):
        mask &= v != float(attrs["_FillValue"])
    # netCDF default float fill (9.969e36) and friends.
    mask &= np.abs(v) < 1e30
    return mask


def _apply_scale(v: np.ndarray, attrs: dict) -> np.ndarray:
    v = v.astype("float64")
    if "scale_factor" in attrs:
        v = v * float(attrs["scale_factor"])
    if "add_offset" in attrs:
        v = v + float(attrs["add_offset"])
    return v


async def read_point(
    client: httpx.AsyncClient,
    ds: DatasetMeta,
    variable: str,
    *,
    latitude: float,
    longitude: float,
    day: date,
    depth_m: Optional[float],
    max_distance_km: float,
    window_days: int = 1,
    params: Optional[dict] = None,
    retries: int = 1,
) -> PointRead:
    """Value of `variable` at the nearest valid ocean cell for `day`.

    `depth_m` None means the shallowest level. The search for a valid cell is
    limited to `max_distance_km` and to the fetched chunk; when nothing valid
    is in reach, `value` is None (the caller reports it as unavailable) --
    never an interpolated or neighbouring-day value.
    """
    meta = ds.meta
    zkey = f"{variable}/.zarray"
    if zkey not in meta:
        raise ProviderUnavailable(f"variable {variable!r} is not in {ds.base_url}")
    zarray = meta[zkey]
    attrs = meta.get(f"{variable}/.zattrs", {})
    dims = attrs.get("_ARRAY_DIMENSIONS") or []
    units = attrs.get("units", "")

    # --- time: the daily step that covers `day` ---------------------------
    target = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    ti = int(np.argmin(np.abs(ds.times - target)))
    if abs(ds.times[ti] - target) >= 86400:
        lo, hi = ds.time_range()
        raise ProviderUnavailable(f"date {day.isoformat()} is outside the dataset time axis ({lo} to {hi})")

    # --- horizontal: nearest grid index ---------------------------------
    lon0 = float(ds.lon[0])
    qlon = ((longitude - lon0) % 360.0) + lon0
    yi = int(np.argmin(np.abs(ds.lat - latitude)))
    xi = int(np.argmin(np.abs(ds.lon - qlon)))

    # --- vertical ---------------------------------------------------------
    zi = None
    if ds.depth is not None and ("elevation" in dims or "depth" in dims):
        want = float(depth_m) if depth_m is not None else float(np.min(ds.depth))
        zi = int(np.argmin(np.abs(ds.depth - want)))

    index_by_dim = {"time": ti, "latitude": yi, "lat": yi, "longitude": xi, "lon": xi,
                    "elevation": zi, "depth": zi}
    try:
        idx = [index_by_dim[d] for d in dims]
    except KeyError as exc:
        raise ProviderUnavailable(f"unexpected dimension {exc} in {variable}") from exc
    if any(i is None for i in idx):
        raise ProviderUnavailable(f"could not index all dimensions {dims} of {variable}")

    chunks = zarray["chunks"]
    sep = zarray.get("dimension_separator", ".")
    ckey = sep.join(str(i // c) for i, c in zip(idx, chunks))
    chunk_url = f"{ds.base_url}/{variable}/{ckey}"

    arr = _chunk_cache.get(chunk_url)
    if arr is None:
        resp = await get_with_retry(client, chunk_url, params=params, retries=retries,
                                    what=f"Copernicus Marine {variable} chunk", allow_404=True)
        if resp.status_code == 404:
            # Zarr: a missing chunk is all fill (e.g. entirely land).
            arr = np.full(chunks, np.nan, dtype="float32")
        else:
            arr = _decode_chunk(resp.content, zarray)
        _chunk_cache[chunk_url] = arr
        while len(_chunk_cache) > _CHUNK_CACHE_MAX:
            _chunk_cache.popitem(last=False)
    else:
        _chunk_cache.move_to_end(chunk_url)

    local = {d: i % c for d, i, c in zip(dims, idx, chunks)}
    origin = {d: i - (i % c) for d, i, c in zip(dims, idx, chunks)}
    ydim = "latitude" if "latitude" in dims else "lat"
    xdim = "longitude" if "longitude" in dims else "lon"
    ypos, xpos = dims.index(ydim), dims.index(xdim)

    # 2-D slab (lat x lon) at the target time/level.
    sel: list[Any] = []
    for d in dims:
        sel.append(slice(None) if d in (ydim, xdim) else local[d])
    slab = arr[tuple(sel)]
    if ypos > xpos:
        slab = slab.T
    valid = _valid_mask(slab, zarray, attrs)

    lat_vals = ds.lat[origin[ydim]: origin[ydim] + slab.shape[0]]
    lon_vals = ds.lon[origin[xdim]: origin[xdim] + slab.shape[1]]
    grid_lat, grid_lon = np.meshgrid(lat_vals, lon_vals, indexing="ij")
    dist = _haversine_km(latitude, qlon, grid_lat, grid_lon)
    dist = np.where(valid, dist, np.inf)
    best = np.unravel_index(int(np.argmin(dist)), dist.shape)
    best_d = float(dist[best])

    cell_lat = float(lat_vals[best[0]])
    cell_lon = float(lon_vals[best[1]])
    if cell_lon > 180:
        cell_lon -= 360.0
    used_depth = float(ds.depth[zi]) if zi is not None else None

    value: Optional[float] = None
    series: list[tuple[str, Optional[float]]] = []
    if math.isfinite(best_d) and best_d <= max_distance_km:
        value = float(_apply_scale(np.asarray(slab[best]), attrs))
        # Daily series at the chosen cell, inside this chunk only.
        if "time" in dims and window_days > 1:
            tpos = dims.index("time")
            t0 = origin["time"]
            for t_local in range(arr.shape[tpos]):
                t_global = t0 + t_local
                if t_global >= len(ds.times):
                    break
                age_days = (target - ds.times[t_global]) / 86400
                if not (0 <= age_days < window_days):
                    continue
                s = []
                for d in dims:
                    if d == "time":
                        s.append(t_local)
                    elif d == ydim:
                        s.append(best[0])
                    elif d == xdim:
                        s.append(best[1])
                    else:
                        s.append(local[d])
                raw = np.asarray(arr[tuple(s)])
                ok = bool(_valid_mask(raw, zarray, attrs))
                series.append((_iso_date(ds.times[t_global]),
                               float(_apply_scale(raw, attrs)) if ok else None))
        best_cell = best_d
    else:
        # Report the nearest grid cell even though it held no data.
        best_cell = float(_haversine_km(latitude, qlon, float(ds.lat[yi]), float(ds.lon[xi])))
        cell_lat, cell_lon = float(ds.lat[yi]), float(ds.lon[xi])
        if cell_lon > 180:
            cell_lon -= 360.0

    return PointRead(
        value=value,
        latitude=round(cell_lat, 5),
        longitude=round(cell_lon, 5),
        depth_m=round(used_depth, 3) if used_depth is not None else None,
        time=_iso_ts(ds.times[ti]),
        distance_km=round(best_cell, 2),
        chunk_url=chunk_url,
        units=units,
        series=series,
    )
