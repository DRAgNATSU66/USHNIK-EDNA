"""
B14: one novelty cutoff, imported everywhere.

- The API and worker each define DEFAULT_NOVELTY_THRESHOLD in their own
  app/config.py (separate images, no shared package). The two must be equal.
- No app module may compare a novelty score against a bare 0.45 again.
- GET /health exposes the value for the frontend slider.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

import app.config as api_config

API_APP = Path(__file__).resolve().parents[1] / "app"
WORKER_CONFIG = Path(__file__).resolve().parents[2] / "worker" / "app" / "config.py"

# A bare 0.44 (current cutoff, B5 recalibration 2026-10-20) or 0.45 (pre-B5)
# number token (not 0.450, 10.45, 0.455).
_VAL = r"0\.4[45]"
_BARE = re.compile(rf"(?<![\d.]){_VAL}(?![\d])")
# A comparison against it: `>= 0.45`, `< 0.44`, `0.45 <=`, ...
_CMP = re.compile(rf"(?:[<>]=?|==)\s*{_VAL}(?![\d])|(?<![\d.]){_VAL}\s*(?:[<>]=?|==)")


def _module_constant(path: Path, name: str) -> float:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not defined at module level in {path}")


def _offending_lines(text: str) -> list[tuple[int, str]]:
    """Lines that use a bare 0.45 as a novelty cutoff.

    Flagged: any line with a bare 0.45 that mentions novelty, or that compares
    a *score* against 0.45 (catches `min_score: float = 0.45` and
    `if score >= 0.45`). Unrelated 0.45s (a GC-ratio band, a signal weight)
    mention neither and are left alone.
    """
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not _BARE.search(line):
            continue
        low = line.lower()
        if "novelt" in low or ("score" in low and (_CMP.search(line) or "=" in line)):
            hits.append((lineno, line.strip()))
    return hits


def test_api_and_worker_defaults_are_equal():
    assert WORKER_CONFIG.is_file(), f"worker config not found at {WORKER_CONFIG}"
    api_default = _module_constant(API_APP / "config.py", "DEFAULT_NOVELTY_THRESHOLD")
    worker_default = _module_constant(WORKER_CONFIG, "DEFAULT_NOVELTY_THRESHOLD")
    assert api_default == worker_default == api_config.DEFAULT_NOVELTY_THRESHOLD


@pytest.mark.skipif("NOVELTY_THRESHOLD" in os.environ, reason="threshold overridden by env")
def test_constant_resolves_to_default():
    # 0.44: dev-recalibrated 2026-10-20 (B5, t-1024-1), was 0.45.
    assert api_config.NOVELTY_THRESHOLD == api_config.DEFAULT_NOVELTY_THRESHOLD == 0.44


def test_settings_field_reads_env(monkeypatch):
    monkeypatch.setenv("NOVELTY_THRESHOLD", "0.6")
    assert api_config.Settings().novelty_threshold == 0.6


@pytest.mark.parametrize("bad", ["0", "1", "-0.1", "1.5"])
def test_settings_field_rejects_out_of_range(monkeypatch, bad):
    monkeypatch.setenv("NOVELTY_THRESHOLD", bad)
    with pytest.raises(Exception):
        api_config.Settings()


def test_grep_catches_the_old_literals():
    # Guard against the scan silently matching nothing.
    old = [
        'novelty_count = sum(1 for r in results if float(r.get("novelty_score", 0.0)) >= 0.45)',
        "    min_score: float = 0.45,",
        "    if novelty_score >= 0.45:",
        '            "is_novelty": novelty_score >= 0.45,',
        "_NOVELTY_THRESHOLD = 0.45",
        "        if score >= 0.45:",
        "    if novelty_score >= 0.44:",
    ]
    assert len(_offending_lines("\n".join(old))) == len(old)
    assert _offending_lines("    if 0.38 <= gc_ratio <= 0.45:\n        gc_mean=0.45,") == []


def test_no_bare_novelty_cutoff_in_api_app():
    offenders = []
    for path in sorted(API_APP.rglob("*.py")):
        if path == API_APP / "config.py":
            continue  # the one definition
        for lineno, line in _offending_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(API_APP.parent)}:{lineno}: {line}")
    assert not offenders, (
        "Bare 0.45 novelty cutoff found; import NOVELTY_THRESHOLD from app.config:\n"
        + "\n".join(offenders)
    )


@pytest.mark.anyio
async def test_health_exposes_novelty_threshold(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["novelty_threshold"] == api_config.NOVELTY_THRESHOLD
