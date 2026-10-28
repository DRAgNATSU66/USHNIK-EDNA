"""
Tests for training/fetch_supplementary.py and its consumers (sources.iter_supplementary,
build_dataset.ingest). No network: every parser and the labelling path run on fixtures.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.inference.models import ROUTE_LABEL_SETS
from training import fetch_supplementary as fs
from training.build_dataset import MAX_SEQ_LEN, Collector, ingest
from training.sources import Record, iter_supplementary, iter_univec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

METAZOA_ENV = {  # what TaxonomyResolver returns for an "environmental samples" taxon
    "kingdom": "Metazoa", "phylum": "Annelida", "class": "Polychaeta",
    "order": "Eunicida", "family": "Eunicidae", "species": "Eunicidae environmental sample",
}
METAZOA_NAMED = {"kingdom": "Metazoa", "phylum": "Annelida", "class": "Polychaeta",
                 "genus": "Palola", "species": "Palola viridis"}
FISH_ENV = {"kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
            "species": "Actinopteri environmental sample"}
HUMAN = {"kingdom": "Metazoa", "phylum": "Chordata", "class": "Mammalia", "order": "Primates",
         "family": "Hominidae", "genus": "Homo", "species": "Homo sapiens"}
# Actinopterygii is a superclass in NCBI, so "Actinopterygii environmental sample" has no class rank
FISH_SUPERCLASS_ENV = {"kingdom": "Metazoa", "phylum": "Chordata",
                       "species": "Actinopterygii environmental sample"}


class FakeTaxonomy:
    table = {
        1: (METAZOA_ENV, "Eunicidae environmental sample"),
        2: (METAZOA_NAMED, "Palola viridis"),
        3: (FISH_ENV, "Actinopteri environmental sample"),
        4: (HUMAN, "Homo sapiens"),
        5: (FISH_SUPERCLASS_ENV, "Actinopterygii environmental sample"),
    }

    def lineage(self, taxid):
        return dict(self.table.get(taxid, ({}, None))[0])

    def scientific_name(self, taxid):
        return self.table.get(taxid, ({}, None))[1]


ANIMAL_Q = fs.QUERIES_BY_ID["ncbi_animal_env_coi"]
VECTOR_Q = fs.QUERIES_BY_ID["ncbi_cloning_vectors"]
SEQ_300 = ("ACGTTGCA" * 40)[:300]


# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

class TestQueryDefinitions:
    def test_ids_unique(self):
        ids = [q.query_id for q in fs.QUERIES]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("q", fs.QUERIES, ids=lambda q: q.query_id)
    def test_target_label_allowed_for_route(self, q):
        assert q.target_label in ROUTE_LABEL_SETS[q.target_route]

    @pytest.mark.parametrize("q", fs.QUERIES, ids=lambda q: q.query_id)
    def test_source_and_basis_known(self, q):
        assert q.source in fs.LICENCES
        assert q.label_basis in ("taxonomy", "provenance")
        assert 0 < q.min_len < q.max_len

    @pytest.mark.parametrize("q", [q for q in fs.QUERIES if q.label_basis == "taxonomy"],
                             ids=lambda q: q.query_id)
    def test_taxonomy_queries_not_chunked_by_build_dataset(self, q):
        # labelled here on the exact sequence build_dataset will label
        assert q.max_len <= MAX_SEQ_LEN

    def test_ncbi_term_carries_length_bounds(self):
        assert ANIMAL_Q.search_term().endswith("AND 150:2000[SLEN]")

    def test_ena_term_carries_length_bounds(self):
        term = fs.QUERIES_BY_ID["ena_animal_env_any"].search_term()
        assert "base_count>=150" in term and "base_count<=2000" in term
        assert "environmental_sample=true" in term


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class TestParsers:
    def test_parse_ncbi_fasta(self):
        text = ">KM364577.1 Eunicidae environmental sample 16S\nACGT\nTTGA\n>NC_001422.1 phiX\nGGG\n"
        assert fs.parse_ncbi_fasta(text) == {"KM364577.1": "ACGTTTGA", "NC_001422.1": "GGG"}

    def test_parse_ena_fasta_versionless_key(self):
        text = ">ENA|AB219791|AB219791.1 Uncultured Urochordata 18S\nACGT\nAC\n>ENA|KC274067|KC274067.2 x\nTT\n"
        assert fs.parse_ena_fasta(text) == {"AB219791": "ACGTAC", "KC274067": "TT"}

    def test_parse_esummary_skips_errors(self):
        payload = {"result": {
            "uids": ["9626372", "1"],
            "9626372": {"accessionversion": "NC_001422.1", "taxid": 2886930,
                        "title": "Escherichia phage phiX174, complete genome",
                        "organism": "Escherichia phage phiX174", "slen": 5386},
            "1": {"error": "cannot get document summary"},
        }}
        out = fs.parse_esummary(payload)
        assert list(out) == ["NC_001422.1"]
        assert out["NC_001422.1"]["taxid"] == "2886930"

    def test_parse_ena_tsv(self):
        text = "accession\ttax_id\tscientific_name\tdescription\tbase_count\n" \
               "AB219791\t335429\tuncultured Urochordata\t18S rRNA\t556\n"
        rows = fs.parse_ena_tsv(text)
        assert rows == [{"accession": "AB219791", "tax_id": "335429",
                         "scientific_name": "uncultured Urochordata",
                         "description": "18S rRNA", "base_count": "556"}]
        assert fs.parse_ena_tsv("") == []

    def test_versionless(self):
        assert fs.versionless("KM364577.1") == "KM364577"
        assert fs.versionless("AB219791") == "AB219791"


# ---------------------------------------------------------------------------
# Sampling, rate limiting, request params
# ---------------------------------------------------------------------------

class TestSamplingAndHttp:
    def test_sample_is_deterministic_and_order_independent(self):
        ids = [str(i) for i in range(1000)]
        a = fs.sample_candidates(ids, 50, "q1")
        b = fs.sample_candidates(list(reversed(ids)), 50, "q1")
        assert a == b and len(a) == 50 and len(set(a)) == 50

    def test_sample_differs_per_query(self):
        ids = [str(i) for i in range(1000)]
        assert fs.sample_candidates(ids, 50, "q1") != fs.sample_candidates(ids, 50, "q2")

    def test_sample_larger_than_pool_returns_all(self):
        assert sorted(fs.sample_candidates(["b", "a", "a"], 10, "q")) == ["a", "b"]

    def test_rate_limiter_spaces_calls(self):
        now = [0.0]
        slept = []

        def sleep(s):
            slept.append(s)
            now[0] += s

        rl = fs.RateLimiter(0.4, clock=lambda: now[0], sleep=sleep)
        rl.wait()
        now[0] += 0.1
        rl.wait()
        rl.wait()
        assert slept == pytest.approx([0.3, 0.4])

    def test_ncbi_rate_under_three_per_second(self):
        assert 1 / fs.NCBI_MIN_INTERVAL_S <= 3

    def test_ncbi_params_identify_tool_without_email(self, monkeypatch):
        monkeypatch.delenv("NCBI_API_KEY", raising=False)
        p = fs.ncbi_params(db="nuccore", term="x")
        assert p["tool"] == "synthveda"
        assert "email" not in p and "api_key" not in p


# ---------------------------------------------------------------------------
# Labelling: must agree with routing.lineage_to_route + labeling.assign_label
# ---------------------------------------------------------------------------

class TestLabelCandidate:
    def test_metazoan_environmental_sample_is_animal_novelty(self):
        out, reason = fs.label_candidate(ANIMAL_Q, SEQ_300, "1", "", FakeTaxonomy())
        assert reason == "ok"
        assert (out["route"], out["label"]) == ("animal_general", "possible_novelty")
        assert out["lineage"]["kingdom"] == "Metazoa"

    def test_named_species_rejected(self):
        out, reason = fs.label_candidate(ANIMAL_Q, SEQ_300, "2", "", FakeTaxonomy())
        assert out is None and reason == "labelled:known_species"

    def test_fish_lineage_rejected_from_animal_query(self):
        out, reason = fs.label_candidate(ANIMAL_Q, SEQ_300, "3", "", FakeTaxonomy())
        assert out is None and reason == "routed_to:fish"

    def test_fish_lineage_accepted_by_fish_query(self):
        q = fs.QUERIES_BY_ID["ncbi_fish_env"]
        out, reason = fs.label_candidate(q, SEQ_300, "3", "", FakeTaxonomy())
        assert reason == "ok" and (out["route"], out["label"]) == ("fish", "possible_novelty")

    def test_superclass_only_fish_routes_to_animal_and_is_rejected(self):
        # documents the measured fish yield loss (README): no class rank -> animal_general
        q = fs.QUERIES_BY_ID["ncbi_fish_env"]
        out, reason = fs.label_candidate(q, SEQ_300, "5", "", FakeTaxonomy())
        assert out is None and reason == "routed_to:animal_general"

    @pytest.mark.parametrize("qid", ["ncbi_human_mito_control_region", "ncbi_human_nuclear_rrna"])
    def test_human_queries_label_through_taxonomy(self, qid):
        q = fs.QUERIES_BY_ID[qid]
        assert q.label_basis == "taxonomy"
        out, reason = fs.label_candidate(q, SEQ_300, "4", "", FakeTaxonomy())
        assert reason == "ok"
        assert (out["route"], out["label"]) == ("human_domestic_contamination", "known_species")
        # a non-human record matching the query text is rejected, not relabelled
        assert fs.label_candidate(q, SEQ_300, "2", "", FakeTaxonomy())[1] == "routed_to:animal_general"

    def test_human_queries_exclude_archaic_subspecies_and_pdb(self):
        for qid in ("ncbi_human_mito_control_region", "ncbi_human_nuclear_rrna"):
            assert "txid9606[Organism:noexp]" in fs.QUERIES_BY_ID[qid].base_query
        assert "NOT srcdb_pdb[PROP]" in fs.QUERIES_BY_ID["ncbi_human_nuclear_rrna"].base_query

    def test_unknown_or_missing_taxid(self):
        assert fs.label_candidate(ANIMAL_Q, SEQ_300, "999", "", FakeTaxonomy())[1] == "taxid_not_in_local_taxdump"
        assert fs.label_candidate(ANIMAL_Q, SEQ_300, "", "", FakeTaxonomy())[1] == "no_taxid"

    def test_length_and_validity(self):
        assert fs.label_candidate(ANIMAL_Q, "ACGT" * 10, "1", "", FakeTaxonomy())[1] == "length_out_of_bounds"
        assert fs.label_candidate(ANIMAL_Q, "ACGT-XYZ", "1", "", FakeTaxonomy())[1] == "invalid_sequence"

    def test_provenance_label_needs_no_taxonomy(self):
        out, reason = fs.label_candidate(VECTOR_Q, "ACGT" * 500, "", "Cloning vector pUC19", None)
        assert reason == "ok"
        assert (out["route"], out["label"]) == ("human_domestic_contamination", "possible_contamination")
        assert out["lineage"] == {}


# ---------------------------------------------------------------------------
# Manifest rows, round-trip into build_dataset
# ---------------------------------------------------------------------------

def _cand(acc, taxid="1", seq=SEQ_300, organism=""):
    return {"accession": acc, "taxid": taxid, "organism": organism, "title": f"title {acc}", "raw_seq": seq}


class TestManifestRoundTrip:
    def test_build_rows_dedup_exclude_and_cap(self):
        q = fs.SupplementaryQuery(**{**fs.asdict(ANIMAL_Q), "max_records": 2})
        cands = [_cand("A1.1"), _cand("A1.2"), _cand("B1.1"), _cand("X9.1"), _cand("C1.1"), _cand("D1.1")]
        rows, fasta, reasons = fs.build_rows(q, cands, FakeTaxonomy(), "2026-10-19T00:00:00+00:00", exclude={"B1"})
        assert [r.accession for r in rows] == ["A1.1", "X9.1"]
        assert reasons["duplicate_accession"] == 2  # A1.2 (same base), B1 (excluded)
        assert reasons["over_cap"] == 2
        r = rows[0]
        assert r.source == "ncbi" and r.retrieved_at.startswith("2026-10-19")
        assert r.licence == fs.LICENCES["ncbi"] and r.taxid == "1" and r.marker == "COI"
        assert fasta[0] == ("A1.1 ncbi_animal_env_coi", SEQ_300)

    def test_files_round_trip_into_records(self, tmp_path):
        ncbi = tmp_path / "ncbi"
        ncbi.mkdir()
        ts = "2026-10-19T00:00:00+00:00"
        rows, fasta, _ = fs.build_rows(ANIMAL_Q, [_cand("A1.1")], FakeTaxonomy(), ts, set())
        fs.write_manifest(ncbi / "ncbi_animal_env_coi.manifest.csv", rows)
        fs.write_fasta(ncbi / "ncbi_animal_env_coi.fasta", fasta)
        vec_seq = "GATC" * 600
        vrows, vfasta, _ = fs.build_rows(VECTOR_Q, [_cand("V1.1", taxid="", seq=vec_seq, organism="Cloning vector pX")],
                                         None, ts, set())
        fs.write_manifest(ncbi / "ncbi_cloning_vectors.manifest.csv", vrows)
        fs.write_fasta(ncbi / "ncbi_cloning_vectors.fasta", vfasta)

        manifest = fs.read_manifest(ncbi / "ncbi_animal_env_coi.manifest.csv")
        assert manifest[0]["accession"] == "A1.1" and manifest[0]["length"] == "300"

        recs = {r.source.split(":")[-1]: r for r in iter_supplementary(tmp_path)}
        animal, vector = recs["ncbi_animal_env_coi"], recs["ncbi_cloning_vectors"]
        assert animal.sequence == SEQ_300 and animal.route is None and animal.label is None
        assert animal.lineage == METAZOA_ENV
        assert (vector.route, vector.label) == ("human_domestic_contamination", "possible_contamination")
        assert fs.already_gathered(tmp_path, fs.QUERIES_BY_ID["ena_animal_env_any"]) == {"A1"}

        collector = Collector(cap=100)
        ingest(collector, iter_supplementary(tmp_path))
        assert collector.buckets[("animal_general", "possible_novelty")] == [SEQ_300]
        # 2400 bp vector > MAX_SEQ_LEN: chunked into 400 bp windows, all provenance-labelled
        vec_windows = collector.buckets[("human_domestic_contamination", "possible_contamination")]
        assert vec_windows and all(len(w) == 400 for w in vec_windows)


class TestIngestProvenance:
    def test_low_quality_window_dropped_not_mislabelled(self):
        rec = Record(sequence="N" * 300, organism_name="v", lineage={}, source="t",
                     route="human_domestic_contamination", label="possible_contamination")
        collector = Collector(cap=10)
        ingest(collector, [rec])
        assert not any(collector.buckets.values())

    def test_univec_is_possible_contamination(self, tmp_path):
        f = tmp_path / "UniVec_Core"
        f.write_text(">gnl|uv|U00001.1:1-50 pUC vector\n" + "GAATTCGAGCTCGGTACCC" * 3 + "\n")
        (rec,) = list(iter_univec(f))
        assert (rec.route, rec.label) == ("human_domestic_contamination", "possible_contamination")
