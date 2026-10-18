"""
Abyss offline credentials and sync (U4, F3, B25).

* Offline licenses and expedition sessions are signed with the API's JWT
  secret but must never authenticate API calls: they last up to 90 / 45 days
  and cannot be revoked. get_current_user used to accept them.
* /abyss/sync stores each preliminary analysis with the router summary the
  device saw, so the server-side record says which router ran.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.abyss.models import ExpeditionDoc
from app.abyss.offline_pack import generate_offline_license
from app.auth.session import create_expedition_session


@pytest.mark.anyio
async def test_expedition_session_token_is_not_an_api_token(client):
    tok = create_expedition_session("exp_x", "usr_admin_001", "admin")
    resp = await client.get("/abyss/expeditions", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 401
    assert "Offline expedition credentials" in resp.json()["detail"]


@pytest.mark.anyio
async def test_offline_license_is_not_an_api_token(client):
    exp = ExpeditionDoc(name="x", created_by="usr_admin_001")
    tok, _ = generate_offline_license(exp, "usr_admin_001")
    resp = await client.get("/abyss/expeditions", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_access_token_still_accepted(client, admin_token):
    resp = await client.get("/abyss/expeditions", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_expedition_session_then_verify(client, admin_token):
    with patch("app.auth.router.SupabaseClient.log_action", new=AsyncMock()):
        import app.db.mongo as _mongo
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value={"expedition_id": "exp_s1"})
        with patch.object(_mongo, "_db", {"abyss_expeditions": coll}):
            resp = await client.post(
                "/auth/expedition/session",
                json={"expedition_id": "exp_s1", "device_fingerprint": "dev_1"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expedition_id"] == "exp_s1"
    v = await client.post("/auth/expedition/verify",
                          json={"expedition_session_token": body["expedition_session_token"]})
    assert v.status_code == 200
    assert v.json()["expedition_id"] == "exp_s1"
    assert v.json()["role"] == "admin"


class _RecordingDb:
    def __init__(self, expedition: dict):
        self.colls: dict[str, MagicMock] = {}
        self._expedition = expedition

    def __getitem__(self, name):
        if name not in self.colls:
            c = MagicMock()
            c.find_one = AsyncMock(return_value=self._expedition if name == "abyss_expeditions" else None)
            c.insert_one = AsyncMock()
            c.insert_many = AsyncMock()
            c.update_one = AsyncMock()
            self.colls[name] = c
        return self.colls[name]


@pytest.mark.anyio
async def test_sync_stores_analysis_with_router_summary(client, admin_token):
    db = _RecordingDb({"expedition_id": "exp_sync", "created_by": "usr_admin_001", "status": "active"})
    router = {"method": "learned", "model_id": "kmer_router_v1", "version": "v1",
              "artifact_sha256": "f335be9a", "counts": {"learned": 2}}
    payload = {
        "expedition_id": "exp_sync",
        "local_logs": [{"event": "analysis_run", "analysis_id": "abyss_1",
                        "at": datetime.now(timezone.utc).isoformat()}],
        "local_analyses": [{
            "abyss_analysis_id": "abyss_1", "sequences_analyzed": 2,
            "possible_novelty_count": 0, "contamination_flag_count": 0,
            "device_id": "dev_1", "raw_results": [{"sequence_id": "s1", "router_method": "learned"}],
            "router": router,
        }],
    }
    with patch("app.abyss.router.get_db", return_value=db):
        resp = await client.post("/abyss/sync", json=payload,
                                 headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["logs_stored"] == 1
    assert body["analyses_stored"] == 1
    assert body["reanalysis_jobs_queued"] == 0

    calls = db.colls["abyss_expedition_logs"].insert_many.await_args_list
    stored = [doc for call in calls for doc in call.args[0]]
    prelim = [d for d in stored if d["log_type"] == "preliminary_analysis"]
    assert len(prelim) == 1
    assert prelim[0]["router"] == router
    assert prelim[0]["expedition_id"] == "exp_sync"
    db.colls["abyss_expeditions"].update_one.assert_awaited()
    assert db.colls["abyss_expeditions"].update_one.await_args.args[1]["$set"]["status"] == "synced"
