#!/usr/bin/env python3
"""Live terminal dashboard for Synth Veda work on gojo (read-only), in the style of the ISRO
watch_training.py and the Dizzy watch.py (~/dev/dizzy/watch.py = laptop ~/dev/sleep/gpu/watch.py).

    python3 scripts/watch.py            # refresh every 2 s; Ctrl+C to quit
    python3 scripts/watch.py --once     # print one frame (no alternate screen) and exit
    ssh gojo -t 'cd ~/dev/synth-veda && python3 scripts/watch.py'    # from the laptop

Standard library only, so any python3 runs it. Everything comes from files on disk, git and /proc,
so it can be closed and reopened at any time:
  - sprint: docs/ROADMAP_REAL_DATA.md (the 18-day table, task ids t-MMDD-n by position) and
    synthveda-data/logs/sprint_progress.json, a local mirror of the claude.ai tracker's done list
    (the tracker itself is not readable offline); git branch/head; worktrees with unmerged or
    uncommitted work; the newest QNA entry in docs/qna.md
  - training: every log with "progress epoch=E/N step=i/S elapsed=Xs rate=Rit/s" lines
    (training/finetune.py) under synthveda-data/logs/ or .claude/worktrees/*/.v2run/logs/, plus the
    stdout of any running finetune; "epoch E/N ... dev_loss=" and "TEST ..." lines for history
  - job logs: any other synthveda-data/logs/**/*.log written in the last 12 h, and
    "progress stage=X step=i/N" lines where a job prints them
  - models: models/registry/*.json (which entry each route serves, and candidates waiting for
    POST /models/{id}/promote), reference/CURRENT + its manifest, processed/build_report.json
  - data: synthveda-data/raw/<source>/ sizes, BLAST tarballs still downloading, BOLD (manual)
  - stack: API :8000, frontend :5173, Mongo :27017, Redis :6379, MinIO :9000 (TCP connect only)
  - processes / system: /proc, nvidia-smi

It never writes anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("SYNTHVEDA_DATA_ROOT") or HERE / "synthveda-data")
WORKTREES = HERE / ".claude" / "worktrees"
ROADMAP = HERE / "docs" / "ROADMAP_REAL_DATA.md"
PROGRESS = DATA / "logs" / "sprint_progress.json"
BASE_BRANCH = "LATEST_USHNIK"
DEADLINE = datetime(2026, 10, 31, 23, 59, tzinfo=timezone(timedelta(hours=5, minutes=30)))
ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")
W = 100     # inner width; reduced per frame to fit the terminal
DETAIL = 3  # 3 = everything; lowered per frame until the frame fits the terminal height
HISTORY_N = 6  # epoch rows for the running training job; reduced per frame to fit
C = {"cyan": "36", "dcyan": "2;36", "green": "32", "dgreen": "2;32", "blue": "34", "yellow": "33",
     "magenta": "35", "red": "31", "grey": "2;37", "white": "37", "bold": "1"}
PROG_RE = re.compile(r"progress epoch=(\d+)/(\d+) step=(\d+)/(\d+) elapsed=([\d.]+)s rate=([\d.]+)it/s")
EPOCH_RE = re.compile(r"^epoch (\d+)/(\d+)\s+train_loss=([\d.]+)\s+dev_loss=([\d.]+)\s+dev_acc=([\d.]+)\s+dev_f1=([\d.]+)")
TEST_RE = re.compile(r"TEST\s+loss=([\d.]+)\s+acc=([\d.]+)\s+macro_f1=([\d.]+)")
LOG_PROG_RE = re.compile(r"progress stage=(\S+) step=(\d+)/(\d+)(?: elapsed=([\d.]+)s)?")
TASK_ROW_RE = re.compile(r"^\| (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d+) (\w{3}) \| (\d+) \| ([^|]+) \| ([^|]+) \|")
CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
SPARK = "  ··░░██"          # ISRO-safe glyphs: Ubuntu Sans Mono lacks ▁-▇, the fallback font overlaps cells
LOG_MAX_AGE_S = 12 * 3600
JOBS = [  # (label, regex on the command line)
    ("head train", r"training\.finetune\b|training/finetune\.py"),
    ("head eval", r"training\.evaluate_checkpoint|evaluate_checkpoint\.py"),
    ("router train", r"training\.train_router|train_router\.py"),
    ("dataset", r"training\.build_dataset|build_dataset\.py"),
    ("reference db", r"training\.build_reference_db|build_reference_db\.py"),
    ("leakage", r"training\.check_leakage|check_leakage\.py"),
    ("ref lookup", r"eval_reference_lookup\.py|training\.eval_reference_lookup"),
    ("supplementary", r"fetch_supplementary\.py|training\.fetch_supplementary"),
    ("blastn", r"(^|/)blastn\s"),
    ("vsearch", r"(^|/)vsearch\s"),
    ("makeblastdb", r"(^|/)makeblastdb\s"),
    ("blastdbcmd", r"(^|/)blastdbcmd\s"),
    ("fetch", r"fetch_reference_data\.sh"),
    ("api", r"uvicorn\s+app\.main"),
    ("worker", r"services/worker.*app\.(main|worker)|python -m app\.worker"),
    ("frontend", r"node .*vite"),
    ("pytest", r"-m pytest|bin/pytest"),
    ("playwright", r"playwright test"),
]
SCRIPT_RE = re.compile(r"python[\d.]*\s+(?:-\S+\s+)*(\S+\.py)\b")
WRAPPER_RE = re.compile(r"(/usr)?(/bin/)?(ba)?sh -c |grep |pgrep |ssh |/usr/bin/time ")


def paint(t: str, c: str) -> str:
    return f"\033[{C[c]}m{t}\033[0m"


def row(t: str, c: str = "white") -> str:
    return paint("║", "dcyan") + paint(t[:W].ljust(W), c) + paint("║", "dcyan")


def rule(k: str = "mid") -> str:
    l, r = {"top": ("╔", "╗"), "mid": ("╠", "╣"), "bot": ("╚", "╝")}[k]
    return paint(l + "═" * W + r, "dcyan")


def title(t: str, sub: str = "") -> list[str]:
    return [row("  " + " ".join(t) + (f"   ::  {sub}" if sub else ""), "cyan"), rule()]


def bar(f: float, w: int = 30) -> str:
    f = min(max(f, 0.0), 1.0)
    return "█" * int(f * w) + "░" * (w - int(f * w))


def dur(s: float | None) -> str:
    if s is None or s < 0 or s != s:
        return "--"
    s = int(s)
    return f"{s // 3600}h {s // 60 % 60:02d}m {s % 60:02d}s"


def short(s: float | None) -> str:
    """Compact duration: 45s, 12m03s, 3h07m, 2d04h."""
    if s is None or s < 0 or s != s:
        return "--"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{s // 60 % 60:02d}m" if s < 86400 else f"{s // 86400}d{s // 3600 % 24:02d}h"


def human(n: float) -> str:  # decimal units
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1000
    return ""


def tail_lines(path: Path, nbytes: int = 200_000) -> list[str]:
    """Last lines of a log, splitting tqdm's \\r-separated updates into separate lines."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - nbytes))
            text = f.read().decode(errors="ignore")
    except OSError:
        return []
    return [l for l in re.split(r"[\r\n]", text.replace("\x00", "")) if l.strip()]


def rel(cmd: str) -> str:
    return (cmd.replace(str(HERE) + "/", "").replace("services/worker/.venv/bin/python", "py")
            .replace("services/api/.venv/bin/python", "py").replace(".venv/bin/python", "py"))


_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    """fn() at most every ttl seconds (git and du are too slow to run on every 2 s frame)."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = hit[1] if hit else None
    _cache[key] = (now, val)
    return val


def git(*args: str, cwd: Path = HERE) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10).stdout.strip()


# ---------------------------------------------------------------- processes
_cpu_prev: dict[int, tuple] = {}


class Procs:
    """One /proc scan per frame: command lines of everything, stat details only for jobs we show."""

    def __init__(self) -> None:
        self.cmd: dict[int, str] = {}
        me = os.getpid()
        for d in os.listdir("/proc"):
            if d.isdigit() and int(d) != me:
                try:
                    c = Path(f"/proc/{d}/cmdline").read_bytes()
                except OSError:
                    continue
                if c:
                    self.cmd[int(d)] = c.replace(b"\0", b" ").decode(errors="ignore").strip()
        self.uptime = float(Path("/proc/uptime").read_text().split()[0])

    def find(self, pattern: str) -> list[int]:
        rx = re.compile(pattern)
        return sorted(p for p, c in self.cmd.items() if rx.search(c) and not WRAPPER_RE.match(c))

    def info(self, pid: int) -> dict | None:
        try:
            st = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return None
        f = st[st.rindex(")") + 2:].split()
        cpu_s = (int(f[11]) + int(f[12])) / CLK
        now = time.time()
        prev = _cpu_prev.get(pid)
        if prev and now - prev[1] < 1.0:
            pct = prev[2]
        else:
            pct = (cpu_s - prev[0]) / (now - prev[1]) * 100 if prev else None
            _cpu_prev[pid] = (cpu_s, now, pct)
        return {"state": f[0], "age": self.uptime - int(f[19]) / CLK, "rss": int(f[21]) * PAGE, "cpu": pct,
                "ppid": int(f[1])}

    def stdout(self, pid: int) -> Path | None:
        try:
            p = os.readlink(f"/proc/{pid}/fd/1")
        except OSError:
            return None
        return Path(p) if p.startswith("/") and p.endswith(".log") else None


def sv_jobs(procs: Procs) -> list[tuple[str, int]]:
    """(label, pid) of everything Synth Veda is running. Known jobs first; then any python script started
    in or from the repo, labelled by its file name, and any other CUDA process, so nothing is invisible.
    A job's own worker processes (DataLoader workers share the parent's command line) are folded in."""
    out, seen = [], set()
    for label, pat in JOBS:
        for pid in procs.find(pat):
            i = procs.info(pid)
            if i and i["ppid"] in seen:
                seen.add(pid)
                continue
            out.append((label, pid))
            seen.add(pid)
    for pid, cmd in sorted(procs.cmd.items()):
        if pid in seen or WRAPPER_RE.match(cmd):
            continue
        m = SCRIPT_RE.search(cmd)
        if not m or Path(m.group(1)).name == "watch.py":
            continue
        try:
            cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            cwd = Path("/")
        if cwd == HERE or HERE in cwd.parents or str(HERE) in cmd:
            out.append((Path(m.group(1)).stem, pid))
            seen.add(pid)
    for pid in sorted(_gpu_apps):
        if pid not in seen and pid in procs.cmd:
            out.append(("GPU: " + Path(procs.cmd[pid].split()[0]).name[:8], pid))
    return out


# ---------------------------------------------------------------- sprint
def roadmap_days() -> list[dict]:
    """The 18-day table: day, date, focus, task texts, and task ids t-MMDD-n (n = position in the row)."""
    months = {"Oct": 10, "Nov": 11, "Sep": 9}
    days = []
    for line in ROADMAP.read_text(errors="ignore").splitlines():
        m = TASK_ROW_RE.match(line)
        if not m:
            continue
        dd, mon, n, focus, tasks = int(m[1]), m[2], int(m[3]), m[4].strip(), m[5].strip()
        texts = [t.strip() for t in tasks.split(" · ")]
        days.append({"day": n, "date": (months.get(mon, 10), dd), "focus": focus,
                     "tasks": [(f"t-{months.get(mon, 10):02d}{dd:02d}-{i + 1}", t) for i, t in enumerate(texts)]})
    return days


def done_ids() -> tuple[set[str], str]:
    try:
        d = json.loads(PROGRESS.read_text())
        return set(d.get("done", [])), d.get("updated", "")
    except (OSError, ValueError):
        return set(), ""


def in_flight() -> list[tuple[str, int, int]]:
    """(branch, commits ahead of the base branch, uncommitted files) for worktrees with unmerged work."""
    out = []
    porcelain = git("worktree", "list", "--porcelain")
    for block in porcelain.split("\n\n"):
        path = re.search(r"^worktree (.+)$", block, re.M)
        br = re.search(r"^branch refs/heads/(.+)$", block, re.M)
        if not path or not br or Path(path[1]) == HERE:
            continue
        ahead = git("rev-list", "--count", f"{BASE_BRANCH}..{br[1]}")
        dirty = [l for l in git("status", "--porcelain", cwd=Path(path[1])).splitlines()
                 if "node_modules" not in l]
        a = int(ahead) if ahead.isdigit() else 0
        if a or dirty:
            out.append((br[1], a, len(dirty)))
    return out


def sprint_rows(procs: Procs, tick: bool) -> list[str]:
    days = cached("roadmap", 60, roadmap_days) or []
    done, updated = done_ids()
    total = sum(len(d["tasks"]) for d in days)
    n_done = sum(1 for d in days for tid, _ in d["tasks"] if tid in done)
    now = datetime.now(DEADLINE.tzinfo)
    left = (DEADLINE - now).total_seconds()
    out = title("SPRINT", f"v1 real data · deadline Sat 31 Oct 23:59 IST · {short(left)} left")
    if not days:
        return out + [row(f"  roadmap table not found in {ROADMAP.relative_to(HERE)}", "red")]
    frac = n_done / total if total else 0
    out.append(row(f"  TASKS [{bar(frac, 44)}] {n_done}/{total}  {frac * 100:5.1f}%"
                   f"   tracker mirror {updated[:16] or 'missing'}", "green"))
    cal_day = next((d["day"] for d in days if d["date"] == (now.month, now.day)), None)
    # Pace ignores YOU: tasks (only the user can do them; BOLD would otherwise pin the sprint to day 1).
    first_open = next((d["day"] for d in days if any(t not in done and not txt.startswith("YOU")
                                                       for t, txt in d["tasks"])), None)
    yours = sum(1 for d in days for t, txt in d["tasks"] if t not in done and txt.startswith("YOU"))
    pace = f"calendar day {cal_day}" if cal_day else "outside the sprint calendar"
    if cal_day and first_open:
        gap = cal_day - first_open
        pace += f" · first open day {first_open}{f' (not counting {yours} of yours)' if yours else ''} · " \
            + (f"{-gap} day(s) ahead" if gap < 0 else
                                                          "on schedule" if gap == 0 else f"{gap} day(s) behind")
    out.append(row(f"  {pace}", "green" if cal_day and first_open and first_open >= cal_day else "yellow"))
    cells = []
    for d in days:
        k = sum(1 for t, _ in d["tasks"] if t in done)
        cells.append(f"D{d['day']} {k}/{len(d['tasks'])}")
    line = "  "
    for c in cells:  # wrap the 18 day cells over as many rows as the width needs
        if len(line) + len(c) + 2 > W:
            out.append(row(line, "dgreen"))
            line = "  "
        line += c + "  "
    out.append(row(line.rstrip(), "dgreen"))
    if DETAIL >= 2:
        nxt = [(d["day"], t, txt) for d in days for t, txt in d["tasks"] if t not in done][:5]
        for day, tid, txt in nxt:
            txt = re.sub(r"^(ALL|BE|FE|ML|YOU): ", r"\1 ", txt)
            out.append(row(f"  · D{day:<2} {tid}  {txt}", "yellow" if txt.startswith("YOU") else "white"))
    head = cached("git_head", 20, lambda: (git("rev-parse", "--abbrev-ref", "HEAD"), git("log", "-1", "--format=%h %s"),
                                           len([l for l in git("status", "--porcelain").splitlines()
                                                if not l.startswith("??")])))
    if head:
        br, last, dirty = head
        out.append(row(f"  git {br} @ {last[:W - 30]}{f'   {dirty} uncommitted' if dirty else ''}",
                       "yellow" if dirty else "blue"))
    qna = cached("qna", 30, lambda: re.findall(r"^## (QNA-\d+) — (\d{4}-\d\d-\d\d) — (.+)$",
                                               (HERE / "docs" / "qna.md").read_text(errors="ignore"), re.M))
    if qna:
        q = qna[-1]
        out.append(row(f"  transcript {q[0]} ({q[1]}): {q[2]}", "blue"))
    flights = cached("in_flight", 30, in_flight) or []
    for br, ahead, dirty in flights[: 6 if DETAIL >= 2 else 2]:
        state = ", ".join(s for s in (f"{ahead} commit(s) not merged" if ahead else "",
                                      f"{dirty} uncommitted" if dirty else "") if s)
        out.append(row(f"  ⇢ {br:<34} {state}", "magenta"))
    return out


# ---------------------------------------------------------------- training
def training_logs(procs: Procs) -> list[Path]:
    """Logs with finetune progress lines: running jobs' stdout first, then recent ones on disk."""
    found: dict[Path, None] = {}
    for pid in procs.find(JOBS[0][1]):
        if (p := procs.stdout(pid)) is not None:
            found[p] = None
    now = time.time()
    globs = list((DATA / "logs").glob("**/*.log")) + list(WORKTREES.glob("*/.v2run/logs/*.log")) \
        + list(WORKTREES.glob("*/logs/*.log"))
    for p in sorted(globs, key=lambda p: -p.stat().st_mtime):
        if now - p.stat().st_mtime < LOG_MAX_AGE_S and "progress epoch=" in "".join(tail_lines(p, 20_000)):
            found[p] = None
    return list(found)


def parse_train(log: Path, procs: Procs) -> dict:
    st = {"log": log, "epochs": [], "prog": None, "test": None, "done": False, "ep_sec": {}, "error": None}
    for line in tail_lines(log, 2_000_000):
        if m := PROG_RE.search(line):
            st["prog"] = [int(m[1]), int(m[2]), int(m[3]), int(m[4]), float(m[5]), float(m[6])]
            st["ep_sec"][int(m[1])] = float(m[5])
        elif m := EPOCH_RE.match(line.strip()):
            st["epochs"].append({"ep": int(m[1]), "of": int(m[2]), "train": float(m[3]), "dev_loss": float(m[4]),
                                 "acc": float(m[5]), "f1": float(m[6])})
        elif m := TEST_RE.search(line):
            st["test"] = (float(m[1]), float(m[2]), float(m[3]))
        elif line.strip() == "done.":
            st["done"] = True
        elif re.search(r"\b(Error|Traceback|CUDA out of memory|Killed)\b", line):
            st["error"] = line.strip()
    route = re.sub(r"^train_", "", log.stem)
    st["route"] = route
    st["pids"] = [p for p in procs.find(JOBS[0][1]) if procs.stdout(p) == log
                  or (f"--route {route} " in procs.cmd[p] + " " and procs.stdout(p) is None)]
    st["mtime"] = log.stat().st_mtime
    return st


def train_rows(procs: Procs, tick: bool) -> list[str]:
    out = title("TRAINING", "route heads (finetune.py progress lines), newest first")
    logs = training_logs(procs)
    if not logs:
        return out + [row("  no training log in the last 12 h", "grey")]
    blink = "◉" if tick else "○"
    states = [parse_train(p, procs) for p in logs]
    states.sort(key=lambda s: (not s["pids"], -s["mtime"]))
    for idx, s in enumerate(states[: 8 if DETAIL >= 2 else 3]):
        prog, ago = s["prog"], short(time.time() - s["mtime"])
        where = "worktree " + s["log"].parts[-4][-10:] if WORKTREES in s["log"].parents else str(s["log"].parent.name)
        if s["done"] or (s["test"] and not s["pids"]):
            t = s["test"]
            best = min(s["epochs"], key=lambda e: e["dev_loss"]) if s["epochs"] else None
            out.append(row(f"  ✓ {s['route']:<30} TEST acc={t[1]:.4f} macro_f1={t[2]:.4f}" if t else
                           f"  ✓ {s['route']:<30} finished", "dgreen"))
            if best and DETAIL >= 2:
                out.append(row(f"      best dev_loss {best['dev_loss']:.4f} at epoch {best['ep']}/{best['of']}"
                               f"   train {dur(sum(s['ep_sec'].values()))}   ({ago} ago, {where})", "dgreen"))
            continue
        if not prog:
            out.append(row(f"  · {s['route']:<30} {'starting' if s['pids'] else 'no progress lines'}  ({ago} ago)",
                           "yellow" if s["pids"] else "grey"))
            continue
        ep, of, step, steps, el, rate = prog
        running = bool(s["pids"])
        secs = [s["ep_sec"][e] for e in sorted(s["ep_sec"]) if e < ep]
        per_ep = (sum(secs[-3:]) / len(secs[-3:])) if secs else (steps / rate if rate else None)
        f_ep = step / steps if steps else 0
        f_tot = ((ep - 1) + f_ep) / of if of else 0
        ep_eta = (steps - step) / rate if rate and running else None
        tot_eta = (ep_eta or 0) + (of - ep) * per_ep if per_ep and running else None
        evaluating = running and step >= steps and time.time() - s["mtime"] > 3
        col = "blue" if running else "red"
        if idx == 0 and running:  # the job on the GPU gets the ISRO layout
            out.append(row(f"  {blink} {s['route']}   RUNNING   pid {s['pids'][0]}   {where}", "cyan"))
            out.append(row(f"  TOTAL [{bar(f_tot, 44)}] {f_tot * 100:6.2f}%   elapsed {dur(sum(secs) + el)}"
                           f"   ETA {dur(tot_eta)}", "green"))
            out.append(row(f"  EPOCH {ep}/{of} [{bar(f_ep, 36)}] {f_ep * 100:6.2f}%   step {step}/{steps}"
                           f"  {rate:.2f} it/s   ETA {dur(ep_eta)}", "blue"))
            if evaluating:
                out.append(row(f"  {blink} dev evaluation after epoch {ep}…", "yellow"))
            hist = s["epochs"][-HISTORY_N:] if HISTORY_N else []
            best = min((e["dev_loss"] for e in s["epochs"]), default=None)
            for e in hist:
                mark = "  [BEST]" if e["dev_loss"] == best else ""
                out.append(row(f"  [OK] epoch {e['ep']}/{e['of']}  train_loss={e['train']:.4f}  dev_loss={e['dev_loss']:.4f}"
                               f"  dev_acc={e['acc']:.4f}  dev_f1={e['f1']:.4f}  {short(s['ep_sec'].get(e['ep']))}{mark}",
                               "green" if mark else "dgreen"))
            continue
        out.append(row(f"  {blink if running else '○'} {s['route'][:22]:<22} ep {ep}/{of} [{bar(f_tot, 26)}] "
                       f"{f_tot * 100:5.1f}%  {'ETA ' + dur(tot_eta) if running else 'stopped ' + ago + ' ago'}", col))
        if s["error"] and not running:
            out.append(row(f"      ✗ {s['error'][:W - 10]}", "red"))
    for chain in {s["log"].parent / "chain.log" for s in states}:
        if chain.exists() and DETAIL >= 2:
            last = tail_lines(chain, 2000)[-1:]
            out.append(row(f"  chain: {last[0][:W - 12] if last else '(empty)'}", "grey"))
    return out


# ---------------------------------------------------------------- other job logs
def logs_rows(procs: Procs, tick: bool) -> list[str]:
    """synthveda-data/logs/**/*.log that are not training logs: the last progress line, else the last line."""
    out = title("JOB LOGS", "synthveda-data/logs, last 12 h")
    now = time.time()
    logs = sorted((p for p in (DATA / "logs").glob("**/*.log") if now - p.stat().st_mtime < LOG_MAX_AGE_S
                   and "progress epoch=" not in "".join(tail_lines(p, 20_000))), key=lambda p: -p.stat().st_mtime)
    for log in logs[: 5 if DETAIL >= 2 else 2]:
        lines = tail_lines(log, 100_000)
        pids = procs.find(rf"\b{re.escape(log.stem)}\.py") or [p for p in procs.cmd if procs.stdout(p) == log]
        name = str(log.relative_to(DATA / "logs"))
        ago = short(now - log.stat().st_mtime)
        p = [m for l in lines if (m := LOG_PROG_RE.search(l))]
        if p:
            stage, i, n = p[-1][1], int(p[-1][2]), int(p[-1][3])
            out.append(row(f"  {'◉' if pids and tick else '○'} {name[:26]:<26} {stage[:8]:<8} "
                           f"[{bar(i / n if n else 0, 26)}] {i}/{n}  ({ago} ago)", "blue" if pids else "grey"))
        else:
            last = lines[-1].strip() if lines else "(empty)"
            out.append(row(f"  {'◉' if pids and tick else '·'} {name[:26]:<26} {last[:W - 44]}  ({ago} ago)",
                           "yellow" if pids else "grey"))
    if not logs:
        out.append(row("  no other job logs in the last 12 h", "grey"))
    return out


# ---------------------------------------------------------------- models
STATUS_RANK = {"production": 3, "staging": 2, "experimental": 1}


def registry() -> list[dict]:
    out = []
    for p in sorted((HERE / "models" / "registry").glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            out.append({"model_id": p.stem, "route": "?", "status": "unreadable"})
    return out


def models_rows(procs: Procs, tick: bool) -> list[str]:
    out = title("MODELS", "models/registry · what each route serves (best_available) and what waits for promotion")
    reg = cached("registry", 10, registry) or []
    for route in ROUTES + ("router",):
        entries = [e for e in reg if e.get("route") == route]
        served = max((e for e in entries if e.get("status") in STATUS_RANK),
                     key=lambda e: (STATUS_RANK[e["status"]], e.get("created_at", "")), default=None)
        cands = [e for e in entries if e.get("status") == "candidate"]
        m = (served or {}).get("metrics", {})
        acc = m.get("test_accuracy") or m.get("test_acc") or m.get("accuracy")
        s = f"{served['model_id']} [{served['status']}]" if served else "nothing servable"
        line = f"  {route:<29} {s:<38} {'acc ' + format(acc, '.4f') if isinstance(acc, (int, float)) else ''}"
        out.append(row(line, "white" if served else "red"))
        for c in cands:
            cm = c.get("metrics", {})
            cacc = cm.get("test_accuracy") or cm.get("test_acc")
            out.append(row(f"      ↑ candidate {c['model_id']:<30} {'acc ' + format(cacc, '.4f') if isinstance(cacc, (int, float)) else ''}"
                           "   promote: POST /models/{id}/promote", "yellow"))
    ref = cached("refdb", 30, _refdb)
    if ref:
        out.append(row(f"  reference DB {ref}", "blue"))
    build = cached("build", 30, _build_report)
    if build:
        out.append(row(f"  processed/ {build}", "blue"))
    return out


def _refdb() -> str:
    cur = (DATA / "reference" / "CURRENT").read_text().strip()
    m = json.loads((DATA / "reference" / cur / "manifest.json").read_text())
    seqs = sum(r.get("sequences", 0) for r in m.get("routes", {}).values())
    return f"{cur} (CURRENT) built {m.get('created', '?')[:16]} · {seqs:,} sequences · " \
           f"held-out excluded {m.get('heldout_exclusion', {}).get('unique_sequences', '?')}"


def _build_report() -> str:
    b = json.loads((DATA / "processed" / "build_report.json").read_text())
    n = sum(r.get("total", 0) for r in b.get("routes", {}).values())
    skipped = ", ".join(sorted(b.get("skipped", {}) if isinstance(b.get("skipped"), dict) else b.get("skipped") or []))
    return f"built {str(b.get('built_at', '?'))[:16]} · {n:,} rows" + (f" · skipped: {skipped}" if skipped else "")


# ---------------------------------------------------------------- data
def _sizes() -> dict[str, int]:
    out = {}
    for d in sorted((DATA / "raw").iterdir()):
        if d.is_dir():
            r = subprocess.run(["du", "-sb", str(d)], capture_output=True, text=True, timeout=60).stdout
            out[d.name] = int(r.split()[0]) if r else 0
    return out


_size_thread: threading.Thread | None = None


def data_rows(procs: Procs, tick: bool) -> list[str]:
    global _size_thread
    out = title("DATA", "synthveda-data/raw")
    hit = _cache.get("raw_sizes")
    if (not hit or time.time() - hit[0] > 300) and (_size_thread is None or not _size_thread.is_alive()):
        # du over ~100 GB takes seconds: refresh in the background, show the last result meanwhile
        _size_thread = threading.Thread(target=lambda: _cache.__setitem__("raw_sizes", (time.time(), _sizes())),
                                        daemon=True, name="du")
        _size_thread.start()
    sizes = hit[1] if hit else {}
    cells = []
    for name in sorted({d.name for d in (DATA / "raw").iterdir() if d.is_dir()} if (DATA / "raw").exists() else []):
        n = sizes.get(name)
        if name == "bold" and not any((DATA / "raw" / "bold").glob("BOLD_Public*.parquet")):
            cells.append(("bold", "manual (you): needs a BOLD login", "yellow"))
        else:
            cells.append((name, human(n) if n is not None else "…", "dgreen"))
    for name, txt, col in cells:
        out.append(row(f"  {'✓' if col == 'dgreen' else '!'} {name:<16} {txt}", col))
    blast = DATA / "raw" / "ncbi_blastdb"
    partial = sorted(blast.glob("*.tar.gz")) if blast.exists() else []
    fetching = procs.find(r"fetch_reference_data\.sh|wget .*ncbi|curl .*ncbi")
    for p in partial[:4]:
        out.append(row(f"  {'◉' if fetching and tick else '○'} {p.name:<36} {human(p.stat().st_size):>10}  "
                       f"{'downloading' if fetching else 'not being fetched (rerun scripts/fetch_reference_data.sh --all)'}",
                       "yellow" if fetching else "grey"))
    if not partial:
        out.append(row(f"  BLAST DBs: {len(list((blast / 'extracted').iterdir())) if (blast / 'extracted').exists() else 0}"
                       " extracted, no tarballs pending", "dgreen"))
    return out


# ---------------------------------------------------------------- stack
STACK = [("API", 8000), ("frontend", 5173), ("Mongo", 27017), ("Redis", 6379), ("MinIO", 9000)]


def _port_up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def stack_rows(procs: Procs, tick: bool) -> list[str]:
    out = title("STACK", "local services (TCP connect only)")
    cells = [f"{'●' if _port_up(p) else '○'} {n} :{p}" for n, p in STACK]
    out.append(row("  " + "   ".join(cells), "white"))
    return out


# ---------------------------------------------------------------- processes
def proc_rows(procs: Procs, tick: bool) -> list[str]:
    out = title("PROCESSES")
    out.append(row(f"    {'job':<13} {'pid':>7}  st  {'up':>7}  {'cpu':>5}  {'rss':>8}  {'vram':>8}  command", "grey"))
    n = 0
    for label, pid in sv_jobs(procs):
        i = procs.info(pid)
        if not i:
            continue
        n += 1
        cpu = f"{i['cpu']:.0f}%" if i["cpu"] is not None else "--"
        vram = f"{_gpu_apps[pid]} MiB" if pid in _gpu_apps else ""
        busy = i["state"] == "R" or (i["cpu"] or 0) > 5
        mark = ("◉" if tick else "○") if busy else ("■" if i["state"] == "T" else "·")
        out.append(row(f"  {mark} {label:<13} {pid:>7}  {i['state']:<2}  {short(i['age']):>7}  {cpu:>5}  "
                       f"{human(i['rss']):>8}  {vram:>8}  {rel(procs.cmd[pid])}",
                       "red" if i["state"] in "TZ" else "yellow" if busy else "white"))
    if not n:
        out.append(row("  no Synth Veda jobs running", "grey"))
    return out


# ---------------------------------------------------------------- system
_prev: dict[str, tuple] = {}
_util_hist: deque = deque(maxlen=30)
_gpu_apps: dict[int, int] = {}   # pid -> MiB, refreshed by gpu_query() each frame


def _rate(key: str, value: float) -> float:
    """Per-second rate since the last sample >= 1 s ago (a frame may be built several times while fitting)."""
    now = time.time()
    p = _prev.get(key)
    if p and now - p[0] < 1.0:
        return p[2]
    r = (value - p[1]) / (now - p[0]) if p else 0.0
    _prev[key] = (now, value, r)
    return r


def _disk_dev() -> str | None:
    try:
        st = os.stat(HERE)
        return Path(f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}/uevent").read_text() \
            .split("DEVNAME=")[1].split()[0]
    except (OSError, IndexError):
        return None


DISK_DEV = _disk_dev()


def gpu_query() -> list[str] | None:
    global _gpu_apps
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
                            "power.draw,power.limit,fan.speed,clocks.sm", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5).stdout.strip().split(", ")
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=5).stdout
        _gpu_apps = {int(a.split(",")[0]): int(a.split(",")[1]) for a in apps.strip().splitlines() if "," in a}
        return g if len(g) == 9 else None
    except Exception:
        _gpu_apps = {}
        return None


def sys_rows(procs: Procs) -> list[str]:
    out = title("SYSTEM")
    mem = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines()}
    total, avail = mem["MemTotal"] / 1024, mem["MemAvailable"] / 1024
    swap_used = (mem["SwapTotal"] - mem["SwapFree"]) / 1024
    ram_color = "red" if avail < 1536 else "yellow" if avail < 3072 else "green"
    out.append(row(f"  RAM  [{bar(1 - avail / total, 30)}] available {avail / 1024:.1f} GB of {total / 1024:.1f} GB"
                   f"   swap used {swap_used / 1024:.1f} GB", ram_color))
    cpu = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    busy_r, all_r = _rate("cpu_busy", sum(cpu) - cpu[3] - cpu[4]), _rate("cpu_all", sum(cpu))
    cpu_f = busy_r / all_r if all_r else 0
    load = " ".join(Path("/proc/loadavg").read_text().split()[:3])
    out.append(row(f"  CPU  [{bar(cpu_f, 30)}] {cpu_f * 100:5.1f}% of {os.cpu_count()} threads   load {load}",
                   "red" if cpu_f > 0.9 else "yellow" if cpu_f > 0.6 else "green"))
    g = gpu_query()
    if g:
        name, util, mu, mt, temp, pw, pl, fan, clk = g
        u, used, tot, t = int(util), int(mu), int(mt), int(temp)
        _util_hist.append(u)
        spark = "".join(SPARK[min(7, x * 8 // 101)] for x in _util_hist)
        out.append(row(f"  GPU  [{bar(u / 100, 30)}] util {u:>3}%  last {len(_util_hist) * 2}s {spark}", "blue"))
        out.append(row(f"  VRAM [{bar(used / tot, 30)}] {used / 1024:.1f}/{tot / 1024:.1f} GB   {t}°C  "
                       f"{float(pw):.0f}/{float(pl):.0f} W  fan {fan}%  SM {clk} MHz",
                       "red" if t >= 83 or used / tot > 0.95 else "yellow" if t >= 75 or used / tot > 0.85 else "blue"))
        if not _gpu_apps:
            out.append(row(f"       {name}: no compute processes", "grey"))
        for pid, mib in sorted(_gpu_apps.items()):
            out.append(row(f"       → pid {pid:>7}  {mib:>5} MiB  {rel(procs.cmd.get(pid, '?'))}", "yellow"))
    else:
        out.append(row("  GPU  nvidia-smi unavailable", "red"))
    du = shutil.disk_usage(HERE)
    free_gb = du.free / 1e9
    io = ""
    if DISK_DEV:
        for l in Path("/proc/diskstats").read_text().splitlines():
            f = l.split()
            if f[2] == DISK_DEV:
                io = f"   {DISK_DEV} write {human(_rate('dw', int(f[9]) * 512))}/s read {human(_rate('dr', int(f[5]) * 512))}/s"
    out.append(row(f"  DISK [{bar(1 - du.free / du.total, 30)}] free {free_gb:.0f} GB of {du.total / 1e9:.0f} GB{io}",
                   "red" if free_gb < 20 else "yellow" if free_gb < 60 else "green"))
    rx = tx = 0
    for l in Path("/proc/net/dev").read_text().splitlines()[2:]:
        iface, d = l.split(":", 1)
        if not iface.strip().startswith(("lo", "docker", "veth", "br-", "tailscale")):
            rx, tx = rx + int(d.split()[0]), tx + int(d.split()[8])
    out.append(row(f"  NET ↓ {human(_rate('rx', rx))}/s   ↑ {human(_rate('tx', tx))}/s", "magenta"))
    return out


# ---------------------------------------------------------------- frame
_pmon: dict[int, int] = {}                    # pid -> GPU SM % (nvidia-smi pmon, background thread)
_cpu_tot: dict[str, tuple] = {}


def _pmon_loop() -> None:
    while True:
        try:
            out = subprocess.run(["nvidia-smi", "pmon", "-c", "1", "-s", "u"], capture_output=True,
                                 text=True, timeout=10).stdout
            d = {}
            for line in out.splitlines():
                f = line.split()
                if len(f) > 3 and f[1].isdigit():
                    d[int(f[1])] = int(f[3]) if f[3].isdigit() else 0
            _pmon.clear(); _pmon.update(d)
        except Exception:
            pass
        time.sleep(2)


def _machine_cpu() -> float | None:
    """Whole-machine CPU busy % since the last frame, from /proc/stat."""
    f = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    idle, total = f[3] + f[4], sum(f)
    prev = _cpu_tot.get("all")
    _cpu_tot["all"] = (idle, total)
    if not prev or total == prev[1]:
        return None
    return 100 * (1 - (idle - prev[0]) / (total - prev[1]))


def _job_step(label: str, cmd: str, procs: Procs, pid: int) -> str:
    """Plain words for what a job is doing right now."""
    route = re.search(r"--route (\S+)", cmd)
    if label == "head train":
        log = procs.stdout(pid)
        p = [m for l in tail_lines(log, 4000) if (m := PROG_RE.search(l))] if log else []
        where = f": epoch {p[-1][1]}/{p[-1][2]}, step {p[-1][3]}/{p[-1][4]}" if p else ""
        return f"fine-tuning the {route[1] if route else '?'} head (DNABERT-2 on the GPU){where}"
    if label == "head eval":
        return f"scoring the {route[1] if route else '?'} head on a test split (GPU)"
    if label == "router train":
        return "training the k-mer router (CPU, scikit-learn)"
    if label == "dataset":
        return "rebuilding processed/ from the raw sources (CPU, reads BLAST DBs)"
    if label == "reference db":
        return "building the per-route reference DB (FASTA + BLAST/vsearch indexes)"
    if label == "leakage":
        return "checking processed/ for cross-split duplicates"
    if label == "ref lookup":
        return "evaluating the reference lookup on held-out rows (BLAST)"
    if label in ("blastn", "vsearch", "makeblastdb", "blastdbcmd"):
        db = re.search(r"-db (\S+)|--db (\S+)", cmd)
        return f"{label} on {Path((db[1] or db[2]) if db else '?').parent.name or '?'}"
    if label == "fetch":
        return "downloading reference data (NCBI BLAST DBs and friends)"
    if label == "api":
        return "FastAPI on :8000"
    if label == "worker":
        return "inference worker"
    if label == "frontend":
        return "Vite dev server"
    if label == "pytest":
        return "running tests"
    if label == "playwright":
        return "running the e2e suite"
    return rel(cmd)[:60]


def now_rows(procs: Procs, tick: bool) -> list[str]:
    """What is running right now and where the CPU, RAM and GPU go: one plain line per active job,
    then everything else on the machine, so the columns add up to the totals."""
    ncpu = os.cpu_count() or 1
    out = title("NOW RUNNING", "what each job is doing and what it uses")
    out.append(row(f"    {'job':<13} {f'CPU (of {ncpu})':>11} {'RAM':>9} {'GPU use':>8} {'GPU mem':>9}   doing", "grey"))
    jobs_cpu = jobs_rss = jobs_vram = jobs_gpu = 0.0
    n = 0
    for label, pid in sv_jobs(procs):
        i = procs.info(pid)
        if not i:
            continue
        kids = [p for p in procs.cmd if p != pid and (k := procs.info(p)) and k["ppid"] == pid]
        rss = i["rss"] + sum(procs.info(k)["rss"] for k in kids if procs.info(k))
        n += 1
        cpu = ((i["cpu"] or 0) + sum((procs.info(k) or {}).get("cpu") or 0 for k in kids)) / ncpu
        vram, sm = _gpu_apps.get(pid, 0), _pmon.get(pid, 0)
        jobs_cpu += cpu; jobs_rss += rss; jobs_vram += vram; jobs_gpu += sm
        out.append(row(f"  {'◉' if tick else '○'} {label:<13} {cpu:>10.0f}% {human(rss):>9} {sm:>7}% {vram:>6} MiB   "
                       f"{_job_step(label, procs.cmd[pid], procs, pid)}", "yellow"))
    g = gpu_query()
    if not n:
        busy = bool(g) and int(g[1]) >= 20
        out.append(row("  nothing from Synth Veda is running" + (f", but the GPU is {g[1]}% busy: see PROCESSES"
                       if busy else ": CPU and GPU are free"), "yellow" if busy else "green"))
    mcpu = _machine_cpu()
    mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in Path("/proc/meminfo").read_text().splitlines()}
    used = mem["MemTotal"] - mem["MemAvailable"]
    gutil, gmem = (int(g[1]), int(g[2])) if g else (0, 0)
    gtot = int(g[3]) if g else 0
    out.append(row(f"  · {'other':<13} {max(0.0, (mcpu or 0) - jobs_cpu):>10.0f}% {human(max(0, used - jobs_rss)):>9} "
                   f"{max(0, gutil - jobs_gpu):>7.0f}% {max(0, gmem - jobs_vram):>6.0f} MiB   "
                   "everything else: desktop, system, this dashboard", "white"))
    out.append(row(f"  = {'TOTAL':<13}{(mcpu or 0):>10.0f}% {human(used):>9} {gutil:>7}% {gmem:>6} MiB   "
                   f"of {ncpu} CPU threads · {human(mem['MemTotal'])} RAM · {gtot} MiB GPU memory", "cyan"))
    return out


def build_frame(tick: bool) -> list[str]:
    procs = Procs()
    out = [rule("top"), row(f"  {'◉' if tick else '○'} S Y N T H   V E D A  on {socket.gethostname()}   ::   "
                            f"~/dev/synth-veda   ::   {time.strftime('%a %d %b  %H:%M:%S')}", "bold"), rule()]
    sysr = sys_rows(procs)  # first: it refreshes the GPU pid list used by NOW RUNNING and PROCESSES
    out += now_rows(procs, tick) + [rule()]
    out += sprint_rows(procs, tick) + [rule()]
    out += train_rows(procs, tick) + [rule()]
    if DETAIL >= 1:
        out += models_rows(procs, tick) + [rule()]
    if DETAIL >= 2:
        out += logs_rows(procs, tick) + [rule()]
        out += data_rows(procs, tick) + [rule()]
    out += stack_rows(procs, tick) + [rule()]
    if DETAIL >= 3:
        out += proc_rows(procs, tick) + [rule()]
    out += sysr + [rule("bot")]
    out.append(paint(f"  {time.strftime('%H:%M:%S')}   Ctrl+C to exit (read-only; nothing is stopped)", "grey"))
    return out


def fit_frame(tick: bool) -> list[str]:
    """Like ISRO: shrink W to the terminal, then fewer history rows, then less detail, then cut."""
    global W, DETAIL, HISTORY_N
    cols, rows_ = shutil.get_terminal_size((110, 60))
    W = max(60, min(cols - 2, 110))
    DETAIL, HISTORY_N = 3, 6
    out = build_frame(tick)
    if len(out) > rows_:
        HISTORY_N = max(0, 6 - (len(out) - rows_))
        out = build_frame(tick)
    for DETAIL in (2, 1, 0):
        if len(out) <= rows_:
            break
        out = build_frame(tick)
    if len(out) > rows_:
        hidden = len(out) - rows_ + 1
        out = out[: rows_ - 1] + [paint(f"  … {hidden} more lines; enlarge the window to see them", "grey")]
    return out


def main() -> None:
    threading.Thread(target=_pmon_loop, daemon=True, name="pmon").start()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="print one frame and exit (for testing)")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()
    if args.once:
        build_frame(False)  # primes the rate counters and starts the background du
        time.sleep(3)
        if _size_thread is not None:
            _size_thread.join(timeout=60)
        print("\n".join(fit_frame(False)))
        return
    tick = False
    sys.stdout.write("\033[?1049h\033[?25l")  # alternate screen, like top: nothing piles up in scrollback
    try:
        while True:
            tick = not tick
            out = fit_frame(tick)
            sys.stdout.write("\033[H" + "\n".join(l + "\033[K" for l in out) + "\033[J")
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")


if __name__ == "__main__":
    main()
