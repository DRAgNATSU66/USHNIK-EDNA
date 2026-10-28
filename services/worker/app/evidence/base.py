"""
Evidence-provider interface (Day 9, tracker t-1022-1; decision Q7).

An evidence provider is one independent source of evidence about a sequence
(a route's classifier head, the reference lookup, the novelty scorer, the
contamination detector). The orchestrator (app/orchestrator/) calls every
provider the same way:

    records = provider.collect([(sequence_id, sequence), ...], route, context)
    # -> list[EvidenceRecord], one per input, in input order

`route` is the route the evidence is about, which need not be the router's
top pick: the orchestrator runs the head and the reference lookup of every
candidate route it planned. `context` is optional, one dict per input (the
sequence's pipeline dict plus whatever earlier providers produced), for the
providers that score on top of other evidence (novelty, contamination).

A provider never raises for a missing model, database or tool, and never for
one bad sequence: it returns status "unavailable" with the reason. "skipped"
means the provider ran but had nothing to say by design (e.g. no head runs on
the low_quality route). Only "ok" records carry evidence the combiner uses.

EvidenceRecord.to_dict() is what the decision trace stores: JSON- and
BSON-safe, bounded (providers cap hit lists; embeddings never go in).
Anything large or private a later stage needs (the head's [CLS] embedding for
the novelty scorer) travels in `artifacts`, which to_dict() leaves out.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

EVIDENCE_OK = "ok"
EVIDENCE_UNAVAILABLE = "unavailable"
EVIDENCE_SKIPPED = "skipped"
EVIDENCE_STATUSES = (EVIDENCE_OK, EVIDENCE_UNAVAILABLE, EVIDENCE_SKIPPED)


@dataclass
class EvidenceRecord:
    provider: str
    provider_version: str
    sequence_id: str
    route: str | None
    status: str                       # ok | unavailable | skipped
    payload: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0
    reason: str | None = None
    # Not stored: large or private values a later stage needs (embedding).
    artifacts: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"evidence status must be one of {EVIDENCE_STATUSES}, got {self.status!r}")

    @property
    def ok(self) -> bool:
        return self.status == EVIDENCE_OK

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "sequence_id": self.sequence_id,
            "route": self.route,
            "status": self.status,
            "reason": self.reason,
            "elapsed_ms": round(float(self.elapsed_ms), 2),
            "payload": self.payload,
        }


@runtime_checkable
class EvidenceProvider(Protocol):
    name: str
    version: str

    def collect(
        self,
        items: Sequence[tuple[str, str]],
        route: str,
        context: Sequence[dict] | None = None,
    ) -> list[EvidenceRecord]:
        ...


def unavailable_records(provider: EvidenceProvider, items: Sequence[tuple[str, str]], route: str | None,
                        reason: str, elapsed_ms: float = 0.0) -> list[EvidenceRecord]:
    """One "unavailable" record per input, for a provider that could not run."""
    per = elapsed_ms / len(items) if items else 0.0
    return [EvidenceRecord(provider=provider.name, provider_version=provider.version, sequence_id=str(sid),
                           route=route, status=EVIDENCE_UNAVAILABLE, reason=reason, elapsed_ms=per)
            for sid, _ in items]


def elapsed_ms_since(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def plain(value: Any) -> Any:
    """Coerce numpy scalars and other number-likes to built-ins so a payload
    is BSON-encodable (pymongo cannot encode numpy.float32)."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return plain(item())
        except (TypeError, ValueError):
            pass
    return str(value)
