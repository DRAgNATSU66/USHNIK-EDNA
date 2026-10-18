"""Evidence providers: independent sources of evidence about a sequence that
the Day 9 orchestrator will combine. Each provider takes a batch of
(sequence_id, sequence) pairs plus the route and returns one structured
evidence record per input, in input order, never raising for a missing
database or tool (it returns evidence marked unavailable instead)."""
from app.evidence.reference_lookup import (
    HumanGenomeEvidence,
    LookupThresholds,
    ReferenceEvidence,
    ReferenceHit,
    ReferenceLookupProvider,
    TaxonAssignment,
    assign_taxon,
    lookup_reference,
)

__all__ = [
    "HumanGenomeEvidence",
    "LookupThresholds",
    "ReferenceEvidence",
    "ReferenceHit",
    "ReferenceLookupProvider",
    "TaxonAssignment",
    "assign_taxon",
    "lookup_reference",
]
