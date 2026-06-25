"""Background worker — provisioning, outbox sync, notifications."""

import asyncio
import json
import logging
import signal
import sys

from app.db.redis_client import get_redis
from app.services.provisioning import (
    QUEUE_KEY,
    process_provision_tenant,
    process_tenant_outboxes,
)

logger = logging.getLogger(__name__)


async def process_job(job: dict) -> None:
    job_type = job.get("type")
    payload = job.get("payload", {})
    if job_type == "provision_tenant":
        await process_provision_tenant(payload)
    elif job_type == "sync_outboxes":
        import uuid

        await process_tenant_outboxes(uuid.UUID(payload["tenant_id"]))
    else:
        logger.warning("Unknown job type: %s", job_type)


async def run_worker() -> None:
    logger.info("Worker started")
    r = get_redis()
    while True:
        try:
            result = await r.brpop(QUEUE_KEY, timeout=5)
            if not result:
                continue
            _, raw = result
            job = json.loads(raw)
            await process_job(job)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Job processing failed")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(*_):
        loop.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        loop.run_until_complete(run_worker())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
