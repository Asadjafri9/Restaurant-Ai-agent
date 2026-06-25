import json
import logging
import uuid

from app.db.redis_client import get_redis

logger = logging.getLogger(__name__)


async def publish_order_event(tenant_id: uuid.UUID, event: dict) -> None:
    channel = f"tenant:{tenant_id}:orders"
    r = get_redis()
    await r.publish(channel, json.dumps(event, default=str))
    logger.info("Published event to %s: %s", channel, event.get("type"))
