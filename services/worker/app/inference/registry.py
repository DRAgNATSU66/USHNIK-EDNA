"""
Model registry reader.

Reads JSON metadata files from models/registry/ and exposes them as
ModelRegistryEntry objects.  The registry is a flat directory of .json files —
one file per model version.

Registry is resolved relative to this file's location at:
  <repo_root>/models/registry/
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .models import ModelRegistryEntry

logger = logging.getLogger(__name__)


def _resolve_registry_dir() -> Path:
    """
    Resolve models/registry/, robust to both local dev (deep repo tree) and
    Docker (shallow /app tree — MODELS_REGISTRY_PATH or a mounted volume).
    """
    env_path = os.environ.get("MODELS_REGISTRY_PATH")
    if env_path:
        return Path(env_path)
    p = Path(__file__).resolve()
    for _ in range(10):
        candidate = p / "models" / "registry"
        if candidate.exists():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return Path("/app/models/registry")  # Docker default (empty if not mounted)


_REGISTRY_DIR = _resolve_registry_dir()

# Registry entries refer to local artifacts as "data:<path>", relative to the
# data root, so the same JSON works on every machine (the old entries
# hardcoded E:\\synthveda-data\\... and only ever resolved on one laptop).
# Anything without the prefix is passed through untouched (HF Hub ids, URLs).
DATA_URI_PREFIX = "data:"


# Selection rank per registry status. "candidate" is what POST /models/register
# writes (B8): the entry is on file and checksum-verified, but ranks below every
# tier, so registering a model never changes what is served. Only promotion
# (status -> production) does. Unknown statuses rank like "retired".
# Mirrored in services/api/app/models/router.py (_TIER_ORDER).
STATUS_RANK = {"candidate": -1, "experimental": 0, "staging": 1, "production": 2, "retired": -1}

# How often (seconds) a long-lived registry re-stats models/registry/*.json to
# notice a promotion written by the API. 0 = check on every lookup.
_RECHECK_SECONDS = float(os.environ.get("SYNTHVEDA_REGISTRY_RECHECK_S", "5"))


def _resolve_data_root() -> Path:
    env_path = os.environ.get("SYNTHVEDA_DATA_ROOT")
    if env_path:
        return Path(env_path)
    p = Path(__file__).resolve()
    for _ in range(10):
        candidate = p / "synthveda-data"
        if candidate.exists():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return Path("/data")  # Docker default (mount synthveda-data here)


def resolve_data_uri(uri: str | None) -> str | None:
    """Expand a "data:<relative path>" registry value against the data root."""
    if uri and uri.startswith(DATA_URI_PREFIX):
        return str(_resolve_data_root() / uri[len(DATA_URI_PREFIX):])
    return uri


class ModelRegistry:
    """
    Lazily loads and caches all model registry entries from models/registry/*.json.
    """

    def __init__(self, registry_dir: Path | str | None = None, recheck_seconds: float | None = None):
        self._dir = Path(registry_dir) if registry_dir else _REGISTRY_DIR
        self._entries: dict[str, ModelRegistryEntry] | None = None
        self._recheck_s = _RECHECK_SECONDS if recheck_seconds is None else recheck_seconds
        self._fingerprint: tuple | None = None
        self._checked_at = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all_entries(self) -> list[ModelRegistryEntry]:
        return list(self._load().values())

    def get(self, model_id: str) -> ModelRegistryEntry | None:
        return self._load().get(model_id)

    def for_route(self, route: str, min_status: str = "experimental") -> list[ModelRegistryEntry]:
        """Return all entries for a route at or above the given status tier."""
        min_rank = STATUS_RANK.get(min_status, 0)
        return [
            e for e in self._load().values()
            if e.route == route and STATUS_RANK.get(e.status, -1) >= min_rank
        ]

    def production_model(self, route: str) -> ModelRegistryEntry | None:
        """Return the production model for a route, or None."""
        entries = self.for_route(route, min_status="production")
        if not entries:
            return None
        # Prefer most recent by created_at string (ISO sort works).
        return max(entries, key=lambda e: e.created_at)

    def best_available(self, route: str) -> ModelRegistryEntry | None:
        """
        Return the best runnable model for a route.

        Preference: production > staging > experimental.
        Returns None if no runnable entry exists.
        """
        for status in ("production", "staging", "experimental"):
            entries = [e for e in self.for_route(route, min_status=status) if e.is_runnable]
            if entries:
                return max(entries, key=lambda e: e.created_at)
        return None

    def refresh(self) -> None:
        """Force reload of all registry files."""
        self._entries = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _dir_fingerprint(self) -> tuple:
        """(name, inode, mtime_ns, size) per *.json. The API writes entries with
        os.replace, so a promotion always changes at least the inode."""
        out = []
        for f in self._dir.glob("*.json"):
            try:
                st = f.stat()
            except OSError:
                continue
            out.append((f.name, st.st_ino, st.st_mtime_ns, st.st_size))
        return tuple(sorted(out))

    def _load(self) -> dict[str, ModelRegistryEntry]:
        if self._entries is not None:
            now = time.monotonic()
            if now - self._checked_at < self._recheck_s:
                return self._entries
            self._checked_at = now
            if not self._dir.exists() or self._dir_fingerprint() == self._fingerprint:
                return self._entries
            logger.info("Model registry changed on disk; reloading %s", self._dir)

        self._entries = {}
        self._checked_at = time.monotonic()
        # Fingerprint before reading: a write that lands mid-read shows up as a
        # change on the next check instead of being missed.
        self._fingerprint = self._dir_fingerprint() if self._dir.exists() else None
        if not self._dir.exists():
            logger.warning("Model registry directory not found: %s", self._dir)
            return self._entries

        for json_file in self._dir.glob("*.json"):
            try:
                with open(json_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                entry = _parse_entry(data, json_file)
                self._entries[entry.model_id] = entry
            except Exception as exc:
                logger.error("Failed to parse registry file %s: %s", json_file.name, exc)

        logger.info("Model registry: loaded %d entries from %s", len(self._entries), self._dir)
        return self._entries


def _parse_entry(data: dict, source: Path) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id=data["model_id"],
        route=data["route"],
        base_model=resolve_data_uri(data["base_model"]),
        head_type=data.get("head_type", "sequence_classification"),
        embedding_dim=data.get("embedding_dim", 768),
        label_set_version=data.get("label_set_version", "v1"),
        status=data.get("status", "experimental"),
        training_dataset_version=data.get("training_dataset_version"),
        metrics=data.get("metrics", {}),
        thresholds=data.get("thresholds", {}),
        artifact_uri=resolve_data_uri(data.get("artifact_uri")),
        checksum=data.get("checksum"),
        created_at=data.get("created_at", ""),
        promoted_by=data.get("promoted_by"),
        trusted_remote_code=data.get("trusted_remote_code", False),
        base_model_revision=data.get("base_model_revision"),
        label_set=list(data.get("label_set") or []),
    )


# Module-level singleton — shared across all worker tasks.
_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
