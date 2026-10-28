#!/bin/bash
# Heads v3b (QNA-048): hierarchical LTG loss, sqrt class weights, candidate = by_dev_acc (best dev
# parent-class accuracy, chosen before any test score), tau on dev, test scored once vs production.
# GPU shared with Dizzy: VRAM capped at 4.3 GB by vram_cap.py; RAM-capped scopes.
set -u
ROOT=/home/natsu/dev/synth-veda; D=$ROOT/synthveda-data; H=$D/logs/heads_v3b
O=$ROOT/docs/ml/results/heads_v3b; P=$O/probs; DSV="processed-2026-10-28T00:05:40+0530"
cd $ROOT/services/worker || exit 1
say() { echo "$(date +%H:%M:%S) $*" | tee -a $H/train_v3b.chain.log; }
declare -A WD=([fish]=0.01 [plant]=0.01 [animal_general]=0.05)
for route in ${ROUTES:-fish plant animal_general}; do
  ck=$D/checkpoints/${route}_v3b
  if [ ! -f $ck/eval_report.json ]; then
    [ -d $ck ] && mv $ck ${ck}_interrupted_$(date +%H%M%S)
    say "train $route wd=${WD[$route]}"
    systemd-run --user --scope -q -p MemoryMax=4G -p MemorySwapMax=0 .venv/bin/python -u $H/vram_cap.py training.finetune \
      --route $route --data-dir $D --output-dir $ck --epochs 6 --max-length 256 --num-workers 2 \
      --dataset-version "$DSV" --hierarchical --leaf-weight 0.3 --class-weight-power 0.5 --weight-decay ${WD[$route]} \
      > $H/train_$route.log 2>&1
    say "trained $route $(grep -E '^TEST' $H/train_$route.log | tr '\n' ' ')"
  fi
  for split in dev test; do
    systemd-run --user --scope -q -p MemoryMax=3G .venv/bin/python -u $H/vram_cap.py training.evaluate_checkpoint \
      --route $route --checkpoint-dir $ck/by_dev_acc --data-dir $D --max-length 256 --split $split \
      --report-out $O/v3b_${route}_${split}.json --dump-probs $P/v3b_${route}_${split}.npz > $H/dump_v3b_${route}_${split}.log 2>&1
  done
  .venv/bin/python -m training.hier_decode --route $route --prod-dev $P/prod_${route}_dev.npz --prod-test $P/prod_${route}_test.npz \
    --cand-dev $P/v3b_${route}_dev.npz --cand-test $P/v3b_${route}_test.npz --out $O/hier_v3b_$route.json 2>&1 | tee -a $H/train_v3b.chain.log
done
say ALL_DONE
