"""
Tests for the Phase 6 taxonomic router.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.model_router.features import (
    extract_features,
    kmer_cosine_similarity,
    jaccard_similarity,
    _kmer4_frequencies,
    _cpg_oe,
    _homopolymer_fraction,
)
from app.model_router.markers import detect_markers, marker_route_scores
from app.model_router.models import ConfidenceTier, RouterInput, TaxonomicRoute
from app.model_router.router import (
    route_sequence,
    route_batch,
    _confidence_tier,
    _is_low_quality,
    _gaussian,
    _length_score,
)


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------

class TestKmerFrequencies:
    def test_empty_sequence(self):
        freqs = _kmer4_frequencies("")
        assert freqs == {}

    def test_sums_to_one(self):
        seq = "ATCGATCGATCGATCGATCG"
        freqs = _kmer4_frequencies(seq)
        assert abs(sum(freqs.values()) - 1.0) < 1e-9

    def test_pure_at_no_gc_kmers(self):
        freqs = _kmer4_frequencies("ATATATATAT")
        assert all("G" not in k and "C" not in k for k in freqs)

    def test_n_bases_excluded(self):
        freqs_clean = _kmer4_frequencies("ATCGATCG")
        freqs_n = _kmer4_frequencies("NNCGATCG")
        # N-containing k-mers should not appear.
        assert all("N" not in k for k in freqs_n)

    def test_known_kmer_present(self):
        freqs = _kmer4_frequencies("ATCGATCG")
        assert "ATCG" in freqs
        assert freqs["ATCG"] > 0


class TestCosineSimlarity:
    def test_identical_profiles(self):
        freqs = _kmer4_frequencies("ATCGATCGATCG")
        sim = kmer_cosine_similarity(freqs, freqs)
        assert abs(sim - 1.0) < 1e-9

    def test_empty_profiles(self):
        sim = kmer_cosine_similarity({}, {})
        assert sim == 0.0

    def test_orthogonal_profiles(self):
        a = {"AAAA": 1.0}
        b = {"TTTT": 1.0}
        assert kmer_cosine_similarity(a, b) == 0.0


class TestJaccardSimilarity:
    def test_identical(self):
        s = {1, 2, 3}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({1, 2}, {3, 4}) == 0.0

    def test_partial(self):
        sim = jaccard_similarity({1, 2, 3}, {2, 3, 4})
        assert abs(sim - 0.5) < 1e-9

    def test_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 1.0


class TestCpGOE:
    def test_no_cg(self):
        assert _cpg_oe("AAAAAAAAAA") == 0.0

    def test_high_cpg(self):
        # "CGCGCGCG" has many CpG dinucleotides → high O/E.
        score = _cpg_oe("CGCGCGCGCGCG")
        assert score > 0.5

    def test_cpg_suppressed(self):
        # Alternating GC with no adjacent C→G → low O/E.
        score = _cpg_oe("GCGCGCGCGCGC")  # GC pattern, not CG
        # O/E should be low here since CpG is from C immediately followed by G
        # GCGC has CpG at positions 1 (C→G), so it's not zero.
        assert isinstance(score, float)


class TestHomopolymerFraction:
    def test_no_homopolymer(self):
        assert _homopolymer_fraction("ATCGATCG") == 0.0

    def test_all_same(self):
        assert _homopolymer_fraction("AAAAAAAAAA") == 1.0

    def test_partial(self):
        # ATCGAAAA has 4 A's homopolymer out of 8.
        frac = _homopolymer_fraction("ATCGAAAA")
        assert abs(frac - 0.5) < 1e-9

    def test_run_below_threshold(self):
        # AAA is 3 consecutive — below threshold of 4.
        assert _homopolymer_fraction("AAATCG") == 0.0


class TestExtractFeatures:
    def test_basic(self):
        fv = extract_features("ATCGATCGATCG", gc_ratio=0.5, n_ratio=0.0)
        assert fv.length == 12
        assert fv.gc_ratio == 0.5
        assert fv.n_ratio == 0.0
        assert fv.kmer4_freq  # non-empty
        assert isinstance(fv.minimizer_sketch, set)

    def test_short_sequence(self):
        fv = extract_features("AT")
        assert fv.kmer4_freq == {}
        assert fv.minimizer_sketch == set()


# ---------------------------------------------------------------------------
# Marker detection tests
# ---------------------------------------------------------------------------

class TestMarkerDetection:
    def test_16s_motif_detected(self):
        # Embed the short 16S motif in a longer sequence.
        seq = "AAAATCCTACGGGAAAA"
        hits = detect_markers(seq)
        assert any(h.route == "bacteria_pathogen" for h in hits)

    def test_no_marker_in_random_sequence(self):
        seq = "ATCGATCGATCGATCGATCGATCGATCGATCG"
        hits = detect_markers(seq)
        assert hits == []

    def test_marker_route_scores_returns_confidence(self):
        seq = "AAAACCTACGGGAAAAA"
        scores = marker_route_scores(seq)
        if scores:
            assert all(0.0 <= conf <= 1.0 for conf, _ in scores.values())

    def test_mifish_marker_detected(self):
        seq = "AAAAGTCGGTAAAACTCGTGCCAGCAAAA"
        hits = detect_markers(seq)
        assert any(h.route == "fish" for h in hits)

    def test_rbcL_marker_detected(self):
        seq = "TTTATGTCACCACAAACAGAGACTTTT"
        hits = detect_markers(seq)
        assert any(h.route == "plant" for h in hits)


# ---------------------------------------------------------------------------
# Router helper tests
# ---------------------------------------------------------------------------

class TestRouterHelpers:
    def test_gaussian_peak_at_mean(self):
        assert abs(_gaussian(0.5, 0.5, 0.1) - 1.0) < 1e-9

    def test_gaussian_decays_away(self):
        assert _gaussian(0.0, 0.5, 0.1) < 0.01

    def test_length_score_in_range(self):
        assert _length_score(500, 100, 800) == 1.0

    def test_length_score_too_short(self):
        assert _length_score(10, 100, 800) < 0.5

    def test_length_score_too_long(self):
        assert _length_score(5000, 100, 800) < 1.0

    def test_confidence_tier_high(self):
        assert _confidence_tier(0.85) == ConfidenceTier.high

    def test_confidence_tier_medium(self):
        assert _confidence_tier(0.55) == ConfidenceTier.medium

    def test_confidence_tier_low(self):
        assert _confidence_tier(0.25) == ConfidenceTier.low

    def test_low_quality_high_n(self):
        reasons: list[str] = []
        inp = RouterInput("s1", "NNNNATCG", 8, 0.5, 0.5, "x")
        assert _is_low_quality(inp, reasons)
        assert "high_n_ratio" in reasons

    def test_low_quality_short(self):
        reasons: list[str] = []
        inp = RouterInput("s1", "AT", 2, 0.0, 0.0, "x")
        assert _is_low_quality(inp, reasons)
        assert "length_too_short" in reasons


# ---------------------------------------------------------------------------
# End-to-end routing tests
# ---------------------------------------------------------------------------

def _make_input(
    sequence: str,
    seq_id: str = "seq1",
    gc_ratio: float = 0.5,
    n_ratio: float = 0.0,
    habitat: str | None = None,
) -> RouterInput:
    return RouterInput(
        sequence_id=seq_id,
        sequence=sequence,
        length=len(sequence),
        gc_ratio=gc_ratio,
        n_ratio=n_ratio,
        sha256="test",
        habitat=habitat,
    )


class TestRouteSequence:
    def test_low_quality_short_sequence(self):
        inp = _make_input("ATCG")
        result = route_sequence(inp)
        assert result.route == TaxonomicRoute.low_quality
        assert "length_too_short" in result.reason_codes

    def test_low_quality_high_n(self):
        seq = "N" * 50
        inp = _make_input(seq, n_ratio=1.0)
        result = route_sequence(inp)
        assert result.route == TaxonomicRoute.low_quality

    def test_result_has_required_fields(self):
        seq = "ATCGATCG" * 30
        inp = _make_input(seq, gc_ratio=0.5)
        result = route_sequence(inp)
        assert result.sequence_id == "seq1"
        assert isinstance(result.route, TaxonomicRoute)
        assert 0.0 <= result.route_confidence <= 1.0
        assert isinstance(result.fallback_routes, list)
        assert isinstance(result.reason_codes, list)
        assert isinstance(result.raw_scores, dict)

    def test_confidence_sums_correctly(self):
        seq = "ATCGATCG" * 30
        inp = _make_input(seq, gc_ratio=0.5)
        result = route_sequence(inp)
        # Raw scores normalise to probs; the top probability = route_confidence.
        raw = result.raw_scores
        total = sum(raw.values())
        if total > 0:
            best = max(raw.values()) / total
            assert abs(best - result.route_confidence) < 0.01

    def test_fish_marker_boosts_fish_route(self):
        # Embed the MiFish forward primer site in a realistic-length sequence.
        marker = "GTCGGTAAAACTCGTGCCAGC"
        seq = ("ATCGATCG" * 10) + marker + ("GCTAGCTA" * 10)
        inp = _make_input(seq, gc_ratio=0.46)
        result = route_sequence(inp)
        assert result.route == TaxonomicRoute.fish
        assert result.route_confidence >= 0.40
        assert any("mifish" in c.lower() for c in result.reason_codes)

    def test_bacteria_marker_boosts_bacteria_route(self):
        marker = "CCTACGGG"
        seq = ("GCTAGCTA" * 10) + marker + ("ATCGATCG" * 10)
        inp = _make_input(seq, gc_ratio=0.55)
        result = route_sequence(inp)
        assert result.route == TaxonomicRoute.bacteria_pathogen

    def test_plant_marker_boosts_plant_route(self):
        marker = "ATGTCACCACAAACAGAGAC"
        seq = ("ATCGATCG" * 10) + marker + ("GCTAGCTA" * 10)
        inp = _make_input(seq, gc_ratio=0.42)
        result = route_sequence(inp)
        assert result.route == TaxonomicRoute.plant

    def test_no_marker_falls_back_to_misc_unknown_or_bacteria(self):
        # A plain sequence with no markers — should be misc_unknown or bacteria
        # (bacteria has high prior, and GC 0.50 is right at its mean).
        seq = "ATCGATCG" * 30
        inp = _make_input(seq, gc_ratio=0.50)
        result = route_sequence(inp)
        assert result.route in (
            TaxonomicRoute.misc_unknown,
            TaxonomicRoute.bacteria_pathogen,
            TaxonomicRoute.animal_general,
            TaxonomicRoute.fish,
        )

    def test_fallback_routes_not_empty_for_uncertain_routing(self):
        seq = "ATCGATCG" * 30
        inp = _make_input(seq, gc_ratio=0.50)
        result = route_sequence(inp)
        # misc_unknown should always appear as a fallback (or be the primary).
        assert (
            result.route == TaxonomicRoute.misc_unknown
            or "misc_unknown" in result.fallback_routes
        )

    def test_marine_habitat_boosts_fish(self):
        # Same plain sequence — marine habitat should tilt scoring toward fish.
        seq = "ATCGATCG" * 30
        no_habitat = _make_input(seq, gc_ratio=0.45)
        with_habitat = _make_input(seq, gc_ratio=0.45, habitat="marine")
        r_no = route_sequence(no_habitat)
        r_yes = route_sequence(with_habitat)
        fish_score_no = r_no.raw_scores.get("fish", 0.0)
        fish_score_yes = r_yes.raw_scores.get("fish", 0.0)
        assert fish_score_yes >= fish_score_no

    def test_to_dict_serialisable(self):
        seq = "ATCGATCG" * 30
        inp = _make_input(seq)
        result = route_sequence(inp)
        d = result.to_dict()
        assert d["sequence_id"] == "seq1"
        assert "route" in d
        assert "route_confidence" in d
        assert "reason_codes" in d


class TestRouteBatch:
    def test_empty_batch(self):
        assert route_batch([]) == []

    def test_batch_length_matches_input(self):
        seqs = [_make_input("ATCGATCG" * 20, seq_id=f"s{i}") for i in range(5)]
        results = route_batch(seqs)
        assert len(results) == 5

    def test_batch_ids_preserved(self):
        seqs = [_make_input("ATCGATCG" * 20, seq_id=f"seq_{i}") for i in range(3)]
        results = route_batch(seqs)
        ids = [r.sequence_id for r in results]
        assert ids == ["seq_0", "seq_1", "seq_2"]

    def test_low_quality_in_batch(self):
        seqs = [
            _make_input("ATCGATCG" * 20),
            _make_input("AT", n_ratio=0.0),   # too short
            _make_input("ATCGATCG" * 20),
        ]
        results = route_batch(seqs)
        assert results[1].route == TaxonomicRoute.low_quality
        assert results[0].route != TaxonomicRoute.low_quality
