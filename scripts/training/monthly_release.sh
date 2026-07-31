#!/usr/bin/env bash
# monthly_release.sh — Monthly model retraining pipeline for Synth Veda.
#
# Usage:
#   ./scripts/training/monthly_release.sh \
#       --batch-id   tbatch_202606_fish_abc12345 \
#       --route      fish \
#       --run-id     dnabert2_fish_v2 \
#       [--epochs    3] \
#       [--batch-size 8]
#
# Steps:
#   1. Export frozen training batch from MongoDB → CSV dataset
#   2. Fine-tune DNABERT-2 with LoRA on the dataset
#   3. Evaluate model on the validation split
#   4. Pause and show metrics — human must decide whether to promote
#   5. On human approval, write new registry JSON entry (status=experimental)
#
# Anti-poisoning:
#   This script NEVER automatically sets status=production.
#   After promotion, edit models/registry/<run-id>.json to set "status": "production"
#   only after A/B validation against the current production model.
#
# Prerequisites:
#   pip install -r scripts/training/requirements.txt
#   MongoDB running and MONGODB_URI set in .env

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────────────────────
BATCH_ID=""
ROUTE=""
RUN_ID=""
EPOCHS=3
BATCH_SIZE=8
BASE_MODEL="zhihan1996/DNABERT-2-117M"
PROMOTED_BY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --batch-id)    BATCH_ID="$2";    shift 2 ;;
    --route)       ROUTE="$2";       shift 2 ;;
    --run-id)      RUN_ID="$2";      shift 2 ;;
    --epochs)      EPOCHS="$2";      shift 2 ;;
    --batch-size)  BATCH_SIZE="$2";  shift 2 ;;
    --base-model)  BASE_MODEL="$2";  shift 2 ;;
    --promoted-by) PROMOTED_BY="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -z "$BATCH_ID" || -z "$ROUTE" || -z "$RUN_ID" ]]; then
  echo "Usage: $0 --batch-id <id> --route <route> --run-id <run_id> [options]"
  exit 1
fi

BATCH_DIR="data/batches/${BATCH_ID}"
LOG_DIR="models/runs/${RUN_ID}/logs"
mkdir -p "$LOG_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Synth Veda — Monthly Model Release Pipeline             ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Batch  : ${BATCH_ID}"
echo "║  Route  : ${ROUTE}"
echo "║  Run ID : ${RUN_ID}"
echo "║  Epochs : ${EPOCHS}   Batch size: ${BATCH_SIZE}"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Load .env if present ─────────────────────────────────────────────────────
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

# ── Step 1: Export batch ──────────────────────────────────────────────────────
echo "▶ Step 1/4 — Exporting batch ${BATCH_ID} …"
python scripts/training/export_batch.py \
  --batch-id "$BATCH_ID" \
  --out-dir  "$BATCH_DIR" \
  2>&1 | tee "${LOG_DIR}/export.log"
echo "  ✓ Export complete → ${BATCH_DIR}/sequences.csv"
echo ""

# ── Step 2: Train ─────────────────────────────────────────────────────────────
echo "▶ Step 2/4 — Training ${RUN_ID} …"
python scripts/training/train.py \
  --route      "$ROUTE" \
  --batch-dir  "$BATCH_DIR" \
  --run-id     "$RUN_ID" \
  --base-model "$BASE_MODEL" \
  --epochs     "$EPOCHS" \
  --batch-size "$BATCH_SIZE" \
  2>&1 | tee "${LOG_DIR}/train.log"
echo "  ✓ Training complete → models/runs/${RUN_ID}/"
echo ""

# ── Step 3: Evaluate ──────────────────────────────────────────────────────────
echo "▶ Step 3/4 — Evaluating ${RUN_ID} …"
python scripts/training/evaluate.py \
  --run-id    "$RUN_ID" \
  --batch-dir "$BATCH_DIR" \
  2>&1 | tee "${LOG_DIR}/eval.log"
echo "  ✓ Evaluation complete → models/runs/${RUN_ID}/eval_report.json"
echo ""

# ── Step 4: Human sign-off ───────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  HUMAN REVIEW REQUIRED                                   ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Review the evaluation report:                           ║"
echo "║    cat models/runs/${RUN_ID}/eval_report.json"
echo "║                                                          ║"
echo "║  Do the metrics meet your quality bar?                   ║"
echo "║  (accuracy, per-class F1, confusion matrix)              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

read -rp "  Promote to registry? [y/N] " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "  Skipped. Re-run promote.py manually when ready:"
  echo "    python scripts/training/promote.py --run-id ${RUN_ID} --approve"
  exit 0
fi

PROMOTE_ARGS="--run-id ${RUN_ID} --status experimental --approve"
if [[ -n "$PROMOTED_BY" ]]; then
  PROMOTE_ARGS="${PROMOTE_ARGS} --promoted-by ${PROMOTED_BY}"
fi

echo ""
echo "▶ Step 4/4 — Promoting ${RUN_ID} to registry (status=experimental) …"
# shellcheck disable=SC2086
python scripts/training/promote.py $PROMOTE_ARGS \
  2>&1 | tee "${LOG_DIR}/promote.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Monthly release complete                                ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Registry entry: models/registry/${RUN_ID}.json"
echo "║  Status: experimental                                    ║"
echo "║                                                          ║"
echo "║  NEXT STEPS (manual):                                    ║"
echo "║  1. A/B test vs current production model                 ║"
echo "║  2. Edit registry JSON → \"status\": \"staging\"            ║"
echo "║  3. Monitor worker inference metrics for 1 week          ║"
echo "║  4. Edit registry JSON → \"status\": \"production\"         ║"
echo "║                                                          ║"
echo "║  Anti-poisoning: NO automatic status=production path.    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
