"""
Hash-chained chain of custody (roadmap M2, t-1027-2).

One append-only chain per sample upload, stored in the `custody_events`
Mongo collection. Each event is a JSON document; its hash is

    hash = sha256( prev_hash || canonical_json(event) )

where `||` is string concatenation of the previous event's hex hash and the
canonical JSON of this event (every stored field except `prev_hash`, `hash`
and Mongo's `_id`), UTF-8 encoded. The first event's prev_hash is
GENESIS_HASH (64 zeros). Changing, adding or removing any field of a stored
event, deleting or reordering an event, or rewriting one event's hash all
break verification at the first affected link (verify_chain).

Why one chain per upload, not per analysis: custody is about the sample. The
upload exists before any analysis, and one upload can be analysed more than
once; every analysis, review and export of that sample lands on the same
linear chain, each event naming its analysis_id.

No forks: a unique index on (chain_id, seq) (db/indexes.py) makes "append at
seq N" a compare-and-set. Two writers that read the same head both try to
insert seq N+1; Mongo accepts exactly one, the other gets DuplicateKeyError,
re-reads the head and retries at N+2. A second unique index on
(chain_id, event_key) makes keyed events (upload_created, analysis_completed)
idempotent under the same race.

What the chain does not prove: deleting the newest event(s) leaves a shorter
chain that still verifies. Every export records the head hash at export time
(the FAIR ZIP's custody.json, the export event's payload), so a truncation
is detectable against any copy that left the system.

Pure helpers (canonical_json, event_hash, verify_chain) do no I/O; append and
load take the Motor database.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
from datetime import date, datetime, timezone
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

CUSTODY_COLLECTION = "custody_events"
CUSTODY_SCHEMA = "synthveda.custody.v1"
GENESIS_HASH = "0" * 64
HASH_ALGORITHM = "sha256(prev_hash || canonical_json(event))"
CANONICALIZATION = (
    "JSON, keys sorted, separators (',', ':'), UTF-8, no ASCII escaping; "
    "datetimes as ISO 8601 strings; every stored field except prev_hash, hash and _id"
)

# Fields that are not part of the hashed body.
_UNHASHED_FIELDS = ("_id", "prev_hash", "hash")

# Contention on one chain is a handful of concurrent requests at most (an
# upload, a review, an export); 25 attempts with jitter is ample.
_MAX_APPEND_ATTEMPTS = 25


class CustodyAppendError(RuntimeError):
    """The event could not be appended (persistent contention or a DB error)."""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    # ObjectId, Decimal128, enums without a JSON form: their string value.
    return str(obj)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON text for hashing (see CANONICALIZATION)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default,
    )


def _jsonable(obj: Any) -> Any:
    """
    The value as it will read back from Mongo: round-trip it through
    canonical JSON so datetimes become the same ISO strings that were hashed.
    Storing a raw datetime would not work: BSON truncates to milliseconds and
    drops the timezone, so the stored value would hash differently.
    """
    return json.loads(canonical_json(obj))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hashed_body(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if k not in _UNHASHED_FIELDS}


def event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    return sha256_hex(prev_hash + canonical_json(hashed_body(event)))


def results_sha256(results: list[dict[str, Any]]) -> str:
    """sha256 of the canonical serialization of an analysis_results `results` list."""
    return sha256_hex(canonical_json(results))


def chain_id_for_upload(upload_id: str) -> str:
    return f"upload:{upload_id}"


def chain_id_for_analysis(analysis_doc: dict[str, Any]) -> str:
    """The chain an analysis belongs to: its upload's, else its own (no upload_id)."""
    upload_id = analysis_doc.get("upload_id")
    if upload_id:
        return chain_id_for_upload(upload_id)
    return f"analysis:{analysis_doc.get('analysis_id', 'unknown')}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def append_event(
    db: Any,
    chain_id: str,
    event_type: str,
    *,
    actor: dict[str, Any],
    subject: dict[str, Any],
    payload: dict[str, Any],
    event_key: Optional[str] = None,
) -> tuple[dict[str, Any], bool]:
    """
    Append one event to `chain_id` and return (event, created).

    With `event_key`, the append is idempotent: if an event with that key is
    already on the chain it is returned unchanged with created=False.
    Raises CustodyAppendError if no slot could be claimed.
    """
    coll = db[CUSTODY_COLLECTION]
    for attempt in range(_MAX_APPEND_ATTEMPTS):
        if event_key is not None:
            existing = await coll.find_one({"chain_id": chain_id, "event_key": event_key})
            if existing:
                existing.pop("_id", None)
                return existing, False

        head = await coll.find_one({"chain_id": chain_id}, sort=[("seq", -1)])
        seq = int(head["seq"]) + 1 if head else 0
        prev_hash = head["hash"] if head else GENESIS_HASH

        event: dict[str, Any] = {
            "schema": CUSTODY_SCHEMA,
            "chain_id": chain_id,
            "seq": seq,
            "event_type": event_type,
            "recorded_at": _utc_now_iso(),
            "actor": _jsonable(actor),
            "subject": _jsonable(subject),
            "payload": _jsonable(payload),
        }
        if event_key is not None:
            event["event_key"] = event_key
        event["prev_hash"] = prev_hash
        event["hash"] = event_hash(prev_hash, event)

        try:
            await coll.insert_one(dict(event))  # copy: insert_one adds _id in place
        except DuplicateKeyError:
            # Lost the race for this seq (or for this event_key): re-read and retry.
            await asyncio.sleep(random.uniform(0, 0.005 * (attempt + 1)))
            continue
        return event, True

    raise CustodyAppendError(
        f"could not append {event_type} to custody chain {chain_id} after {_MAX_APPEND_ATTEMPTS} attempts"
    )


async def load_chain(db: Any, chain_id: str) -> list[dict[str, Any]]:
    """Every event on the chain, in seq order, without Mongo's _id."""
    events: list[dict[str, Any]] = []
    async for ev in db[CUSTODY_COLLECTION].find({"chain_id": chain_id}).sort("seq", 1):
        ev.pop("_id", None)
        events.append(ev)
    return events


def verify_chain(events: list[dict[str, Any]], chain_id: Optional[str] = None) -> dict[str, Any]:
    """
    Recompute every hash and check every link, in seq order.

    Returns {valid, length, head_hash, first_break, algorithm,
    canonicalization}. first_break is None for an intact chain, else the
    first failing event: {seq, index, reason, ...}. Checks per event i:
      1. seq == i (no gap, duplicate or reorder) and chain_id matches;
      2. prev_hash == the stored hash of event i-1 (GENESIS_HASH for i=0);
      3. the stored hash == sha256(prev_hash || canonical_json(event)).
    """
    expected_chain = chain_id if chain_id is not None else (events[0].get("chain_id") if events else None)
    prev_stored = GENESIS_HASH
    first_break: Optional[dict[str, Any]] = None

    for i, ev in enumerate(events):
        seq = ev.get("seq")
        if seq != i:
            first_break = {
                "seq": seq, "index": i,
                "reason": f"sequence gap or reorder: expected seq {i}, found {seq}",
            }
            break
        if ev.get("chain_id") != expected_chain:
            first_break = {
                "seq": seq, "index": i,
                "reason": f"event belongs to chain {ev.get('chain_id')!r}, not {expected_chain!r}",
            }
            break
        if ev.get("prev_hash") != prev_stored:
            first_break = {
                "seq": seq, "index": i,
                "reason": "prev_hash does not match the previous event's hash",
                "expected_prev_hash": prev_stored,
                "stored_prev_hash": ev.get("prev_hash"),
            }
            break
        recomputed = event_hash(prev_stored, ev)
        if recomputed != ev.get("hash"):
            first_break = {
                "seq": seq, "index": i,
                "reason": "stored hash does not match the recomputed hash (event content was altered)",
                "recomputed_hash": recomputed,
                "stored_hash": ev.get("hash"),
            }
            break
        prev_stored = ev["hash"]

    return {
        "valid": first_break is None,
        "length": len(events),
        "head_hash": events[-1].get("hash") if events else None,
        "first_break": first_break,
        "algorithm": HASH_ALGORITHM,
        "canonicalization": CANONICALIZATION,
        "genesis_prev_hash": GENESIS_HASH,
    }
