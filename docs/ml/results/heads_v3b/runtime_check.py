"""Does the worker's real inference path reproduce hier_decode's scored predictions? (QNA-048)"""
import csv, json, sys, time
import numpy as np
sys.path.insert(0, ".")
from pathlib import Path
from app.inference.registry import _parse_entry
from app.inference.loader import get_or_load
from app.inference import predictor
from training import hier_decode as hd

route, ck, tau = sys.argv[1], sys.argv[2], float(sys.argv[3])
m = json.load(open(f"../../synthveda-data/checkpoints/{ck}/metrics.json"))
entry = _parse_entry({"model_id": f"check_{ck}", "route": route, "base_model": f"data:checkpoints/{ck}/backbone",
                      "head_type": "sequence_classification", "embedding_dim": 768,
                      "label_set_version": m["label_set_version"], "label_set": m["label_set"], "status": "candidate",
                      "metrics": {"max_length": m["max_length"]},
                      "thresholds": {"high_confidence": 0.7, "low_confidence": 0.35, "ltg_share_tau": tau},
                      "artifact_uri": f"data:checkpoints/{ck}/head.pt", "trusted_remote_code": True}, Path("check"))
model, tok = get_or_load(entry)
rows = list(csv.DictReader(open(f"../../synthveda-data/processed/{route}/test.csv")))
ct = hd.load(f"../../docs/ml/results/heads_v3b/probs/{sys.argv[4]}_{route}_test.npz")
offline = hd.decode(ct, tau)
names = ct["label_names"]
agree = final_changed = 0; maxdiff = 0.0; t0 = time.time()
for i, r in enumerate(rows):
    res = predictor._run_model(f"r{i}", r["sequence"], route, entry, model, tok)
    lab, _ = predictor.hierarchical_best(res.label_scores, tau)
    agree += (str(lab) == names[offline[i]])
    final_changed += (str(res.result_class) != str(lab))
    p = np.array([res.label_scores[l] for l in ct["head_labels"]])
    maxdiff = max(maxdiff, float(np.abs(p - ct["probs"][i]).max()))
out = {"route": route, "checkpoint": ck, "tau": tau, "rows": len(rows), "runtime_label_equals_hier_decode": agree,
       "max_abs_prob_diff": round(maxdiff, 5), "final_result_class_changed_by_confidence_thresholds": final_changed,
       "inference_mode": str(res.inference_mode), "seconds": round(time.time() - t0, 1)}
print(json.dumps(out))
open(f"../../docs/ml/results/heads_v3b/runtime_check_{route}.json", "w").write(json.dumps(out, indent=2))
