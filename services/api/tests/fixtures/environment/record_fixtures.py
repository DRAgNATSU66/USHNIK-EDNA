"""
Re-record the HTTP fixtures used by tests/test_environment_context.py.

    cd services/api && .venv/bin/python tests/fixtures/environment/record_fixtures.py

Makes LIVE calls to every provider (Copernicus Marine ARCO, NOAA NCEI ERDDAP,
Open-Meteo ERA5 + Marine) for the Q5 sample point (15.6 N, 82.3 E,
2026-10-01), prints the values, and writes each response under
tests/fixtures/environment/bay_of_bengal/.

Copernicus data chunks are ~1.2 MB each, so they are stored sparsified: the
recorded values are kept for the cells within +-4 grid steps of the query
point and +-10 days of the sample date, every other cell is set to the
array's fill value, and the chunk is re-compressed with the same blosc
settings. The kept values are byte-for-byte the live ones.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import blosc
import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))  # services/api

from app.environment import providers, zarr_point  # noqa: E402
from app.environment.providers import LookupQuery, ProviderContext  # noqa: E402
from app.environment.service import fetch_public  # noqa: E402

CASE = HERE / "bay_of_bengal"
LAT, LON = 15.6, 82.3
WHEN = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
KEEP_CELLS, KEEP_DAYS = 4, 10

_CHUNK_RE = re.compile(r"^(?P<base>.+\.zarr)/(?P<var>[A-Za-z0-9_]+)/(?P<key>\d+(?:\.\d+)+)$")


def strip_cop_params(url: str) -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("x-cop-")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


class Recorder(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport()
        self.records: dict[str, tuple[int, str, bytes]] = {}

    async def handle_async_request(self, request):
        resp = await self.inner.handle_async_request(request)
        body = await resp.aread()
        url = strip_cop_params(str(request.url))
        self.records[url] = (resp.status_code, resp.headers.get("content-type", ""), body)
        # aread() already decoded any gzip/br body: drop the encoding headers
        # so the client does not try to decode it a second time.
        headers = [(k, v) for k, v in resp.headers.items()
                   if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        return httpx.Response(resp.status_code, headers=headers, content=body, request=request)


def sparsify(url: str, body: bytes, day) -> bytes:
    m = _CHUNK_RE.match(url)
    if not m:
        return body
    base, var, key = m["base"], m["var"], m["key"]
    if var in ("latitude", "longitude", "time", "elevation", "depth"):
        return body
    ds = zarr_point._meta_cache[base][1]
    zarray = ds.meta[f"{var}/.zarray"]
    dims = ds.meta[f"{var}/.zattrs"]["_ARRAY_DIMENSIONS"]
    chunks = zarray["chunks"]
    arr = np.frombuffer(blosc.decompress(body), dtype=zarray["dtype"]).reshape(chunks).copy()
    origin = [int(k) * c for k, c in zip(key.split("."), chunks)]
    keep = np.zeros(chunks, dtype=bool)
    target = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    yi = int(np.argmin(np.abs(ds.lat - LAT)))
    xi = int(np.argmin(np.abs(ds.lon - LON)))
    ti = int(np.argmin(np.abs(ds.times - target)))
    centre = {"time": (ti, KEEP_DAYS), "latitude": (yi, KEEP_CELLS), "longitude": (xi, KEEP_CELLS)}
    sl = []
    for d, o, c in zip(dims, origin, chunks):
        if d in centre:
            g, r = centre[d]
            lo, hi = max(g - r - o, 0), min(g + r + 1 - o, c)
            sl.append(slice(lo, hi))
        else:
            sl.append(slice(None))
    keep[tuple(sl)] = True
    fill = zarray["fill_value"]
    arr[~keep] = np.float32(fill if isinstance(fill, (int, float)) else np.nan)
    comp = zarray["compressor"]
    return blosc.compress(arr.tobytes(), typesize=arr.dtype.itemsize, clevel=comp["clevel"],
                          shuffle=comp["shuffle"], cname=comp["cname"])


async def main() -> None:
    rec = Recorder()
    providers.clear_caches()

    def factory(timeout):
        return httpx.AsyncClient(transport=rec, timeout=timeout, follow_redirects=True)

    surface = LookupQuery(latitude=LAT, longitude=LON, collected_at=WHEN, day=WHEN.date(), depth_m=None)
    deep = LookupQuery(latitude=LAT, longitude=LON, collected_at=WHEN, day=WHEN.date(), depth_m=50)

    out = {}
    for name, q in (("surface", surface), ("depth_50m", deep)):
        results, transient = await fetch_public(q, client_factory=factory)
        out[name] = {"transient": transient,
                     **{k: r.model_dump(mode="json") for k, r in results.items()}}

    async with factory(15) as client:
        ctx = ProviderContext(client=client, retries=1, max_distance_km=30)
        for prov, var in ((providers.OISST, "temperature"), (providers.MARINE_CURRENT, "current")):
            try:
                v = await prov.fetch(var, surface, ctx)
                out[f"{prov.name}_{var}"] = v.model_dump(mode="json")
            except providers.ProviderUnavailable as exc:
                out[f"{prov.name}_{var}"] = {"unavailable": exc.reason}

    CASE.mkdir(parents=True, exist_ok=True)
    for old in CASE.glob("*"):
        old.unlink()
    index = []
    for i, (url, (status, ctype, body)) in enumerate(sorted(rec.records.items())):
        body = sparsify(url, body, WHEN.date()) if status == 200 else body
        fname = f"r{i:03d}.bin"
        (CASE / fname).write_bytes(body)
        index.append({"url": url, "status": status, "content_type": ctype, "file": fname})
    (CASE / "index.json").write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {"latitude": LAT, "longitude": LON, "collected_at": WHEN.isoformat()},
        "responses": index,
    }, indent=1))
    (CASE / "live_results.json").write_text(json.dumps(out, indent=1, default=str))

    for name in ("surface", "depth_50m"):
        print(f"== {name}")
        for var, r in out[name].items():
            if var == "transient":
                print("   transient:", r)
                continue
            v = r.get("value")
            if v:
                gp = v["grid_point"]
                print(f"   {var:17s} {v['value']} {v['unit']}  [{v['provider']} {v['dataset_id']}] "
                      f"cell {gp['latitude']},{gp['longitude']} depth {gp['depth_m']} t {gp['time']} "
                      f"d={gp.get('distance_km')}km raw={v.get('raw_value')} {v.get('details', {}).get('direction_deg', '')}")
                if v.get("details", {}).get("profile"):
                    print("     profile:", v["details"]["profile"])
                if v.get("series"):
                    print("     series:", v["series"])
            else:
                print(f"   {var:17s} UNAVAILABLE: {r.get('reason')}")
    for k in ("noaa_erddap_temperature", "open_meteo_marine_current"):
        v = out[k]
        if "value" in v:
            print(f"== {k}: {v['value']} {v['unit']} cell {v['grid_point']} url {v['query_url']}")
        else:
            print(f"== {k}: {v}")
    total = sum((CASE / e['file']).stat().st_size for e in index)
    print(f"recorded {len(index)} responses, {total} bytes on disk")


if __name__ == "__main__":
    asyncio.run(main())
