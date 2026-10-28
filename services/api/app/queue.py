"""
Thin API-side Redis client for enqueuing jobs.
The worker has its own Redis module with dequeue + dispatcher logic.
"""
import json
import redis.asyncio as aioredis
from .config import get_settings

QUEUE_KEY = "synthveda:jobs:analysis"

_redis: aioredis.Redis | None = None


async def connect_queue() -> None:
    global _redis
    settings = get_settings()
    redis_url = getattr(settings, "redis_url", "redis://localhost:6379/0")
    _redis = aioredis.from_url(redis_url, decode_responses=True)
    await _redis.ping()


async def close_queue() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def enqueue_job(job_id: str, upload_id: str, mode: str = "online_full") -> None:
    if _redis is None:
        raise RuntimeError("Redis queue not connected")
    envelope = json.dumps({"job_id": job_id, "upload_id": upload_id, "mode": mode})
    await _redis.lpush(QUEUE_KEY, envelope)
