"""
Per-route known-class centroids for the novelty scorer (B5, tracker t-1024-1).

For every SERVED route head (ModelRegistry.best_available(route), the same
choice app/inference makes), embed the TRAIN split's known rows with that
head's own backbone exactly as inference does -- app.inference.loader
get_or_load(entry), heads.tokenize_dna at max_length.resolve_max_length(entry)
(padding="max_length"), heads.get_cls_embedding ([CLS] = last_hidden_state
[:, 0]) -- then fit spherical k-means per known class and write a versioned
artifact next to the head (app/novelty/centroids.py documents the format).

Known classes: known_species, likely_taxonomic_group, and on misc_unknown
(which has no known_species rows) unknown_needs_online_confirmation -- the
non-novel, usable class of that route, as in the QNA-020 evaluation.
possible_novelty, possible_contamination and low_quality_unusable rows are
never used.

Run from services/worker/ with SYNTHVEDA_DATA_ROOT set:

  python -m training.novelty_centroids embed [--routes fish,plant,...]
      GPU pass; caches embeddings under <data>/cache/novelty_centroids/<model_id>/
      and checks the batched embedding against predictor.run_inference on a
      few rows (cosine >= 0.9999 or it stops).
  python -m training.novelty_centroids fit --k 32 [--calib-frac 0.1 --seed 1024]
      Fits the centroids on (1 - calib_frac) of each class's rows and writes
      calib_quantiles from the held-out calib_frac rows (so the ECDF is not
      measured on the rows that placed the centroids). Writes
      <head dir>/novelty_centroids_v1.{npz,json}.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# Same Triton guard as evaluate_checkpoint.py (DNABERT-2 custom code).
sys.modules.setdefault("triton", None)  # type: ignore[arg-type]

ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")
KNOWN_CLASSES = ("known_species", "likely_taxonomic_group", "unknown_needs_online_confirmation")
N_QUANTILES = 1001
MIN_ROWS_PER_CENTROID = 20


def data_root() -> Path:
    return Path(os.environ.get("SYNTHVEDA_DATA_ROOT", "synthveda-data")).resolve()


def cache_dir(model_id: str) -> Path:
    return data_root() / "cache" / "novelty_centroids" / model_id


def read_split(route: str, split: str) -> list[tuple[int, str, str]]:
    csv.field_size_limit(sys.maxsize)
    with open(data_root() / "processed" / route / f"{split}.csv", encoding="utf-8", newline="") as fh:
        return [(i, r["sequence"].strip().upper(), r["label"]) for i, r in enumerate(csv.DictReader(fh))]


def sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       cwd=Path(__file__).resolve().parent).strip()
    except Exception:
        return None


def served_entry(route: str):
    from app.inference.registry import get_registry
    e = get_registry().best_available(route)
    if e is None:
        raise SystemExit(f"no served model for {route}")
    return e


# ---------------------------------------------------------------------------
# embedding (the served inference path, batched)
# ---------------------------------------------------------------------------

def embed_sequences(entry, seqs: list[str], batch_size: int = 32, log_every: int = 2000) -> np.ndarray:
    import torch

    from app.inference.heads import get_cls_embedding, tokenize_dna
    from app.inference.loader import get_or_load
    from app.inference.max_length import resolve_max_length

    pair = get_or_load(entry)
    if pair is None:
        raise SystemExit(f"backbone for {entry.model_id} did not load")
    model, tok = pair
    max_length, src = resolve_max_length(entry)
    out = np.zeros((len(seqs), entry.embedding_dim), dtype=np.float32)
    t0 = time.perf_counter()
    for b in range(0, len(seqs), batch_size):
        chunk = seqs[b:b + batch_size]
        inputs = tokenize_dna(chunk, tok, max_length=max_length)
        with torch.no_grad():
            emb = get_cls_embedding(model, inputs)
        out[b:b + len(chunk)] = emb.numpy()
        if log_every and (b // batch_size) % max(1, log_every // batch_size) == 0:
            print(f"  {entry.model_id}: {b + len(chunk)}/{len(seqs)} ({time.perf_counter() - t0:.0f}s, "
                  f"max_length {max_length} from {src})", flush=True)
    return out


def check_against_served(entry, route: str, seqs: list[str], emb: np.ndarray, n: int = 6) -> float:
    """Min cosine between the batched embedding and predictor.run_inference's."""
    from app.inference.predictor import run_inference
    worst = 1.0
    for i in range(min(n, len(seqs))):
        pred = run_inference(sequence_id=f"chk{i}", sequence=seqs[i], route=route)
        if pred.embedding is None or pred.model_version_used != entry.model_id:
            raise SystemExit(f"served inference on {route} gave no embedding / a different model "
                             f"({pred.model_version_used}, {pred.stub_reason})")
        a, b = np.asarray(pred.embedding, dtype=np.float32), emb[i]
        cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
        worst = min(worst, cos)
    return worst


def cmd_embed(args: argparse.Namespace) -> None:
    import torch
    routes = args.routes.split(",") if args.routes else list(ROUTES)
    for route in routes:
        entry = served_entry(route)
        rows = [(i, s, lab) for i, s, lab in read_split(route, "train") if lab in KNOWN_CLASSES]
        cd = cache_dir(entry.model_id)
        cd.mkdir(parents=True, exist_ok=True)
        print(f"{route}: {entry.model_id} ({entry.status}), {len(rows)} train-known rows", flush=True)
        t0 = time.perf_counter()
        emb = embed_sequences(entry, [s for _, s, _ in rows], batch_size=args.batch_size)
        secs = time.perf_counter() - t0
        worst = check_against_served(entry, route, [s for _, s, _ in rows], emb)
        print(f"  {route}: {secs:.0f}s; min cosine batched vs run_inference = {worst:.6f}", flush=True)
        if worst < 0.9999:
            raise SystemExit(f"{route}: batched embedding disagrees with served inference ({worst})")
        np.save(cd / "train_known_emb.npy", emb)
        meta = {"model_id": entry.model_id, "route": route, "status": entry.status,
                "head_checksum": entry.checksum, "rows": [i for i, _, _ in rows],
                "labels": [lab for _, _, lab in rows], "seconds": round(secs, 1),
                "min_cosine_vs_run_inference": worst,
                "train_csv_sha256": sha256_path(data_root() / "processed" / route / "train.csv"),
                "peak_gpu_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if torch.cuda.is_available() else None}
        (cd / "train_known_meta.json").write_text(json.dumps(meta))
        from app.inference.loader import unload
        unload(entry.model_id)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

def _unit(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(n, 1e-12)


def load_train_cache(model_id: str) -> tuple[np.ndarray, list[str], dict]:
    cd = cache_dir(model_id)
    meta = json.loads((cd / "train_known_meta.json").read_text())
    return np.load(cd / "train_known_emb.npy"), meta["labels"], meta


def fit_centroids(emb: np.ndarray, labels: list[str], k: int, calib_frac: float = 0.1, seed: int = 1024
                  ) -> dict:
    """Spherical k-means per known class on the fit fold; ECDF quantiles of the
    nearest-centroid cosine distance on the held-out calib fold."""
    from sklearn.cluster import KMeans

    rng = np.random.default_rng(seed)
    x = _unit(emb.astype(np.float32))
    labels_a = np.asarray(labels)
    cents, cls, k_by_class, n_fit, n_calib = [], [], {}, {}, {}
    calib_idx = []
    for c in sorted(set(labels)):
        idx = np.flatnonzero(labels_a == c)
        rng.shuffle(idx)
        n_cal = int(round(len(idx) * calib_frac)) if len(idx) >= 20 else 0
        cal, fit = idx[:n_cal], idx[n_cal:]
        calib_idx.extend(cal.tolist())
        kc = int(max(1, min(k, len(fit) // MIN_ROWS_PER_CENTROID)))
        if kc == 1:
            centers = x[fit].mean(axis=0, keepdims=True)
        else:
            km = KMeans(n_clusters=kc, n_init=4, random_state=seed).fit(x[fit])
            centers = km.cluster_centers_
        cents.append(_unit(centers))
        cls.extend([c] * len(centers))
        k_by_class[c], n_fit[c], n_calib[c] = kc, int(len(fit)), int(len(cal))
    C = np.vstack(cents).astype(np.float32)
    cal_x = x[np.asarray(calib_idx, dtype=int)] if calib_idx else x
    d = 1.0 - (cal_x @ C.T).max(axis=1)
    q = np.quantile(d, np.linspace(0, 1, N_QUANTILES)).astype(np.float32)
    return {"centroids": C, "centroid_class": np.asarray(cls), "calib_quantiles": q,
            "k_by_class": k_by_class, "n_fit": n_fit, "n_calib": n_calib,
            "calib_distance": {"p50": float(np.quantile(d, 0.5)), "p90": float(np.quantile(d, 0.9)),
                               "p99": float(np.quantile(d, 0.99)), "max": float(d.max())}}


def centroid_set_from_fit(fit: dict, model_id: str, route: str):
    from app.novelty.centroids import CentroidSet
    return CentroidSet(model_id=model_id, route=route, centroids=fit["centroids"],
                       centroid_class=[str(c) for c in fit["centroid_class"]],
                       calib_quantiles=np.sort(fit["calib_quantiles"]))


def write_artifact(entry, route: str, fit: dict, meta: dict, k: int, calib_frac: float, seed: int,
                   out_dir: Path | None = None) -> dict:
    from app.novelty.centroids import ARRAYS_NAME, CENTROIDS_VERSION, FORMAT_VERSION, MANIFEST_NAME
    d = out_dir or Path(entry.artifact_uri).parent
    d.mkdir(parents=True, exist_ok=True)
    npz = d / ARRAYS_NAME
    tmp = d / (ARRAYS_NAME + ".tmp.npz")
    np.savez(tmp, centroids=fit["centroids"], centroid_class=fit["centroid_class"].astype("U"),
             calib_quantiles=fit["calib_quantiles"])
    os.replace(tmp, npz)
    from app.inference.max_length import resolve_max_length
    max_length, ml_src = resolve_max_length(entry)
    manifest = {
        "format_version": FORMAT_VERSION,
        "centroids_version": CENTROIDS_VERSION,
        "model_id": entry.model_id,
        "route": route,
        "head_checksum": entry.checksum,
        "embedding": "[CLS] = last_hidden_state[:, 0] (app/inference/heads.get_cls_embedding)",
        "embedding_dim": int(fit["centroids"].shape[1]),
        "max_length": max_length, "max_length_source": ml_src,
        "distance": "cosine (1 - cos) to the nearest centroid; centroids L2-normalised",
        "method": "spherical k-means per known class (sklearn KMeans on unit vectors, n_init=4)",
        "known_classes": list(KNOWN_CLASSES),
        "k_requested": k, "k_by_class": fit["k_by_class"], "min_rows_per_centroid": MIN_ROWS_PER_CENTROID,
        "n_fit": fit["n_fit"], "n_calib": fit["n_calib"], "calib_frac": calib_frac, "seed": seed,
        "calib_distance": fit["calib_distance"], "n_quantiles": int(len(fit["calib_quantiles"])),
        "train_split": f"processed/{route}/train.csv", "train_csv_sha256": meta.get("train_csv_sha256"),
        "training_dataset_version": entry.training_dataset_version,
        "min_cosine_batched_vs_run_inference": meta.get("min_cosine_vs_run_inference"),
        "npz_sha256": sha256_path(npz),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "script": "services/worker/training/novelty_centroids.py",
        "git_commit": git_commit(),
    }
    mtmp = d / (MANIFEST_NAME + ".tmp")
    mtmp.write_text(json.dumps(manifest, indent=2))
    os.replace(mtmp, d / MANIFEST_NAME)
    return manifest


def cmd_fit(args: argparse.Namespace) -> None:
    routes = args.routes.split(",") if args.routes else list(ROUTES)
    summary = {}
    for route in routes:
        entry = served_entry(route)
        emb, labels, meta = load_train_cache(entry.model_id)
        if meta.get("head_checksum") != entry.checksum:
            raise SystemExit(f"{route}: cached embeddings are for a different head checksum")
        fit = fit_centroids(emb, labels, args.k, args.calib_frac, args.seed)
        m = write_artifact(entry, route, fit, meta, args.k, args.calib_frac, args.seed,
                           Path(args.out_dir) / route if args.out_dir else None)
        summary[route] = {k: m[k] for k in ("model_id", "k_by_class", "n_fit", "n_calib", "calib_distance",
                                            "npz_sha256", "max_length")}
        print(f"{route}: {m['model_id']} K={sum(m['k_by_class'].values())} {m['k_by_class']} "
              f"calib p50/p99 {m['calib_distance']['p50']:.4f}/{m['calib_distance']['p99']:.4f} "
              f"sha256 {m['npz_sha256'][:16]}", flush=True)
    if args.summary_out:
        Path(args.summary_out).write_text(json.dumps(summary, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("embed")
    e.add_argument("--routes", default="")
    e.add_argument("--batch-size", type=int, default=32)
    f = sub.add_parser("fit")
    f.add_argument("--routes", default="")
    f.add_argument("--k", type=int, required=True)
    f.add_argument("--calib-frac", type=float, default=0.1)
    f.add_argument("--seed", type=int, default=1024)
    f.add_argument("--out-dir", default="", help="write here instead of beside each head")
    f.add_argument("--summary-out", default="")
    args = ap.parse_args()
    {"embed": cmd_embed, "fit": cmd_fit}[args.cmd](args)


if __name__ == "__main__":
    main()
