"""
B14: one novelty cutoff, imported everywhere (worker side).

The API-side twin is services/api/tests/test_novelty_threshold.py; both check
that the two services' DEFAULT_NOVELTY_THRESHOLD values are equal.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.config as worker_config  # noqa: E402
from app.job_runner import _build_auto_reviews  # noqa: E402
from app.novelty.models import NoveltyLevel  # noqa: E402
from app.novelty.scorer import _novelty_level  # noqa: E402

WORKER_APP = Path(__file__).resolve().parents[1] / "app"
API_CONFIG = Path(__file__).resolve().parents[2] / "api" / "app" / "config.py"

# The current cutoff (0.44 since the B5 recalibration, 2026-10-20) and the
# pre-B5 0.45: neither may appear as a bare novelty literal in app code.
_VAL = r"0\.4[45]"
_BARE = re.compile(rf"(?<![\d.]){_VAL}(?![\d])")
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
    """Lines with a bare 0.45 that mention novelty, or compare a score to it."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not _BARE.search(line):
            continue
        low = line.lower()
        if "novelt" in low or ("score" in low and (_CMP.search(line) or "=" in line)):
            hits.append((lineno, line.strip()))
    return hits


def test_worker_and_api_defaults_are_equal():
    assert API_CONFIG.is_file(), f"API config not found at {API_CONFIG}"
    worker_default = _module_constant(WORKER_APP / "config.py", "DEFAULT_NOVELTY_THRESHOLD")
    api_default = _module_constant(API_CONFIG, "DEFAULT_NOVELTY_THRESHOLD")
    assert worker_default == api_default == worker_config.DEFAULT_NOVELTY_THRESHOLD


@pytest.mark.skipif("NOVELTY_THRESHOLD" in os.environ, reason="threshold overridden by env")
def test_constant_resolves_to_default():
    # 0.44: dev-recalibrated 2026-10-20 (B5, t-1024-1), was 0.45.
    assert worker_config.NOVELTY_THRESHOLD == worker_config.DEFAULT_NOVELTY_THRESHOLD == 0.44


def test_settings_field_reads_env(monkeypatch):
    monkeypatch.setenv("NOVELTY_THRESHOLD", "0.6")
    assert worker_config.WorkerSettings().novelty_threshold == 0.6


def test_grep_catches_the_old_literals():
    old = [
        "        if nr.novelty_score >= 0.45:",
        '        elif rc == "possible_novelty" or r.get("novelty_score", 0.0) >= 0.45:',
        '                "is_novelty": novelty_score >= 0.45,',
        "    NoveltyLevel.medium: (0.45, 0.70),",
        "        if nr.novelty_score >= 0.44:",
    ]
    assert len(_offending_lines("\n".join(old))) == len(old)
    # Unrelated 0.45s in worker/app stay legal.
    assert _offending_lines(
        "    if 0.38 <= gc_ratio <= 0.45:\n        gc_mean=0.45,\n"
        '    "likely_taxonomic_group": 0.45,'
    ) == []


def test_no_bare_novelty_cutoff_in_worker_app():
    offenders = []
    for path in sorted(WORKER_APP.rglob("*.py")):
        if path == WORKER_APP / "config.py":
            continue  # the one definition
        for lineno, line in _offending_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(WORKER_APP.parent)}:{lineno}: {line}")
    assert not offenders, (
        "Bare 0.45 novelty cutoff found; import NOVELTY_THRESHOLD from app.config:\n"
        + "\n".join(offenders)
    )


def test_review_trigger_and_level_band_share_the_cutoff():
    t = worker_config.NOVELTY_THRESHOLD
    at = _build_auto_reviews("a1", "j1", [{"sequence_id": "s", "novelty_score": t}])
    below = _build_auto_reviews("a1", "j1", [{"sequence_id": "s", "novelty_score": t - 0.001}])
    assert [r["correction_type"] for r in at] == ["auto_novelty_flag"]
    assert below == []
    assert _novelty_level(t) == NoveltyLevel.medium
    assert _novelty_level(t - 0.001) == NoveltyLevel.low
