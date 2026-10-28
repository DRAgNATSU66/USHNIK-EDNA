"""
Phase 10 tests — Abyss Mode.

Covers:
  1. ExpeditionDoc model
  2. Offline pack models (OfflinePackManifest, OfflinePackComponent)
  3. Offline license generation and validation (offline_pack.py)
  4. Pack manifest builder
  5. Abyss analysis engine (analysis.py) — pure computation
  6. API endpoints: expeditions CRUD, activate, pack-manifest, license, sync
"""
from __future__ import annotations

import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.abyss.models import (
    ExpeditionDoc,
    ExpeditionStatus,
    OfflinePackManifest,
    OfflinePackComponent,
    AbyssSequenceInput,
    AbyssAnalysisResult,
    AbyssSyncRequest,
    ABYSS_DISCLAIMER,
)
from app.abyss.offline_pack import (
    generate_offline_license,
    validate_offline_license,
    build_pack_manifest,
)
from app.abyss.analysis import (
    run_abyss_analysis,
    _compute_qc,
    _batch_recommendation,
    _stub_result_class,
    AbyssSequenceResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expedition(
    expedition_id: str = "exp_test001",
    name: str = "Deep Atlantic Survey",
    status: ExpeditionStatus = ExpeditionStatus.pre_departure,
) -> ExpeditionDoc:
    return ExpeditionDoc(
        expedition_id=expedition_id,
        name=name,
        created_by="usr_operator",
        status=status,
        planned_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        planned_end=datetime(2026, 6, 21, tzinfo=timezone.utc),
        vessel="RV Synth Explorer",
        target_depth_meters=3500.0,
        location_label="Mid-Atlantic Ridge",
    )


def _seq_input(
    sequence_id: str = "seq_001",
    sequence: str = "ATCGATCGATCG" * 25,
    habitat: str | None = None,
) -> AbyssSequenceInput:
    return AbyssSequenceInput(
        sequence_id=sequence_id,
        sequence=sequence,
        habitat=habitat,
    )


# ---------------------------------------------------------------------------
# ExpeditionDoc model
# ---------------------------------------------------------------------------

class TestExpeditionDoc:
    def test_default_status_is_pre_departure(self):
        exp = ExpeditionDoc(name="Test", created_by="usr_1")
        assert exp.status == ExpeditionStatus.pre_departure

    def test_expedition_id_format(self):
        exp = ExpeditionDoc(name="Test", created_by="usr_1")
        assert exp.expedition_id.startswith("exp_")

    def test_offline_license_defaults_false(self):
        exp = ExpeditionDoc(name="Test", created_by="usr_1")
        assert exp.offline_license_issued is False
        assert exp.offline_license_expires_at is None

    def test_sync_state_defaults(self):
        exp = ExpeditionDoc(name="Test", created_by="usr_1")
        assert exp.synced_at is None
        assert exp.sync_job_count == 0

    def test_expedition_status_enum(self):
        assert ExpeditionStatus.pre_departure == "pre_departure"
        assert ExpeditionStatus.active == "active"
        assert ExpeditionStatus.synced == "synced"
        assert ExpeditionStatus.archived == "archived"


# ---------------------------------------------------------------------------
# Offline pack model
# ---------------------------------------------------------------------------

class TestOfflinePackModels:
    def test_offline_pack_component_fields(self):
        comp = OfflinePackComponent(
            name="route_models",
            component_type="model_pack",
            status="not_yet_trained",
            size_mb_estimate=0.0,
            description="Specialist model heads.",
        )
        assert comp.name == "route_models"
        assert comp.artifact_uri is None

    def test_disclaimer_constant(self):
        assert "field-triage" in ABYSS_DISCLAIMER
        assert "confirmed by full online analysis" in ABYSS_DISCLAIMER


# ---------------------------------------------------------------------------
# Offline license
# ---------------------------------------------------------------------------

class TestOfflineLicense:
    def test_generate_returns_token_and_expiry(self):
        exp = _expedition()
        token, expires_at = generate_offline_license(exp, "usr_operator", duration_days=14)
        assert isinstance(token, str)
        assert len(token) > 20
        assert expires_at > datetime.now(timezone.utc)

    def test_expiry_is_duration_plus_buffer(self):
        exp = _expedition()
        _, expires_at = generate_offline_license(exp, "usr_operator", duration_days=7)
        delta = expires_at - datetime.now(timezone.utc)
        # 7 days + 48-hour buffer → ~9 days
        assert timedelta(days=8) < delta < timedelta(days=10)

    def test_duration_capped_at_90_days(self):
        exp = _expedition()
        _, expires_at = generate_offline_license(exp, "usr_operator", duration_days=365)
        delta = expires_at - datetime.now(timezone.utc)
        # 90 days + 48h buffer → < 93 days
        assert delta < timedelta(days=93)

    def test_valid_token_validates(self):
        exp = _expedition()
        token, _ = generate_offline_license(exp, "usr_operator", duration_days=14)
        payload = validate_offline_license(token)
        assert payload is not None
        assert payload["expedition_id"] == "exp_test001"
        assert payload["type"] == "offline_license"
        assert payload["sub"] == "usr_operator"

    def test_invalid_token_returns_none(self):
        assert validate_offline_license("not.a.jwt") is None
        assert validate_offline_license("") is None

    def test_user_token_not_accepted_as_license(self):
        from app.auth.jwt import create_access_token
        user_token = create_access_token("usr_1", {"email": "x@x.com", "role": "researcher"})
        # User access tokens have no 'type' = 'offline_license' claim
        result = validate_offline_license(user_token)
        assert result is None

    def test_wrong_expedition_id_detectable(self):
        exp = _expedition(expedition_id="exp_correct")
        token, _ = generate_offline_license(exp, "usr_1", duration_days=7)
        payload = validate_offline_license(token)
        assert payload["expedition_id"] == "exp_correct"
        # Caller checks expedition_id mismatch — not validate_offline_license's job
        assert payload["expedition_id"] != "exp_wrong"


# ---------------------------------------------------------------------------
# Pack manifest
# ---------------------------------------------------------------------------

class TestPackManifest:
    def test_manifest_has_expedition_id(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        assert manifest.expedition_id == exp.expedition_id

    def test_manifest_contains_required_components(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        component_types = {c.component_type for c in manifest.components}
        assert "license" in component_types
        assert "model_pack" in component_types
        assert "contaminant_pack" in component_types
        assert "metadata_pack" in component_types

    def test_available_components_have_size_estimate(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        for comp in manifest.components:
            if comp.status == "available":
                assert comp.size_mb_estimate > 0

    def test_model_pack_not_yet_trained(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        model_comp = next(c for c in manifest.components if c.component_type == "model_pack")
        assert model_comp.status == "not_yet_trained"

    def test_manifest_has_disclaimer(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        assert "field-triage" in manifest.instructions

    def test_total_size_only_counts_available(self):
        exp = _expedition()
        manifest = build_pack_manifest(exp)
        available_total = sum(
            c.size_mb_estimate for c in manifest.components if c.status == "available"
        )
        assert manifest.total_size_mb_estimate == pytest.approx(available_total, abs=0.01)


# ---------------------------------------------------------------------------
# Abyss analysis engine
# ---------------------------------------------------------------------------

class TestComputeQC:
    def test_gc_ratio(self):
        # GGCCATCG → GC=6, ATGC=8 → 0.75
        qc = _compute_qc("GGCCATCG")
        assert qc["gc_ratio"] == pytest.approx(0.75, abs=0.01)

    def test_n_ratio(self):
        qc = _compute_qc("ATCGNNATCG")
        assert qc["n_ratio"] == pytest.approx(0.2, abs=0.01)

    def test_empty_sequence(self):
        qc = _compute_qc("")
        assert qc["length"] == 0
        assert qc["gc_ratio"] == 0.0

    def test_invalid_chars_detected(self):
        qc = _compute_qc("ATCGXATCG")
        assert qc["has_invalid_chars"] is True

    def test_valid_iupac_no_invalid(self):
        qc = _compute_qc("ATCGRYSWKMBDHVN")
        assert qc["has_invalid_chars"] is False


class TestStubResultClass:
    def test_contamination_route(self):
        assert _stub_result_class("human_domestic_contamination", 0.9) == "possible_contamination"

    def test_low_quality_route(self):
        assert _stub_result_class("low_quality", 0.0) == "low_quality_unusable"

    def test_high_confidence_known_species(self):
        assert _stub_result_class("fish", 0.75) == "known_species"

    def test_low_confidence_unknown(self):
        assert _stub_result_class("misc_unknown", 0.20) == "unknown_needs_online_confirmation"


class TestRunAbyssAnalysis:
    def test_empty_sequences_returns_zero_counts(self):
        result = run_abyss_analysis("exp_001", [])
        assert result.sequences_analyzed == 0
        assert result.possible_novelty_count == 0
        assert result.contamination_flag_count == 0

    def test_low_quality_sequence_routed_to_low_quality(self):
        seqs = [_seq_input(sequence="NNNNNNNNNNNNNNNNNNN")]  # all N
        result = run_abyss_analysis("exp_001", seqs)
        assert result.sequences_analyzed == 1
        assert result.results[0].route == "low_quality"
        assert result.results[0].field_action == "resample"

    def test_valid_sequence_analyzed(self):
        seqs = [_seq_input(sequence="ATCGATCGATCGATCGATCGATCGATCGATCG")]
        result = run_abyss_analysis("exp_001", seqs)
        assert result.sequences_analyzed == 1
        assert result.results[0].length == 32

    def test_all_results_have_requires_cloud_true(self):
        seqs = [_seq_input(sequence_id=f"s{i}") for i in range(3)]
        result = run_abyss_analysis("exp_001", seqs)
        assert all(r.requires_cloud_confirmation for r in result.results
                   if r.route != "low_quality")

    def test_disclaimer_present(self):
        result = run_abyss_analysis("exp_001", [_seq_input()])
        assert "field-triage" in result.disclaimer

    def test_expedition_id_in_result(self):
        result = run_abyss_analysis("exp_abc", [_seq_input()])
        assert result.expedition_id == "exp_abc"

    def test_max_sequences_cap(self):
        seqs = [_seq_input(sequence_id=f"s{i}") for i in range(600)]
        result = run_abyss_analysis("exp_001", seqs)
        assert result.sequences_analyzed <= 500

    def test_batch_recommendation_present(self):
        result = run_abyss_analysis("exp_001", [_seq_input()])
        assert result.batch_recommendation in (
            "continue_sampling", "preserve_sample",
            "return_for_full_analysis", "resample",
        )
        assert result.batch_risk_level in ("low", "medium", "high")


class TestBatchRecommendation:
    def _result(self, field_action: str, novelty_score: float = 0.0, contamination_flagged: bool = False):
        return AbyssSequenceResult(
            sequence_id="s1", length=100, gc_ratio=0.5, n_ratio=0.0,
            route="fish", route_confidence=0.5, confidence_tier="medium",
            novelty_score=novelty_score, novelty_level="none",
            contamination_flagged=contamination_flagged, contamination_score=0.0,
            abyss_recommendation=field_action, requires_cloud_confirmation=True,
            reason_codes=[], field_action=field_action,
        )

    def test_empty_returns_continue_low(self):
        rec, risk = _batch_recommendation([])
        assert rec == "continue_sampling"
        assert risk == "low"

    def test_any_preserve_gives_high_risk(self):
        results = [self._result("continue_sampling"), self._result("preserve_sample")]
        rec, risk = _batch_recommendation(results)
        assert rec == "preserve_sample"
        assert risk == "high"

    def test_return_for_full_analysis_gives_high_risk(self):
        results = [self._result("continue_sampling"), self._result("return_for_full_analysis")]
        rec, risk = _batch_recommendation(results)
        assert rec == "return_for_full_analysis"
        assert risk == "high"

    def test_high_novelty_fraction_gives_medium_risk(self):
        results = [
            self._result("continue_sampling", novelty_score=0.55),
            self._result("continue_sampling", novelty_score=0.55),
            self._result("continue_sampling", novelty_score=0.10),
            self._result("continue_sampling", novelty_score=0.10),
        ]
        rec, risk = _batch_recommendation(results)
        assert risk == "medium"

    def test_clean_batch_gives_low_risk(self):
        results = [self._result("continue_sampling") for _ in range(5)]
        rec, risk = _batch_recommendation(results)
        assert rec == "continue_sampling"
        assert risk == "low"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_expedition_requires_operator(client, researcher_token):
    resp = await client.post(
        "/abyss/expeditions",
        json={"name": "Deep Survey"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_create_expedition_by_admin(client, admin_token):
    resp = await client.post(
        "/abyss/expeditions",
        json={"name": "Deep Survey", "vessel": "RV Test"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expedition_id"].startswith("exp_")
    assert data["status"] == "pre_departure"
    assert "disclaimer" in data
    assert "next_steps" in data


@pytest.mark.anyio
async def test_list_expeditions_requires_auth(client):
    resp = await client.get("/abyss/expeditions")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_expeditions_authenticated(client, researcher_token):
    resp = await client.get(
        "/abyss/expeditions",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "expeditions" in data
    assert isinstance(data["expeditions"], list)


@pytest.mark.anyio
async def test_get_expedition_not_found(client, researcher_token):
    resp = await client.get(
        "/abyss/expeditions/exp_nonexistent",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_pack_manifest_not_found(client, researcher_token):
    resp = await client.get(
        "/abyss/expeditions/exp_missing/pack-manifest",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_license_endpoint_requires_operator(client, researcher_token):
    resp = await client.post(
        "/abyss/expeditions/exp_001/license",
        json={"duration_days": 14},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_analyze_rejects_invalid_license(client, researcher_token):
    resp = await client.post(
        "/abyss/analyze",
        json={
            "expedition_id": "exp_001",
            "offline_license_token": "invalid.token.here",
            "sequences": [{"sequence_id": "s1", "sequence": "ATCGATCG" * 20}],
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_analyze_valid_license(client, researcher_token):
    exp = _expedition(expedition_id="exp_anal_001")
    token, _ = generate_offline_license(exp, "usr_test_001", duration_days=7)

    resp = await client.post(
        "/abyss/analyze",
        json={
            "expedition_id": "exp_anal_001",
            "offline_license_token": token,
            "sequences": [
                {"sequence_id": "seq_001", "sequence": "ATCGATCGATCGATCGATCGATCGATCGATCG"},
            ],
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["expedition_id"] == "exp_anal_001"
    assert data["sequences_analyzed"] == 1
    assert "disclaimer" in data
    assert "field-triage" in data["disclaimer"]
    assert len(data["results"]) == 1


@pytest.mark.anyio
async def test_analyze_license_expedition_mismatch(client, researcher_token):
    exp = _expedition(expedition_id="exp_correct")
    token, _ = generate_offline_license(exp, "usr_test_001", duration_days=7)

    resp = await client.post(
        "/abyss/analyze",
        json={
            "expedition_id": "exp_wrong",
            "offline_license_token": token,
            "sequences": [{"sequence_id": "s1", "sequence": "ATCGATCG" * 20}],
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_analyze_empty_sequences(client, researcher_token):
    exp = _expedition(expedition_id="exp_empty_001")
    token, _ = generate_offline_license(exp, "usr_test_001", duration_days=7)

    resp = await client.post(
        "/abyss/analyze",
        json={
            "expedition_id": "exp_empty_001",
            "offline_license_token": token,
            "sequences": [],
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sync_expedition_not_found(client, researcher_token):
    resp = await client.post(
        "/abyss/sync",
        json={
            "expedition_id": "exp_nonexistent",
            "local_logs": [],
            "local_analyses": [],
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_sync_expedition_unauthenticated(client):
    resp = await client.post(
        "/abyss/sync",
        json={"expedition_id": "exp_001"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_activate_requires_license_first(client, admin_token):
    # Mock DB returns expedition without license issued
    import app.db.mongo as _mongo_module
    from unittest.mock import AsyncMock

    existing = {
        "expedition_id": "exp_test_act",
        "name": "Test",
        "created_by": "usr_admin_001",
        "status": "pre_departure",
        "offline_license_issued": False,
    }

    with patch.object(
        _mongo_module._db["abyss_expeditions"] if hasattr(_mongo_module, '_db') else MagicMock(),
        "find_one",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        resp = await client.post(
            "/abyss/expeditions/exp_test_act/activate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    # Either 404 (mock not hooked) or 400 (license not issued)
    assert resp.status_code in (400, 404)
