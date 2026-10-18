"""
Register a trained model with the API, and optionally promote it (B8).

This script no longer writes models/registry/*.json itself. It calls
POST /models/register and POST /models/{model_id}/promote, so the CLI and the
Admin page go through the same validation (artifact checksum under the data
root, required metrics), the same one-production-per-route rule, and the same
audit trail (MongoDB audit_logs + model_eval_metrics).

Auth: an admin JWT in $SYNTHVEDA_ADMIN_TOKEN (log in to the app as an admin and
copy localStorage.sv_access_token). API base URL: --api-url or $SYNTHVEDA_API_URL.

Usage (dry run: prints the request, touches nothing):
    python scripts/training/promote.py --model-id dnabert2_fish_v2 --route fish \\
        --artifact-uri data:checkpoints/fish/v2/head.pt \\
        --base-model data:checkpoints/fish/backbone \\
        --metrics ../synthveda-data/checkpoints/fish/v2/metrics.json \\
        --training-dataset-version tbatch_202610_fish_ab12cd34

    ... --approve             register it (status "candidate": stored, not served)
    ... --approve --promote   register, show the comparison with the model serving
                              the route now, ask for the model_id to confirm, promote
    --yes                     skip the typed confirmation (non-interactive use)
    --entry FILE              take fields from a registry-entry-shaped JSON; flags override

Registration never changes what the worker serves. Promotion does: the entry
becomes status "production" and any previous production entry on the route
becomes "staging".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DATA_URI_PREFIX = "data:"

# Old evaluate.py keys -> registry keys (finetune.py already writes registry keys).
_LEGACY_METRIC_KEYS = {"accuracy": "test_accuracy", "f1_macro": "test_macro_f1", "test_samples": "test_size"}
# metrics.json fields that describe the model, not its performance.
_NON_METRIC_KEYS = {"embedding_dim", "num_classes", "num_labels"}

_ENTRY_FIELDS = (
    "model_id", "route", "base_model", "artifact_uri", "checksum", "metrics", "label_set_version",
    "training_dataset_version", "label_set", "head_type", "embedding_dim", "thresholds",
    "trusted_remote_code", "created_at", "notes",
)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


def resolve_data_root() -> Path:
    env = os.environ.get("SYNTHVEDA_DATA_ROOT")
    if env:
        return Path(env)
    p = Path.cwd().resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "synthveda-data").is_dir():
            return candidate / "synthveda-data"
    raise SystemExit("cannot find the data root: set SYNTHVEDA_DATA_ROOT or pass --checksum")


def local_checksum(artifact_uri: str) -> str:
    if not artifact_uri.startswith(DATA_URI_PREFIX):
        raise SystemExit(f"--artifact-uri must be data:<relative path>, got {artifact_uri!r}")
    path = resolve_data_root() / artifact_uri[len(DATA_URI_PREFIX):]
    if not path.is_file():
        raise SystemExit(f"artifact not found: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_metrics(path: Path) -> dict:
    """Top-level numeric fields of a metrics.json / eval_report.json, registry-keyed."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in raw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or k in _NON_METRIC_KEYS:
            continue
        key = _LEGACY_METRIC_KEYS.get(k, k)
        out[key] = round(v, 4) if isinstance(v, float) and key != "temperature" else v
    return out


def build_register_body(args) -> dict:
    body: dict = {}
    if args.entry:
        entry = json.loads(Path(args.entry).read_text(encoding="utf-8"))
        body.update({k: entry[k] for k in _ENTRY_FIELDS if entry.get(k) is not None})
    for flag, key in (("model_id", "model_id"), ("route", "route"), ("base_model", "base_model"),
                      ("artifact_uri", "artifact_uri"), ("checksum", "checksum"),
                      ("label_set_version", "label_set_version"),
                      ("training_dataset_version", "training_dataset_version"),
                      ("created_at", "created_at"), ("notes", "notes")):
        value = getattr(args, flag)
        if value is not None:
            body[key] = value
    if args.label_set:
        body["label_set"] = [s.strip() for s in args.label_set.split(",") if s.strip()]
    if args.metrics:
        body["metrics"] = load_metrics(Path(args.metrics))
    body.setdefault("label_set_version", "v1")
    missing = [k for k in ("model_id", "route", "base_model", "artifact_uri", "metrics",
                           "training_dataset_version") if not body.get(k)]
    if missing:
        raise SystemExit(f"missing required field(s): {', '.join(missing)} (pass flags or --entry)")
    if not body.get("checksum"):
        body["checksum"] = local_checksum(body["artifact_uri"])
    return body


def api_call(api_url: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        api_url.rstrip("/") + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except Exception:
            detail = exc.reason
        raise ApiError(exc.code, str(detail)) from None


def format_plan(plan: dict) -> str:
    lines = [
        f"Promote {plan['model_id']} ({plan['from_status']}) to production on route {plan['route']}",
        f"Currently serving: {plan['current_model_id'] or 'nothing'}"
        + (f" ({plan['current_status']})" if plan.get("current_status") else ""),
    ]
    if plan["demoted_model_ids"]:
        lines.append(f"Will demote to staging: {', '.join(plan['demoted_model_ids'])}")
    lines.append(f"{'metric':<34}{'candidate':>12}{'current':>12}{'delta':>12}")

    def fmt(v):
        return "-" if v is None else (f"{v:+.4f}" if isinstance(v, float) else str(v))

    for row in plan["metric_deltas"]:
        cand = "-" if row["candidate"] is None else str(row["candidate"])
        cur = "-" if row["current"] is None else str(row["current"])
        lines.append(f"{row['metric']:<34}{cand:>12}{cur:>12}{fmt(row['delta']):>12}")
    for w in plan["warnings"]:
        lines.append(f"warning: {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Register (and optionally promote) a trained model via the API")
    ap.add_argument("--model-id", "--run-id", dest="model_id")
    ap.add_argument("--route")
    ap.add_argument("--base-model")
    ap.add_argument("--artifact-uri", help="data:<relative path> to head.pt / router.npz")
    ap.add_argument("--checksum", help="SHA-256 of the artifact (default: computed from the local data root)")
    ap.add_argument("--metrics", help="metrics.json / eval_report.json with test_accuracy, test_macro_f1, test_size")
    ap.add_argument("--training-dataset-version", help="frozen batch id or dataset version the model was trained on")
    ap.add_argument("--label-set-version")
    ap.add_argument("--label-set", help="comma-separated class names")
    ap.add_argument("--created-at", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--notes")
    ap.add_argument("--entry", help="registry-entry-shaped JSON to take fields from")
    ap.add_argument("--api-url", default=os.environ.get("SYNTHVEDA_API_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--approve", action="store_true", help="actually register (default: dry run)")
    ap.add_argument("--promote", action="store_true", help="after registering, promote to production")
    ap.add_argument("--promote-only", action="store_true", help="promote an already registered --model-id")
    ap.add_argument("--yes", action="store_true", help="skip the typed confirmation before promoting")
    args = ap.parse_args(argv)

    token = os.environ.get("SYNTHVEDA_ADMIN_TOKEN", "")
    try:
        if not args.promote_only:
            body = build_register_body(args)
            print(json.dumps(body, indent=2))
            if not args.approve:
                print("\n[DRY RUN] Nothing sent. Re-run with --approve to register.")
                return 0
            if not token:
                raise SystemExit("set SYNTHVEDA_ADMIN_TOKEN to an admin access token")
            reg = api_call(args.api_url, token, "POST", "/models/register", body)
            print(f"\n[REGISTERED] {reg['model']['model_id']} -> models/registry/{reg['registry_file']} "
                  f"(status candidate; route {reg['model']['route']} still served by {reg['serving_model_id']})")
            if not args.promote:
                return 0
            model_id = body["model_id"]
        else:
            if not args.model_id:
                raise SystemExit("--promote-only needs --model-id")
            if not token:
                raise SystemExit("set SYNTHVEDA_ADMIN_TOKEN to an admin access token")
            model_id = args.model_id

        plan = api_call(args.api_url, token, "POST", f"/models/{model_id}/promote", {"dry_run": True})
        print("\n" + format_plan(plan))
        if not args.yes:
            typed = input(f"\nType the model_id ({model_id}) to promote it, anything else to stop: ").strip()
            if typed != model_id:
                print("Not promoted. It stays registered as a candidate.")
                return 1
        done = api_call(args.api_url, token, "POST", f"/models/{model_id}/promote",
                        {"expected_current_model_id": plan["current_model_id"],
                         "notes": args.notes or "promoted with scripts/training/promote.py"})
        print(f"[PROMOTED] {model_id} now serves route {done['route']} (at {done['promoted_at']}). "
              "Commit the changed models/registry/*.json.")
        return 0
    except ApiError as exc:
        print(f"API refused: {exc}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"cannot reach the API at {args.api_url}: {exc.reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
