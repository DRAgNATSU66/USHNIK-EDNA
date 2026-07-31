"""
Tests for MongoDB index definitions.
Verifies that ensure_indexes() issues the correct create_indexes calls
without needing a real MongoDB connection.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


@pytest.mark.anyio
async def test_ensure_indexes_calls_all_collections():
    """ensure_indexes() must touch every required collection."""
    from app.db.indexes import ensure_indexes

    called_collections = set()
    mock_coll = MagicMock()
    mock_coll.create_indexes = AsyncMock()

    def getitem(key):
        called_collections.add(key)
        return mock_coll

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=getitem)

    await ensure_indexes(mock_db)

    expected = {
        "uploads",
        "analysis_jobs",
        "analysis_results",
        "raw_model_outputs",
        "reports",
        "sequence_batches",
        "reviews",
        "abyss_expeditions",
        "abyss_expedition_logs",
        "audit_logs",
    }
    assert expected == called_collections, (
        f"Missing collections: {expected - called_collections}"
    )


@pytest.mark.anyio
async def test_uploads_has_unique_index():
    from app.db.indexes import ensure_indexes
    from pymongo import ASCENDING

    captured_indexes: list = []
    mock_coll = MagicMock()

    async def capture_create(*args, **kwargs):
        captured_indexes.extend(args[0])

    mock_coll.create_indexes = capture_create

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)

    await ensure_indexes(mock_db)

    # SON keys compare as dicts; convert to list-of-tuples for ordering check
    unique_keys = [
        list(idx.document["key"].items())
        for idx in captured_indexes
        if idx.document.get("unique")
    ]
    assert [("upload_id", ASCENDING)] in unique_keys


@pytest.mark.anyio
async def test_jobs_has_worker_poll_compound_index():
    from app.db.indexes import ensure_indexes
    from pymongo import ASCENDING

    captured_indexes: list = []
    mock_coll = MagicMock()

    async def capture_create(*args, **kwargs):
        captured_indexes.extend(args[0])

    mock_coll.create_indexes = capture_create

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)

    await ensure_indexes(mock_db)

    # Convert SON to list-of-tuples to check key order
    all_keys = [list(idx.document["key"].items()) for idx in captured_indexes]
    assert [("state", ASCENDING), ("queued_at", ASCENDING)] in all_keys
