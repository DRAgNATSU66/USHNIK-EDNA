"""
Reference-lookup evidence provider (roadmap B4, tracker t-1021-2).

The route heads say *what kind* of result a sequence is; this provider says
*which taxon* it is closest to, at what rank, and how sure the identity lets
us be. It searches the versioned per-route reference DB that
training/build_reference_db.py writes:

    <data>/reference/CURRENT                      -> "v2"
    <data>/reference/<version>/manifest.json      version, per-route sha256, cap
    <data>/reference/<version>/<route>/ref.udb    vsearch index
    <data>/reference/<version>/<route>/blast/ref  BLAST+ v5 DB
    <data>/reference/<version>/human_domestic_contamination/grch38_blast/grch38

Interface (what the Day 9 orchestrator calls):

    provider = ReferenceLookupProvider()               # settings from app.config
    evidence = provider.lookup([(seq_id, seq), ...], route)
    # -> list[ReferenceEvidence], one per input, same order; .to_dict() is JSON-safe

One search process per call, all sequences batched into it (vsearch loads
the whole UDB on every call, so one call per sequence would reload GBs per
read); identical sequences are searched once. Calls are serialised across
threads and processes on this host by a lock, so two jobs never hold two UDBs
in RAM at once.

Assignment (assign_taxon, pure, unit-tested):
  1. A hit is eligible if it covers >= min_query_coverage % of the query over
     >= min_alignment_length columns.
  2. Hits within tie_delta identity points of the best eligible hit are the
     tie set. If they name different taxa the lineage is their lowest common
     ancestor: ranks down to the deepest rank that every tied hit fills and
     agrees on (a reference resolved only to genus, tied with a species,
     yields the genus, never that species).
  3. The best identity caps the rank: >= species_identity -> may name a
     species, >= genus_identity -> at most genus, >= family_identity -> at
     most family, below that -> status "below_threshold" (the nearest hit is
     still reported, which is what novelty needs).
  4. The assigned taxon is the deepest rank of the capped LCA lineage.

Why 80 % query coverage: identity is computed over the aligned columns only,
so a 100 %-identity hit over 30 % of a read says that 30 % is conserved (a
primer-flanked rRNA stem, the shared half of a chimera), not that the read is
that species. Requiring 80 % means at least 4/5 of the read supports the
identity; 400 bp windows (build_dataset's chunks) still match a longer
reference fully, and a read with a 20 % adapter/low-quality tail still
qualifies. The 50-column floor matches the builder's MIN_LEN: below it a
97 % identity is 1-2 mismatches and does not separate species.

Why tie_delta 0.5: one mismatch over a 200-250 bp barcode is 0.4-0.5
identity points, within sequencing error. Two references that close to the
best do not discriminate, so their disagreement must coarsen the answer
rather than the search order picking one.

Identity definitions: vsearch reports its default --iddef 2 (matches over
alignment columns, terminal gaps excluded); BLAST reports pident over the
HSP. With the coverage floor both are identity over >= 80 % of the read.

Missing DB, manifest, route, tool, or a failed/timed-out search -> every
sequence gets status "unavailable" with the reason. Never a fake taxon.

This module must not import training/: the worker image ships only app/.
parse_reference_header mirrors training.build_reference_db.parse_header;
tests/test_reference_lookup.py checks the two agree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

try:  # POSIX only; the worker runs on Linux
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

RANKS = ("superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species")
_CODE_TO_RANK = {"d": "superkingdom", "k": "kingdom", "p": "phylum", "c": "class",
                 "o": "order", "f": "family", "g": "genus", "s": "species"}

EVIDENCE_TYPE = "reference_lookup"
HUMAN_ROUTE = "human_domestic_contamination"

# status values
ASSIGNED = "assigned"
BELOW_THRESHOLD = "below_threshold"
NO_HIT = "no_hit"
NO_CONSENSUS = "no_consensus"
UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# header parsing (mirror of training.build_reference_db.parse_header)
# ---------------------------------------------------------------------------

def parse_reference_header(header: str) -> dict:
    """`<ID>;tax=d:..,..,s:..;src=..;marker=..;acc=..;[taxid=..;]n=..;`, with
    or without '>', or BLAST's '<id> <rest>'. Returns id, lineage, src,
    marker, acc, taxid (int|None), n (int|None)."""
    h = header.strip()
    if h.startswith(">"):
        h = h[1:]
    h = h.replace(" ", ";", 1)
    fields = [f for f in h.split(";") if f]
    out: dict = {"id": fields[0] if fields else "", "lineage": {}, "src": None, "marker": None,
                 "acc": None, "taxid": None, "n": 1}
    for f in fields[1:]:
        key, sep, value = f.partition("=")
        if not sep:
            continue
        if key == "tax":
            lineage: dict[str, str] = {}
            for part in value.split(","):
                code, s, v = part.partition(":")
                rank = _CODE_TO_RANK.get(code)
                if s and rank and v:
                    lineage[rank] = v.replace("_", " ")
            out["lineage"] = lineage
        elif key in ("taxid", "n"):
            out[key] = int(value) if value.isdigit() else None
        elif key in ("src", "marker", "acc"):
            out[key] = value
    if out["id"].startswith("lcl|"):
        out["id"] = out["id"][4:]
    return out


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LookupThresholds:
    species: float = 97.0
    genus: float = 95.0
    family: float = 90.0
    min_query_coverage: float = 80.0
    min_alignment_length: int = 50
    tie_delta: float = 0.5

    def __post_init__(self) -> None:
        if not (self.species >= self.genus >= self.family):
            raise ValueError(f"identity thresholds must satisfy species >= genus >= family, got "
                             f"{self.species}/{self.genus}/{self.family}")

    @classmethod
    def from_settings(cls, s: Any) -> "LookupThresholds":
        return cls(species=s.reference_species_identity, genus=s.reference_genus_identity,
                   family=s.reference_family_identity, min_query_coverage=s.reference_min_query_coverage,
                   min_alignment_length=s.reference_min_alignment_length, tie_delta=s.reference_tie_delta)

    def rank_for_identity(self, identity: float) -> str | None:
        """Deepest rank the identity alone permits naming, or None."""
        if identity >= self.species:
            return "species"
        if identity >= self.genus:
            return "genus"
        if identity >= self.family:
            return "family"
        return None


@dataclass
class ReferenceHit:
    target_id: str
    accession: str | None
    source: str | None
    marker: str | None
    taxid: int | None
    identity: float            # percent
    alignment_length: int
    query_coverage: float      # percent of the query covered by the alignment
    lineage: dict[str, str] = field(default_factory=dict)
    merged_copies: int | None = None   # n= in the header: identical sequences merged in the DB

    @property
    def taxon(self) -> str | None:
        return _deepest(self.lineage)[1]

    @property
    def rank(self) -> str | None:
        return _deepest(self.lineage)[0]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["taxon"], d["rank"] = self.taxon, self.rank
        return d


@dataclass
class TaxonAssignment:
    status: str                       # assigned | below_threshold | no_hit | no_consensus | unavailable
    taxon: str | None = None
    rank: str | None = None
    lineage: dict[str, str] = field(default_factory=dict)
    identity: float | None = None     # best eligible hit
    query_coverage: float | None = None
    identity_rank: str | None = None  # deepest rank the identity permits
    tied_hits: int = 0                # hits in the tie set
    tied_taxa: int = 0                # distinct lineages among them
    lca_applied: bool = False         # the tie set disagreed and was coarsened
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HumanGenomeEvidence:
    available: bool
    reason: str | None = None
    hit: bool = False                 # passed identity + coverage thresholds
    contamination: bool = False       # hit, and no better non-human route-DB assignment
    identity: float | None = None
    query_coverage: float | None = None
    alignment_length: int | None = None
    subject: str | None = None        # GRCh38 sequence id (chromosome / contig)
    start: int | None = None
    end: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReferenceEvidence:
    sequence_id: str
    route: str
    available: bool
    status: str
    assignment: TaxonAssignment
    hits: list[ReferenceHit] = field(default_factory=list)
    method: str | None = None                 # vsearch | blast
    reference_db: str | None = None
    reference_db_version: str | None = None
    reference_db_sha256: str | None = None    # route ref.fasta sha256 from the manifest
    reason: str | None = None
    thresholds: dict = field(default_factory=dict)
    run: dict = field(default_factory=dict)   # batch timing, peak RSS, method choice
    human_genome: HumanGenomeEvidence | None = None
    evidence_type: str = EVIDENCE_TYPE

    @property
    def taxon(self) -> str | None:
        return self.assignment.taxon

    @property
    def rank(self) -> str | None:
        return self.assignment.rank

    @property
    def identity(self) -> float | None:
        return self.assignment.identity

    def to_dict(self) -> dict:
        return {
            "evidence_type": self.evidence_type,
            "sequence_id": self.sequence_id,
            "route": self.route,
            "available": self.available,
            "status": self.status,
            "reason": self.reason,
            "taxon": self.taxon,
            "rank": self.rank,
            "identity": self.identity,
            "assignment": self.assignment.to_dict(),
            "hits": [h.to_dict() for h in self.hits],
            "method": self.method,
            "reference_db": self.reference_db,
            "reference_db_version": self.reference_db_version,
            "reference_db_sha256": self.reference_db_sha256,
            "thresholds": self.thresholds,
            "run": self.run,
            "human_genome": self.human_genome.to_dict() if self.human_genome else None,
        }


# ---------------------------------------------------------------------------
# assignment logic (pure)
# ---------------------------------------------------------------------------

def _deepest(lineage: dict[str, str]) -> tuple[str | None, str | None]:
    for rank in reversed(RANKS):
        if lineage.get(rank):
            return rank, lineage[rank]
    return None, None


def lca(lineages: Sequence[dict[str, str]]) -> dict[str, str]:
    """Lowest common ancestor of lineages. A rank only some lineages fill is
    kept above the deepest rank all of them fill and agree on (sources differ
    in which intermediate ranks they carry), and dropped below it."""
    if not lineages:
        return {}
    deepest = -1
    for i, rank in enumerate(RANKS):
        vals = [lin.get(rank) for lin in lineages]
        present = [v for v in vals if v]
        if present and len(set(present)) > 1:
            break
        if len(present) == len(lineages):
            deepest = i
    out: dict[str, str] = {}
    for rank in RANKS[:deepest + 1]:
        v = next((lin[rank] for lin in lineages if lin.get(rank)), None)
        if v:
            out[rank] = v
    return out


def _sort_key(h: ReferenceHit) -> tuple:
    return (-h.identity, -h.query_coverage, -h.alignment_length, h.target_id)


def eligible_hits(hits: Sequence[ReferenceHit], th: LookupThresholds) -> list[ReferenceHit]:
    return sorted((h for h in hits if h.query_coverage >= th.min_query_coverage
                   and h.alignment_length >= th.min_alignment_length), key=_sort_key)


def assign_taxon(hits: Sequence[ReferenceHit], th: LookupThresholds) -> TaxonAssignment:
    ok = eligible_hits(hits, th)
    if not ok:
        reason = "no reference hit" if not hits else (
            f"no hit covers >= {th.min_query_coverage:g}% of the query over >= {th.min_alignment_length} columns")
        return TaxonAssignment(status=NO_HIT, reason=reason)
    best = ok[0]
    tied = [h for h in ok if h.identity >= best.identity - th.tie_delta]
    distinct = {tuple(sorted(h.lineage.items())) for h in tied}
    lineage = lca([h.lineage for h in tied]) if len(distinct) > 1 else dict(best.lineage)
    allowed = th.rank_for_identity(best.identity)
    base = dict(identity=best.identity, query_coverage=best.query_coverage, identity_rank=allowed,
                tied_hits=len(tied), tied_taxa=len(distinct), lca_applied=len(distinct) > 1)
    if allowed is None:
        return TaxonAssignment(status=BELOW_THRESHOLD, reason=(
            f"best identity {best.identity:g}% is below the family threshold {th.family:g}%"), **base)
    cut = RANKS.index(allowed)
    capped = {r: v for r, v in lineage.items() if RANKS.index(r) <= cut}
    rank, taxon = _deepest(capped)
    if rank is None:
        return TaxonAssignment(status=NO_CONSENSUS, lineage=capped, reason=(
            "tied hits share no rank" if base["lca_applied"] else "best hit carries no lineage"), **base)
    reason = None
    if rank != allowed:
        reason = (f"identity permits {allowed} but tied hits agree only to {rank}" if base["lca_applied"]
                  else f"identity permits {allowed} but the reference is resolved only to {rank}")
    return TaxonAssignment(status=ASSIGNED, taxon=taxon, rank=rank, lineage=capped, reason=reason, **base)


# ---------------------------------------------------------------------------
# reference DB resolution
# ---------------------------------------------------------------------------

@dataclass
class _RouteDB:
    route: str
    version: str
    version_dir: Path
    manifest: dict
    udb: Path
    blast_prefix: Path
    grch38_prefix: Path

    @property
    def route_info(self) -> dict:
        return (self.manifest.get("routes") or {}).get(self.route) or {}

    @property
    def fasta_sha256(self) -> str | None:
        return (self.route_info.get("fasta") or {}).get("sha256")

    @staticmethod
    def blast_present(prefix: Path) -> bool:
        return any(prefix.parent.glob(prefix.name + ".n*")) if prefix.parent.exists() else False


class _Unavailable(Exception):
    pass


def _default_data_root() -> Path:
    from app.inference.registry import _resolve_data_root
    return _resolve_data_root()


def _find_tool(name: str, tools_dir: Path | None, data_root: Path) -> Path | None:
    cands: list[Path] = []
    if tools_dir is not None:
        cands += [tools_dir / name, tools_dir / "bin" / name, tools_dir / "vsearch" / "bin" / name,
                  tools_dir / "blast" / "bin" / name]
    for c in cands:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    for c in (data_root / "tools" / "vsearch" / "bin" / name, data_root / "tools" / "blast" / "bin" / name):
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


# ---------------------------------------------------------------------------
# running the search tools
# ---------------------------------------------------------------------------

_THREAD_LOCK = threading.Lock()


@contextmanager
def _search_lock() -> Iterator[None]:
    """One search process at a time on this host: a UDB is GBs of RAM."""
    with _THREAD_LOCK:
        fh = None
        if fcntl is not None:
            try:
                fh = open(Path(tempfile.gettempdir()) / "synthveda-reference-search.lock", "a")
                fcntl.flock(fh, fcntl.LOCK_EX)
            except OSError:
                fh = None
        try:
            yield
        finally:
            if fh is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
                fh.close()


@dataclass
class _ToolRun:
    returncode: int
    seconds: float
    peak_rss_bytes: int | None
    stderr_tail: str
    timed_out: bool


def _run_tool(cmd: list[str], timeout: float) -> _ToolRun:
    """Runs cmd and reports its own peak RSS (os.wait4 rusage of that child)."""
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err)
        killed = threading.Event()

        def _kill() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        rss = None
        try:
            if hasattr(os, "wait4"):
                _, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
                rss = int(usage.ru_maxrss) * 1024  # Linux reports KiB
            else:  # pragma: no cover
                proc.wait()
        finally:
            timer.cancel()
        err.seek(0)
        tail = err.read()[-1500:].decode("utf-8", errors="replace").strip()
    return _ToolRun(proc.returncode, round(time.monotonic() - t0, 2), rss, tail, killed.is_set())


def _write_queries(path: Path, queries: dict[str, str]) -> None:
    with open(path, "w", encoding="ascii") as fh:
        for qid, seq in queries.items():
            fh.write(f">{qid}\n{seq}\n")


def _normalise(seq: str) -> str:
    s = "".join(seq.split()).upper().replace("U", "T")
    return s.replace("-", "").replace(".", "")


# ---------------------------------------------------------------------------
# provider
# ---------------------------------------------------------------------------

class ReferenceLookupProvider:
    """Reference-lookup evidence provider. Stateless between calls apart from
    a cached manifest; safe to share across jobs."""

    name = EVIDENCE_TYPE

    def __init__(self, settings: Any = None, *, data_root: Path | str | None = None):
        if settings is None:
            from app.config import get_worker_settings
            settings = get_worker_settings()
        self.settings = settings
        self.thresholds = LookupThresholds.from_settings(settings)
        self._data_root = Path(data_root) if data_root else None
        self._manifest_cache: dict[Path, tuple[float, dict]] = {}

    # -- paths ---------------------------------------------------------------

    @property
    def data_root(self) -> Path:
        if self._data_root is None:
            self._data_root = _default_data_root()
        return self._data_root

    @property
    def reference_root(self) -> Path:
        r = self.settings.reference_db_root
        return Path(r) if r else self.data_root / "reference"

    def _tool(self, name: str) -> Path | None:
        d = self.settings.reference_tools_dir
        return _find_tool(name, Path(d) if d else None, self.data_root)

    def _manifest(self, path: Path) -> dict:
        mtime = path.stat().st_mtime
        hit = self._manifest_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        data = json.loads(path.read_text(encoding="utf-8"))
        self._manifest_cache[path] = (mtime, data)
        return data

    def resolve(self, route: str) -> _RouteDB:
        root = self.reference_root
        if not root.is_dir():
            raise _Unavailable(f"reference DB root not found: {root}")
        version = self.settings.reference_db_version
        if not version:
            cur = root / "CURRENT"
            if not cur.is_file():
                raise _Unavailable(f"no reference version configured and {cur} is missing")
            version = cur.read_text(encoding="utf-8").strip()
        vdir = root / version
        mpath = vdir / "manifest.json"
        if not mpath.is_file():
            raise _Unavailable(f"reference manifest not found: {mpath}")
        try:
            manifest = self._manifest(mpath)
        except (OSError, ValueError) as exc:
            raise _Unavailable(f"reference manifest unreadable: {mpath}: {exc}") from exc
        routes = manifest.get("routes") or {}
        if route not in routes:
            raise _Unavailable(f"route {route!r} has no reference DB in {version} (has: {', '.join(sorted(routes))})")
        rdir = vdir / route
        return _RouteDB(route=route, version=str(manifest.get("version") or version), version_dir=vdir,
                        manifest=manifest, udb=rdir / "ref.udb", blast_prefix=rdir / "blast" / "ref",
                        grch38_prefix=vdir / HUMAN_ROUTE / "grch38_blast" / "grch38")

    def choose_method(self, db: _RouteDB) -> tuple[str, Path, str]:
        """(method, tool path, why). Raises _Unavailable."""
        s = self.settings
        vsearch, blastn = self._tool("vsearch"), self._tool("blastn")
        udb_ok = db.udb.is_file()
        blast_ok = db.blast_present(db.blast_prefix)
        budget = s.reference_vsearch_max_udb_gb * 1e9
        if s.reference_method == "vsearch":
            if not udb_ok:
                raise _Unavailable(f"vsearch requested but {db.udb} is missing")
            if vsearch is None:
                raise _Unavailable("vsearch requested but the vsearch binary was not found")
            return "vsearch", vsearch, "configured"
        if s.reference_method == "blast":
            if not blast_ok:
                raise _Unavailable(f"BLAST requested but no BLAST DB at {db.blast_prefix}")
            if blastn is None:
                raise _Unavailable("BLAST requested but the blastn binary was not found")
            return "blast", blastn, "configured"
        reasons = []
        if udb_ok and vsearch is not None:
            size = db.udb.stat().st_size
            if size <= budget:
                return "vsearch", vsearch, f"UDB {size / 1e9:.2f} GB within {budget / 1e9:.2f} GB budget"
            reasons.append(f"UDB {size / 1e9:.2f} GB over {budget / 1e9:.2f} GB vsearch budget")
        elif not udb_ok:
            reasons.append(f"no UDB at {db.udb}")
        else:
            reasons.append("vsearch binary not found")
        if blast_ok and blastn is not None:
            return "blast", blastn, "; ".join(reasons + ["using BLAST (memory-mapped)"])
        reasons.append(f"no BLAST DB at {db.blast_prefix}" if not blast_ok else "blastn binary not found")
        raise _Unavailable("; ".join(reasons))

    def thresholds_dict(self) -> dict:
        d = asdict(self.thresholds)
        d["search_min_identity"] = self.settings.reference_search_min_identity
        d["max_accepts"] = self.settings.reference_max_accepts
        return d

    # -- searches ------------------------------------------------------------

    def _search_vsearch(self, tool: Path, db: _RouteDB, qfile: Path, out: Path) -> tuple[_ToolRun, dict[str, list[ReferenceHit]]]:
        s, th = self.settings, self.thresholds
        cmd = [str(tool), "--usearch_global", str(qfile), "--db", str(db.udb), "--strand", "both",
               "--id", f"{s.reference_search_min_identity / 100:.4f}",
               "--query_cov", f"{th.min_query_coverage / 100:.4f}", "--mincols", str(th.min_alignment_length),
               "--maxaccepts", str(s.reference_max_accepts), "--maxrejects", str(max(32, 2 * s.reference_max_accepts)),
               "--userout", str(out), "--userfields", "query+target+id+alnlen+qcov",
               "--threads", str(s.reference_threads), "--quiet"]
        run = _run_tool(cmd, s.reference_timeout_seconds)
        hits: dict[str, list[ReferenceHit]] = {}
        if run.returncode == 0 and out.exists():
            with open(out, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    p = line.rstrip("\n").split("\t")
                    if len(p) < 5 or p[1] == "*":
                        continue
                    hits.setdefault(p[0], []).append(self._hit(p[1], float(p[2]), int(p[3]), float(p[4])))
        return run, hits

    def _search_blast(self, tool: Path, prefix: Path, qfile: Path, out: Path, *, max_targets: int,
                      min_identity: float, min_cov: float) -> _ToolRun:
        s = self.settings
        cmd = [str(tool), "-task", s.reference_blast_task, "-query", str(qfile), "-db", str(prefix),
               "-outfmt", "6 qseqid sseqid pident length qcovhsp sstart send stitle",
               "-max_target_seqs", str(max_targets), "-max_hsps", "1", "-perc_identity", f"{min_identity:g}",
               "-qcov_hsp_perc", f"{min_cov:g}", "-num_threads", str(s.reference_threads), "-out", str(out)]
        return _run_tool(cmd, s.reference_timeout_seconds)

    @staticmethod
    def _hit(label: str, identity: float, alnlen: int, qcov: float) -> ReferenceHit:
        h = parse_reference_header(label)
        return ReferenceHit(target_id=h["id"], accession=h["acc"], source=h["src"], marker=h["marker"],
                            taxid=h["taxid"], identity=round(identity, 2), alignment_length=alnlen,
                            query_coverage=round(qcov, 1), lineage=h["lineage"], merged_copies=h["n"])

    def _blast_route_hits(self, out: Path) -> dict[str, list[ReferenceHit]]:
        hits: dict[str, list[ReferenceHit]] = {}
        if not out.exists():
            return hits
        with open(out, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) < 8:
                    continue
                hits.setdefault(p[0], []).append(self._hit(f"{p[1]} {p[7]}", float(p[2]), int(p[3]), float(p[4])))
        return hits

    # -- public --------------------------------------------------------------

    def lookup(self, sequences: Sequence[tuple[str, str]], route: str) -> list[ReferenceEvidence]:
        t0 = time.monotonic()
        th_dict = self.thresholds_dict()
        items = [(str(sid), _normalise(seq or "")) for sid, seq in sequences]
        if not items:
            return []

        def unavailable(reason: str, db: _RouteDB | None = None, method: str | None = None,
                        run: dict | None = None) -> list[ReferenceEvidence]:
            return [ReferenceEvidence(
                sequence_id=sid, route=route, available=False, status=UNAVAILABLE,
                assignment=TaxonAssignment(status=UNAVAILABLE, reason=reason), method=method,
                reference_db=f"synthveda-reference/{route}" if db else None,
                reference_db_version=db.version if db else None,
                reference_db_sha256=db.fasta_sha256 if db else None,
                reason=reason, thresholds=th_dict, run=run or {"batch_size": len(items)}) for sid, _ in items]

        try:
            db = self.resolve(route)
        except _Unavailable as exc:
            return unavailable(str(exc))
        try:
            method, tool, why = self.choose_method(db)
        except _Unavailable as exc:
            return unavailable(str(exc), db)

        # one query per distinct searchable sequence
        min_len = self.thresholds.min_alignment_length
        qid_of: dict[str, str] = {}
        queries: dict[str, str] = {}
        for _, seq in items:
            if len(seq) >= min_len and seq not in qid_of:
                qid = f"q{len(queries)}"
                qid_of[seq] = qid
                queries[qid] = seq

        hits: dict[str, list[ReferenceHit]] = {}
        human: dict[str, HumanGenomeEvidence] = {}
        run_info: dict = {"method": method, "method_reason": why, "batch_size": len(items),
                          "unique_queries": len(queries), "threads": self.settings.reference_threads}
        if queries:
            with tempfile.TemporaryDirectory(prefix="synthveda-reflookup-") as tmp:
                qfile, out = Path(tmp) / "q.fa", Path(tmp) / "hits.tsv"
                _write_queries(qfile, queries)
                with _search_lock():
                    if method == "vsearch":
                        run, hits = self._search_vsearch(tool, db, qfile, out)
                    else:
                        run = self._search_blast(tool, db.blast_prefix, qfile, out,
                                                 max_targets=self.settings.reference_max_accepts,
                                                 min_identity=self.settings.reference_search_min_identity,
                                                 min_cov=self.thresholds.min_query_coverage)
                        if run.returncode == 0:
                            hits = self._blast_route_hits(out)
                    run_info.update(search_seconds=run.seconds,
                                    peak_rss_mb=round(run.peak_rss_bytes / 2**20, 1) if run.peak_rss_bytes else None)
                    if run.returncode != 0:
                        why_failed = (f"{method} timed out after {self.settings.reference_timeout_seconds}s"
                                      if run.timed_out else f"{method} exited {run.returncode}: {run.stderr_tail[-400:]}")
                        run_info["elapsed_seconds"] = round(time.monotonic() - t0, 2)
                        return unavailable(why_failed, db, method, run_info)
                    if route == HUMAN_ROUTE:
                        human, hrun = self._human_genome(qfile, Path(tmp) / "grch38.tsv", db, set(queries))
                        if hrun is not None:
                            run_info["grch38_seconds"] = hrun.seconds
                            run_info["grch38_peak_rss_mb"] = (round(hrun.peak_rss_bytes / 2**20, 1)
                                                              if hrun.peak_rss_bytes else None)

        elapsed = round(time.monotonic() - t0, 2)
        run_info["elapsed_seconds"] = elapsed
        run_info["per_sequence_seconds"] = round(elapsed / len(items), 4)
        n_report = self.settings.reference_report_hits
        results: list[ReferenceEvidence] = []
        for sid, seq in items:
            qid = qid_of.get(seq)
            if qid is None:
                reason = ("empty sequence" if not seq else
                          f"query length {len(seq)} is below the minimum alignment length {min_len}")
                assignment = TaxonAssignment(status=NO_HIT, reason=reason)
                qhits: list[ReferenceHit] = []
            else:
                qhits = eligible_hits(hits.get(qid, []), self.thresholds)
                assignment = assign_taxon(qhits, self.thresholds)
            hg = None
            if route == HUMAN_ROUTE:
                hg = human.get(qid) if qid else None
                if hg is None:
                    hg = HumanGenomeEvidence(available=bool(qid) and False, reason=(
                        "query not searched" if not qid else "GRCh38 search not run"))
                if hg.hit:
                    non_human_better = (assignment.status == ASSIGNED and assignment.lineage.get("genus") != "Homo"
                                        and (assignment.identity or 0) > (hg.identity or 0))
                    hg.contamination = not non_human_better
            results.append(ReferenceEvidence(
                sequence_id=sid, route=route, available=True, status=assignment.status, assignment=assignment,
                hits=qhits[:n_report], method=method, reference_db=f"synthveda-reference/{route}",
                reference_db_version=db.version, reference_db_sha256=db.fasta_sha256,
                reason=assignment.reason, thresholds=th_dict, run=dict(run_info), human_genome=hg))
        return results

    def _human_genome(self, qfile: Path, out: Path, db: _RouteDB, qids: set[str]
                      ) -> tuple[dict[str, HumanGenomeEvidence], _ToolRun | None]:
        s = self.settings
        blastn = self._tool("blastn")
        reason = None
        if blastn is None:
            reason = "blastn binary not found"
        elif not db.blast_present(db.grch38_prefix):
            reason = f"no GRCh38 BLAST DB at {db.grch38_prefix}"
        if reason:
            return {q: HumanGenomeEvidence(available=False, reason=reason) for q in qids}, None
        # floor below the decision threshold so near-misses are reported too
        run = self._search_blast(blastn, db.grch38_prefix, qfile, out, max_targets=5,
                                 min_identity=min(90.0, s.reference_human_genome_identity),
                                 min_cov=min(50.0, s.reference_human_genome_min_coverage))
        if run.returncode != 0:
            why = "GRCh38 BLAST timed out" if run.timed_out else f"GRCh38 BLAST exited {run.returncode}: {run.stderr_tail[-300:]}"
            return {q: HumanGenomeEvidence(available=False, reason=why) for q in qids}, run
        best: dict[str, tuple] = {}
        with open(out, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) < 7:
                    continue
                ident, alnlen, qcov = float(p[2]), int(p[3]), float(p[4])
                key = (ident * qcov, alnlen)
                if p[0] not in best or key > best[p[0]][0]:
                    subj = p[1][4:] if p[1].startswith("lcl|") else p[1]
                    best[p[0]] = (key, ident, alnlen, qcov, subj, int(p[5]), int(p[6]))
        res: dict[str, HumanGenomeEvidence] = {}
        for q in qids:
            b = best.get(q)
            if b is None:
                res[q] = HumanGenomeEvidence(available=True, reason="no GRCh38 hit")
                continue
            _, ident, alnlen, qcov, subj, ss, se = b
            passed = (ident >= s.reference_human_genome_identity and qcov >= s.reference_human_genome_min_coverage
                      and alnlen >= self.thresholds.min_alignment_length)
            res[q] = HumanGenomeEvidence(
                available=True, hit=passed, identity=round(ident, 2), query_coverage=round(qcov, 1),
                alignment_length=alnlen, subject=subj, start=min(ss, se), end=max(ss, se),
                reason=None if passed else (f"best GRCh38 hit {ident:g}% over {qcov:g}% of the query is below "
                                            f"{s.reference_human_genome_identity:g}%/{s.reference_human_genome_min_coverage:g}%"))
        return res, run


def lookup_reference(sequences: Sequence[tuple[str, str]], route: str, settings: Any = None) -> list[ReferenceEvidence]:
    """Convenience wrapper: one-shot provider with the worker settings."""
    return ReferenceLookupProvider(settings).lookup(sequences, route)
