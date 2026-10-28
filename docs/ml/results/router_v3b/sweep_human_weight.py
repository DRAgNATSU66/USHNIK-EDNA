"""Dev-only sweep of the human route's class-weight multiplier for router v3b (QNA-048).
Same config as router v3: k=9 canonical, LinearSVC C=1, cap 8000, seed 0. No test rows are read."""
import json, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, ".")
from training import train_router as tr

root = Path("/home/natsu/dev/synth-veda/synthveda-data")
data = tr.load_splits(root / "processed")
routes_of, splits_of = tr.occurrence_index(data)
Xtr, ytr, _ = tr.build_train(data, routes_of, splits_of, 8000, 0)
Xdv, ydv, _, _ = tr.build_heldout(data, routes_of, splits_of, "dev")
A, yA = tr.train_matrix(Xtr, ytr, 9, "canonical")
D = tr.featurise(Xdv, 9, "canonical")
H = tr.ROUTES.index("human_domestic_contamination")
rows = []
for mult in [float(x) for x in sys.argv[1].split(",")]:
    t0 = time.time()
    m = tr.make_model("svm", 1.0, 0, tr.route_class_weights(yA, {"human_domestic_contamination": mult})).fit(A, yA)
    pred = np.asarray(D @ m.coef_.T + m.intercept_).argmax(1)
    per = {r: round(float((pred[ydv == i] == i).mean()), 4) for i, r in enumerate(tr.ROUTES)}
    prec_h = float((ydv[pred == H] == H).mean()) if (pred == H).any() else None
    row = {"human_mult": mult, "dev_acc": round(float((pred == ydv).mean()), 4), "dev_per_route_recall": per,
           "dev_human_precision": round(prec_h, 4) if prec_h is not None else None,
           "dev_human_to_fish": int(((ydv == H) & (pred == tr.ROUTES.index("fish"))).sum()),
           "fit_seconds": round(time.time() - t0, 1)}
    rows.append(row)
    print(json.dumps(row), flush=True)
out = root / "logs/router_v3b/sweep_human_weight.json"
out.write_text(json.dumps({"dev_rows": int(len(ydv)), "rule": "smallest mult with dev human recall >= 0.891", "rows": rows}, indent=2))
