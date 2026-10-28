"""
Worker dispatcher — polls Redis queue and runs jobs concurrently.

Uses asyncio.Semaphore to cap concurrent jobs at WORKER_CONCURRENCY.
Handles graceful shutdown via SIGINT/SIGTERM.
"""
import asyncio
import signal
import sys

from motor.motor_asyncio import AsyncIOMotorClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .config import get_worker_settings
from .queue import connect_redis, close_redis, dequeue_job, queue_depth
from .job_runner import run_job

# Backoff while Redis is unreachable: doubles up to the cap. The client's pool
# opens a fresh connection on the next BRPOP once Redis is back.
REDIS_RETRY_INITIAL_S = 1.0
REDIS_RETRY_MAX_S = 30.0


async def _process_loop(db, semaphore: asyncio.Semaphore, shutdown: asyncio.Event) -> None:
    settings = get_worker_settings()
    print("[dispatcher] ready — polling for jobs")
    retry_s = None  # None while Redis answers

    while not shutdown.is_set():
        try:
            envelope = await dequeue_job(timeout=int(settings.poll_interval_seconds))
        except (RedisConnectionError, RedisTimeoutError) as exc:
            # A Redis restart used to end the process here (QNA-042 Q6). Wait
            # and retry instead; a shutdown signal cuts the wait short.
            retry_s = REDIS_RETRY_INITIAL_S if retry_s is None else min(retry_s * 2, REDIS_RETRY_MAX_S)
            print(f"[dispatcher] Redis unavailable ({type(exc).__name__}: {exc}) — retrying in {retry_s:g}s")
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=retry_s)
            except asyncio.TimeoutError:
                pass
            continue
        if retry_s is not None:
            print("[dispatcher] Redis reachable again — polling resumed")
            retry_s = None

        if envelope is None:
            continue

        job_id = envelope.get("job_id")
        if not job_id:
            print(f"[dispatcher] malformed envelope: {envelope}")
            continue

        await semaphore.acquire()

        async def _run(jid: str) -> None:
            try:
                await run_job(db, jid)
            except Exception as exc:
                # run_job already marks the job failed for pipeline errors; this
                # line also surfaces the ones it can't (Mongo down before the
                # try, _fail_job itself failing). Never re-raise: one bad job
                # must not kill the poll loop.
                print(f"[dispatcher] job {jid} raised {type(exc).__name__}: {exc}")
            finally:
                semaphore.release()

        asyncio.create_task(_run(job_id))

    print("[dispatcher] shutdown signal received — draining in-flight jobs")
    # Wait for all semaphore slots to be released (all tasks done)
    for _ in range(settings.worker_concurrency):
        await semaphore.acquire()
    print("[dispatcher] all jobs drained — exiting")


def health_check() -> None:
    """
    Liveness check invoked by the Dockerfile HEALTHCHECK.

    Runs as a fresh, separate process each time (Docker can't introspect the
    running dispatcher directly), so it re-verifies Redis and Mongo are
    reachable with the current settings rather than checking in-process
    state. Raises on failure; the HEALTHCHECK CMD's non-zero exit marks the
    container unhealthy.
    """
    import redis as redis_sync
    from pymongo import MongoClient

    settings = get_worker_settings()
    redis_sync.from_url(settings.redis_url).ping()
    MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000).admin.command("ping")


async def main() -> None:
    settings = get_worker_settings()

    mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    db = mongo_client[settings.mongodb_db]

    await connect_redis()
    depth = await queue_depth()
    print(f"[dispatcher] connected — {depth} jobs already queued")

    semaphore = asyncio.Semaphore(settings.worker_concurrency)
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _signal_handler():
        print("[dispatcher] shutdown requested")
        shutdown.set()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
        loop.add_signal_handler(signal.SIGINT, _signal_handler)

    try:
        await _process_loop(db, semaphore, shutdown)
    finally:
        await close_redis()
        mongo_client.close()
        print("[dispatcher] clean exit")


if __name__ == "__main__":
    asyncio.run(main())
