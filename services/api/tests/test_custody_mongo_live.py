"""
Opt-in check of the custody chain against a real MongoDB (t-1027-2).

The unit tests (test_custody_fair.py) use an in-memory stand-in, which cannot
prove two things only a real server can: that the unique indexes created by
db/indexes.py actually serialise racing appends, and that a stored event still
hashes the same after a BSON round trip (datetimes, floats, unicode, nested
dicts). Skipped unless SYNTHVEDA_TEST_MONGO_URI is set; it works in a
throwaway database (synthveda_custody_test_<random>) and drops it afterwards.

    SYNTHVEDA_TEST_MONGO_URI=mongodb://localhost:27017 pytest tests/test_custody_mongo_live.py
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

from app.custody import append_event, ensure_analysis_events, load_chain, verify_chain
from app.custody.chain import chain_id_for_upload

MONGO_URI = os.environ.get("SYNTHVEDA_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not MONGO_URI, reason="SYNTHVEDA_TEST_MONGO_URI not set")


@pytest.fixture
async def live_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.db.indexes import _custody_indexes

    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    name = f"synthveda_custody_test_{uuid.uuid4().hex[:10]}"
    db = client[name]
    await _custody_indexes(db)
    try:
        yield db
    finally:
        await client.drop_database(name)
        client.close()


async def test_live_concurrent_appends_stay_linear_and_bson_roundtrip_verifies(live_db):
    chain = "upload:upl_live"
    payload = {
        "when": datetime(2026, 10, 19, 8, 1, 2, 345678, tzinfo=timezone.utc),
        "ratio": 0.1 + 0.2, "count": 3, "text": "Sardinella longiceps — é", "nested": {"b": [1.5, None, True]},
    }
    await asyncio.gather(*[
        append_event(live_db, chain, "test_event", actor={"type": "system", "id": str(i)},
                     subject={"i": i}, payload=payload)
        for i in range(40)
    ])
    events = await load_chain(live_db, chain)
    assert [e["seq"] for e in events] == list(range(40))
    assert sorted(e["subject"]["i"] for e in events) == list(range(40))
    assert verify_chain(events, chain)["valid"] is True


async def test_live_analysis_completed_appended_once_under_race(live_db):
    analysis = {
        "analysis_id": "ana_live", "upload_id": "upl_live2", "job_id": "job_live", "mode": "local",
        "created_at": datetime(2026, 10, 18, 10, 0, 0, 123456),
        "results": [{"sequence_id": "s1", "confidence": 0.873, "route": "fish"}],
    }
    upload = {"upload_id": "upl_live2", "user_id": "usr_x", "created_at": datetime(2026, 10, 18, 9, 0),
              "checksum_sha256": "a" * 64, "ph": 8.1}
    await asyncio.gather(*[ensure_analysis_events(live_db, analysis, upload) for _ in range(10)])
    events = await load_chain(live_db, chain_id_for_upload("upl_live2"))
    assert [e["event_type"] for e in events] == ["upload_created", "analysis_completed"]
    assert verify_chain(events)["valid"] is True
