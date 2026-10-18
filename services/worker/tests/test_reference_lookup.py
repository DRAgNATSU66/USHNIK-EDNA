"""Reference-lookup evidence provider (B4, t-1021-2): rank thresholds, LCA on
ties, query coverage, unavailable paths, and end-to-end vsearch / BLAST /
GRCh38 searches against a tiny synthetic reference built in tmp (skipped
cleanly when the tools are not installed)."""
from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import pytest

from app.config import WorkerSettings
from app.evidence import reference_lookup as rl
from app.evidence.reference_lookup import (
    LookupThresholds,
    ReferenceHit,
    ReferenceLookupProvider,
    assign_taxon,
    lca,
    parse_reference_header,
)
from training import build_reference_db as brd

TH = LookupThresholds()  # 97 / 95 / 90, 80 % coverage, 50 columns, tie 0.5

PERCA_FLU = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
             "order": "Perciformes", "family": "Percidae", "genus": "Perca", "species": "Perca fluviatilis"}
PERCA_FLA = {**PERCA_FLU, "species": "Perca flavescens"}
SANDER = {**PERCA_FLU, "genus": "Sander", "species": "Sander lucioperca"}
SALMO = {**PERCA_FLU, "order": "Salmoniformes", "family": "Salmonidae", "genus": "Salmo", "species": "Salmo trutta"}


def hit(lineage, identity, qcov=100.0, alnlen=300, tid="X1"):
    return ReferenceHit(target_id=tid, accession="ACC1", source="midori2", marker="CO1", taxid=None,
                        identity=identity, alignment_length=alnlen, query_coverage=qcov, lineage=dict(lineage))


# ---------------------------------------------------------------------------
# pure assignment logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("identity,rank,taxon", [
    (100.0, "species", "Perca fluviatilis"),
    (97.0, "species", "Perca fluviatilis"),     # boundary is inclusive
    (96.9, "genus", "Perca"),
    (95.0, "genus", "Perca"),
    (94.9, "family", "Percidae"),
    (90.0, "family", "Percidae"),
])
def test_identity_thresholds_cap_the_rank(identity, rank, taxon):
    a = assign_taxon([hit(PERCA_FLU, identity)], TH)
    assert (a.status, a.rank, a.taxon, a.identity) == ("assigned", rank, taxon, identity)
    assert "species" not in a.lineage or rank == "species"


def test_below_family_threshold_is_not_assigned_but_keeps_nearest():
    a = assign_taxon([hit(PERCA_FLU, 89.9)], TH)
    assert a.status == "below_threshold" and a.taxon is None and a.rank is None
    assert a.identity == 89.9 and a.identity_rank is None


def test_no_hits():
    a = assign_taxon([], TH)
    assert a.status == "no_hit" and a.taxon is None and a.reason == "no reference hit"


def test_low_coverage_hit_is_ignored():
    # 100 % identity over 60 % of the query: a fragment, not the read
    a = assign_taxon([hit(PERCA_FLU, 100.0, qcov=60.0)], TH)
    assert a.status == "no_hit" and "80%" in a.reason
    # ... but a full-coverage lower-identity hit is used instead
    a = assign_taxon([hit(PERCA_FLU, 100.0, qcov=60.0, tid="A"), hit(SANDER, 96.0, qcov=95.0, tid="B")], TH)
    assert (a.rank, a.taxon) == ("genus", "Sander")


def test_short_alignment_is_ignored():
    a = assign_taxon([hit(PERCA_FLU, 100.0, alnlen=40)], TH)
    assert a.status == "no_hit"


def test_tie_across_species_resolves_to_genus():
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(PERCA_FLA, 98.6, tid="B")], TH)
    assert (a.status, a.rank, a.taxon) == ("assigned", "genus", "Perca")
    assert a.lca_applied and a.tied_hits == 2 and a.tied_taxa == 2
    assert "agree only to genus" in a.reason


def test_tie_across_genera_resolves_to_family_and_across_orders_to_class():
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(SANDER, 99.0, tid="B")], TH)
    assert (a.rank, a.taxon) == ("family", "Percidae")
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(SALMO, 99.0, tid="B")], TH)
    assert (a.rank, a.taxon) == ("class", "Actinopteri")


def test_hit_outside_tie_delta_does_not_coarsen():
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(PERCA_FLA, 98.4, tid="B")], TH)
    assert (a.rank, a.taxon) == ("species", "Perca fluviatilis") and not a.lca_applied
    strict = LookupThresholds(tie_delta=0.0)
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(PERCA_FLA, 98.9, tid="B")], strict)
    assert a.rank == "species"


def test_same_taxon_ties_are_not_an_lca():
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(PERCA_FLU, 99.0, tid="B")], TH)
    assert a.rank == "species" and not a.lca_applied and a.tied_hits == 2 and a.tied_taxa == 1


def test_genus_only_reference_tied_with_species_gives_genus():
    genus_only = {k: v for k, v in PERCA_FLU.items() if k != "species"}
    a = assign_taxon([hit(PERCA_FLU, 99.0, tid="A"), hit(genus_only, 99.0, tid="B")], TH)
    assert (a.rank, a.taxon) == ("genus", "Perca")


def test_reference_resolved_only_to_genus_reports_genus():
    genus_only = {k: v for k, v in PERCA_FLU.items() if k != "species"}
    a = assign_taxon([hit(genus_only, 100.0)], TH)
    assert (a.rank, a.taxon) == ("genus", "Perca") and "resolved only to genus" in a.reason


def test_lca_tolerates_missing_intermediate_ranks():
    no_class = {k: v for k, v in PERCA_FLA.items() if k != "class"}
    out = lca([PERCA_FLU, no_class])
    assert out["genus"] == "Perca" and out["class"] == "Actinopteri" and "species" not in out


def test_no_consensus_when_tied_hits_share_nothing():
    a = assign_taxon([hit({"species": "A a"}, 99.0, tid="A"), hit({"species": "B b"}, 99.0, tid="B")], TH)
    assert a.status == "no_consensus" and a.taxon is None


def test_threshold_order_is_validated():
    with pytest.raises(ValueError):
        LookupThresholds(species=95.0, genus=97.0)


def test_thresholds_come_from_settings(monkeypatch):
    monkeypatch.setenv("REFERENCE_SPECIES_IDENTITY", "98.5")
    monkeypatch.setenv("REFERENCE_MIN_QUERY_COVERAGE", "70")
    th = LookupThresholds.from_settings(WorkerSettings(_env_file=None))
    assert th.species == 98.5 and th.min_query_coverage == 70.0 and th.genus == 95.0


def test_header_parser_matches_builder():
    headers = [
        brd.format_header("FSH0000001", PERCA_FLU, "midori2", "CO1", "MG559732.1", 8168, 3),
        brd.format_header("BAC0000002", {"superkingdom": "Bacteria", "genus": "Bacillus"}, "silva", "SSU", "", None, 1),
        "lcl|HDC0000003 tax=k:Metazoa,s:Homo_sapiens;src=univec;marker=vector;acc=NA;n=1;",
    ]
    for h in headers:
        assert parse_reference_header(h) == brd.parse_header(h)
        assert parse_reference_header(">" + h) == brd.parse_header(">" + h)


# ---------------------------------------------------------------------------
# synthetic reference on disk
# ---------------------------------------------------------------------------

def _tool(name):
    return rl._find_tool(name, None, brd.default_data_root())


HAVE_VSEARCH = _tool("vsearch") is not None
HAVE_BLAST = _tool("blastn") is not None and _tool("makeblastdb") is not None

_rng = random.Random(7)
BASE = "".join(_rng.choice("ACGT") for _ in range(300))


def mutate(seq: str, positions) -> str:
    s = list(seq)
    for p in positions:
        s[p] = {"A": "C", "C": "G", "G": "T", "T": "A"}[s[p]]
    return "".join(s)


def spread(n: int, offset: int = 0, length: int = 300) -> list[int]:
    step = length // n
    return [(offset + i * step) % length for i in range(n)]


REF_A = BASE                                   # Perca fluviatilis
REF_B = mutate(BASE, spread(30, 3))            # Perca flavescens, 90 % to A
REF_C = mutate(BASE, spread(60, 5))            # Sander lucioperca, 80 % to A
TIE_1 = "".join(_rng.choice("ACGT") for _ in range(300))       # Salmo trutta
TIE_2 = mutate(TIE_1, [100, 200])                                # Salmo salar
HUMAN = "".join(_rng.choice("ACGT") for _ in range(400))
SALMO_SALAR = {**SALMO, "species": "Salmo salar"}

REFS = [("FSH0000001", PERCA_FLU, REF_A), ("FSH0000002", PERCA_FLA, REF_B), ("FSH0000003", SANDER, REF_C),
        ("FSH0000004", SALMO, TIE_1), ("FSH0000005", SALMO_SALAR, TIE_2)]


def _write_route(vdir: Path, route: str, refs, udb: bool, blast: bool) -> dict:
    rdir = vdir / route
    rdir.mkdir(parents=True)
    fasta = rdir / "ref.fasta"
    tmap = rdir / "taxid_map.txt"
    with open(fasta, "w") as fh, open(tmap, "w") as tm:
        for i, (sid, lin, seq) in enumerate(refs, 1):
            fh.write(f">{brd.format_header(sid, lin, 'midori2', 'CO1', f'ACC{i}.1', 1000 + i, 1)}\n{seq}\n")
            tm.write(f"{sid}\t{1000 + i}\n")
    if udb:
        assert brd.build_udb(_tool("vsearch"), fasta, rdir / "ref.udb", 1)["ok"]
    if blast:
        assert brd.build_blastdb(_tool("makeblastdb"), fasta, rdir / "blast" / "ref", "t", tmap)["ok"]
    return {"sequences": len(refs), "fasta": {"sha256": brd.sha256_file(fasta)}}


@pytest.fixture
def refroot(tmp_path):
    root = tmp_path / "reference"
    vdir = root / "vtest"
    routes = {"fish": _write_route(vdir, "fish", REFS, HAVE_VSEARCH, HAVE_BLAST)}
    human_refs = [("HDC0000001", {"genus": "Gallus", "species": "Gallus gallus"}, REF_A)]
    routes["human_domestic_contamination"] = _write_route(vdir, "human_domestic_contamination", human_refs,
                                                          HAVE_VSEARCH, HAVE_BLAST)
    if HAVE_BLAST:
        g = vdir / "human_domestic_contamination" / "grch38_blast"
        g.mkdir()
        fa = g / "in.fa"
        fa.write_text(f">lcl|chr7 Homo sapiens GRCh38 chr7\n{'A' * 50}{HUMAN}{'C' * 50}\n")
        subprocess.run([str(_tool("makeblastdb")), "-in", str(fa), "-dbtype", "nucl", "-parse_seqids",
                        "-blastdb_version", "5", "-out", str(g / "grch38"), "-taxid", "9606"],
                       check=True, capture_output=True)
    (vdir / "manifest.json").write_text(json.dumps({"version": "vtest", "routes": routes}))
    (root / "CURRENT").write_text("vtest\n")
    return root


def provider(root: Path, **kw) -> ReferenceLookupProvider:
    s = WorkerSettings(_env_file=None, reference_db_root=str(root), reference_threads=1, **kw)
    return ReferenceLookupProvider(s, data_root=root.parent)


# 'tie': TIE_1 with position 100 set to TIE_2's base -> one mismatch to each
_t = list(TIE_1)
_t[100] = TIE_2[100]
TIE_QUERY = "".join(_t)

QUERIES = [
    ("exact", REF_A),                               # 100 % -> species
    ("genus", mutate(REF_A, spread(12, 1))),        # 96 % -> genus Perca
    ("family", mutate(REF_A, spread(21, 2))),       # 93 % -> family Percidae
    ("far", mutate(REF_A, spread(45, 4))),          # 85 % -> below threshold
    ("chimera", REF_A[:150] + "".join(random.Random(3).choice("ACGT") for _ in range(150))),  # 50 % coverage
    ("tie", TIE_QUERY),                             # equidistant from Salmo trutta / salar -> genus
    ("short", REF_A[:30]),
    ("dup", REF_A),
]
EXPECT = {
    "exact": ("assigned", "species", "Perca fluviatilis"),
    "genus": ("assigned", "genus", "Perca"),
    "family": ("assigned", "family", "Percidae"),
    "far": ("below_threshold", None, None),
    "chimera": ("no_hit", None, None),
    "tie": ("assigned", "genus", "Salmo"),
    "short": ("no_hit", None, None),
    "dup": ("assigned", "species", "Perca fluviatilis"),
}


def _check(evidence, method):
    assert [e.sequence_id for e in evidence] == [q for q, _ in QUERIES]
    got = {e.sequence_id: (e.status, e.rank, e.taxon) for e in evidence}
    assert got == EXPECT
    by = {e.sequence_id: e for e in evidence}
    for e in evidence:
        assert e.available and e.method == method
        assert e.reference_db == "synthveda-reference/fish" and e.reference_db_version == "vtest"
        assert e.reference_db_sha256 and e.thresholds["species"] == 97.0
        assert e.run["elapsed_seconds"] >= 0 and e.run["batch_size"] == len(QUERIES)
    assert by["exact"].identity == 100.0 and by["exact"].hits[0].accession == "ACC1.1"
    assert abs(by["genus"].identity - 96.0) < 0.6
    assert by["far"].hits and by["far"].identity < 90  # nearest neighbour still reported
    assert by["tie"].assignment.lca_applied and by["tie"].assignment.tied_taxa == 2
    assert by["exact"].run["unique_queries"] == 6  # 'dup' searched once, 'short' not searched
    d = by["exact"].to_dict()
    json.dumps(d)
    assert d["taxon"] == "Perca fluviatilis" and d["hits"][0]["lineage"]["genus"] == "Perca"


@pytest.mark.skipif(not HAVE_VSEARCH, reason="vsearch not installed")
def test_vsearch_end_to_end(refroot):
    ev = provider(refroot, reference_method="vsearch").lookup(QUERIES, "fish")
    _check(ev, "vsearch")
    assert ev[0].run["peak_rss_mb"] and ev[0].run["method_reason"] == "configured"


@pytest.mark.skipif(not HAVE_BLAST, reason="BLAST+ not installed")
def test_blast_end_to_end(refroot):
    # task blastn (word 11): the spread-out mismatches of the 96 % / 93 % queries
    # leave no 28-mer seed, so megablast (the default) would miss them, which
    # is megablast's known sensitivity floor, not the parsing under test here.
    _check(provider(refroot, reference_method="blast", reference_blast_task="blastn").lookup(QUERIES, "fish"), "blast")


@pytest.mark.skipif(not (HAVE_VSEARCH and HAVE_BLAST), reason="vsearch and BLAST+ needed")
def test_auto_falls_back_to_blast_over_udb_budget(refroot):
    ev = provider(refroot).lookup(QUERIES[:1], "fish")
    assert ev[0].method == "vsearch" and "within" in ev[0].run["method_reason"]
    ev = provider(refroot, reference_vsearch_max_udb_gb=1e-9).lookup(QUERIES[:1], "fish")
    assert ev[0].method == "blast" and "over" in ev[0].run["method_reason"]
    assert ev[0].taxon == "Perca fluviatilis"


@pytest.mark.skipif(not HAVE_BLAST, reason="BLAST+ not installed")
def test_human_route_grch38_hit_is_contamination_evidence(refroot):
    ev = provider(refroot, reference_method="blast").lookup(
        [("human", HUMAN[20:320]), ("gallus", REF_A)], "human_domestic_contamination")
    h, g = ev
    assert h.human_genome.available and h.human_genome.hit and h.human_genome.contamination
    assert h.human_genome.subject == "chr7" and h.human_genome.identity == 100.0
    assert h.status == "no_hit"  # nothing in the route DB; the genome is separate evidence
    assert g.taxon == "Gallus gallus" and g.human_genome.available and not g.human_genome.hit
    assert ev[0].run["grch38_seconds"] is not None


def test_non_human_route_has_no_genome_evidence(refroot, monkeypatch):
    monkeypatch.setattr(rl.ReferenceLookupProvider, "choose_method", lambda self, db: (_ for _ in ()).throw(rl._Unavailable("x")))
    ev = provider(refroot).lookup([("a", REF_A)], "fish")
    assert ev[0].human_genome is None


# ---------------------------------------------------------------------------
# unavailable paths: explicit reason, never a taxon
# ---------------------------------------------------------------------------

def _assert_unavailable(ev, needle):
    assert len(ev) == 2
    for e in ev:
        assert not e.available and e.status == "unavailable" and e.taxon is None and e.rank is None
        assert not e.hits and needle in e.reason and e.assignment.reason == e.reason
        assert e.to_dict()["status"] == "unavailable"


TWO = [("a", REF_A), ("b", REF_B)]


def test_unavailable_missing_root(tmp_path):
    _assert_unavailable(provider(tmp_path / "nope").lookup(TWO, "fish"), "root not found")


def test_unavailable_missing_current(refroot):
    (refroot / "CURRENT").unlink()
    _assert_unavailable(provider(refroot).lookup(TWO, "fish"), "CURRENT")


def test_unavailable_missing_version_and_manifest(refroot):
    _assert_unavailable(provider(refroot, reference_db_version="v9").lookup(TWO, "fish"), "manifest not found")
    (refroot / "vtest" / "manifest.json").write_text("{not json")
    _assert_unavailable(provider(refroot).lookup(TWO, "fish"), "manifest unreadable")


def test_unavailable_unknown_route(refroot):
    _assert_unavailable(provider(refroot).lookup(TWO, "plant"), "has no reference DB")


def test_unavailable_no_tools(refroot, monkeypatch):
    monkeypatch.setattr(rl, "_find_tool", lambda name, tools_dir, data_root: None)
    ev = provider(refroot).lookup(TWO, "fish")
    _assert_unavailable(ev, "not found")
    assert ev[0].reference_db_version == "vtest"  # provenance still reported


def test_unavailable_no_index_files(refroot):
    (refroot / "vtest" / "fish" / "ref.udb").unlink(missing_ok=True)
    for f in (refroot / "vtest" / "fish").glob("blast/*"):
        f.unlink()
    _assert_unavailable(provider(refroot).lookup(TWO, "fish"), "no UDB")
    _assert_unavailable(provider(refroot, reference_method="blast").lookup(TWO, "fish"), "no BLAST DB")


@pytest.mark.skipif(not HAVE_VSEARCH, reason="vsearch not installed")
def test_unavailable_when_search_fails(refroot):
    (refroot / "vtest" / "fish" / "ref.udb").write_bytes(b"not a udb")
    _assert_unavailable(provider(refroot, reference_method="vsearch").lookup(TWO, "fish"), "vsearch exited")


def test_empty_input_returns_empty(refroot):
    assert provider(refroot).lookup([], "fish") == []
