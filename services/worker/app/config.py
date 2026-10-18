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
DEFAULT_NOVELTY_THRESHOLD = 0.45


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
    # auto: vsearch when the route's UDB fits the memory budget, else BLAST.
    reference_method: Literal["auto", "vsearch", "blast"] = "auto"
    # vsearch loads the whole UDB per call (v1 animal_general: 3.45 GB UDB,
    # 4.1 GB RSS). Routes whose UDB is larger are searched with BLAST, which
    # memory-maps its DB. Default admits fish 1.87 GB, misc 1.72 GB,
    # bacteria 1.43 GB, plant 0.52 GB, human 0.42 GB; not animal_general.
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


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


# Import this, never a bare 0.45. Resolved once at import time (the settings
# getter is lru_cached).
NOVELTY_THRESHOLD: float = get_worker_settings().novelty_threshold
