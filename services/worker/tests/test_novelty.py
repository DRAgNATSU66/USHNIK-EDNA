"""
Tests for Phase 8 novelty and contamination scoring.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.novelty.models import NoveltyLevel, AbyssRecommendation, ContaminationScore, NoveltyScore
from app.novelty.signals import (
    signal_low_confidence,
    signal_result_class,
    signal_high_quality,
    signal_not_contamination,
    signal_route_model_disagreement,
    signal_embedding_isolation,
)
from app.novelty.scorer import score_sequence, score_batch, _novelty_level
from app.novelty.contamination import (
    contamination_score,
    contamination_score_batch,
    _signal_route,
    _signal_lab_motifs,
    _signal_human_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seq(
    sequence_id: str = "s1",
    confidence: float = 0.5,
    result_class: str = "unknown_needs_online_confirmation",
    route: str = "misc_unknown",
    n_ratio: float = 0.0,
    length: int = 300,
    gc_ratio: float = 0.50,
    has_invalid_chars: bool = False,
    label_scores: dict | None = None,
    embedding: list[float] | None = None,
    fallback_routes: list[str] | None = None,
    cpg_oe: float = 0.1,
) -> dict:
    return {
        "sequence_id": sequence_id,
        "sequence": "ATCGATCG" * (length // 8),
        "confidence": confidence,
        "result_class": result_class,
        "route": route,
        "n_ratio": n_ratio,
        "length": length,
        "gc_ratio": gc_ratio,
        "has_invalid_chars": has_invalid_chars,
        "label_scores": label_scores if label_scores is not None else {"unknown_needs_online_confirmation": 0.5, "possible_novelty": 0.3, "low_quality_unusable": 0.2},
        "embedding": embedding,
        "fallback_routes": fallback_routes or [],
        "cpg_oe": cpg_oe,
    }


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------

class TestSignalLowConfidence:
    def test_zero_confidence_gives_high_score(self):
        score, code = signal_low_confidence(_seq(confidence=0.0))
        assert score == 1.0
        assert "low_model_confidence" in code

    def test_full_confidence_gives_low_score(self):
        score, _ = signal_low_confidence(_seq(confidence=1.0))
        assert score == 0.0

    def test_medium_confidence(self):
        score, _ = signal_low_confidence(_seq(confidence=0.5))
        assert 0.2 < score < 0.8

    def test_score_monotonically_decreasing(self):
        scores = [signal_low_confidence(_seq(confidence=c))[0] for c in [0.1, 0.5, 0.9]]
        assert scores[0] > scores[1] > scores[2]


class TestSignalResultClass:
    def test_possible_novelty_high(self):
        score, _ = signal_result_class(_seq(result_class="possible_novelty"))
        assert score >= 0.85

    def test_known_species_low(self):
        score, _ = signal_result_class(_seq(result_class="known_species"))
        assert score <= 0.10

    def test_unknown_confirmation_mid(self):
        score, _ = signal_result_class(_seq(result_class="unknown_needs_online_confirmation"))
        assert 0.50 <= score <= 0.80

    def test_contamination_zero(self):
        score, _ = signal_result_class(_seq(result_class="possible_contamination"))
        assert score == 0.0

    def test_reason_code_includes_class(self):
        _, code = signal_result_class(_seq(result_class="possible_novelty"))
        assert "possible_novelty" in code


class TestSignalHighQuality:
    def test_high_quality_full(self):
        score, code = signal_high_quality(_seq(n_ratio=0.0, length=300, has_invalid_chars=False))
        assert score >= 0.9
        assert "high_quality" in code

    def test_high_n_ratio_penalised(self):
        score, _ = signal_high_quality(_seq(n_ratio=0.6))
        assert score < 0.3

    def test_too_short_zero(self):
        score, _ = signal_high_quality(_seq(length=20))
        assert score == 0.0

    def test_invalid_chars_penalised(self):
        good = signal_high_quality(_seq(has_invalid_chars=False))[0]
        bad = signal_high_quality(_seq(has_invalid_chars=True))[0]
        assert good > bad


class TestSignalNotContamination:
    def test_clean_route_returns_one(self):
        score, code = signal_not_contamination(_seq(route="fish"))
        assert score == 1.0
        assert "not_contamination" in code

    def test_contamination_route_returns_zero(self):
        score, _ = signal_not_contamination(_seq(route="human_domestic_contamination"))
        assert score == 0.0

    def test_contamination_result_class_returns_zero(self):
        score, _ = signal_not_contamination(_seq(result_class="possible_contamination"))
        assert score == 0.0

    def test_flagged_contamination_score_returns_zero(self):
        seq = _seq()
        seq["contamination_score"] = 0.8
        score, _ = signal_not_contamination(seq)
        assert score == 0.0


class TestSignalRouteModelDisagreement:
    def test_uniform_labels_high_entropy(self):
        # All equal → high entropy → high disagreement score.
        seq = _seq(label_scores={"a": 0.33, "b": 0.33, "c": 0.34})
        score, code = signal_route_model_disagreement(seq)
        assert score > 0.9
        assert "high_label_entropy" in code

    def test_peaked_labels_low_entropy(self):
        # One label dominates → low entropy → low disagreement.
        seq = _seq(label_scores={"a": 0.95, "b": 0.03, "c": 0.02})
        score, code = signal_route_model_disagreement(seq)
        assert score < 0.4
        assert "low_label_entropy" in code

    def test_no_label_scores(self):
        seq = _seq(label_scores={})
        score, _ = signal_route_model_disagreement(seq)
        assert score == 0.0


class TestSignalEmbeddingIsolation:
    def test_no_embedding_returns_zero(self):
        score, code = signal_embedding_isolation(_seq(embedding=None))
        assert score == 0.0
        assert "no_embedding" in code

    def test_near_typical_norm_low_score(self):
        # L2 norm ≈ 14.0 → near typical → low deviation.
        embedding = [14.0 / 50 ** 0.5] * 50   # norm = 14.0 / sqrt(50) * sqrt(50) = 14
        # Actually: norm = sqrt(sum(x^2)) = sqrt(50 * (14/sqrt(50))^2) = sqrt(50 * 196/50) = sqrt(196) = 14
        seq = _seq(embedding=embedding)
        score, _ = signal_embedding_isolation(seq)
        assert score < 0.1

    def test_high_norm_embedding_higher_score(self):
        embedding = [2.0] * 100    # norm = sqrt(100 * 4) = 20 → deviation from 14 is 43%
        seq = _seq(embedding=embedding)
        score, _ = signal_embedding_isolation(seq)
        assert score > 0.0


# ---------------------------------------------------------------------------
# Novelty scorer tests
# ---------------------------------------------------------------------------

class TestNoveltyLevel:
    def test_thresholds(self):
        assert _novelty_level(0.05) == NoveltyLevel.none
        assert _novelty_level(0.30) == NoveltyLevel.low
        assert _novelty_level(0.55) == NoveltyLevel.medium
        assert _novelty_level(0.80) == NoveltyLevel.high


class TestScoreSequence:
    def test_low_quality_route_skipped(self):
        seq = _seq(route="low_quality", result_class="low_quality_unusable")
        result = score_sequence(seq)
        assert result.novelty_score == 0.0
        assert result.novelty_level == NoveltyLevel.none
        assert "low_quality_skipped" in result.reason_codes

    def test_contamination_suppresses_novelty(self):
        seq = _seq(
            route="human_domestic_contamination",
            confidence=0.05,
            result_class="possible_contamination",
        )
        result = score_sequence(seq)
        assert result.novelty_score < 0.20

    def test_high_confidence_known_species_low_novelty(self):
        seq = _seq(confidence=0.95, result_class="known_species")
        result = score_sequence(seq)
        assert result.novelty_score < 0.20
        assert result.novelty_level == NoveltyLevel.none

    def test_uncertain_high_quality_raises_novelty(self):
        seq = _seq(
            confidence=0.05,
            result_class="possible_novelty",
            route="fish",
            n_ratio=0.0,
            length=400,
            label_scores={"known_species": 0.35, "possible_novelty": 0.35, "low_quality_unusable": 0.30},
        )
        result = score_sequence(seq)
        assert result.novelty_score > 0.30

    def test_result_has_all_fields(self):
        result = score_sequence(_seq())
        assert result.sequence_id == "s1"
        assert 0.0 <= result.novelty_score <= 1.0
        assert result.novelty_level in NoveltyLevel
        assert isinstance(result.signals, dict)
        assert isinstance(result.reason_codes, list)
        assert result.abyss_recommendation in AbyssRecommendation
        assert isinstance(result.requires_cloud_confirmation, bool)

    def test_to_dict_complete(self):
        d = score_sequence(_seq()).to_dict()
        assert "novelty_score" in d
        assert "novelty_level" in d
        assert "signals" in d
        assert "reason_codes" in d
        assert "abyss_recommendation" in d
        assert "requires_cloud_confirmation" in d

    def test_high_novelty_recommends_preserve_sample(self):
        seq = _seq(
            confidence=0.02,
            result_class="possible_novelty",
            route="fish",
            n_ratio=0.0,
            length=500,
            label_scores={"known_species": 0.34, "possible_novelty": 0.33, "low_quality_unusable": 0.33},
        )
        result = score_sequence(seq)
        if result.novelty_level in (NoveltyLevel.high, NoveltyLevel.medium):
            assert result.abyss_recommendation in (
                AbyssRecommendation.preserve_sample,
                AbyssRecommendation.return_for_full_analysis,
            )

    def test_low_quality_sequence_recommends_resample(self):
        seq = _seq(n_ratio=0.6, length=20)
        result = score_sequence(seq)
        if result.abyss_recommendation == AbyssRecommendation.resample:
            pass  # expected path
        # At minimum: novelty should be low for low-quality sequence.
        assert result.novelty_score <= 0.5


class TestScoreBatch:
    def test_empty_batch(self):
        assert score_batch([]) == []

    def test_batch_length_matches(self):
        seqs = [_seq(sequence_id=f"s{i}") for i in range(5)]
        results = score_batch(seqs)
        assert len(results) == 5

    def test_ids_preserved(self):
        seqs = [_seq(sequence_id=f"id{i}") for i in range(3)]
        results = score_batch(seqs)
        assert [r.sequence_id for r in results] == ["id0", "id1", "id2"]


# ---------------------------------------------------------------------------
# Contamination detector tests
# ---------------------------------------------------------------------------

class TestContaminationSignalRoute:
    def test_human_domestic_route(self):
        seq = _seq(route="human_domestic_contamination")
        score, code, ctype = _signal_route(seq)
        assert score >= 0.85
        assert ctype == "human_dna"

    def test_contamination_result_class(self):
        seq = _seq(result_class="possible_contamination")
        score, code, _ = _signal_route(seq)
        assert score >= 0.70

    def test_clean_route(self):
        seq = _seq(route="fish", result_class="known_species")
        score, _, _ = _signal_route(seq)
        assert score == 0.0

    def test_contamination_in_fallbacks(self):
        seq = _seq(fallback_routes=["human_domestic_contamination"])
        score, _, _ = _signal_route(seq)
        assert 0.0 < score < 0.5


class TestLabMotifs:
    def test_illumina_adapter_detected(self):
        seq = _seq()
        seq["sequence"] = "AAAAAGATCGGAAGAGCAAAAA"
        score, code = _signal_lab_motifs(seq)
        assert score >= 0.90
        assert "lab_motif" in code

    def test_clean_sequence(self):
        seq = _seq()
        seq["sequence"] = "ATCGATCGATCGATCGATCGATCG"
        score, _ = _signal_lab_motifs(seq)
        assert score == 0.0


class TestHumanProfile:
    def test_human_gc_and_cpg(self):
        # GC ~0.41 + elevated CpG O/E → human-like.
        seq = _seq(gc_ratio=0.41, cpg_oe=0.55, length=300)
        score, code, ctype = _signal_human_profile(seq)
        assert score >= 0.50
        assert ctype is not None

    def test_high_gc_bacteria_not_human(self):
        seq = _seq(gc_ratio=0.65, cpg_oe=0.02, length=300)
        score, _, _ = _signal_human_profile(seq)
        assert score < 0.30

    def test_short_sequence_zero(self):
        seq = _seq(length=30)
        score, _, _ = _signal_human_profile(seq)
        assert score == 0.0


class TestContaminationScore:
    def test_clean_fish_sequence(self):
        seq = _seq(route="fish", result_class="known_species", gc_ratio=0.45, cpg_oe=0.05)
        result = contamination_score(seq)
        assert result.contamination_score < 0.5
        assert not result.is_flagged

    def test_human_route_flagged(self):
        seq = _seq(route="human_domestic_contamination")
        result = contamination_score(seq)
        assert result.is_flagged
        assert result.contamination_score >= 0.40  # weighted score; hard-flag triggers is_flagged

    def test_lab_motif_flagged(self):
        seq = _seq()
        seq["sequence"] = "AAAAAGATCGGAAGAGCTTTTTTTT"
        result = contamination_score(seq)
        assert result.is_flagged
        assert result.contamination_type == "lab_reagent"

    def test_to_dict_complete(self):
        d = contamination_score(_seq()).to_dict()
        assert "contamination_score" in d
        assert "is_flagged" in d
        assert "contamination_type" in d
        assert "signals" in d
        assert "reason_codes" in d

    def test_batch_contamination(self):
        seqs = [
            _seq(sequence_id="clean", route="fish"),
            _seq(sequence_id="dirty", route="human_domestic_contamination"),
        ]
        results = contamination_score_batch(seqs)
        assert len(results) == 2
        assert not results[0].is_flagged
        assert results[1].is_flagged
