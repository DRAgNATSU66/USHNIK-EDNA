# Novelty: centroid embedding isolation + reference low identity (B5, t-1024-1)

Date: 2026-10-27 (pipeline run 2026-10-20, report on the held-out TEST split 2026-10-27).
Data: `novelty_centroid_2026-10-27.json` (this directory). Logs: `synthveda-data/logs/novelty_centroid/`.

## What changed

- `services/worker/app/novelty/signals.py` `embedding_isolation()`: the `typical_norm = 14.0` L2-norm proxy is replaced by
  the cosine distance from the read's [CLS] embedding to the nearest known-class centroid of the head that produced it,
  mapped through the empirical CDF of that distance on held-out known TRAIN reads (0 = as close as known reads, 1 = farther
  than all of them). The proxy is kept only as a fallback when the head has no verified artefact, at its old weight 0.03,
  and the record says so (`embedding_proxy_<reason>`).
- Artefacts: `<head dir>/novelty_centroids_v1.{json,npz}` per served head (built by `training/novelty_centroids.py`; loaded
  and sha256/model-id/head-checksum verified by `app/novelty/centroids.py`).
- New separate term `reference_low_identity()`: 1.0 for no reference hit, linear 90 % -> 80 % identity, 0 at or above the
  family band; left out (not counted as novelty) when the lookup did not run.
- Both terms and their weights are written to every novelty record (`payload.details`). Novelty provider 1.0 -> 2.0,
  orchestrator-1.2.0 -> 1.3.0.
- Shared `NOVELTY_THRESHOLD` 0.45 -> 0.44 (`services/{worker,api}/app/config.py`, equality + grep tests unchanged in spirit).

## Selection (DEV only, criterion fixed before the run)

max mean over routes (fish, plant, animal_general, bacteria_pathogen, misc_unknown) of the possible_novelty F1 of the final flag (gated score >= T or final result_class possible_novelty); ties -> pooled F1, then T closest to 0.45.

- K (centroids per known class) by mean centroid-signal AUROC on dev: K=1: 0.9606 · K=4: 0.8911 · K=16: 0.8377 · K=32: 0.8148 · K=64: 0.829. K=1 chosen (bacteria drops from 0.936 at K=1 to
  0.581 at K=64; untested hypothesis: with more centroids the novel reads also land near some known sub-cluster).
- Weights x threshold grid (7 x 7 x 50): best = W_EMB 0, W_REF 0, T 0.44, mean F1 0.8233
  (old scorer @0.45: 0.8223). Dev-best per ablation: centroid only
  0.2 @ 0.55 -> 0.823; reference only
  0.05 @ 0.44 -> 0.8166; both
  0.50 / 0.05 @ 0.64 -> 0.8229.
- Result served: **both new terms at weight 0**. The F1 surface is flat to the 4th decimal (a few rows) across the grid.

## Held-out TEST: signal AUROC (possible_novelty vs known, per route)

| route | L2-norm proxy (dev / test) | centroid K=1 (dev / test) | reference low identity (dev / test) |
|---|---|---|---|
| fish | 0.948 / 0.9197 | 0.954 / 0.9216 | 0.5037 / 0.4963 |
| plant | 0.8783 / 0.9297 | 0.9816 / 0.9791 | 0.5162 / 0.496 |
| animal_general | 0.7741 / 0.7423 | 0.9752 / 0.9763 | 0.6025 / 0.5493 |
| bacteria_pathogen | 0.8561 / 0.8679 | 0.9358 / 0.953 | 0.5816 / 0.5938 |
| misc_unknown | 0.9373 / 0.9235 | 0.9565 / 0.9645 | 0.7667 / 0.7848 |
| _mean | 0.8788 / 0.8766 | 0.9606 / 0.9589 | 0.5941 / 0.584 |

The centroid signal is a much better isolation signal than the proxy, on held-out data, on every route (largest gain
animal_general 0.742 -> 0.976; smallest fish 0.920 -> 0.922). The reference low-identity term is at chance on
fish / plant (0.496 / 0.496) and only informative on misc_unknown (0.785).

## Held-out TEST: the orchestrator's final flag (served config vs old)

Flag = final reference-gated score >= T, or final result_class possible_novelty (what a user sees).
3238 rows (cap 600/route, seed 1024; human 300 known rows, false flags only); 0 rows dropped by QC; 4 rows routed
low_quality. Served path used the centroid term on 3234 rows,
proxy fallback on 0.

| route | old @0.45 P / R / F1 | served @0.44 P / R / F1 | n pos |
|---|---|---|---|
| fish | 0.872 / 0.405 / 0.553 (fp 5, flagged 39/584) | 0.872 / 0.405 / 0.553 (fp 5, flagged 39/584) | 84 |
| plant | 0.889 / 0.914 / 0.901 (fp 8, flagged 72/555) | 0.889 / 0.914 / 0.901 (fp 8, flagged 72/555) | 70 |
| animal_general | 0.933 / 0.641 / 0.759 (fp 13, flagged 193/599) | 0.928 / 0.641 / 0.758 (fp 14, flagged 194/599) | 281 |
| bacteria_pathogen | 0.969 / 0.752 / 0.847 (fp 7, flagged 229/600) | 0.961 / 0.759 / 0.849 (fp 9, flagged 233/600) | 295 |
| misc_unknown | 0.947 / 0.890 / 0.918 (fp 15, flagged 283/600) | 0.947 / 0.897 / 0.921 (fp 15, flagged 285/600) | 301 |
| human_domestic_contamination | 0.000 / 0.000 / 0.000 (fp 0, flagged 0/300) | 0.000 / 0.000 / 0.000 (fp 0, flagged 0/300) | 0 |
| _pooled_novelty_routes | 0.941 / 0.745 / 0.832 (fp 48, flagged 816/2938) | 0.938 / 0.749 / 0.833 (fp 51, flagged 823/2938) | 1031 |
| **mean F1, 5 novelty routes** | 0.7958 | 0.7964 | |

## Held-out TEST: served vs the not-served alternatives (all fixed on dev)

| config (W_EMB / W_REF @T), fixed on dev | test mean F1 | pooled P / R / F1 | flips vs old: +flags (TP/FP), -flags (TP/FP) | paired bootstrap mean-F1 diff vs old, median [95% CI] | raw-score AUROC mean |
|---|---|---|---|---|---|
| served (0 / 0 @0.44) | 0.7964 | 0.938 / 0.749 / 0.833 | +7 (4/3), -0 (0/0) | +0.0006 [-0.0012, +0.0027] | 0.9377 |
| both terms (0.50 / 0.05 @0.64) | 0.7961 | 0.938 / 0.749 / 0.833 | +20 (10/10), -13 (6/7) | +0.0004 [-0.0038, +0.0046] | 0.9411 |
| centroid only (0.20 / 0 @0.55) | 0.797 | 0.942 / 0.749 / 0.834 | +8 (5/3), -4 (1/3) | +0.0013 [-0.0018, +0.0044] | 0.9356 |
| reference only (0 / 0.05 @0.44) | 0.7955 | 0.925 / 0.756 / 0.832 | +40 (18/22), -13 (6/7) | -0.0002 [-0.0054, +0.0047] | 0.9438 |
| old (proxy 0.03, no ref @0.45) | 0.7958 | 0.941 / 0.745 / 0.832 | - | - | 0.9377 |

## Reading the numbers (as measured)

1. **The flag barely moves.** Served vs old on test: +7 flags (4 true, 3 false), 0 lost; mean F1 +0.0006, bootstrap 95 %
   CI [-0.0012, +0.0027]. Old scorer at 0.44 alone gives 0.7962: almost all of
   the change in the flag is the 0.45 -> 0.44 threshold, not the centroid (which is at weight 0). No route's F1 changes by more than 0.004; animal_general
   F1 is slightly worse (0.7595 -> 0.7579, one extra FP).
2. **Why the centroid does not reach the flag:** the flag is dominated by the head's own possible_novelty class (OR rule)
   and by the reference gate (`novelty_suppressed_by_reference` on 821
   of 3238 test rows). The flag is scored against the same labelling scheme the head was trained on, so a
   second signal that mostly agrees with the head adds little on this benchmark.
3. **Weighting the centroid does not help on test either.** centroid-only (0.20 @ 0.55) is the best alternative on test
   (mean F1 0.7970) but its CI includes 0 and fish gets worse (0.5528 -> 0.5484); both-terms raises composite raw-score
   AUROC 0.9377 -> 0.9411 but fish raw AUROC drops 0.9215 -> 0.8910 and misc_unknown FPs rise 15 -> 23.
4. **Fish recall is poor in every configuration (0.405 on test, 0.631 on dev).** This is not caused or fixed by B5.
5. The composite raw score (AUROC mean 0.938) ranks novel vs known reads *worse* than the centroid signal alone (0.959).

## Verdict against the Day-11 done-criterion

"Novelty uses centroid distance, measured on held-out data": the centroid distance **replaces** the proxy in the scorer
and is computed, verified and recorded on every novelty record (test: centroid used on all usable rows, 0 fallbacks),
and its separation is measured on held-out data (AUROC 0.959 vs 0.877). But by the pre-stated dev criterion it is served
at **weight 0**, so it does **not** contribute to `novelty_score` or to the flag. Changing that weight is a one-line edit
(`scorer.WEIGHTS`) but would be a choice made against the pre-registered criterion; it is left as an open decision.
