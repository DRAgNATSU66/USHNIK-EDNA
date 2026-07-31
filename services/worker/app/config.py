from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
