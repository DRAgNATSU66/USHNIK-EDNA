"""
Novelty and contamination scoring data models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NoveltyLevel(StrEnum):
    """Qualitative novelty suspicion tier — used by Abyss Mode summary."""
    none = "none"        # clearly known, no novelty signal
    low = "low"          # one weak signal
    medium = "medium"    # multiple weak signals or one strong signal
    high = "high"        # multiple strong signals — flag for expert review


class AbyssRecommendation(StrEnum):
    """
    Field triage recommendation output for Abyss Mode.
    Not a scientific claim — a decision-support signal only.
    """
    continue_sampling = "continue_sampling"
    preserve_sample = "preserve_sample"      # possible novelty — archive sample
    resample = "resample"                    # quality issue — try again
    return_for_full_analysis = "return_for_full_analysis"  # too uncertain offline


@dataclass
class NoveltyScore:
    sequence_id: str
    novelty_score: float          # 0.0 (definitely known) → 1.0 (strongly novel)
    novelty_level: NoveltyLevel
    # Individual signal contributions (all 0.0–1.0).
    signals: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    # Abyss Mode field triage output.
    abyss_recommendation: AbyssRecommendation = AbyssRecommendation.continue_sampling
    requires_cloud_confirmation: bool = False

    def to_dict(self) -> dict:
        return {
            "novelty_score": round(self.novelty_score, 4),
            "novelty_level": str(self.novelty_level),
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "reason_codes": self.reason_codes,
            "abyss_recommendation": str(self.abyss_recommendation),
            "requires_cloud_confirmation": self.requires_cloud_confirmation,
        }


@dataclass
class ContaminationScore:
    sequence_id: str
    contamination_score: float    # 0.0 (clean) → 1.0 (very likely contamination)
    is_flagged: bool              # True when score >= flag_threshold (default 0.5)
    contamination_type: str | None  # e.g. "human_dna", "domestic_animal", "lab_reagent"
    signals: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "contamination_score": round(self.contamination_score, 4),
            "is_flagged": self.is_flagged,
            "contamination_type": self.contamination_type,
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "reason_codes": self.reason_codes,
        }
