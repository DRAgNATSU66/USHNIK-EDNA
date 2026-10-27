#!/usr/bin/env bash
# Heads v3 (QNA-047): retrain the six route heads on processed/ v3 (BOLD,
# label set v2), then score production and v3 on the same v3 test rows.
# Settings as QNA-022: DNABERT-2 117M base weights, 6 epochs, max_length 256,
# 4 data workers, best dev loss checkpoint, smallest route first.
set -u
ROOT=/home/natsu/dev/synth-veda
DATA=$ROOT/synthveda-data
LOG=$DATA/logs/rebuild_v3
OUT=$ROOT/docs/ml/results/heads_v3
DSV="processed-2026-10-28T00:05:40+0530"
PY=$ROOT/services/worker/.venv/bin/python
mkdir -p "$OUT"
cd "$ROOT/services/worker"
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG/chain.log"; }

for route in fish plant human_domestic_contamination animal_general misc_unknown bacteria_pathogen; do
  ck=$DATA/checkpoints/${route}_v3
  if [ -f "$ck/eval_report.json" ]; then say "skip $route (eval_report.json exists)"; continue; fi
  if [ -d "$ck" ]; then mv "$ck" "${ck}_interrupted_$(date +%Y%m%d%H%M%S)"; say "moved interrupted $ck aside"; fi
  say "start $route"
  systemd-run --user --scope -q -p MemoryMax=6G -p MemorySwapMax=0 \
    $PY -u -m training.finetune --route "$route" --data-dir "$DATA" --output-dir "$ck" \
      --epochs 6 --max-length 256 --num-workers 4 --dataset-version "$DSV" \
      > "$LOG/train_$route.log" 2>&1
  say "end $route rc=$? $(grep -E '^TEST' "$LOG/train_$route.log" | tail -1)"
done

# Production checkpoints as of QNA-023: fish/animal/human/misc v2, plant/bacteria v1.
declare -A PROD=([fish]=fish_v2 [plant]=plant [human_domestic_contamination]=human_domestic_contamination_v2
                 [animal_general]=animal_general_v2 [misc_unknown]=misc_unknown_v2 [bacteria_pathogen]=bacteria_pathogen)
for route in fish plant human_domestic_contamination animal_general misc_unknown bacteria_pathogen; do
  for which in prod v3; do
    if [ "$which" = prod ]; then ck=$DATA/checkpoints/${PROD[$route]}; else ck=$DATA/checkpoints/${route}_v3; fi
    systemd-run --user --scope -q -p MemoryMax=6G -p MemorySwapMax=0 \
      $PY -u -m training.evaluate_checkpoint --route "$route" --checkpoint-dir "$ck" --data-dir "$DATA" \
        --max-length 256 --report-out "$OUT/${which}_${route}_on_v3test.json" \
        > "$LOG/score_${which}_$route.log" 2>&1
    say "score $which $route ($(basename "$ck")) rc=$? $(grep -E '^TEST' "$LOG/score_${which}_$route.log" | tail -1)"
  done
done
say "ALL DONE"
