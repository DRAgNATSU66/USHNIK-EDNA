"""
Fine-tunes one route's classifier head (+ backbone, unless --freeze-backbone)
on services/worker/training/build_dataset.py's output.

Reuses DNAClassifierHead from app.inference.heads directly — the saved
head.pt is loadable by the exact same class predictor.py uses at inference
time, no format drift possible. Tokenization mirrors app.inference.heads.
tokenize_dna's parameters (max_length=512) so train/inference preprocessing
matches; it isn't imported as-is because that helper hardcodes torch.no_grad()
around the forward pass, which would block gradients to the backbone here.

Run from services/worker/:
    python -m training.finetune --route fish
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# DNABERT-2's custom modeling code falls back to plain PyTorch attention when
# Triton is unavailable (see its bert_layers.py's `except ImportError`) -- but
# a community `triton-windows` package (installed for a later, unrelated
# experiment) makes `import triton` succeed while its JIT compiler still
# isn't available (no C compiler on PATH), so it takes the Triton path and
# crashes instead of falling back. Force the ImportError so it degrades the
# way the architecture actually intends on this machine. See
# evaluate_checkpoint.py for the reproduction that surfaced this.
sys.modules["triton"] = None  # type: ignore[assignment]

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from app.inference.heads import DNAClassifierHead
from app.inference.models import ROUTE_LABEL_SETS


class SequenceDataset(Dataset):
    def __init__(self, csv_path: Path, label_to_idx: dict[str, int], tokenizer, max_length: int):
        self.rows: list[tuple[str, int]] = []
        with open(csv_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                self.rows.append((row["sequence"], label_to_idx[row["label"]]))
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.label_counts = Counter(label for _, label in self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int):
        seq, label = self.rows[idx]
        enc = self.tokenizer(
            seq, truncation=True, max_length=self.max_length,
            padding="max_length", return_tensors="pt",
        )
        return {k: v.squeeze(0) for k, v in enc.items()}, label


def extract_cls(out) -> torch.Tensor:
    """DNABERT-2's custom MosaicBERT forward returns a plain tuple (no
    .last_hidden_state attribute) — same case app.inference.heads.
    get_cls_embedding already anticipates ("Most HuggingFace models expose
    last_hidden_state at outputs[0]"). [CLS] is always the first token."""
    last_hidden = out.last_hidden_state if hasattr(out, "last_hidden_state") else out[0]
    return last_hidden[:, 0, :]


def collate(batch):
    xs, ys = zip(*batch)
    batched = {k: torch.stack([x[k] for x in xs]) for k in xs[0].keys()}
    return batched, torch.tensor(ys, dtype=torch.long)


def run_eval(backbone, head, loader, device, criterion):
    from sklearn.metrics import accuracy_score, f1_score

    backbone.eval()
    head.eval()
    all_preds, all_labels = [], []
    # A class-weighted CrossEntropyLoss with reduction="mean" divides by the
    # sum of the batch's class weights, NOT by the batch size. Accumulating
    # `loss.item() * batch_size` and dividing by N therefore mixes two
    # different denominators, giving a dev_loss that shifts with each batch's
    # class composition. That matters here because dev_loss is what selects
    # the saved checkpoint. Accumulate the true weighted sum instead and
    # divide by the total weight, matching what the criterion actually means.
    class_w = getattr(criterion, "weight", None)
    loss_sum = 0.0
    weight_sum = 0.0
    with torch.no_grad():
        for batch, labels in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            labels = labels.to(device)
            out = backbone(**batch)
            cls_emb = extract_cls(out)
            logits = head(cls_emb)
            per_example = nn.functional.cross_entropy(
                logits, labels, weight=class_w, reduction="none"
            )
            loss_sum += per_example.sum().item()
            weight_sum += (class_w[labels].sum().item() if class_w is not None else labels.size(0))
            all_preds.extend(logits.argmax(dim=-1).cpu().tolist())
            all_labels.extend(labels.cpu().tolist())
    avg_loss = loss_sum / max(weight_sum, 1e-12)
    acc = accuracy_score(all_labels, all_preds) if all_labels else 0.0
    f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0) if all_labels else 0.0
    return avg_loss, acc, f1, all_labels, all_preds


def build_eval_report(labels_true: list[int], preds: list[int], label_names: list[str]) -> dict:
    """Per-class precision/recall/F1 + confusion matrix, in the same schema
    scripts/training/evaluate.py already writes — kept identical on purpose
    so both training pipelines' eval_report.json files are interchangeable
    for downstream reporting (e.g. the IEEE paper's results tables)."""
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    acc = accuracy_score(labels_true, preds) if labels_true else 0.0
    f1 = f1_score(labels_true, preds, average="macro", zero_division=0) if labels_true else 0.0
    report = classification_report(
        labels_true, preds, target_names=label_names,
        labels=list(range(len(label_names))), output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(labels_true, preds, labels=list(range(len(label_names)))).tolist()
    return {
        "accuracy": acc,
        "f1_macro": f1,
        "per_class": report,
        "confusion_matrix": cm,
        "label_order": label_names,
        "test_samples": len(labels_true),
    }


def save_checkpoint(
    save_dir: Path, head, backbone, tokenizer, args, labels, embedding_dim,
    train_ds, dev_ds, test_ds, best_dev_loss: float, extra_metrics: dict | None = None,
    eval_report: dict | None = None,
) -> None:
    """Writes head/backbone weights + metrics.json to disk immediately.

    Called both right after a new best dev score is found (mid-training,
    so a late crash -- e.g. during the final test eval -- doesn't lose an
    already-trained result that was previously held only in CPU RAM until
    end-of-script) and again at the very end with test metrics included.

    save_dir is the exact directory files land in -- callers pass either
    the route's main output_dir (best-by-dev_loss checkpoint) or a
    subdirectory like output_dir/"by_dev_acc" (best-by-dev_acc checkpoint,
    tracked separately so both selection criteria can actually be compared
    against the real test set instead of committing to one blindly).
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    head_path = save_dir / "head.pt"
    torch.save(head.state_dict(), head_path)
    print(f"  saved head weights: {head_path}")

    if not args.freeze_backbone:
        backbone_dir = save_dir / "backbone"
        backbone.save_pretrained(backbone_dir)
        tokenizer.save_pretrained(backbone_dir)

        # save_pretrained() only writes weights/config -- for a model loaded
        # via trust_remote_code=True, the custom modeling .py files (e.g.
        # DNABERT-2's bert_layers.py) live in the HF cache, not the model
        # object, and AutoModel.from_pretrained on a bare local directory
        # can't fetch them from the Hub the way it would for a Hub ID.
        # Without these the saved backbone silently fails to load later.
        import shutil
        org, _, name = args.base_model.partition("/")
        cache_model_dir = (
            Path.home() / ".cache" / "huggingface" / "modules" / "transformers_modules"
            / org / name.replace("-", "_hyphen_").replace(".", "_dot_")
        )
        revision_dirs = (
            [d for d in cache_model_dir.glob("*") if d.is_dir() and d.name != "__pycache__"]
            if cache_model_dir.exists() else []
        )
        if revision_dirs:
            src_dir = max(revision_dirs, key=lambda d: d.stat().st_mtime)
            copied = 0
            for py_file in src_dir.glob("*.py"):
                if py_file.name != "__init__.py":
                    shutil.copy(py_file, backbone_dir / py_file.name)
                    copied += 1
            print(f"  copied {copied} custom modeling file(s) from {src_dir}")
        else:
            print(f"  WARNING: no cached custom code found for {args.base_model} — "
                  f"saved backbone may not be loadable if it needs trust_remote_code")
        print(f"  saved fine-tuned backbone: {backbone_dir}")

    metrics = {
        "dev_loss_best": round(best_dev_loss, 4),
        "embedding_dim": embedding_dim,
        "base_model": args.base_model,
        "route": args.route,
        "num_classes": len(labels),
        "train_size": len(train_ds),
        "dev_size": len(dev_ds),
        "test_size": len(test_ds),
    }
    if extra_metrics:
        metrics.update(extra_metrics)
    (save_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    if eval_report is not None:
        report_path = save_dir / "eval_report.json"
        report_path.write_text(json.dumps(eval_report, indent=2))
        print(f"  saved per-class eval report: {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, choices=list(ROUTE_LABEL_SETS.keys()))
    parser.add_argument("--base-model", default="zhihan1996/DNABERT-2-117M")
    parser.add_argument("--data-dir", default="E:/synthveda-data")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--grad-accum", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    # Both AdamW and bitsandbytes' AdamW8bit default to 0.01 -- exposed here
    # (not just relying on the default) so it can be raised deliberately to
    # fight overfitting, e.g. after a run whose train_loss collapsed near
    # zero while dev_loss kept climbing for the back half of training.
    parser.add_argument("--weight-decay", type=float, default=0.01)
    # Real tokenized lengths for our data (checked empirically): median
    # ~133, p90 ~241 tokens. 512 was needlessly padding everything and
    # blowing the attention memory budget (O(seqlen^2), no flash-attention
    # available for DNABERT-2 on Windows) — 256 covers p90 with margin at
    # ~4x less attention memory than 512.
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--freeze-backbone", action="store_true")
    parser.add_argument("--seed", type=int, default=1337)
    # Default matches this machine's 8-core/16-thread CPU (i7-11700F) minus
    # headroom for the main process/CUDA driver thread — see
    # PC hardware specs in project memory. Each worker tokenizes on-the-fly
    # (SequenceDataset.__getitem__) in parallel instead of serially blocking
    # the GPU between steps, which is why CPU sat at ~9% with num_workers=0.
    parser.add_argument("--num-workers", type=int, default=10)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    from transformers import AutoConfig, AutoModel, AutoModelForMaskedLM, AutoTokenizer, get_linear_schedule_with_warmup

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")

    labels = ROUTE_LABEL_SETS[args.route]
    label_to_idx = {str(label): i for i, label in enumerate(labels)}

    data_dir = Path(args.data_dir) / "processed" / args.route
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.data_dir) / "checkpoints" / args.route
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading backbone: {args.base_model}")
    # trust_remote_code=True: this script is an explicit, human-invoked
    # training run against a named, known model — a different trust context
    # than the production loader (see ModelRegistryEntry.trusted_remote_code
    # for how that's gated at inference time).
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    config = AutoConfig.from_pretrained(args.base_model, trust_remote_code=True)
    if "AutoModel" not in getattr(config, "auto_map", {}) and getattr(config, "model_type", None) == "esm":
        # Some ESM-family repos (e.g. Nucleotide Transformer) only map
        # AutoModelForMaskedLM to their custom gated-FFN encoder class, not
        # plain AutoModel. Calling AutoModel directly then silently resolves
        # to transformers' built-in (non-gated) EsmModel, whose FFN shape
        # doesn't match the checkpoint's fused gate+up weights. Go through
        # the mapped class and pull out its encoder submodule instead.
        backbone = AutoModelForMaskedLM.from_pretrained(args.base_model, trust_remote_code=True).esm
    else:
        backbone = AutoModel.from_pretrained(args.base_model, trust_remote_code=True)
    backbone = backbone.to(device)
    embedding_dim = backbone.config.hidden_size

    head = DNAClassifierHead(embedding_dim=embedding_dim, num_classes=len(labels)).to(device)

    if args.freeze_backbone:
        for p in backbone.parameters():
            p.requires_grad = False

    train_ds = SequenceDataset(data_dir / "train.csv", label_to_idx, tokenizer, args.max_length)
    dev_ds = SequenceDataset(data_dir / "dev.csv", label_to_idx, tokenizer, args.max_length)
    test_ds = SequenceDataset(data_dir / "test.csv", label_to_idx, tokenizer, args.max_length)
    print(f"train={len(train_ds)} dev={len(dev_ds)} test={len(test_ds)}")

    loader_kwargs: dict[str, Any] = {"collate_fn": collate}
    if device == "cuda":
        loader_kwargs["pin_memory"] = True

    train_loader_kwargs = dict(loader_kwargs)
    if args.num_workers > 0:
        train_loader_kwargs["num_workers"] = args.num_workers
        # persistent_workers only pays off for train_loader, which is
        # iterated once per epoch across all 8 epochs. dev/test_loader are
        # each iterated at most once per epoch (dev) or once total (test)
        # -- keeping their worker pools alive between those single uses
        # just piles up extra idle processes for no benefit, and doing it
        # for all three loaders at once (train's 10 persistent + dev's 10 +
        # test's 10) was the likely cause of a real crash: a "paging file
        # too small" OSError loading a CUDA DLL right as the run reached
        # the eval phase, i.e. exactly when this pileup peaked.
        train_loader_kwargs["persistent_workers"] = True
        train_loader_kwargs["prefetch_factor"] = 4
        loader_kwargs["num_workers"] = min(2, args.num_workers)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, **train_loader_kwargs)
    dev_loader = DataLoader(dev_ds, batch_size=args.batch_size * 2, shuffle=False, **loader_kwargs)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size * 2, shuffle=False, **loader_kwargs)

    params = list(head.parameters()) if args.freeze_backbone else list(head.parameters()) + list(backbone.parameters())
    if device == "cuda":
        # Full fine-tuning of larger backbones (e.g. NT-500M) has enough
        # params that standard AdamW's two fp32 moment buffers alone exceed
        # what an 8GB GPU has left after the model itself — OOMs inside
        # optimizer.step() before a single update happens. bitsandbytes'
        # 8-bit AdamW quantizes those moment buffers, cutting optimizer
        # state to ~1/4 size with a documented, small accuracy cost.
        import bitsandbytes as bnb
        optimizer = bnb.optim.AdamW8bit(params, lr=args.lr, weight_decay=args.weight_decay)
    else:
        optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)
    steps_per_epoch = max(len(train_loader) // args.grad_accum, 1)
    total_steps = steps_per_epoch * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(0.06 * total_steps), num_training_steps=total_steps,
    )
    # Inverse-frequency class weighting: some routes have real, legitimate
    # class imbalance (e.g. bacteria_pathogen's likely_taxonomic_group is a
    # genuinely rarer label than known_species/possible_novelty in the real
    # data, not a sampling artifact) — without this the loss just favors
    # whichever classes are most common, which is exactly what tanked that
    # class's F1 in an earlier run despite decent overall accuracy.
    num_labels = len(labels)
    class_counts = [max(train_ds.label_counts.get(i, 0), 1) for i in range(num_labels)]
    total_examples = sum(class_counts)
    class_weights = torch.tensor(
        [total_examples / (num_labels * c) for c in class_counts], dtype=torch.float32, device=device,
    )
    print("class weights:", {str(l): round(w, 3) for l, w in zip(labels, class_weights.cpu().tolist())})
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    scaler = torch.amp.GradScaler("cuda", enabled=(device == "cuda"))

    best_dev_loss = float("inf")
    best_state: dict | None = None
    # Tracked in parallel with best_dev_loss/best_state so both selection
    # criteria can be evaluated against the real test set at the end,
    # rather than committing to dev_loss-based selection without ever
    # checking whether the highest-dev_acc epoch would have generalized
    # better -- that gap wasn't checkable before (see THEORY_README.md §2).
    best_dev_acc = 0.0
    best_state_by_acc: dict | None = None
    total_steps_per_epoch = len(train_loader)

    for epoch in range(args.epochs):
        head.train()
        if not args.freeze_backbone:
            backbone.train()
        optimizer.zero_grad()
        running_loss = 0.0
        epoch_start = time.time()
        last_progress_print = 0.0

        for step, (batch, batch_labels) in enumerate(train_loader):
            batch = {k: v.to(device) for k, v in batch.items()}
            batch_labels = batch_labels.to(device)

            with torch.autocast(device_type="cuda", enabled=(device == "cuda"), dtype=torch.float16):
                if args.freeze_backbone:
                    with torch.no_grad():
                        out = backbone(**batch)
                else:
                    out = backbone(**batch)
                cls_emb = extract_cls(out)
                logits = head(cls_emb)
                loss = criterion(logits, batch_labels) / args.grad_accum

            scaler.scale(loss).backward()
            running_loss += loss.item() * args.grad_accum

            if (step + 1) % args.grad_accum == 0:
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad()

            # Real per-second progress, not just once-per-epoch — a full
            # epoch on a large route can take minutes, and a live monitor
            # watching this log needs something finer to show than "0%
            # until the epoch happens to finish".
            now = time.time()
            if now - last_progress_print >= 1.0:
                elapsed = now - epoch_start
                rate = (step + 1) / elapsed if elapsed > 0 else 0
                print(
                    f"progress epoch={epoch + 1}/{args.epochs} step={step + 1}/{total_steps_per_epoch} "
                    f"elapsed={elapsed:.1f}s rate={rate:.2f}it/s",
                    flush=True,
                )
                last_progress_print = now

        dev_loss, dev_acc, dev_f1, _, _ = run_eval(backbone, head, dev_loader, device, criterion)
        print(
            f"epoch {epoch + 1}/{args.epochs}  train_loss={running_loss / len(train_loader):.4f}  "
            f"dev_loss={dev_loss:.4f}  dev_acc={dev_acc:.4f}  dev_f1={dev_f1:.4f}"
        )

        if dev_loss < best_dev_loss:
            best_dev_loss = dev_loss
            best_state = {"head": {k: v.cpu().clone() for k, v in head.state_dict().items()}}
            if not args.freeze_backbone:
                best_state["backbone"] = {k: v.cpu().clone() for k, v in backbone.state_dict().items()}
            print(f"  new best dev_loss={dev_loss:.4f} — saving checkpoint now (crash-resilience, not waiting for test eval)")
            save_checkpoint(
                output_dir, head, backbone, tokenizer, args, labels, embedding_dim,
                train_ds, dev_ds, test_ds, best_dev_loss,
                extra_metrics={"dev_acc_at_save": round(dev_acc, 4), "epoch_saved": epoch + 1},
            )

        if dev_acc > best_dev_acc:
            best_dev_acc = dev_acc
            best_state_by_acc = {"head": {k: v.cpu().clone() for k, v in head.state_dict().items()}}
            if not args.freeze_backbone:
                best_state_by_acc["backbone"] = {k: v.cpu().clone() for k, v in backbone.state_dict().items()}
            print(f"  new best dev_acc={dev_acc:.4f} — saving to by_dev_acc/ (separate from the dev_loss checkpoint)")
            save_checkpoint(
                output_dir / "by_dev_acc", head, backbone, tokenizer, args, labels, embedding_dim,
                train_ds, dev_ds, test_ds, dev_loss,
                extra_metrics={"dev_acc_at_save": round(dev_acc, 4), "epoch_saved": epoch + 1},
            )

    if best_state is not None:
        head.load_state_dict(best_state["head"])
        if "backbone" in best_state:
            backbone.load_state_dict(best_state["backbone"])

    test_loss, test_acc, test_f1, test_labels, test_preds = run_eval(backbone, head, test_loader, device, criterion)
    print(f"\nTEST  loss={test_loss:.4f}  acc={test_acc:.4f}  macro_f1={test_f1:.4f}")

    label_names = [str(l) for l in labels]
    eval_report = build_eval_report(test_labels, test_preds, label_names)
    from sklearn.metrics import classification_report
    print(classification_report(
        test_labels, test_preds, target_names=label_names,
        labels=list(range(len(labels))), zero_division=0,
    ))

    save_checkpoint(
        output_dir, head, backbone, tokenizer, args, labels, embedding_dim,
        train_ds, dev_ds, test_ds, best_dev_loss,
        extra_metrics={"test_accuracy": round(test_acc, 4), "test_macro_f1": round(test_f1, 4)},
        eval_report=eval_report,
    )

    # Also test the best-by-dev_acc checkpoint against the real test set,
    # skipping if it's the exact same epoch's weights the dev_loss criterion
    # already picked (no point re-running an identical eval).
    if best_state_by_acc is not None and best_state_by_acc is not best_state:
        head.load_state_dict(best_state_by_acc["head"])
        if "backbone" in best_state_by_acc:
            backbone.load_state_dict(best_state_by_acc["backbone"])
        acc_test_loss, acc_test_acc, acc_test_f1, acc_test_labels, acc_test_preds = run_eval(backbone, head, test_loader, device, criterion)
        print(
            f"\nTEST (by_dev_acc checkpoint)  loss={acc_test_loss:.4f}  "
            f"acc={acc_test_acc:.4f}  macro_f1={acc_test_f1:.4f}"
        )
        acc_eval_report = build_eval_report(acc_test_labels, acc_test_preds, label_names)
        save_checkpoint(
            output_dir / "by_dev_acc", head, backbone, tokenizer, args, labels, embedding_dim,
            train_ds, dev_ds, test_ds, best_dev_loss,
            extra_metrics={
                "dev_acc_best": round(best_dev_acc, 4),
                "test_accuracy": round(acc_test_acc, 4),
                "test_macro_f1": round(acc_test_f1, 4),
            },
            eval_report=acc_eval_report,
        )
        print(
            f"\nSelection comparison: by_dev_loss test_acc={test_acc:.4f}  "
            f"vs by_dev_acc test_acc={acc_test_acc:.4f}"
        )

    print("done.")


if __name__ == "__main__":
    main()
