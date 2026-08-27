from functools import lru_cache
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Synth Veda API"
    app_version: str = "0.1.0"
    debug: bool = False

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

    # Storage
    object_storage_url: str = ""
    object_storage_bucket: str = "synthveda-uploads"

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

    # Local disk storage for uploaded files (dev / single-node deployments).
    # Must resolve to the same directory for both the API (writer) and the
    # worker (reader) — in Docker Compose that's the shared uploads_data
    # volume; for plain local `uvicorn`/`python -m app.dispatcher` runs (each
    # with a different CWD) this needs to be an absolute path.
    upload_storage_dir: str = "uploads"

    # Redis / job queue
    redis_url: str = "redis://localhost:6379/0"

    # Workers
    worker_concurrency: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
