"""
Redis-backed job queue.

Jobs are stored as JSON strings in a Redis list (LPUSH / BRPOP).
Key: synthveda:jobs:analysis

Each entry is a minimal envelope:
  {"job_id": "job_abc123", "upload_id": "upl_...", "mode": "online_full"}

The worker fetches the full job document from MongoDB once it dequeues
the envelope — the queue only carries the routing key, not the payload.
"""
import json
from typing import Any

import redis.asyncio as aioredis

from .config import get_worker_settings

QUEUE_KEY = "synthveda:jobs:analysis"

_redis: aioredis.Redis | None = None


async def connect_redis() -> None:
    global _redis
    settings = get_worker_settings()
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not connected. Call connect_redis() first.")
    return _redis


async def enqueue_job(job_id: str, upload_id: str, mode: str = "online_full") -> None:
    """Push a job envelope onto the queue. Called by the API after creating a job doc."""
    r = get_redis()
    envelope = json.dumps({"job_id": job_id, "upload_id": upload_id, "mode": mode})
    await r.lpush(QUEUE_KEY, envelope)


async def dequeue_job(timeout: int = 2) -> dict[str, Any] | None:
    """
    Block-pop the next job from the queue.
    Returns the parsed envelope dict, or None on timeout.
    """
    r = get_redis()
    result = await r.brpop(QUEUE_KEY, timeout=timeout)
    if result is None:
        return None
    _key, raw = result
    return json.loads(raw)


async def queue_depth() -> int:
    """Return current number of pending jobs in the queue."""
    r = get_redis()
    return await r.llen(QUEUE_KEY)
