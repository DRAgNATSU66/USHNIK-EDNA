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


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


# Import this, never a bare 0.45. Resolved once at import time (the settings
# getter is lru_cached).
NOVELTY_THRESHOLD: float = get_worker_settings().novelty_threshold
