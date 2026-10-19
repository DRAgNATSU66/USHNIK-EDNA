"""
Scores each served route head on its held-out test split twice: at
max_length 512 (what predictor.py used for every head before the alignment
fix) and at the max_length the head was trained at (resolved from its own
record by app/inference/max_length.py). Reports accuracy / macro-F1 both ways
plus where the two disagree.

Everything on the model side goes through the production inference code:
loader.get_or_load (fp32 backbone), heads.get_head (trained head.pt),
heads.tokenize_dna (padding="max_length", truncation) and
heads.get_cls_embedding. Only the batching is added (a list of sequences per
tokenize_dna call instead of one), so the numbers describe what the worker
actually serves.

"Served" means registry.best_available(route): the production entry where a
route has one, otherwise the best experimental entry (plant and bacteria
still serve v1 as of QNA-023).

Run from services/worker/:
    SYNTHVEDA_DATA_ROOT=/path/to/synthveda-data \\
        python -m training.eval_maxlen_alignment \\
        --out ../../docs/ml/results/maxlen_alignment_2026-10-19.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Same Triton guard as finetune.py / evaluate_checkpoint.py.
sys.modules["triton"] = None  # type: ignore[assignment]

import torch

from app.inference import loader
from app.inference.heads import get_cls_embedding, get_head, tokenize_dna
from app.inference.max_length import resolve_max_length
from app.inference.models import ROUTE_LABEL_SETS
from app.inference.registry import ModelRegistry, _resolve_data_root

ROUTES = ["fish", "plant", "bacteria_pathogen", "animal_general", "human_domestic_contamination", "misc_unknown"]
REPO_ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _score(model, tokenizer, head, seqs: list[str], max_length: int, batch_size: int) -> list[list[float]]:
    """Softmax probabilities per sequence. On CUDA OOM (another job may share
    the GPU) the batch is halved and retried; at batch 1 it waits and retries."""
    probs: list[list[float]] = []
    i = 0
    bs = batch_size
    waits = 0
    while i < len(seqs):
        chunk = seqs[i:i + bs]
        try:
            inputs = tokenize_dna(chunk, tokenizer, max_length=max_length)
            cls = get_cls_embedding(model, inputs)
            with torch.no_grad():
                probs.extend(torch.softmax(head(cls), dim=-1).tolist())
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if bs > 1:
                bs = max(1, bs // 2)
                print(f"  CUDA OOM -- retrying with batch {bs}", flush=True)
            else:
                waits += 1
                if waits > 10:
                    raise
                print("  CUDA OOM at batch 1 -- waiting 30 s", flush=True)
                time.sleep(30)
            continue
        i += len(chunk)
    return probs


def _metrics(y_true: list[int], y_pred: list[int], label_names: list[str]) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

    if not y_true:
        return {"n": 0, "accuracy": None, "f1_macro": None}
    labels = list(range(len(label_names)))
    per_class = f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "f1_per_class": {n: round(float(f), 4) for n, f in zip(label_names, per_class)},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }


def evaluate_route(reg: ModelRegistry, route: str, data_root: Path, compare_length: int,
                   batch_size: int, limit: int | None, seed: int) -> dict:
    entry = reg.best_available(route)
    if entry is None:
        return {"route": route, "skipped": "no runnable registry entry"}
    trained_len, source = resolve_max_length(entry)
    label_names = [str(l) for l in ROUTE_LABEL_SETS[route]]
    label_to_idx = {n: i for i, n in enumerate(label_names)}

    test_csv = data_root / "processed" / route / "test.csv"
    with open(test_csv, encoding="utf-8") as fh:
        rows = [(r["sequence"], label_to_idx[r["label"]]) for r in csv.DictReader(fh)]
    n_total = len(rows)
    sampled = False
    if limit is not None and limit < n_total:
        rows = random.Random(seed).sample(rows, limit)
        sampled = True
    seqs = [s for s, _ in rows]
    y_true = [y for _, y in rows]

    print(f"[{route}] {entry.model_id} ({entry.status}) trained max_length={trained_len} "
          f"(source {source}); {len(rows)}/{n_total} test rows", flush=True)

    pair = loader.get_or_load(entry)
    if pair is None:
        return {"route": route, "model_id": entry.model_id, "skipped": "backbone failed to load"}
    model, tokenizer = pair
    head = get_head(route=route, model_id=entry.model_id, embedding_dim=entry.embedding_dim,
                    head_weights_path=entry.artifact_uri)

    # Untruncated token count (incl. [CLS]/[SEP]) per row: which rows each
    # window actually cuts.
    ntok = [len(ids) for ids in tokenizer(seqs, add_special_tokens=True, truncation=False)["input_ids"]]

    lengths = sorted({trained_len, compare_length})
    by_len: dict[int, dict] = {}
    for L in lengths:
        t0 = time.time()
        probs = _score(model, tokenizer, head, seqs, L, batch_size)
        secs = time.time() - t0
        preds = [max(range(len(p)), key=p.__getitem__) for p in probs]
        by_len[L] = {"probs": probs, "preds": preds, "seconds": round(secs, 1)}
        m = _metrics(y_true, preds, label_names)
        print(f"  max_length={L}: acc={m['accuracy']} macro_f1={m['f1_macro']} ({secs:.0f}s)", flush=True)

    def subset(idx: list[int], L: int) -> dict:
        return _metrics([y_true[i] for i in idx], [by_len[L]["preds"][i] for i in idx], label_names)

    short_idx = [i for i, n in enumerate(ntok) if n <= trained_len]
    long_idx = [i for i, n in enumerate(ntok) if n > trained_len]
    a, b = by_len[trained_len], by_len[compare_length]
    flips = [i for i in range(len(seqs)) if a["preds"][i] != b["preds"][i]]
    max_dp = [max(abs(x - y) for x, y in zip(a["probs"][i], b["probs"][i])) for i in range(len(seqs))]
    sorted_ntok = sorted(ntok)

    loader.unload(entry.model_id)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "route": route,
        "model_id": entry.model_id,
        "registry_status": entry.status,
        "trained_max_length": trained_len,
        "trained_max_length_source": source,
        "compare_max_length": compare_length,
        "test_csv": str(test_csv.relative_to(data_root)),
        "test_csv_sha256": _sha256(test_csv),
        "test_rows_total": n_total,
        "test_rows_scored": len(rows),
        "sampled": sampled,
        "registry_test_metrics": {k: entry.metrics.get(k) for k in ("test_accuracy", "test_macro_f1", "test_size")},
        "token_length": {
            "median": sorted_ntok[len(sorted_ntok) // 2],
            "p90": sorted_ntok[int(0.9 * (len(sorted_ntok) - 1))],
            "max": sorted_ntok[-1],
            "rows_over_trained_max_length": len(long_idx),
            "rows_over_compare_max_length": sum(1 for n in ntok if n > compare_length),
        },
        "at_trained_max_length": {**_metrics(y_true, a["preds"], label_names), "seconds": a["seconds"]},
        "at_compare_max_length": {**_metrics(y_true, b["preds"], label_names), "seconds": b["seconds"]},
        "rows_within_trained_max_length": {
            "at_trained": subset(short_idx, trained_len), "at_compare": subset(short_idx, compare_length),
            "max_abs_prob_diff": round(max((max_dp[i] for i in short_idx), default=0.0), 6),
        },
        "rows_over_trained_max_length": {
            "at_trained": subset(long_idx, trained_len), "at_compare": subset(long_idx, compare_length),
            "max_abs_prob_diff": round(max((max_dp[i] for i in long_idx), default=0.0), 6),
        },
        "top1_flips": {
            "total": len(flips),
            "within_trained_max_length": sum(1 for i in flips if ntok[i] <= trained_len),
            "over_trained_max_length": sum(1 for i in flips if ntok[i] > trained_len),
            "fixed_by_trained": sum(1 for i in flips if a["preds"][i] == y_true[i]),
            "broken_by_trained": sum(1 for i in flips if b["preds"][i] == y_true[i]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-dir", default=str(REPO_ROOT / "models" / "registry"))
    parser.add_argument("--routes", nargs="*", default=ROUTES, choices=ROUTES)
    parser.add_argument("--compare-length", type=int, default=512,
                        help="The window inference used before the fix.")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None,
                        help="Score a seeded random sample of this many rows per route instead of the full split.")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data_root = _resolve_data_root()
    reg = ModelRegistry(args.registry_dir)
    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    started = time.time()
    results = [
        evaluate_route(reg, r, data_root, args.compare_length, args.batch_size, args.limit, args.seed)
        for r in args.routes
    ]

    import transformers
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "services/worker/training/eval_maxlen_alignment.py",
        "question": "Served route heads scored on their held-out test split at max_length 512 "
                    "(pre-fix inference) vs the max_length each head was trained at.",
        "metric_note": "Top-1 argmax over the head's label set, as in finetune.py / evaluate_checkpoint.py; "
                       "the confidence-threshold mapping to result_class is not applied.",
        "device": device,
        "dtype": "float32",
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "batch_size_requested": args.batch_size,
        "limit": args.limit,
        "seed": args.seed if args.limit else None,
        "total_seconds": round(time.time() - started, 1),
        "routes": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
