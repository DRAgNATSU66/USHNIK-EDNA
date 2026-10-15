# Synth Veda — QNA transcript

A stenographic record of major changes, written as they happen. It never blocks a merge,
commit or push. Entries are append-only: a wrong entry is superseded by a new one that says so,
and the original stays. Numbers are recorded as measured, including unflattering ones.

Recorded: changes over 3 files · routing, orchestration, agent or model-registry changes · model
or dataset swaps · schema and migrations · anything claimed in the paper or a demo.

---

## QNA-001 — 2026-10-14 — Portable model registry, bacteria entry correction, router accuracy measured

**Commit:** uncommitted working tree on `LATEST_USHNIK` (base `492b20a`). Update this line with the
commit hash once it lands.

**Q1. Mechanism: what changed in how models are found and loaded?**
Registry entries now say `"base_model": "data:checkpoints/<route>/backbone"` and
`"artifact_uri": "data:checkpoints/<route>/head.pt"`.
`services/worker/app/inference/registry.py` expands the `data:` prefix against
`$SYNTHVEDA_DATA_ROOT`. Without that variable it walks up from the module to the first
`synthveda-data/` directory, and in Docker it falls back to `/data`. Values without the prefix
(Hugging Face ids) pass through unchanged. Before this, every entry hardcoded
`E:\synthveda-data\...`, so `_resolve_local` failed on every machine except the old Windows laptop
and all six routes ran stub inference.

**Q2. Rationale: why a `data:` prefix and not plain relative paths?**
`base_model` legitimately holds Hugging Face ids such as `zhihan1996/DNABERT-2-117M`, which look
identical to a relative path. The prefix makes the intent explicit, and an HF id can never be
mistaken for a local file.

**Q3. Blast radius: what else changed, and what breaks if it is wrong?**
- `models/registry/dnabert2_bacteria_v1.json` described an older run (test acc 0.8006, macro-F1
  0.8468, train 12,320) than the `head.pt` on disk. The file is a 4-class head whose
  `eval_report.json` and `metrics.json` give acc 0.842, macro-F1 0.8529, train 37,832. Its
  SHA-256 matched neither the registry checksum nor anything else on record. The entry now
  describes the weights that actually run. The other five checksums matched.
- If the data root resolves wrong, the loader returns `None` and the predictor falls back to stub
  mode. That is visible as `inference_mode: "stub"` on every result, not a silent wrong answer.

**Q4. Verification: what proves it works?**
- `run_inference` on 20 held-out test sequences per route: `inference_mode=model` on all six
  routes, on the RTX 3070. Predicted class matched the label for fish 20/20, plant 16/20,
  bacteria 17/20, animal 20/20, human 20/20, misc 19/20. A smoke test, not an evaluation.
- Full pipeline through the API and worker (upload `upl_593a3f5bae874205`, job
  `job_08439d04b5844a0c`): completed in about 1.1 s with real model ids on every result.
- Test suites: API 269 passed (including the new `tests/test_api_contract.py`), worker 142 passed.

**Q5. Defence: "your per-route models are 94–99% accurate, so the system works", right?**
No, and this is the most important number recorded today. The end-to-end run routed fish and
plant sequences to the wrong model. Measured on 300 held-out non-low-quality test sequences per
route, **the heuristic router picks the correct route for 24.1% (433/1,800)**: fish 0.3%,
plant 0.0%, animal 1.7%, human 11.0%, misc 54.0%, bacteria 77.3%. The per-route head metrics
hold only when routing is right, so any end-to-end claim built on them is overstated until
routing is fixed. A 10-second, untuned 6-mer hashed logistic classifier, trained on up to 4,000
sequences per route from the same `train.csv` files, reached **82.4%** on the same test set
(macro-F1 0.824; animal 0.714 and misc 0.753 are the weak classes). Not yet wired in: scheduled
for Day 4. The paper must not report per-route accuracy as system accuracy.

**Q6. What is still unverified?**
- The 82.4% has had no leakage check across routes (the existing dedup is per route) and no
  calibration.
- The Google-login round-trip in the browser was not exercised. The API was driven with a locally
  minted dev JWT.
