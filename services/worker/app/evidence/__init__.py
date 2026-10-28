"""Evidence providers: independent sources of evidence about a sequence that
the Day 9 orchestrator (app/orchestrator/) combines. Each provider takes a
batch of (sequence_id, sequence) pairs plus the route (and optional
per-input context) and returns one EvidenceRecord per input, in input order,
never raising for a missing model, database or tool (the record is marked
"unavailable" with the reason instead). See app/evidence/base.py."""
from app.evidence.base import (
    EVIDENCE_OK,
    EVIDENCE_SKIPPED,
    EVIDENCE_UNAVAILABLE,
    EvidenceProvider,
    EvidenceRecord,
)
from app.evidence.providers import (
    ContaminationProvider,
    NoveltyProvider,
    ReferenceEvidenceProvider,
    RouteHeadProvider,
)
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
    "EVIDENCE_OK",
    "EVIDENCE_SKIPPED",
    "EVIDENCE_UNAVAILABLE",
    "ContaminationProvider",
    "EvidenceProvider",
    "EvidenceRecord",
    "HumanGenomeEvidence",
    "LookupThresholds",
    "NoveltyProvider",
    "ReferenceEvidence",
    "ReferenceEvidenceProvider",
    "ReferenceHit",
    "ReferenceLookupProvider",
    "RouteHeadProvider",
    "TaxonAssignment",
    "assign_taxon",
    "lookup_reference",
]
