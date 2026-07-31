"""
Worker dispatcher — polls Redis queue and runs jobs concurrently.

Uses asyncio.Semaphore to cap concurrent jobs at WORKER_CONCURRENCY.
Handles graceful shutdown via SIGINT/SIGTERM.
"""
import asyncio
import signal
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from .config import get_worker_settings
from .queue import connect_redis, close_redis, dequeue_job, queue_depth
from .job_runner import run_job


async def _process_loop(db, semaphore: asyncio.Semaphore, shutdown: asyncio.Event) -> None:
    settings = get_worker_settings()
    print("[dispatcher] ready — polling for jobs")

    while not shutdown.is_set():
        envelope = await dequeue_job(timeout=int(settings.poll_interval_seconds))

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
            except Exception:
                pass  # run_job already logs and marks the job failed
            finally:
                semaphore.release()

        asyncio.create_task(_run(job_id))

    print("[dispatcher] shutdown signal received — draining in-flight jobs")
    # Wait for all semaphore slots to be released (all tasks done)
    for _ in range(settings.worker_concurrency):
        await semaphore.acquire()
    print("[dispatcher] all jobs drained — exiting")


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
