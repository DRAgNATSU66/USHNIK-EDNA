"""JWT_SECRET startup check (B18, app/config.py).

Outside APP_ENV=dev/test, Settings refuses a placeholder or short secret.
app.config resolves Settings at import, so this is what stops the API booting.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import JWT_SECRET_MIN_BYTES, Settings

GOOD_SECRET = "a" * JWT_SECRET_MIN_BYTES
API_DIR = Path(__file__).resolve().parents[1]


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_default_env_is_dev_and_accepts_the_default_secret():
    s = _settings()
    assert s.app_env == "dev"
    assert s.jwt_secret == "change-me-in-production"


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_and_test_skip_the_check(env):
    assert _settings(app_env=env, jwt_secret="short").jwt_secret == "short"


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize(
    "secret, reason",
    [
        ("change-me-in-production", "placeholder"),
        ("change-me-to-a-random-256-bit-secret", "placeholder"),  # .env.example
        ("x" * (JWT_SECRET_MIN_BYTES - 1), "below the 32-byte minimum"),
        ("", "below the 32-byte minimum"),
    ],
)
def test_non_dev_rejects_weak_secrets(env, secret, reason):
    with pytest.raises(ValidationError) as exc:
        _settings(app_env=env, jwt_secret=secret)
    msg = str(exc.value)
    assert reason in msg
    assert f"APP_ENV={env}" in msg
    assert "Refusing to start" in msg


def test_length_is_counted_in_bytes():
    # 16 two-byte characters = 32 bytes: accepted.
    assert _settings(app_env="production", jwt_secret="é" * 16)


def test_production_accepts_a_long_random_secret():
    assert _settings(app_env="production", jwt_secret=GOOD_SECRET).jwt_secret == GOOD_SECRET


def test_unknown_app_env_is_rejected():
    with pytest.raises(ValidationError):
        _settings(app_env="prod")


def test_app_env_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
    with pytest.raises(ValidationError):
        _settings()


def test_api_refuses_to_import_in_production_with_default_secret():
    """End to end: importing the app (what uvicorn does) fails loudly."""
    env = {"APP_ENV": "production", "PATH": "", "PYTHONPATH": str(API_DIR)}
    r = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_DIR / "tests",  # no .env here
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode != 0
    assert "JWT_SECRET is a placeholder value. Refusing to start." in r.stderr
