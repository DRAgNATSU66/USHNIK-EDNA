"""
Maps a taxonomic lineage onto one of Synth Veda's 6 routes (see
services/worker/app/model_router/reference.py for the route definitions
this must stay consistent with).

Takes a lineage dict with any of: superkingdom, kingdom, phylum, class,
order, family, genus, species (missing keys are fine — real-world records
are often only identified to genus or family).
"""
from __future__ import annotations

FISH_CLASSES = {
    "Actinopterygii", "Actinopteri", "Chondrichthyes", "Hyperoartia",
    "Hyperotreti", "Myxini", "Sarcopterygii", "Cladistia", "Coelacanthimorpha",
}

# Common domestic/lab/human species that show up as contamination in real
# eDNA samples (handlers, lab reagents, livestock near sample sites).
DOMESTIC_SPECIES = {
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
    "Mus musculus", "Rattus norvegicus",  # common lab contaminants too
}

ROUTES = (
    "fish",
    "plant",
    "bacteria_pathogen",
    "animal_general",
    "human_domestic_contamination",
    "misc_unknown",
)


def lineage_to_route(lineage: dict[str, str]) -> str:
    species = lineage.get("species")
    if species in DOMESTIC_SPECIES:
        return "human_domestic_contamination"

    superkingdom = lineage.get("superkingdom")
    if superkingdom in ("Bacteria", "Archaea"):
        return "bacteria_pathogen"

    kingdom = lineage.get("kingdom")
    if kingdom in ("Viridiplantae", "Plantae"):
        return "plant"

    if kingdom == "Metazoa" or lineage.get("phylum") == "Chordata":
        klass = lineage.get("class")
        if klass in FISH_CLASSES:
            return "fish"
        return "animal_general"

    # Fungi, protists, viruses, unclassified/environmental samples, or
    # anything else we don't have a dedicated route for.
    return "misc_unknown"
