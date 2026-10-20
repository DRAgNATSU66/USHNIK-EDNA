"""
t-1023-1 (F9): flat, typed taxon fields on every per-sequence result and the
report's taxa section (richness by rank, top taxa, with/without taxon,
reference DB versions).

Decided results have the shape services/worker/app/orchestrator/combiner.py
writes (decision dict; decision_trace.combine with a "taxon" step). Legacy
results are pre-orchestrator: no decision, no trace.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.models.analysis import AnalysisResultDoc, resolve_taxon_fields
from app.reports.builder import TOP_TAXA_LIMIT, _build_taxa, build_report, build_report_csv


def _decision(taxon=None, rank=None, identity=None, route="fish", db="synthveda-reference/fish", ver="v2",
              result_class="known_species", lookup_ran=True):
    return {"final_route": route, "result_class": result_class, "predicted_taxon": taxon, "taxon_rank": rank,
            "percent_identity": identity, "reference_db": db if lookup_ran else None,
            "reference_db_version": ver if lookup_ran else None, "confidence": 0.9, "rule": "head_class"}


def _taxon_step(rule, outcome=None):
    return {"step": "taxon", "rule": rule, "outcome": outcome, "detail": None}


def _seq(sid, decision=None, taxon_step=None, legacy_taxon=None, route=None, result_class=None):
    r = {"sequence_id": sid, "sequence": "ACGT" * 30, "length": 120, "gc_ratio": 0.5, "n_ratio": 0.0,
         "route": route or (decision or {}).get("final_route") or "fish", "route_confidence": 0.9,
         "result_class": result_class or (decision or {}).get("result_class") or "unknown_needs_online_confirmation",
         "predicted_taxon": (decision or {}).get("predicted_taxon") if decision else legacy_taxon,
         "confidence": 0.9, "novelty_score": 0.0, "contamination_score": 0.0, "model_version_used": "v2",
         "reason_codes": []}
    if decision is not None:
        r["decision"] = decision
        r["decision_trace"] = {"orchestrator_version": "orchestrator-1.2.0", "plan": {}, "evidence": [],
                               "combine": [taxon_step] if taxon_step else []}
    return r


def _doc(results, orchestrator_version="orchestrator-1.2.0"):
    return {"analysis_id": "ana_tax001", "job_id": "job_tax001", "upload_id": "upl_tax001",
            "user_id": "usr_test_001", "mode": "online_full", "model_version_set": "v2",
            "orchestrator_version": orchestrator_version, "results": results,
            "created_at": datetime(2026, 10, 20, tzinfo=timezone.utc)}


# ---------------------------------------------------------------------------
# resolve_taxon_fields / SequenceResult
# ---------------------------------------------------------------------------

class TestResolveTaxonFields:
    def test_decision_first(self):
        r = _seq("s1", _decision("Gadus morhua", "species", 99.5))
        r["predicted_taxon"] = "something stale"  # decision wins, as in partner/summary.py
        assert resolve_taxon_fields(r) == {
            "predicted_taxon": "Gadus morhua", "taxon_rank": "species", "percent_identity": 99.5,
            "reference_db": "synthveda-reference/fish", "reference_db_version": "v2", "taxon_source": "decision",
        }

    def test_decision_without_assignment_keeps_nulls(self):
        out = resolve_taxon_fields(_seq("s1", _decision(None, None, None, result_class="possible_novelty")))
        assert out["predicted_taxon"] is None and out["taxon_rank"] is None and out["percent_identity"] is None
        # The lookup ran, so the reference DB is still named.
        assert out["reference_db"] == "synthveda-reference/fish" and out["reference_db_version"] == "v2"
        assert out["taxon_source"] == "decision"

    def test_legacy_result_has_only_predicted_taxon(self):
        out = resolve_taxon_fields(_seq("s1", legacy_taxon="Gadus morhua"))
        assert out == {"predicted_taxon": "Gadus morhua", "taxon_rank": None, "percent_identity": None,
                       "reference_db": None, "reference_db_version": None, "taxon_source": "legacy"}

    def test_legacy_null_taxon(self):
        out = resolve_taxon_fields(_seq("s1"))
        assert out["predicted_taxon"] is None and out["taxon_source"] == "legacy"

    def test_integer_identity_is_float(self):
        out = resolve_taxon_fields(_seq("s1", _decision("Gadus morhua", "species", 100)))
        assert out["percent_identity"] == 100.0 and isinstance(out["percent_identity"], float)


class TestSequenceResultFlatFields:
    def test_decided_result(self):
        r = AnalysisResultDoc(**_doc([_seq("s1", _decision("Lophius budegassa", "species", 100.0))])).results[0]
        assert (r.predicted_taxon, r.taxon_rank, r.percent_identity, r.reference_db, r.reference_db_version,
                r.taxon_source) == ("Lophius budegassa", "species", 100.0, "synthveda-reference/fish", "v2",
                                    "decision")

    def test_legacy_result(self):
        r = AnalysisResultDoc(**_doc([_seq("s1", legacy_taxon="Gadus morhua")], None)).results[0]
        assert r.predicted_taxon == "Gadus morhua"
        assert r.taxon_rank is None and r.percent_identity is None
        assert r.reference_db is None and r.reference_db_version is None
        assert r.taxon_source == "legacy"

    def test_round_trip_is_stable(self):
        """GET /analysis rebuilds the model from its own dump (AnalysisResultWithContext)."""
        doc = AnalysisResultDoc(**_doc([_seq("s1", _decision("Gadus", "genus", 97.0)),
                                        _seq("s2", legacy_taxon="X y")]))
        again = AnalysisResultDoc(**doc.model_dump())
        assert again.model_dump() == doc.model_dump()


class _Collection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query):
        docs = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]

        class _Cursor:
            def __aiter__(self):
                self._it = iter(docs)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

        return _Cursor()


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def fake_db():
    db = _FakeDb()
    with patch.object(_mongo_module, "_db", db):
        yield db


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(fake_db, results, orchestrator_version="orchestrator-1.2.0"):
    fake_db["uploads"].docs.append({"upload_id": "upl_tax001", "user_id": "usr_test_001",
                                    "original_filename": "s.fasta", "file_size_bytes": 1, "status": "stored"})
    fake_db["analysis_results"].docs.append(_doc(results, orchestrator_version))


@pytest.mark.anyio
async def test_get_analysis_exposes_flat_fields(client, researcher_token, fake_db):
    _seed(fake_db, [_seq("s1", _decision("Lophius budegassa", "species", 100.0)),
                    _seq("s2", _decision(None, None, None, result_class="possible_novelty"),
                         _taxon_step("no_reference_assignment", "no_hit"))])
    for trace in ("true", "false"):
        resp = await client.get(f"/analysis/ana_tax001?include_trace={trace}", headers=_auth(researcher_token))
        assert resp.status_code == 200, resp.text
        r1, r2 = resp.json()["results"]
        assert r1["taxon_rank"] == "species" and r1["percent_identity"] == 100.0
        assert r1["reference_db_version"] == "v2" and r1["taxon_source"] == "decision"
        assert r2["predicted_taxon"] is None and r2["taxon_rank"] is None
        assert r2["reference_db"] == "synthveda-reference/fish"


@pytest.mark.anyio
async def test_get_analysis_legacy_doc_has_null_fields(client, researcher_token, fake_db):
    _seed(fake_db, [_seq("s1")], orchestrator_version=None)
    resp = await client.get("/analysis/ana_tax001", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    r = resp.json()["results"][0]
    for f in ("predicted_taxon", "taxon_rank", "percent_identity", "reference_db", "reference_db_version"):
        assert r[f] is None, f
    assert r["taxon_source"] == "legacy" and r["decision"] is None


# ---------------------------------------------------------------------------
# Report taxa section
# ---------------------------------------------------------------------------

def _mixed_results():
    return [
        _seq("s1", _decision("Gadus morhua", "species", 100.0)),
        _seq("s2", _decision("Gadus morhua", "species", 98.0)),
        _seq("s3", _decision("Gadus morhua", "species", 99.0)),
        # Same genus name at genus rank: counted at genus, not merged with the species.
        _seq("s4", _decision("Gadus", "genus", 96.5, result_class="likely_taxonomic_group")),
        _seq("s5", _decision("Chaetomitrium", "genus", 100.0, route="plant", db="synthveda-reference/plant",
                             result_class="likely_taxonomic_group")),
        _seq("s6", _decision("Cossidae", "family", 91.43, route="animal_general",
                             db="synthveda-reference/animal_general", result_class="likely_taxonomic_group")),
        _seq("s7", _decision(None, None, None, result_class="possible_novelty"),
             _taxon_step("no_reference_assignment", "below_threshold")),
        _seq("s8", _decision(None, None, None, result_class="unknown_needs_online_confirmation", lookup_ran=False),
             _taxon_step("heads_only")),
        _seq("s9", _decision(None, None, None, route="low_quality", result_class="low_quality_unusable",
                             lookup_ran=False)),
        _seq("s10", _decision(None, None, None, result_class="unknown_needs_online_confirmation")),
    ]


class TestTaxaSection:
    def test_counts(self):
        t = _build_taxa(_mixed_results(), "orchestrator-1.2.0")
        assert t.available is True and t.unavailable_reason is None
        assert t.orchestrator_version == "orchestrator-1.2.0"
        assert (t.total_sequences, t.sequences_with_decision, t.sequences_with_taxon, t.sequences_without_taxon) \
            == (10, 10, 6, 4)
        assert t.fraction_with_taxon == 0.6
        assert t.without_taxon_reasons == {
            "heads_only": 1, "low_quality": 1, "no_reference_assignment:below_threshold": 1, "not_recorded": 1,
        }

    def test_richness_by_rank_does_not_mix_ranks(self):
        t = _build_taxa(_mixed_results(), None)
        by_rank = {r.rank: (r.distinct_taxa, r.sequences) for r in t.richness_by_rank}
        assert by_rank == {"species": (1, 3), "genus": (2, 2), "family": (1, 1)}
        # "Gadus" (genus) and "Gadus morhua" (species) are two groups.
        assert t.taxon_groups == 4
        # Finest rank first, not by count.
        assert [r.rank for r in t.richness_by_rank] == ["species", "genus", "family"]

    def test_rank_order_puts_unknown_and_unranked_last(self):
        t = _build_taxa([_seq("s1", _decision("A", None, 90.0)), _seq("s2", _decision("B", "subspecies", 99.0)),
                         _seq("s3", _decision("C", "class", 85.0)), _seq("s4", _decision("D", "species", 99.0))],
                        None)
        assert [r.rank for r in t.richness_by_rank] == ["species", "class", "subspecies", "unranked"]

    def test_top_taxa(self):
        t = _build_taxa(_mixed_results(), None)
        top = t.top_taxa[0]
        assert (top.taxon, top.taxon_rank, top.sequences) == ("Gadus morhua", "species", 3)
        assert top.fraction_of_assigned == 0.5
        assert top.mean_percent_identity == 99.0
        assert (top.min_percent_identity, top.max_percent_identity, top.sequences_with_identity) == (98.0, 100.0, 3)
        assert top.routes == ["fish"] and top.reference_db_versions == ["synthveda-reference/fish v2"]
        # Ties (1 sequence each) by name.
        assert [e.taxon for e in t.top_taxa[1:]] == ["Chaetomitrium", "Cossidae", "Gadus"]
        assert t.top_taxa[3].taxon_rank == "genus"

    def test_identity_missing_is_none_not_zero(self):
        t = _build_taxa([_seq("s1", _decision("Gadus morhua", "species", None))], None)
        e = t.top_taxa[0]
        assert e.mean_percent_identity is None and e.sequences_with_identity == 0

    def test_reference_dbs(self):
        t = _build_taxa(_mixed_results(), None)
        got = {(u.reference_db, u.reference_db_version): (u.sequences, u.sequences_with_taxon)
               for u in t.reference_dbs}
        assert got == {
            ("synthveda-reference/animal_general", "v2"): (1, 1),
            ("synthveda-reference/fish", "v2"): (6, 4),   # s1-s4 assigned, s7 and s10 not
            ("synthveda-reference/plant", "v2"): (1, 1),
        }

    def test_top_taxa_limit(self):
        results = [_seq(f"s{i}", _decision(f"Taxon {i:02d}", "species", 99.0)) for i in range(TOP_TAXA_LIMIT + 5)]
        t = _build_taxa(results, None)
        assert len(t.top_taxa) == TOP_TAXA_LIMIT
        assert t.taxon_groups == TOP_TAXA_LIMIT + 5
        assert t.richness_by_rank[0].distinct_taxa == TOP_TAXA_LIMIT + 5

    def test_unranked_taxon(self):
        t = _build_taxa([_seq("s1", _decision("Something", None, 97.0))], None)
        assert [(r.rank, r.distinct_taxa) for r in t.richness_by_rank] == [("unranked", 1)]
        assert t.top_taxa[0].taxon_rank is None

    def test_all_decided_none_assigned(self):
        t = _build_taxa([_seq("s1", _decision(None, None, None), _taxon_step("no_reference_assignment", "no_hit"))],
                        None)
        assert t.available is True
        assert (t.sequences_with_taxon, t.fraction_with_taxon, t.taxon_groups) == (0, 0.0, 0)
        assert t.top_taxa == [] and t.richness_by_rank == []

    def test_partly_decided_counts_only_decided(self):
        t = _build_taxa([_seq("s1", _decision("Gadus morhua", "species", 99.0)),
                         _seq("s2", legacy_taxon="Legacy name")], None)
        assert (t.total_sequences, t.sequences_with_decision, t.sequences_with_taxon) == (2, 1, 1)
        assert [e.taxon for e in t.top_taxa] == ["Gadus morhua"]


class TestTaxaUnavailable:
    def test_pre_orchestrator_is_unavailable_not_zero(self):
        t = _build_taxa([_seq("s1"), _seq("s2")], None)
        assert t.available is False
        assert "predates the orchestrator" in t.unavailable_reason
        for f in ("sequences_with_taxon", "sequences_without_taxon", "fraction_with_taxon", "taxon_groups"):
            assert getattr(t, f) is None, f
        assert t.richness_by_rank == [] and t.top_taxa == [] and t.reference_dbs == []
        assert t.total_sequences == 2 and t.sequences_with_decision == 0

    def test_pre_orchestrator_with_legacy_names_says_so(self):
        t = _build_taxa([_seq("s1", legacy_taxon="Gadus morhua"), _seq("s2")], None)
        assert t.available is False
        assert "1 of 2 sequences carry a legacy predicted_taxon" in t.unavailable_reason

    def test_empty_analysis(self):
        t = _build_taxa([], None)
        assert t.available is False and t.unavailable_reason == "The analysis has no sequences."
        assert t.sequences_with_taxon is None


class TestReportIntegration:
    def test_build_report_carries_taxa_and_flat_fields(self):
        report = build_report(_doc(_mixed_results()), [], upload=None)
        assert report.report_version == "1.1"
        assert report.taxa is not None and report.taxa.sequences_with_taxon == 6
        known = {e.sequence_id: e for e in report.known_species}
        assert known["s1"].taxon_rank == "species" and known["s1"].percent_identity == 100.0
        assert known["s1"].reference_db_version == "v2" and known["s1"].taxon_source == "decision"
        rows = {e.sequence_id: e for e in report.taxonomic_assignments}
        assert "s9" not in rows                          # low quality stays excluded
        assert rows["s6"].taxon_rank == "family" and rows["s6"].result_class == "likely_taxonomic_group"
        assert rows["s7"].predicted_taxon is None and rows["s7"].reference_db == "synthveda-reference/fish"

    def test_legacy_report(self):
        report = build_report(_doc([_seq("s1", legacy_taxon="Gadus morhua", result_class="known_species")], None),
                              [], upload=None)
        assert report.taxa.available is False
        e = report.known_species[0]
        assert e.predicted_taxon == "Gadus morhua" and e.taxon_rank is None and e.taxon_source == "legacy"
        # Existing field kept for current readers.
        assert report.biodiversity.predicted_taxon_richness == 1

    def test_csv_appends_taxon_columns(self):
        report = build_report(_doc(_mixed_results()), [], upload=None)
        rows = list(csv.DictReader(io.StringIO(build_report_csv(report))))
        header = build_report_csv(report).splitlines()[0].split(",")
        assert header[:11] == ["sequence_id", "route", "category", "predicted_taxon", "confidence",
                               "novelty_score", "novelty_level", "contamination_score", "contamination_type",
                               "model_version_used", "reason_codes"]
        assert header[11:] == ["taxon_rank", "percent_identity", "reference_db", "reference_db_version"]
        s1 = next(r for r in rows if r["sequence_id"] == "s1")
        assert (s1["taxon_rank"], s1["percent_identity"], s1["reference_db_version"]) == ("species", "100.0", "v2")


@pytest.mark.anyio
async def test_report_endpoints_return_taxa(client, researcher_token, fake_db):
    _seed(fake_db, _mixed_results())
    resp = await client.get("/reports/ana_tax001", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    taxa = resp.json()["taxa"]
    assert taxa["available"] is True and taxa["sequences_with_taxon"] == 6
    assert taxa["top_taxa"][0]["taxon"] == "Gadus morhua"
    assert set(taxa["definitions"]) >= {"taxon", "richness_by_rank", "top_taxa", "reference_dbs"}

    resp = await client.get("/reports/ana_tax001/summary", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["taxa"]["richness_by_rank"][0]["rank"] == "species"


@pytest.mark.anyio
async def test_report_endpoint_legacy_taxa_unavailable(client, researcher_token, fake_db):
    _seed(fake_db, [_seq("s1")], orchestrator_version=None)
    resp = await client.get("/reports/ana_tax001/summary", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    taxa = resp.json()["taxa"]
    assert taxa["available"] is False and taxa["sequences_with_taxon"] is None
    assert "predates the orchestrator" in taxa["unavailable_reason"]
