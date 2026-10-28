"""
HTTP plumbing shared by the environmental-context providers (Q5, t-1026-1).

One `httpx.AsyncClient` per lookup run, a per-request timeout, and a bounded
number of retries on network errors and 5xx. Nothing here raises anything but
`ProviderUnavailable`, so a provider can never crash the lookup.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("app.environment")

USER_AGENT = "SynthVeda-API/0.1 (environmental context lookup; Q5)"


class ProviderUnavailable(Exception):
    """A provider could not supply a value.

    `transient` is True for network errors, timeouts and 5xx: the same query
    may work later, so the result is not written to the shared cache.
    False means the answer itself is "no value" (land cell, date outside the
    dataset, variable not in the product) and is safe to cache.
    """

    def __init__(self, reason: str, *, transient: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.transient = transient


HttpClientFactory = Callable[[float], httpx.AsyncClient]


def default_client_factory(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    retries: int = 1,
    backoff_s: float = 1.0,
    what: str = "",
    allow_404: bool = False,
) -> httpx.Response:
    """GET with at most `retries` extra attempts on network errors / 5xx.

    Returns the response for 2xx (and for 404 when `allow_404`). Any other
    outcome raises ProviderUnavailable; network failures are logged at ERROR
    so they show up in the API log rather than vanishing into a status field.
    """
    attempts = max(0, retries) + 1
    last_reason = ""
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            last_reason = f"timeout ({type(exc).__name__}) after {attempt} attempt(s)"
            logger.error("ENV LOOKUP NETWORK ERROR %s: %s GET %s", what, last_reason, url)
        except httpx.HTTPError as exc:
            last_reason = f"network error ({type(exc).__name__}: {exc}) after {attempt} attempt(s)"
            logger.error("ENV LOOKUP NETWORK ERROR %s: %s GET %s", what, last_reason, url)
        else:
            if resp.status_code < 400 or (allow_404 and resp.status_code == 404):
                return resp
            if resp.status_code >= 500 or resp.status_code == 429:
                last_reason = f"HTTP {resp.status_code} after {attempt} attempt(s)"
                logger.error("ENV LOOKUP HTTP ERROR %s: %s GET %s", what, last_reason, url)
            else:
                # 4xx other than 429: retrying will not help.
                raise ProviderUnavailable(
                    f"HTTP {resp.status_code} from {what or url}: {_snippet(resp)}",
                    transient=False,
                )
        if attempt < attempts:
            await asyncio.sleep(backoff_s * attempt)
    raise ProviderUnavailable(f"{what or url}: {last_reason}", transient=True)


def _snippet(resp: httpx.Response, limit: int = 300) -> str:
    try:
        text = resp.text
    except Exception:  # binary body
        return "<binary body>"
    return " ".join(text.split())[:limit]
