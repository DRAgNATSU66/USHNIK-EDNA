from functools import lru_cache
from typing import Any, Literal
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Possible-novelty cutoff: a sequence with novelty_score >= this is counted as
# possible novelty, gets an auto_novelty review and is listed in the report's
# novelty table. Override with the NOVELTY_THRESHOLD env var. The worker image
# defines the same default in services/worker/app/config.py (the two services
# share no package); tests/test_novelty_threshold.py checks the two are equal.
# 0.44 since 2026-10-20 (B5, t-1024-1): recalibrated on the DEV split
# (docs/ml/results/novelty_centroid_2026-10-27.json). Was 0.45.
DEFAULT_NOVELTY_THRESHOLD = 0.44

# JWT_SECRET startup check (B18). Outside APP_ENV=dev/test the API refuses to
# start with a placeholder secret or one shorter than this many bytes. 32
# bytes = 256 bits: RFC 7518 sec. 3.2 requires an HS256 key at least as long
# as the hash output, and `openssl rand -hex 32` (64 chars) clears it easily.
JWT_SECRET_MIN_BYTES = 32
# The code default below and the .env.example placeholder: a copied example
# file must not pass the length check by accident.
_PLACEHOLDER_JWT_SECRETS = frozenset({
    "change-me-in-production",
    "change-me-to-a-random-256-bit-secret",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Synth Veda API"
    app_version: str = "0.1.0"
    # Deployment environment (APP_ENV). dev and test skip the JWT_SECRET
    # check below; the deploy manifests (infra/deployment/cloud-run-api.yml,
    # infra/terraform/main.tf) set APP_ENV=production. The default stays dev
    # so tests, scripts and a bare `make api-run` keep working.
    app_env: Literal["dev", "test", "staging", "production"] = "dev"

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

    @model_validator(mode="after")
    def _require_real_jwt_secret(self) -> "Settings":
        """Refuse to load settings (so the API refuses to start: app.config
        resolves them at import) outside dev/test with a weak JWT_SECRET."""
        if self.app_env in ("dev", "test"):
            return self
        if self.jwt_secret in _PLACEHOLDER_JWT_SECRETS:
            problem = "is a placeholder value"
        elif len(self.jwt_secret.encode()) < JWT_SECRET_MIN_BYTES:
            problem = f"is {len(self.jwt_secret.encode())} bytes, below the {JWT_SECRET_MIN_BYTES}-byte minimum"
        else:
            return self
        raise ValueError(
            f"APP_ENV={self.app_env}: JWT_SECRET {problem}. Refusing to start. "
            "Set JWT_SECRET to a random secret (e.g. `openssl rand -hex 32`), "
            "or set APP_ENV=dev for local development."
        )

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
    # Field Log attachments (photos, PDFs; app/field_log/router.py). Stored
    # through the same backend as uploads, under the field-log/ key prefix.
    field_log_attachment_max_mb: int = 25

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

    # Environmental context per upload (Q5, t-1026-1; app/environment/).
    # Looked up in a background task after an upload with coordinates +
    # collected_at; providers and their order are in app/environment/providers.py.
    environment_context_enabled: bool = True
    environment_provider_timeout_s: float = Field(default=15.0, gt=0)  # per HTTP request
    environment_provider_retries: int = Field(default=1, ge=0, le=3)  # extra attempts on network/5xx
    # Coastal samples often fall on a land cell; use the nearest ocean cell
    # within this distance (inside the fetched chunk), else "unavailable".
    environment_max_cell_distance_km: float = Field(default=30.0, gt=0)
    # Optional Copernicus Marine account. Without it the ARCO stores are read
    # anonymously (worked 2026-10-18, undocumented). The toolbox's own env
    # names are accepted too.
    copernicus_marine_username: str = Field(
        default="",
        validation_alias=AliasChoices("COPERNICUS_MARINE_USERNAME", "COPERNICUSMARINE_SERVICE_USERNAME"),
    )
    copernicus_marine_password: str = Field(
        default="",
        validation_alias=AliasChoices("COPERNICUS_MARINE_PASSWORD", "COPERNICUSMARINE_SERVICE_PASSWORD"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Import this, never a bare 0.45. Resolved once at import time, like the
# rest of the settings (get_settings is lru_cached).
NOVELTY_THRESHOLD: float = get_settings().novelty_threshold
