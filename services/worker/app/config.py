from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Possible-novelty cutoff: a sequence with novelty_score >= this is counted as
# possible novelty, gets an auto_novelty review, and is the low/medium
# novelty-level boundary. Override with the NOVELTY_THRESHOLD env var. The API
# image defines the same default in services/api/app/config.py (the two
# services share no package); services/api/tests/test_novelty_threshold.py
# checks the two are equal.
# 0.44 since 2026-10-20 (B5, t-1024-1): recalibrated on the DEV split with the
# centroid/reference novelty terms (training/eval_novelty_centroid.py
# calibrate; docs/ml/results/novelty_centroid_2026-10-27.json). Was 0.45.
DEFAULT_NOVELTY_THRESHOLD = 0.44


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "synthveda"
    redis_url: str = "redis://localhost:6379/0"
    worker_concurrency: int = 2
    # Poll interval when no jobs are in the queue (seconds)
    poll_interval_seconds: float = 2.0
    # Maximum time a single job may run before being marked failed (seconds)
    job_timeout_seconds: int = 600
    # Novelty (see DEFAULT_NOVELTY_THRESHOLD above).
    novelty_threshold: float = Field(default=DEFAULT_NOVELTY_THRESHOLD, gt=0.0, lt=1.0)
    # Tokenisation window for a route head whose own training record names
    # none (app/inference/max_length.py tries the registry entry, the
    # checkpoint's metrics.json and its tokenizer.json first). 256 is
    # training/finetune.py's --max-length default, the value every recorded
    # head in models/registry was trained at. Env: INFERENCE_DEFAULT_MAX_LENGTH.
    inference_default_max_length: int = Field(default=256, ge=8, le=8192)

    # Upload storage (B7; see app/storage.py). Same fields and defaults as
    # services/api/app/config.py; services/api/tests/test_storage.py checks
    # the two agree. The worker reads each upload from the backend its
    # storage_uri names, so storage_backend only matters to the writer (the
    # API) -- it is defined here so both services take the same .env.
    storage_backend: Literal["local", "s3"] = "local"
    # local:// keys resolve under this directory: it must be the directory
    # the API writes to (compose: the shared uploads_data volume).
    upload_storage_dir: str = "uploads"
    # s3:// URIs are read from this endpoint with these credentials. A blank
    # URL means AWS S3; blank keys use boto3's default credential chain.
    object_storage_url: str = ""
    object_storage_bucket: str = "synthveda-uploads"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"

    # Reference-lookup evidence provider (B4; app/evidence/reference_lookup.py).
    # Every threshold the provider applies lives here, env-overridable
    # (REFERENCE_SPECIES_IDENTITY=98 etc.). Identities are percent.
    # Blank root -> <data root>/reference; blank version -> the CURRENT file.
    reference_db_root: str = ""
    reference_db_version: str = ""
    # Provisional rank cut-offs on the best hit's identity (roadmap B4: 97/95/90).
    reference_species_identity: float = Field(default=97.0, ge=0.0, le=100.0)
    reference_genus_identity: float = Field(default=95.0, ge=0.0, le=100.0)
    reference_family_identity: float = Field(default=90.0, ge=0.0, le=100.0)
    # A hit counts only if it covers this much of the query: identity over a
    # partial alignment speaks for a fragment (a conserved stretch, one half
    # of a chimera), not the read. See the module docstring for the choice.
    reference_min_query_coverage: float = Field(default=80.0, ge=0.0, le=100.0)
    reference_min_alignment_length: int = Field(default=50, ge=1)
    # Hits within this many identity points of the best are ties; ties naming
    # different taxa are resolved to their lowest common ancestor.
    reference_tie_delta: float = Field(default=0.5, ge=0.0, le=10.0)
    # Search floor: hits below it are not reported at all.
    reference_search_min_identity: float = Field(default=80.0, ge=50.0, le=100.0)
    reference_max_accepts: int = Field(default=32, ge=1)   # candidates kept per query (tie detection)
    reference_report_hits: int = Field(default=5, ge=1)     # top hits returned per query
    # blast (default): BLAST+ against <route>/blast/ref for every route.
    # auto: vsearch when the route's UDB fits reference_vsearch_max_udb_gb,
    # else BLAST. vsearch: always vsearch. Measured on 384 held-out fish
    # queries (t-1021-2): vsearch 129 s search, 3.47 GB peak RSS; BLAST 18 s,
    # same assignment on 361/384, species precision 96.3 vs 95.9 %. vsearch
    # on plant (0.52 GB UDB) reached 2.1 GB RSS and had not finished 370
    # queries after 10 min. vsearch loads the whole UDB per call and its RSS
    # runs well above the UDB size; BLAST memory-maps its DB.
    reference_method: Literal["auto", "vsearch", "blast"] = "blast"
    # UDB size admitted to vsearch under "auto". Admits fish 1.87 GB, misc
    # 1.72 GB, bacteria 1.43 GB, plant 0.52 GB, human 0.42 GB; not
    # animal_general 3.45 GB.
    reference_vsearch_max_udb_gb: float = Field(default=2.5, gt=0.0)
    # megablast (word 28) is fast and sound for the >=90% band that drives
    # assignment; dc-megablast finds more of the 80-90% "nearest" hits, slower.
    reference_blast_task: Literal["megablast", "dc-megablast", "blastn"] = "megablast"
    reference_threads: int = Field(default=4, ge=1)
    reference_timeout_seconds: int = Field(default=1800, ge=1)
    # Human route: a GRCh38 hit at/above these is human-contamination evidence.
    reference_human_genome_identity: float = Field(default=99.0, ge=0.0, le=100.0)
    reference_human_genome_min_coverage: float = Field(default=80.0, ge=0.0, le=100.0)
    # Directory holding vsearch/ and blastn when they are not on PATH; blank ->
    # <data root>/tools/{vsearch,blast}/bin.
    reference_tools_dir: str = ""

    # Orchestrator (Day 9, decision Q7; app/orchestrator/). Deterministic:
    # plans candidate routes per sequence, runs the evidence providers,
    # combines them by the rule tables in app/orchestrator/{planner,combiner}.py.
    # Routes planned per sequence, primary included. 1 = router top pick only.
    orchestrator_max_routes: int = Field(default=3, ge=1, le=6)
    # Plan more than one route when the router's top probability is below
    # this. 0.70 is the router's own high-tier cut: on the protocol rows
    # router v2 is 0.947 accurate in the high tier, 0.643 in medium (QNA-021).
    orchestrator_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    # ... or when top-1 minus top-2 probability is below this. Chosen on the
    # DEV split, never test (`python -m training.eval_orchestrator planner`,
    # docs/ml/results/orchestrator_planner_dev_2026-10-19.json; 8,299 dev
    # sequences past the QC gate, 673 router v2 errors). With 3 routes per
    # wide plan, the true route is in the plan for: confidence rule alone
    # 250 errors at 9.9 % planned wide; + weak-route rule 445 at 29.7 %;
    # + margin < 0.5: 449 at 29.9 %; < 0.6: 457 at 30.5 %; < 0.7: 468 at
    # 32.0 %; < 0.8: 491 at 35.0 %. 370 of the 673 errors are at >= 0.70
    # (QNA-021 Q4 measured 368/701 on test). The margin rule adds little
    # beyond the other two; 0.6 is where its cost per recovered error starts
    # to climb.
    orchestrator_margin_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # ... or when the router's top pick is one of these routes. Router v2
    # per-route test accuracy: human 0.832, misc 0.855, the two weakest
    # (QNA-021 Q2); on dev they are the predicted route of 526 of 673 errors.
    orchestrator_weak_routes: list[str] = ["human_domestic_contamination", "misc_unknown"]
    # Second planning pass after the primary route's reference lookup: a miss
    # in the primary route's DB, or a hit whose lineage maps to another route,
    # adds that route (within orchestrator_max_routes).
    orchestrator_reference_expansion: bool = True
    # Run the reference-lookup provider at all. Off -> heads-only decisions,
    # stated in every trace.
    orchestrator_reference_enabled: bool = True
    # Routes whose reference species names are capped at genus. Plant species
    # precision at 97 % identity is 51.9 % (26 of 54 wrong, QNA-020 Q3/Q4).
    orchestrator_genus_cap_routes: list[str] = ["plant"]
    # Reference hits kept per evidence record in the stored trace.
    orchestrator_trace_max_hits: int = Field(default=3, ge=0, le=20)


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


# Import this, never a bare 0.45. Resolved once at import time (the settings
# getter is lru_cached).
NOVELTY_THRESHOLD: float = get_worker_settings().novelty_threshold
