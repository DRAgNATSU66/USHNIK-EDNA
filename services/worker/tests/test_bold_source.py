"""BOLD row normalisation shared by the dataset and reference-DB loaders."""
from __future__ import annotations

from pathlib import Path

import pytest

from training import build_reference_db as brd
from training import sources
from training.labeling import assign_label
from training.routing import lineage_to_route

SEQ = "ACGT" * 60


def _row(**kw):
    base = {"kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta", "order": "Lepidoptera",
            "family": "Geometridae", "genus": "Arhodia", "species": "Arhodia lasiocamparia",
            "identification_rank": "species", "nuc": SEQ, "processid": "AANIC003-10", "marker_code": "COI-5P"}
    base.update(kw)
    return base


def test_animal_maps_to_metazoa_and_routes_animal_general():
    lineage, name = sources.bold_lineage(_row())
    assert lineage["superkingdom"] == "Eukaryota" and lineage["kingdom"] == "Metazoa"
    assert name == "Arhodia lasiocamparia"
    # Before the fix, raw "Animalia" sent every non-chordate to misc_unknown.
    assert lineage_to_route(lineage) == "animal_general"


def test_plant_and_fungi_kingdoms():
    plant, _ = sources.bold_lineage(_row(kingdom="Plantae", phylum="Tracheophyta", genus="Quercus",
                                         species="Quercus robur"))
    assert plant["kingdom"] == "Viridiplantae" and lineage_to_route(plant) == "plant"
    fungus, _ = sources.bold_lineage(_row(kingdom="Fungi", phylum="Ascomycota", genus="Penicillium",
                                          species="Penicillium chrysogenum"))
    assert fungus["kingdom"] == "Fungi" and fungus["superkingdom"] == "Eukaryota"


def test_bacteria_and_viruses_are_superkingdoms_not_eukaryota():
    bac, _ = sources.bold_lineage(_row(kingdom="Bacteria", phylum="Pseudomonadota", genus="Wolbachia",
                                       species="Wolbachia pipientis"))
    assert bac["superkingdom"] == "Bacteria" and "kingdom" not in bac
    assert lineage_to_route(bac) == "bacteria_pathogen"
    vir, _ = sources.bold_lineage(_row(kingdom="Viruses", genus="Betacoronavirus", species="Betacoronavirus x"))
    assert vir["superkingdom"] == "Viruses" and "kingdom" not in vir


@pytest.mark.parametrize("bold_class,ncbi_class", [
    ("Teleostei", "Actinopteri"), ("Chondrostei", "Actinopteri"), ("Holostei", "Actinopteri"),
    ("Cladistii", "Actinopteri"), ("Elasmobranchii", "Chondrichthyes"), ("Holocephali", "Chondrichthyes"),
    ("Petromyzonti", "Hyperoartia"), ("Coelacanthi", "Coelacanthimorpha"), ("Dipneusti", "Sarcopterygii"),
    ("Myxini", "Myxini"),
])
def test_bold_fish_classes_route_to_fish(bold_class, ncbi_class):
    # BOLD's fish classes are not NCBI's; 446,683 Teleostei rows went to
    # animal_general before this mapping.
    lineage, _ = sources.bold_lineage(_row(phylum="Chordata", **{"class": bold_class}, order="Perciformes",
                                           family="Percidae", genus="Perca", species="Perca fluviatilis"))
    assert lineage["class"] == ncbi_class and lineage_to_route(lineage) == "fish"


def test_non_fish_chordates_stay_animal_general():
    lineage, _ = sources.bold_lineage(_row(phylum="Chordata", **{"class": "Aves"}, genus="Parus",
                                           species="Parus major"))
    assert lineage["class"] == "Aves" and lineage_to_route(lineage) == "animal_general"


@pytest.mark.parametrize("nuc,expected", [
    ("---ACGT-ACGT---", "ACGTACGT"),
    ("acgt-n", "ACGTN"),
    ("-----", None),
    ("", None),
    (None, None),
    ("ACGIT", None),
])
def test_bold_sequence_strips_alignment_gaps(nuc, expected):
    # 3,836,703 BOLD sequences carry "-" alignment padding/gaps and were
    # rejected whole by _clean_sequence.
    assert sources.bold_sequence(nuc) == expected


def test_protista_keeps_eukaryota_without_a_kingdom():
    pro, _ = sources.bold_lineage(_row(kingdom="Protista", phylum="Ciliophora", genus="Paramecium",
                                       species="Paramecium caudatum"))
    assert pro["superkingdom"] == "Eukaryota" and "kingdom" not in pro


@pytest.mark.parametrize("kingdom", ["Mixture", None, "", "Something new"])
def test_mixture_and_unknown_kingdoms_are_dropped(kingdom):
    assert sources.bold_lineage(_row(kingdom=kingdom)) is None


def test_no_genus_is_dropped():
    # Family-only rows used to reach assign_label with organism_name "" and
    # come out as known_species.
    assert sources.bold_lineage(_row(genus=None, species=None, identification_rank="family")) is None


@pytest.mark.parametrize("species", [
    "Eupselia sp. ANICMK59", "Ichneutes sp. BOLD:ADI5313", "Philine sp.", "Rhinolophus cf. chaseni",
    "Microplitis jft25",
    # review findings: aggregates, undotted qualifiers, lab codes, hybrids
    "Megaselia pulicaria complex", "Coleophora duplicis group", "Simulium exiguum s.l.",
    "Eudasyphora cf cyanicolor", "Branchiostegus sp", "Brevicornu JKJ-spB", "Catocala crataegi RJB",
    "Gnorimoschema pr. streliciella", "Morone saxatilis x Morone chrysops", "Odontocheilopteryx sp_phoneus",
])
def test_interim_names_become_genus_level(species):
    lineage, name = sources.bold_lineage(_row(genus=species.split()[0], species=species))
    assert name == f"{species.split()[0]} sp."
    assert "species" not in lineage
    assert assign_label("animal_general", SEQ, name, lineage) == "likely_taxonomic_group"


@pytest.mark.parametrize("species", ["Rindgea s-signata", "Arhodia lasiocamparia",
                                     "Parnassius apollo bartholomaeus"])
def test_valid_binomials_and_trinomials_stay_species(species):
    genus = species.split()[0]
    lineage, name = sources.bold_lineage(_row(genus=genus, species=species, identification_rank="species"))
    assert name == species and lineage["species"] == species


@pytest.mark.parametrize("genus", ["EntomobryidaeGEN", "Galumnidae_incertae_sedis", "spiloMalaise2296",
                                   "Hapalidiales_unk1", "LNP-gen1", "Metopina_group"])
def test_placeholder_genera_are_dropped(genus):
    # These are family/order-level identifications dressed as genera.
    assert sources.bold_lineage(_row(genus=genus, species=None, identification_rank="genus")) is None


def test_species_from_another_genus_is_genus_level():
    lineage, name = sources.bold_lineage(_row(genus="Panaeolus", species="Galeropsis polytrichoides",
                                              kingdom="Fungi"))
    assert name == "Panaeolus sp." and "species" not in lineage


def test_genus_rank_identification_is_genus_level():
    lineage, name = sources.bold_lineage(_row(species=None, identification_rank="genus"))
    assert name == "Arhodia sp." and "species" not in lineage and lineage["genus"] == "Arhodia"


def test_species_rank_mismatch_trusts_identification_rank():
    # A species string on a row BOLD itself ranks at genus is not a species ID.
    lineage, name = sources.bold_lineage(_row(identification_rank="genus"))
    assert name == "Arhodia sp." and "species" not in lineage


def test_subspecies_rank_keeps_the_species():
    lineage, name = sources.bold_lineage(_row(identification_rank="subspecies"))
    assert name == "Arhodia lasiocamparia" and lineage["species"] == name


def test_missing_identification_rank_falls_back_to_the_name():
    lineage, name = sources.bold_lineage(_row(identification_rank=None))
    assert name == "Arhodia lasiocamparia"


def test_reference_rows_use_the_same_normalisation():
    rows = [_row(), _row(kingdom="Bacteria", genus="Wolbachia", species="Wolbachia pipientis", processid="B1"),
            _row(kingdom="Mixture", processid="M1"),
            _row(species="Eupselia sp. ANICMK59", genus="Eupselia", processid="I1"),
            _row(genus=None, species=None, processid="F1")]
    recs = list(brd.bold_rows_to_records(rows))
    assert [r.acc for r in recs] == ["AANIC003-10", "B1", "I1"]
    assert recs[1].lineage["superkingdom"] == "Bacteria"
    assert recs[2].organism == "Eupselia" and "species" not in recs[2].lineage


class _FakeNames:
    """NameResolver stand-in: Perca fluviatilis resolves, nothing else does."""

    class tax:
        @staticmethod
        def lineage(taxid):
            return {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata",
                    "class": "Actinopteri", "order": "Perciformes", "family": "Percidae", "genus": "Perca",
                    "species": "Perca fluviatilis"} if taxid == 8168 else {}

    def resolve(self, name, domain):
        return 8168 if name == "Perca fluviatilis" and domain == "Eukaryota" else None


def test_reference_rows_take_ncbi_ranks_when_the_name_resolves():
    # BOLD order "Eupercaria_incertae_sedis" vs NCBI "Perciformes" used to
    # cut the merged reference lineage at order (review finding, 4,575
    # same-species duplicates in a 3-row-group sample).
    row = _row(phylum="Chordata", **{"class": "Teleostei"}, order="Eupercaria_incertae_sedis",
               family="Percidae", genus="Perca", species="Perca fluviatilis")
    rec, = brd.bold_rows_to_records([row], names=_FakeNames())
    assert rec.taxid == 8168 and rec.lineage["order"] == "Perciformes"
    assert rec.lineage["species"] == "Perca fluviatilis"


def test_reference_rows_keep_bold_ranks_when_ncbi_does_not_know_the_name():
    rec, = brd.bold_rows_to_records([_row()], names=_FakeNames())
    assert rec.taxid is None and rec.lineage["family"] == "Geometridae" and rec.lineage["kingdom"] == "Metazoa"


def test_iter_bold_reads_parquet(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    rows = [_row(nuc="--" + SEQ + "--"), _row(kingdom="Mixture"),
            _row(species="Eupselia sp. ANICMK59", genus="Eupselia"),
            _row(nuc=None), _row(genus=None, species=None, identification_rank="family")]
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    p = tmp_path / "BOLD_Public.01-Jan-2026.parquet"
    pq.write_table(pa.table(cols), p)
    recs = list(sources.iter_bold(p))
    assert [r.organism_name for r in recs] == ["Arhodia lasiocamparia", "Eupselia sp."]
    assert recs[0].lineage["kingdom"] == "Metazoa" and recs[0].sequence == SEQ
    refs = list(brd.iter_bold_ref(p))
    assert refs[0].sequence == SEQ
    assert [r.organism for r in refs] == ["Arhodia lasiocamparia", "Eupselia"]
