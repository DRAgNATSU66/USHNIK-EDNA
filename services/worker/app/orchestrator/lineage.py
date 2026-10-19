"""
Which route a reference lineage belongs to.

lineage_to_route mirrors training.routing.lineage_to_route, the rule that
decided every training and reference sequence's route (the worker image ships
only app/, so it cannot import training/). tests/test_orchestrator_combiner.py
checks the two agree on a fixed table.
"""
from __future__ import annotations

FISH_CLASSES = frozenset({
    "Actinopterygii", "Actinopteri", "Chondrichthyes", "Hyperoartia",
    "Hyperotreti", "Myxini", "Sarcopterygii", "Cladistia", "Coelacanthimorpha",
})

DOMESTIC_SPECIES = frozenset({
    "Homo sapiens",
    "Canis lupus familiaris", "Canis familiaris",
    "Felis catus",
    "Bos taurus",
    "Gallus gallus",
    "Sus scrofa domesticus", "Sus scrofa",
    "Ovis aries",
    "Equus caballus",
    "Oryctolagus cuniculus",
    "Capra hircus",
    "Mus musculus", "Rattus norvegicus",
})


def lineage_to_route(lineage: dict[str, str]) -> str:
    species = lineage.get("species")
    if species in DOMESTIC_SPECIES:
        return "human_domestic_contamination"
    if lineage.get("superkingdom") in ("Bacteria", "Archaea"):
        return "bacteria_pathogen"
    kingdom = lineage.get("kingdom")
    if kingdom in ("Viridiplantae", "Plantae"):
        return "plant"
    if kingdom == "Metazoa" or lineage.get("phylum") == "Chordata":
        if lineage.get("class") in FISH_CLASSES:
            return "fish"
        return "animal_general"
    return "misc_unknown"


def implied_route(lineage: dict[str, str] | None) -> str | None:
    """The route a reference assignment's lineage implies, or None when the
    lineage is too coarse to place (e.g. an LCA that kept only
    "superkingdom: Eukaryota", which lineage_to_route would send to
    misc_unknown by default rather than on evidence)."""
    if not lineage:
        return None
    if lineage.get("superkingdom") in ("Bacteria", "Archaea"):
        return "bacteria_pathogen"
    if not any(lineage.get(r) for r in ("kingdom", "phylum", "class")):
        return None
    return lineage_to_route(lineage)
