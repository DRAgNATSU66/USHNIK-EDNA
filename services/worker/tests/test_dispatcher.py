"""Dispatcher poll loop: a Redis outage pauses polling instead of ending the process.

On 2026-10-27 the Docker daemon restarted, Redis went away and the native
dispatcher exited on redis.exceptions.ConnectionError (QNA-042 Q6)."""
import asyncio

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app import dispatcher
from app.config import get_worker_settings


def _slots():
    # The drain at shutdown takes worker_concurrency slots.
    return asyncio.Semaphore(get_worker_settings().worker_concurrency)


async def test_redis_outage_backs_off_then_resumes(monkeypatch):
    shutdown = asyncio.Event()
    calls, ran = [], []
    outcomes = [RedisConnectionError("Connection closed by server."), RedisTimeoutError("timed out"),
                {"job_id": "job_after_outage"}]

    async def fake_dequeue(timeout):
        calls.append(timeout)
        if not outcomes:
            shutdown.set()
            return None
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    async def fake_run_job(db, jid):
        ran.append(jid)

    monkeypatch.setattr(dispatcher, "dequeue_job", fake_dequeue)
    monkeypatch.setattr(dispatcher, "run_job", fake_run_job)
    monkeypatch.setattr(dispatcher, "REDIS_RETRY_INITIAL_S", 0.01)

    await asyncio.wait_for(dispatcher._process_loop(None, _slots(), shutdown), timeout=5)

    assert ran == ["job_after_outage"]
    assert len(calls) == 4  # two failures, one job, one empty poll before shutdown


async def test_shutdown_during_backoff_exits_promptly(monkeypatch):
    shutdown = asyncio.Event()

    async def always_down(timeout):
        shutdown.set()  # SIGTERM arrives while Redis is down
        raise RedisConnectionError("down")

    monkeypatch.setattr(dispatcher, "dequeue_job", always_down)
    monkeypatch.setattr(dispatcher, "REDIS_RETRY_INITIAL_S", 60)  # would hang without the shutdown wake-up

    await asyncio.wait_for(dispatcher._process_loop(None, _slots(), shutdown), timeout=5)
