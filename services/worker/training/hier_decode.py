"""
Hierarchical decoding of a head that has likely_taxonomic_group (LTG) next
to known_species, scored against production on the same rows.

LTG is assigned from the record's name ("Genus sp.", "cf. x"), a curator's
judgment, not a property of the sequence: the same barcode is deposited under
named species too. A flat argmax lets LTG take known_species rows (fish v3:
known_species recall .915 -> .416, QNA-047). Decoded hierarchically, known
and LTG first compete as one class, P(known) + P(LTG), against the other
classes, exactly as the production 3-class head's known_species does; the
row is called LTG only when P(LTG | known or LTG) > tau. tau is chosen on dev,
the smallest value whose dev known_species recall is >= production's dev
recall (tau = 1 never emits LTG), and test is scored once with it.

Inputs are evaluate_checkpoint --dump-probs files:
    python -m training.hier_decode --route fish \
        --prod-dev p_dev.npz --prod-test p_test.npz \
        --cand-dev c_dev.npz --cand-test c_test.npz --out report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

KS, LTG = "known_species", "likely_taxonomic_group"
TAUS = [round(t, 2) for t in np.arange(0.50, 1.0, 0.01)] + [1.0]


def load(path: str | Path) -> dict:
    z = np.load(path)
    return {"probs": z["probs"], "labels": z["labels"],
            "head_labels": [str(x) for x in z["head_labels"]], "label_names": [str(x) for x in z["label_names"]]}


def decode(d: dict, tau: float | None) -> np.ndarray:
    """Predicted index into label_names. tau=None: plain argmax. A head
    trained on fewer labels (a prefix, see checkpoint_labels) never predicts
    the later ones."""
    probs, heads = d["probs"], d["head_labels"]
    if tau is None or LTG not in heads or KS not in heads:
        return probs.argmax(axis=1)
    ks, ltg = heads.index(KS), heads.index(LTG)
    merged = probs.copy()
    merged[:, ks] = probs[:, ks] + probs[:, ltg]
    merged[:, ltg] = -1.0
    pred = merged.argmax(axis=1)
    share = probs[:, ltg] / np.maximum(merged[:, ks], 1e-12)
    pred[(pred == ks) & (share > tau)] = ltg
    return pred


def metrics(d: dict, pred: np.ndarray, old_labels: list[str]) -> dict:
    names, y = d["label_names"], d["labels"]
    old = np.isin(y, [names.index(n) for n in old_labels])
    out = {"n": int(len(y)), "acc": round(float((pred == y).mean()), 4),
           "acc_on_prod_classes": round(float((pred[old] == y[old]).mean()), 4),
           "n_prod_class_rows": int(old.sum())}
    for name, key in ((KS, "known_species"), (LTG, "ltg")):
        if name not in names:
            continue
        i = names.index(name)
        tp = int(((pred == i) & (y == i)).sum())
        support, called = int((y == i).sum()), int((pred == i).sum())
        out[f"{key}_recall"] = round(tp / support, 4) if support else None
        out[f"{key}_precision"] = round(tp / called, 4) if called else None
    return out


def choose_tau(cand_dev: dict, target_ks_recall: float, old_labels: list[str]) -> tuple[float, list[dict]]:
    sweep = []
    chosen = 1.0
    for tau in TAUS:
        m = metrics(cand_dev, decode(cand_dev, tau), old_labels)
        sweep.append({"tau": tau, **m})
        if chosen == 1.0 and m["known_species_recall"] is not None and m["known_species_recall"] >= target_ks_recall:
            chosen = tau
    return chosen, sweep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True)
    for k in ("prod-dev", "prod-test", "cand-dev", "cand-test"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    pd, pt, cd, ct = (load(p) for p in (args.prod_dev, args.prod_test, args.cand_dev, args.cand_test))
    old_labels = pt["head_labels"]  # production's classes
    prod_dev, prod_test = metrics(pd, decode(pd, None), old_labels), metrics(pt, decode(pt, None), old_labels)
    tau, sweep = choose_tau(cd, prod_dev["known_species_recall"], old_labels)
    cand_test = metrics(ct, decode(ct, tau), old_labels)
    flat_test = metrics(ct, decode(ct, None), old_labels)
    ship = (cand_test["acc_on_prod_classes"] >= prod_test["acc_on_prod_classes"]
            and cand_test["known_species_recall"] >= prod_test["known_species_recall"])
    report = {"route": args.route, "prod_labels": old_labels, "cand_labels": ct["head_labels"],
              "tau_chosen_on_dev": tau, "tau_rule": "smallest tau with dev known_species recall >= prod dev",
              "prod": {"dev": prod_dev, "test": prod_test},
              "cand_flat_argmax": {"test": flat_test},
              "cand_hier": {"dev": next(s for s in sweep if s["tau"] == tau), "test": cand_test},
              "ship_rule": "cand_hier test acc_on_prod_classes and known_species_recall both >= prod test",
              "passes_ship_rule": bool(ship), "dev_sweep": sweep,
              "inputs": vars(args)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"{args.route}: tau={tau}  prod test {prod_test}")
    print(f"{' ' * len(args.route)}  hier test {cand_test}  ship={ship}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
