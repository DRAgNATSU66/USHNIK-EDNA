from functools import lru_cache
from typing import Any, Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Possible-novelty cutoff: a sequence with novelty_score >= this is counted as
# possible novelty, gets an auto_novelty review and is listed in the report's
# novelty table. Override with the NOVELTY_THRESHOLD env var. The worker image
# defines the same default in services/worker/app/config.py (the two services
# share no package); tests/test_novelty_threshold.py checks the two are equal.
DEFAULT_NOVELTY_THRESHOLD = 0.45


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Synth Veda API"
    app_version: str = "0.1.0"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "synthveda"

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # Auth
    google_client_id: str = ""
    google_client_secret: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days


    # CORS
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Upload limits
    max_upload_size_mb: int = 100

    # Upload storage (B7; see app/storage.py). The worker defines the same
    # fields in services/worker/app/config.py; tests/test_storage.py checks
    # the two agree.
    #   local -- files under upload_storage_dir. Default for dev and tests.
    #   s3    -- an S3-compatible bucket (MinIO in docker-compose, or AWS).
    storage_backend: Literal["local", "s3"] = "local"
    # local backend: must resolve to the same directory for both the API
    # (writer) and the worker (reader) -- in Docker Compose that's the shared
    # uploads_data volume; for plain local `uvicorn`/`python -m app.dispatcher`
    # runs (each with a different CWD) this needs to be an absolute path.
    upload_storage_dir: str = "uploads"
    # s3 backend. A blank URL means AWS S3; blank keys fall back to boto3's
    # default credential chain (env, instance role).
    object_storage_url: str = ""
    object_storage_bucket: str = "synthveda-uploads"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"

    # Redis / job queue
    redis_url: str = "redis://localhost:6379/0"

    # Workers
    worker_concurrency: int = 2

    # Novelty (see DEFAULT_NOVELTY_THRESHOLD above). Exposed on GET /health.
    novelty_threshold: float = Field(default=DEFAULT_NOVELTY_THRESHOLD, gt=0.0, lt=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Import this, never a bare 0.45. Resolved once at import time, like the
# rest of the settings (get_settings is lru_cached).
NOVELTY_THRESHOLD: float = get_settings().novelty_threshold
