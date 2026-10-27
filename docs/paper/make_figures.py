"""Regenerate the paper's figures from the committed measured results.

Inputs (all in git): docs/ml/results/heads_v2/{v1,v2}_<route>_on_new.json, written by
services/worker/training/evaluate_checkpoint.py --report-out (QNA-022). Nothing here
recomputes a metric; it only plots the stored values.

    python docs/paper/make_figures.py        # needs matplotlib

Writes docs/paper/figures/route_results.pdf and docs/paper/figures/confusion_bacteria.pdf.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "ml" / "results" / "heads_v2"
OUT = HERE / "figures"

ROUTES = [
    ("fish", "fish"),
    ("plant", "plant"),
    ("animal_general", "animal"),
    ("human_domestic_contamination", "human/dom."),
    ("misc_unknown", "misc"),
    ("bacteria_pathogen", "bacteria"),
]
# Served head per route since the 2026-10-19 promotion (QNA-023).
SERVED = {"fish": "v2", "plant": "v1", "animal_general": "v2",
          "human_domestic_contamination": "v2", "misc_unknown": "v2",
          "bacteria_pathogen": "v1"}


def load(version: str, route: str) -> dict:
    return json.loads((RESULTS / f"{version}_{route}_on_new.json").read_text())


def route_results() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    xs = range(len(ROUTES))
    w = 0.38
    for ax, key, title in ((axes[0], "accuracy", "Accuracy"), (axes[1], "f1_macro", "Macro F1")):
        v1 = [load("v1", r)[key] for r, _ in ROUTES]
        v2 = [load("v2", r)[key] for r, _ in ROUTES]
        ax.bar([x - w / 2 for x in xs], v1, w, label="v1 (trained Aug.)", color="#9aa5b1")
        ax.bar([x + w / 2 for x in xs], v2, w, label="v2 (retrained Oct.)", color="#2b6cb0")
        for x, (r, _) in zip(xs, ROUTES):
            served_val = (v1 if SERVED[r] == "v1" else v2)[x]
            ax.plot(x + (-w / 2 if SERVED[r] == "v1" else w / 2), served_val + 0.03, marker="v",
                    color="black", markersize=4)
        ax.set_xticks(list(xs))
        ax.set_xticklabels([lab for _, lab in ROUTES], rotation=35, ha="right", fontsize=7)
        ax.set_title(title, fontsize=9)
        ax.set_ylim(0, 1.1)
        ax.tick_params(axis="y", labelsize=7)
    axes[0].legend(fontsize=6.5, loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "route_results.pdf")
    plt.close(fig)


def confusion_bacteria() -> None:
    d = load("v1", "bacteria_pathogen")  # the served bacteria head (QNA-023)
    cm = d["confusion_matrix"]
    labels = ["known sp.", "likely grp.", "poss. novelty", "poss. contam."]
    norm = [[c / max(sum(row), 1) for c in row] for row in cm]
    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    for i, row in enumerate(cm):
        for j, c in enumerate(row):
            ax.text(j, i, str(c), ha="center", va="center", fontsize=7,
                    color="white" if norm[i][j] > 0.6 else "black")
    ax.set_xticks(range(4))
    ax.set_yticks(range(4))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("predicted", fontsize=8)
    ax.set_ylabel("label", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "confusion_bacteria.pdf")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    route_results()
    confusion_bacteria()
    print("wrote", OUT / "route_results.pdf", "and", OUT / "confusion_bacteria.pdf")
