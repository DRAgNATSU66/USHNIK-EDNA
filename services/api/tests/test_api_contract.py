"""
Frontend ↔ backend contract: every call in web_frontend/src/lib/api.js must hit
a route this FastAPI app actually registers.

Three pages shipped broken because the client and server drifted apart
(GET /reviews vs /reviews/queue, GET /models vs /models/registry, and
POST /abyss/expeditions/{id}/sync vs /abyss/sync). This test turns that class
of bug into a CI failure instead of a 404 in front of a user.
"""
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.main import create_app

API_JS = Path(__file__).resolve().parents[3] / "web_frontend" / "src" / "lib" / "api.js"

# request("GET", "/reports") or request("POST", `/reviews/${review_id}/triage`, ...)
_CALL = re.compile(r'request\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*["`]([^"`]+)["`]')


def _frontend_calls() -> list[tuple[str, str]]:
    calls = []
    for method, path in _CALL.findall(API_JS.read_text(encoding="utf-8")):
        # Template params (${analysis_id}) become a single path segment.
        calls.append((method, re.sub(r"\$\{[^}]+\}", "PARAM", path)))
    return calls


def _backend_routes() -> list[tuple[set[str], re.Pattern]]:
    routes = []
    for r in create_app().routes:
        if isinstance(r, APIRoute):
            pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path) + "$"
            routes.append((r.methods, re.compile(pattern)))
    return routes


@pytest.mark.skipif(not API_JS.exists(), reason="web_frontend not checked out")
def test_api_js_finds_calls():
    # Guards the regex itself: if api.js changes style, the contract test
    # below must not silently pass on zero calls.
    assert len(_frontend_calls()) >= 30


@pytest.mark.skipif(not API_JS.exists(), reason="web_frontend not checked out")
@pytest.mark.parametrize("method,path", _frontend_calls() if API_JS.exists() else [])
def test_every_frontend_call_has_a_backend_route(method, path):
    matches = [m for m, rx in _backend_routes() if rx.match(path) and method in m]
    assert matches, f"{method} {path} is called by lib/api.js but no FastAPI route serves it"
