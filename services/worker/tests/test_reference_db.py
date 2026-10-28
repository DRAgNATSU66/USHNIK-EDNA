"""Reference DB builder (roadmap B4): header format, taxonomy parsing, the
MIDORI2 multi-gene zip and the held-out exclusion, on tiny fixtures."""
from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile
from pathlib import Path

import pytest

from training import build_reference_db as brd
from training import sources
from training.taxonomy import TaxonomyResolver

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

# taxid, parent, rank, name  (2025+ NCBI rank names: "domain", "acellular root")
_NODES = [
    (1, 1, "no rank", "root"),
    (131567, 1, "cellular root", "cellular organisms"),
    (2, 131567, "domain", "Bacteria"),
    (2759, 131567, "domain", "Eukaryota"),
    (10239, 1, "acellular root", "Viruses"),
    (33208, 2759, "kingdom", "Metazoa"),
    (7711, 33208, "phylum", "Chordata"),
    (186623, 7711, "class", "Actinopteri"),
    (8166, 186623, "order", "Perciformes"),
    (8165, 8166, "family", "Percidae"),
    (8167, 8165, "genus", "Perca"),
    (8168, 8167, "species", "Perca fluviatilis"),
    (8169, 8167, "species", "Perca flavescens"),
    (40674, 7711, "class", "Mammalia"),
    (9606, 40674, "species", "Homo sapiens"),
    (1239, 2, "phylum", "Bacillota"),
    (1386, 1239, "genus", "Bacillus"),          # the bacterium
    (1423, 1386, "species", "Bacillus subtilis"),
    (6656, 33208, "phylum", "Arthropoda"),
    (55644, 6656, "genus", "Bacillus"),         # the stick insect (homonym)
    (12345, 10239, "species", "Some virus"),
]


@pytest.fixture()
def taxdump(tmp_path: Path) -> Path:
    d = tmp_path / "taxdump"
    d.mkdir()
    with open(d / "nodes.dmp", "w") as fh:
        for taxid, parent, rank, _ in _NODES:
            fh.write(f"{taxid}\t|\t{parent}\t|\t{rank}\t|\t\t|\n")
    with open(d / "names.dmp", "w") as fh:
        for taxid, _, _, name in _NODES:
            fh.write(f"{taxid}\t|\t{name}\t|\t\t|\tscientific name\t|\n")
    return d


@pytest.fixture()
def taxonomy(taxdump: Path) -> TaxonomyResolver:
    return TaxonomyResolver(taxdump)


# GB273 layout: tab, rank-labelled tokens, names with spaces, clades/no-rank in between
PERCA_HDR = ("MG559732.1.<1.>690\troot_1;cellularroot_cellular_organisms_131567;domain_Eukaryota_2759;"
             "clade_Opisthokonta_33154;kingdom_Metazoa_33208;phylum_Chordata_7711;class_Actinopteri_186623;"
             "order_Perciformes_8166;family_Percidae_8165;genus_Perca_8167;species_Perca fluviatilis_8168")
HOMO_HDR = ("AB000001.1.12.212\troot_1;cellularroot_cellular_organisms_131567;domain_Eukaryota_2759;"
            "kingdom_Metazoa_33208;phylum_Chordata_7711;class_Mammalia_40674;order_Primates_9443;"
            "family_Hominidae_9604;genus_Homo_9605;species_Homo sapiens_9606")
PERCA_OLD_HDR = "MG559732.1.<1.>690###root_1;Eukaryota_2759;Chordata_7711;Actinopteri_186623;Perciformes_8166;Percidae_8165;Perca_8167;Perca_fluviatilis_8168"
# pre-GB273 positional layout with a taxid the local taxdump does not know
NEW_TAXID_HDR = "ZZ000001.1.<1.>300###root_1;Eukaryota_2759;Chordata_7711;Actinopteri_186623;Gadiformes_8043;Gadidae_8045;Gadus_8048;Gadus_newus_99999999"

SEQ_A = "ACGT" * 30
SEQ_B = "TTGCA" * 30
SEQ_C = "GGATCC" * 25


def _gz(text: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as g:
        g.write(text.encode())
    return buf.getvalue()


@pytest.fixture()
def midori_zip(tmp_path: Path) -> Path:
    """Same layout as MIDORI2_GB273_RAW.zip: RAW/{total,uniq,longest}/ with
    one .fasta.gz per gene, .list.gz side files, and an AA member."""
    z = tmp_path / "MIDORI2_GB273_RAW.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("RAW/", b"")
        zf.writestr("RAW/total/MIDORI2_TOTAL_NUC_GB273_CO1_RAW.fasta.gz",
                    _gz(f">{PERCA_HDR}\n{SEQ_A}\n>{PERCA_HDR}\n{SEQ_A}\n"))
        zf.writestr("RAW/uniq/MIDORI2_UNIQ_NUC_GB273_CO1_RAW.fasta.gz", _gz(f">{PERCA_HDR}\n{SEQ_A}\n"))
        zf.writestr("RAW/uniq/MIDORI2_UNIQ_NUC_GB273_CO1.list.gz", _gz("MG559732.1\n"))
        zf.writestr("RAW/uniq/MIDORI2_UNIQ_NUC_GB273_srRNA_RAW.fasta.gz",
                    _gz(f">{HOMO_HDR}\n{SEQ_B}\n>{NEW_TAXID_HDR}\n{SEQ_C}\n"))
        zf.writestr("RAW/longest/MIDORI2_LONGEST_NUC_GB273_Cytb_RAW.fasta.gz", _gz(f">{PERCA_HDR}\n{SEQ_B}\n"))
        zf.writestr("RAW_AA/uniq/MIDORI2_UNIQ_AA_GB273_CO1_RAW.fasta.gz", _gz(f">{PERCA_HDR}\nMKVLAAGIRS\n"))
    return z


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------

def test_domain_rank_is_read_as_superkingdom(taxonomy):
    # The 2026 taxdump has no "superkingdom" rank; routing needs one.
    assert taxonomy.lineage(1423)["superkingdom"] == "Bacteria"
    assert taxonomy.lineage(8168)["superkingdom"] == "Eukaryota"
    assert taxonomy.lineage(12345)["superkingdom"] == "Viruses"


def test_bacteria_route_reachable_from_taxid(taxonomy):
    from training.routing import lineage_to_route
    assert lineage_to_route(taxonomy.lineage(1423)) == "bacteria_pathogen"
    assert lineage_to_route(taxonomy.lineage(8168)) == "fish"


def test_lca_and_homonyms(taxonomy):
    assert taxonomy.lowest_common_ancestor(8168, 8169) == 8167
    assert taxonomy.lowest_common_ancestor(8168, 9606) == 7711
    assert sorted(taxonomy.taxids_for_name("Bacillus")) == [1386, 55644]
    names = brd.NameResolver(taxonomy)
    assert names.resolve("Bacillus sp. XYZ-1", "Bacteria") == 1386
    assert names.resolve("Bacillus sp. XYZ-1", None) is None  # ambiguous without a domain
    assert names.resolve("Perca fluviatilis strain 7", "Eukaryota") == 8168


# ---------------------------------------------------------------------------
# MIDORI2 multi-gene zip
# ---------------------------------------------------------------------------

def test_midori2_members_selection_and_gene(midori_zip):
    with zipfile.ZipFile(midori_zip) as zf:
        members = {(m.selection, m.gene) for m in sources.midori2_members(zf)}
    assert members == {("TOTAL", "CO1"), ("UNIQ", "CO1"), ("UNIQ", "srRNA"), ("LONGEST", "Cytb")}


def test_iter_midori2_reads_every_uniq_gene(midori_zip, taxonomy):
    recs = list(sources.iter_midori2(midori_zip, taxonomy))
    # UNIQ CO1 (1) + UNIQ srRNA (2); TOTAL/LONGEST/AA/.list not read
    assert [r.sequence for r in recs] == [SEQ_A, SEQ_B, SEQ_C]
    assert recs[0].lineage["class"] == "Actinopteri"
    assert recs[1].organism_name == "Homo sapiens"


def test_iter_midori2_gene_and_selection_filters(midori_zip, taxonomy):
    assert len(list(sources.iter_midori2(midori_zip, taxonomy, genes=("srRNA",)))) == 2
    assert len(list(sources.iter_midori2(midori_zip, taxonomy, selection="TOTAL"))) == 2
    assert len(list(sources.iter_midori2(midori_zip, taxonomy, selection=None))) == 6


def test_iter_midori2_old_single_fasta_zip(tmp_path, taxonomy):
    z = tmp_path / "MIDORI2_UNIQ_NUC_GB250_CO1_RAW.fasta.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("MIDORI2_UNIQ_NUC_GB250_CO1_RAW.fasta", f">{PERCA_OLD_HDR}\n{SEQ_A}\n")
    assert [r.sequence for r in sources.iter_midori2(z, taxonomy)] == [SEQ_A]


def test_midori2_header_falls_back_to_positional_lineage(taxonomy):
    acc, organism, lineage, taxid = sources.parse_midori2_header(NEW_TAXID_HDR, taxonomy)
    assert acc == "ZZ000001.1"
    assert taxid == 99999999
    assert organism == "Gadus newus"
    # taxid unknown to the local taxdump -> the header's own ranks are used
    assert lineage == {"superkingdom": "Eukaryota", "phylum": "Chordata", "class": "Actinopteri",
                       "order": "Gadiformes", "family": "Gadidae", "genus": "Gadus", "species": "Gadus newus"}
    # positional header with a known taxid -> taxdump lineage (adds kingdom)
    acc, organism, lineage, taxid = sources.parse_midori2_header(PERCA_OLD_HDR, taxonomy)
    assert (acc, organism, taxid, lineage["kingdom"]) == ("MG559732.1", "Perca fluviatilis", 8168, "Metazoa")


def test_midori2_gb273_labelled_header():
    # no taxdump needed: GB273 carries MIDORI2's own rank-labelled lineage
    acc, organism, lineage, taxid = sources.parse_midori2_header(PERCA_HDR, None)
    assert (acc, organism, taxid) == ("MG559732.1", "Perca fluviatilis", 8168)
    assert lineage == {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata",
                       "class": "Actinopteri", "order": "Perciformes", "family": "Percidae",
                       "genus": "Perca", "species": "Perca fluviatilis"}
    assert sources.parse_midori2_header("NOTAX.1", None) is None


# ---------------------------------------------------------------------------
# header format
# ---------------------------------------------------------------------------

def test_header_round_trip():
    lineage = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata",
               "class": "Actinopteri", "genus": "Perca", "species": "Perca fluviatilis"}
    h = brd.format_header("FSH0000001", lineage, "midori2", "CO1", "MG559732.1", 8168, 3)
    assert h == ("FSH0000001;tax=d:Eukaryota,k:Metazoa,p:Chordata,c:Actinopteri,g:Perca,"
                 "s:Perca_fluviatilis;src=midori2;marker=CO1;acc=MG559732.1;taxid=8168;n=3;")
    assert " " not in h  # vsearch truncates labels at whitespace
    parsed = brd.parse_header(">" + h)
    assert parsed["id"] == "FSH0000001"
    assert parsed["lineage"] == lineage
    assert (parsed["src"], parsed["marker"], parsed["acc"], parsed["taxid"], parsed["n"]) == \
        ("midori2", "CO1", "MG559732.1", 8168, 3)


def test_header_separators_in_names_are_sanitized():
    h = brd.format_header("MSC0000001", {"species": "Virus A, strain: 1; x=2"}, "ref", "viral genome", "X 1", None, 1)
    parsed = brd.parse_header(h)
    assert parsed["lineage"] == {"species": "Virus A strain 1 x 2"}
    assert parsed["marker"] == "viral_genome"
    assert parsed["taxid"] is None


def test_wrapping_quotes_are_dropped_from_rank_names():
    # plant v2 stored g:'Halosarcinochlamys and s:'Halosarcinochlamys_cherokeensis'
    # from SILVA's quoted organism name; the genus sorted first in top-taxa.
    h = brd.format_header("PLT0038408", {"superkingdom": "Eukaryota", "kingdom": "Viridiplantae",
                                         "genus": "'Halosarcinochlamys",
                                         "species": "'Halosarcinochlamys cherokeensis'"},
                          "silva", "LSU", "DQ015760.1.2634", None, 1)
    assert "tax=d:Eukaryota,k:Viridiplantae,g:Halosarcinochlamys,s:Halosarcinochlamys_cherokeensis;" in h
    assert brd.parse_header(h)["lineage"]["genus"] == "Halosarcinochlamys"
    # Quotes that delimit part of a name are nomenclature, not noise: kept.
    for name in ("'Catharanthus roseus' malformation phytoplasma", "Tomato witches'-broom phytoplasma",
                 "'Brenneria populi' Hauben et al. 1998"):
        assert brd.unquote_name(name) == name
        assert brd.clean_rank_name("species", name) == name
    assert brd.clean_rank_name("genus", "'Brenneria") == "Brenneria"
    assert brd.unquote_name('"Quoted name"') == "Quoted name"
    assert brd.unquote_name("'") == "'"


def test_silva_quoted_organism_resolves_without_quotes(tmp_path, taxonomy):
    # A quoted name NCBI knows unquoted gets the NCBI lineage; one it does not
    # know falls back to SILVA's path, without the quotes.
    gz = tmp_path / "silva.fasta.gz"
    seq = "ACGT" * 60
    gz.write_bytes(_gz(
        f">AB1.1.240 Eukaryota;Opisthokonta;'Perca fluviatilis'\n{seq}\n"
        f">AB2.1.240 Eukaryota;Archaeplastida;Chloroplastida;'Halosarcinochlamys cherokeensis'\n{seq}\n"))
    recs = list(brd.iter_silva_ref(gz, brd.NameResolver(taxonomy), "SSU"))
    assert [r.taxid for r in recs] == [8168, None]
    assert recs[0].lineage["species"] == "Perca fluviatilis"
    assert recs[1].organism == "Halosarcinochlamys cherokeensis"
    assert recs[1].lineage["genus"] == "Halosarcinochlamys"
    assert recs[1].lineage["species"] == "Halosarcinochlamys cherokeensis"


def test_parse_header_accepts_blast_defline():
    rest = "tax=d:Bacteria,g:Bacillus;src=silva;marker=SSU;acc=AB1.1.1500;n=1;"
    parsed = brd.parse_header(f"lcl|BAC0000007 {rest}")
    assert parsed["id"] == "BAC0000007"
    assert parsed["lineage"] == {"superkingdom": "Bacteria", "genus": "Bacillus"}


def test_lca_lineage():
    a = brd.lineage_tuple({"superkingdom": "Eukaryota", "genus": "Perca", "species": "Perca fluviatilis"})
    b = brd.lineage_tuple({"superkingdom": "Eukaryota", "family": "Percidae", "genus": "Perca", "species": "Perca flavescens"})
    assert dict(brd.lca_lineage(a, b)) == {"superkingdom": "Eukaryota", "family": "Percidae", "genus": "Perca"}
    assert brd.lca_lineage(a, a) == a


# ---------------------------------------------------------------------------
# accumulation, cap, held-out exclusion
# ---------------------------------------------------------------------------

def _rec(seq, species, genus="Perca", marker="CO1", taxid=None):
    return brd.RefRecord(seq, {"superkingdom": "Eukaryota", "genus": genus, "species": species},
                         taxid, "ACC", "midori2", marker, species)


def test_duplicates_merge_to_lca(tmp_path, taxonomy):
    acc = brd.RouteAccumulator("fish", tmp_path, taxonomy)
    acc.add(_rec(SEQ_A, "Perca fluviatilis", taxid=8168))
    acc.add(_rec(SEQ_A, "Perca flavescens", taxid=8169))
    acc.add(_rec(SEQ_B, "Perca fluviatilis", taxid=8168))
    acc.close()
    keep, k, info = acc.select(10, 10**9)
    out = tmp_path / "ref.fasta"
    written = acc.write(out, keep)
    headers = [line[1:].strip() for line in out.read_text().splitlines() if line.startswith(">")]
    first = brd.parse_header(headers[0])
    assert first["lineage"] == {"superkingdom": "Eukaryota", "genus": "Perca"}
    assert first["taxid"] == 8167 and first["n"] == 2
    assert written["sequences"] == 2
    assert acc.stats.duplicates_merged == 1 and acc.stats.lca_coarsened == 1


def test_cap_keeps_longest_per_taxon_and_marker(tmp_path):
    acc = brd.RouteAccumulator("fish", tmp_path, None)
    for i in range(5):
        acc.add(_rec("A" * (100 + i) + "C", "Perca fluviatilis"))
    acc.add(_rec("G" * 60, "Perca fluviatilis", marker="srRNA"))
    acc.close()
    keep, k, info = acc.select(2, 10**9)
    assert k == 2 and info["kept"] == 3
    lengths = sorted(acc.entries[d].length for d in keep)
    assert lengths == [60, 104, 105]
    # a base budget forces the cap down the ladder
    keep, k, info = acc.select(10, 200)
    assert k == 1 and len(keep) == 2 and not info["over_budget"]
    # no ceiling and room to spare: nothing is removed
    keep, k, info = acc.select(0, 10**9)
    assert k is None and info["removed_by_cap"] == 0 and len(keep) == 6
    # cannot fit even at k=1: kept at k=1 and flagged
    keep, k, info = acc.select(0, 50)
    assert k == 1 and info["over_budget"]


def test_ingest_cap_selects_exactly_what_unbounded_does(tmp_path):
    import random
    rng = random.Random(7)
    recs = []
    for _ in range(600):
        sp = rng.choice(["Perca fluviatilis", "Perca flavescens", "Sander lucioperca"])
        length = rng.choice([80, 90, 90, 100, 120])  # ties on length break by digest
        seq = "".join(rng.choice("ACGT") for _ in range(length))
        recs.append(_rec(seq, sp, marker=rng.choice(["CO1", "srRNA"])))
    recs += recs[::5]  # exact duplicates, including of entries the cap evicts
    rng.shuffle(recs)
    (tmp_path / "full").mkdir()
    (tmp_path / "cut").mkdir()
    full = brd.RouteAccumulator("fish", tmp_path / "full", None)
    cut = brd.RouteAccumulator("fish", tmp_path / "cut", None, ingest_cap=20)
    for r in recs:
        full.add(r)
        cut.add(r)
    full.close()
    cut.close()
    assert len(cut.entries) <= 6 * 20 < len(full.entries)
    for k in (20, 10, 5, 3, 2, 1):
        kf, _, _ = full.select(k, 10**9)
        kc, _, info = cut.select(k, 10**9)
        assert kc == kf and info["ingest_cap"]["exact"]
        assert all(cut.entries[d].n == full.entries[d].n for d in kc)
    _, k, info = cut.select(0, 10**9)
    assert k is None and not info["ingest_cap"]["exact"] and info["ingest_cap"]["groups_cut"] == 6
    out = tmp_path / "cut.fasta"
    assert cut.write(out, set(cut.entries))["sequences"] == len(cut.entries)


def test_heldout_exclusion_exact_and_chunked(tmp_path):
    proc = tmp_path / "processed" / "fish"
    proc.mkdir(parents=True)
    long_seq = ("ACGTTGCA" * 400)  # 3,200 bp: build_dataset chunks it
    from training.build_dataset import chunk_long_sequence
    with open(proc / "test.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sequence", "label"])
        w.writerow([SEQ_A, "known_species"])
        w.writerow([chunk_long_sequence(long_seq)[1], "known_species"])
    with open(proc / "train.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([["sequence", "label"], [SEQ_B, "known_species"]])
    held, info = brd.load_heldout(tmp_path / "processed")
    assert set(info) == {"fish/test.csv"}
    assert brd.is_heldout(SEQ_A, held)
    assert brd.is_heldout(long_seq, held)       # a test chunk came from it
    assert not brd.is_heldout(SEQ_B, held)      # train stays in the reference


def test_bold_rows_hook():
    rows = [{"kingdom": "Animalia", "phylum": "Chordata", "class": "Actinopteri", "genus": "Perca",
             "species": "Perca fluviatilis", "nuc": SEQ_A, "processid": "ABC123-19", "marker_code": "COI-5P"},
            {"kingdom": "Plantae", "genus": "Quercus", "species": None, "nuc": SEQ_B, "processid": "P1", "marker_code": "rbcL"},
            {"kingdom": "Animalia", "species": "Nothing", "nuc": None}]
    recs = list(brd.bold_rows_to_records(rows))
    assert len(recs) == 2
    assert recs[0].lineage["kingdom"] == "Metazoa" and recs[0].acc == "ABC123-19" and recs[0].marker == "COI-5P"
    assert recs[1].lineage["kingdom"] == "Viridiplantae" and recs[1].organism == "Quercus"


# ---------------------------------------------------------------------------
# end to end on a fake data root
# ---------------------------------------------------------------------------

def _fake_root(tmp_path: Path, taxdump: Path, midori_zip: Path) -> Path:
    root = tmp_path / "data"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "taxdump").symlink_to(taxdump)
    (root / "raw" / "midori2").mkdir(parents=True)
    (root / "raw" / "midori2" / midori_zip.name).symlink_to(midori_zip)
    silva = root / "raw" / "silva"
    silva.mkdir()
    with gzip.open(silva / "SILVA_138.2_SSURef_NR99_tax_silva.fasta.gz", "wt") as fh:
        fh.write(">AB1.1.1500 Bacteria;Bacillota;Bacilli;Bacillales;Bacillaceae;Bacillus;Bacillus subtilis\n")
        fh.write("ACGGT" * 40 + "\n")
        fh.write(">AB2.1.1500 Bacteria;Bacillota;Bacilli;Bacillales;Bacillaceae;Bacillus;uncultured bacterium\n")
        fh.write("TTTGG" * 40 + "\n")
    (root / "raw" / "univec").mkdir()
    (root / "raw" / "univec" / "UniVec").write_text(">gnl|uv|NGB00001.1:1-30 Illumina adapter\nAATGATACGGCGACCACCGAGATCTACACT\n")
    proc = root / "processed" / "human_domestic_contamination"
    proc.mkdir(parents=True)
    (proc / "test.csv").write_text(f"sequence,label\n{SEQ_B}\n")
    return root


def test_build_end_to_end_without_indexes(tmp_path, taxdump, midori_zip):
    root = _fake_root(tmp_path, taxdump, midori_zip)
    assert brd.main(["--data-dir", str(root), "--version", "vtest", "--skip-indexes"]) == 0
    out = root / "reference" / "vtest"
    manifest = json.loads((out / "manifest.json").read_text())
    routes = manifest["routes"]
    assert set(routes) == set(brd.ROUTE_PREFIX)
    assert routes["fish"]["sequences"] == 2          # Perca CO1 + Gadus srRNA
    assert routes["bacteria_pathogen"]["sequences"] == 1   # uncultured dropped
    # Homo sapiens srRNA is a held-out test sequence -> excluded, only UniVec remains
    assert routes["human_domestic_contamination"]["heldout_excluded"] == 1
    assert routes["human_domestic_contamination"]["by_source"] == {"univec": 1}
    fasta = (out / "fish" / "ref.fasta").read_text().splitlines()
    assert fasta[0].startswith(">FSH0000001;tax=d:Eukaryota,k:Metazoa,p:Chordata,c:Actinopteri,")
    assert manifest["heldout_exclusion"]["unique_sequences"] == 1
    assert not (root / "reference" / "CURRENT").exists()  # unindexed versions never go live
    with pytest.raises(SystemExit):  # versions are immutable
        brd.main(["--data-dir", str(root), "--version", "vtest", "--skip-indexes"])


def test_index_only_skips_udb_over_budget_and_gates_current(tmp_path, taxdump, midori_zip, monkeypatch):
    root = _fake_root(tmp_path, taxdump, midori_zip)
    assert brd.main(["--data-dir", str(root), "--version", "vtest", "--skip-indexes",
                     "--max-route-bases", "250"]) == 0
    monkeypatch.setattr(brd, "find_tool", lambda name, data_root: None)
    assert brd.main(["--data-dir", str(root), "--version", "vtest", "--index-only", "--skip-grch38"]) == 0
    routes = json.loads((root / "reference" / "vtest" / "manifest.json").read_text())["routes"]
    assert routes["fish"]["bases"] > 250
    assert routes["fish"]["vsearch_udb"]["reason"].startswith("over_budget")
    assert routes["bacteria_pathogen"]["vsearch_udb"]["reason"] == "vsearch not found"
    assert not routes["fish"]["blastdb"]["ok"]
    assert not (root / "reference" / "CURRENT").exists()  # a failed BLAST DB keeps the old version live


def _tool(name):
    return brd.find_tool(name, brd.default_data_root())


@pytest.mark.skipif(_tool("makeblastdb") is None or _tool("blastn") is None, reason="BLAST+ not installed")
def test_blastdb_carries_ids_and_taxids(tmp_path):
    import subprocess
    fasta = tmp_path / "ref.fasta"
    h = brd.format_header("FSH0000001", {"genus": "Perca", "species": "Perca fluviatilis"}, "midori2", "CO1", "MG1.1", 8168, 1)
    seq = "ATGGCACACCCTACAAGACTAGGACTACTAGCCGCCCTTGCCCTGGTCCTAATAGGCGCCGCGCTTATAGCCGGCCTTGCCGTCGGGCTAGCC"
    fasta.write_text(f">{h}\n{seq}\n")
    tmap = tmp_path / "taxid_map.txt"
    tmap.write_text("FSH0000001\t8168\n")
    res = brd.build_blastdb(_tool("makeblastdb"), fasta, tmp_path / "blast" / "ref", "t", tmap)
    assert res["ok"], res
    q = tmp_path / "q.fa"
    q.write_text(f">q\n{seq}\n")
    out = subprocess.run([str(_tool("blastn")), "-query", str(q), "-db", str(tmp_path / "blast" / "ref"),
                          "-outfmt", "6 sseqid pident staxid stitle", "-max_target_seqs", "1"],
                         capture_output=True, text=True, check=True).stdout.strip().split("\t")
    assert out[0] == "FSH0000001" and float(out[1]) == 100.0 and out[2] == "8168"
    assert brd.parse_header(f"{out[0]} {out[3]}")["lineage"]["species"] == "Perca fluviatilis"


@pytest.mark.skipif(_tool("vsearch") is None, reason="vsearch not installed")
def test_udb_sintax_reads_tax_field(tmp_path):
    import subprocess
    fasta = tmp_path / "ref.fasta"
    seqs = {"Perca fluviatilis": "ATGGCACACCCTACAAGACTAGGACTACTAGCCGCCCTTGCCCTGGTCCTAATAGGCGCCGCGCTTATAGCCGGCCTTGCCGTCGGGCTAGCC",
            "Homo sapiens": "GTTTATGTAGCTTACCTCCTCAAAGCAATACACTGAAAATGTTTAGACGGGCTCACATCACCCCATAAACAAATAGGTTTGGTCCTAGCC"}
    with open(fasta, "w") as fh:
        for i, (sp, s) in enumerate(seqs.items(), 1):
            fh.write(f">{brd.format_header(f'X{i:07d}', {'species': sp}, 'midori2', 'CO1', 'A', None, 1)}\n{s}\n")
    res = brd.build_udb(_tool("vsearch"), fasta, tmp_path / "ref.udb", 1)
    assert res["ok"], res
    q = tmp_path / "q.fa"
    q.write_text(f">q\n{seqs['Homo sapiens']}\n")
    out = tmp_path / "hits.tsv"
    subprocess.run([str(_tool("vsearch")), "--usearch_global", str(q), "--db", str(tmp_path / "ref.udb"),
                    "--id", "0.9", "--userout", str(out), "--userfields", "target+id", "--quiet"], check=True)
    target, ident = out.read_text().strip().split("\t")
    assert brd.parse_header(target)["lineage"]["species"] == "Homo sapiens" and float(ident) == 100.0


def test_supplementary_only_finished_queries(tmp_path, taxonomy):
    supp = tmp_path / "supplementary"
    (supp / "ncbi").mkdir(parents=True)
    hdr = "accession,taxid,organism_name,route,marker,lineage\n"
    for q in ("done_q", "running_q"):
        (supp / "ncbi" / f"{q}.manifest.csv").write_text(hdr + f"X1.1,8168,Perca fluviatilis,,COI,\n")
    (supp / "ncbi" / "done_q.fasta").write_text(f">X1.1 done_q\n{SEQ_A}\n")
    (supp / "ncbi" / "done_q.run.json").write_text("{}")
    (supp / "index.json").write_text(json.dumps({"done_q": {}}))
    queries = brd.supplementary_queries(supp)
    assert [m.name for m, _ in queries] == ["done_q.manifest.csv"]
    recs = list(brd.iter_supplementary_ref(supp, taxonomy, queries))
    assert len(recs) == 1 and recs[0].src == "supplementary:done_q" and recs[0].lineage["genus"] == "Perca"
