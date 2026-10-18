"""
Sample-metadata context for results (ROADMAP_REAL_DATA.md F5-F7, decisions.md
2026-10-14 Q2 and Q4).

Every result must state which optional upload fields were provided and which
were missing, with a short accuracy note. A partner report needs collection
date + coordinates. A missing negative control is flagged, never blocked.

Built at read time from the upload document, not snapshotted by the worker:
the field list lives only in the API (`OPTIONAL_METADATA_FIELDS`), and a later
metadata correction (FieldLog edits, Day 11) is reflected without re-running
the analysis. Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from ..models.upload import OPTIONAL_METADATA_FIELDS, PARTNER_REPORT_REQUIRED_FIELDS

NO_NEGATIVE_CONTROL_MESSAGE = "No negative control, contamination not ruled out."
NEGATIVE_CONTROL_NOT_RECORDED_MESSAGE = (
    "Negative control not recorded, contamination not ruled out."
)


class ContextFlag(BaseModel):
    # "partner_report_unavailable" | "no_negative_control" | "upload_not_found"
    code: str
    message: str


class PartnerReportReadiness(BaseModel):
    available: bool
    # Subset of PARTNER_REPORT_REQUIRED_FIELDS, in that order.
    missing_required: list[str]
    reason: Optional[str] = None


class MetadataContext(BaseModel):
    upload_found: bool
    provided: list[str]  # field names, in OPTIONAL_METADATA_FIELDS order
    missing: list[str]
    labels: dict[str, str]  # field name -> human label, for every optional field
    negative_control: Literal["included", "not_included", "not_recorded"]
    partner_report: PartnerReportReadiness
    flags: list[ContextFlag]
    accuracy_note: str


def _is_provided(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _join_labels(fields: list[str]) -> str:
    labels = [OPTIONAL_METADATA_FIELDS[f].lower() if f != "ph" else "pH" for f in fields]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def build_metadata_context(upload: Optional[dict[str, Any]]) -> MetadataContext:
    """Summarise which optional metadata an upload carries and what that limits."""
    upload_found = upload is not None
    doc = upload or {}

    provided = [f for f in OPTIONAL_METADATA_FIELDS if _is_provided(doc.get(f))]
    missing = [f for f in OPTIONAL_METADATA_FIELDS if f not in provided]
    missing_required = [f for f in PARTNER_REPORT_REQUIRED_FIELDS if f not in provided]

    flags: list[ContextFlag] = []
    if not upload_found:
        flags.append(ContextFlag(
            code="upload_not_found",
            message="Upload record not found, so no sample metadata is available.",
        ))

    partner_reason: Optional[str] = None
    if missing_required:
        partner_reason = (
            f"Partner report not available: {_join_labels(missing_required)} not recorded. "
            "A partner report needs the collection date and both coordinates."
        )
        flags.append(ContextFlag(code="partner_report_unavailable", message=partner_reason))

    nc = doc.get("negative_control_included")
    if nc is True:
        negative_control = "included"
    elif nc is False:
        negative_control = "not_included"
        flags.append(ContextFlag(code="no_negative_control", message=NO_NEGATIVE_CONTROL_MESSAGE))
    else:
        negative_control = "not_recorded"
        flags.append(ContextFlag(
            code="no_negative_control", message=NEGATIVE_CONTROL_NOT_RECORDED_MESSAGE,
        ))

    total = len(OPTIONAL_METADATA_FIELDS)
    if not missing:
        summary = f"All {total} optional context fields were provided."
    else:
        # The missing fields themselves are in `missing`; the note stays short.
        summary = (
            f"{len(provided)} of {total} optional context fields were provided. "
            "Missing context can reduce accuracy and limits how these results can be interpreted."
        )
    accuracy_note = " ".join([summary] + [f.message for f in flags])

    return MetadataContext(
        upload_found=upload_found,
        provided=provided,
        missing=missing,
        labels=dict(OPTIONAL_METADATA_FIELDS),
        negative_control=negative_control,
        partner_report=PartnerReportReadiness(
            available=not missing_required,
            missing_required=missing_required,
            reason=partner_reason,
        ),
        flags=flags,
        accuracy_note=accuracy_note,
    )
