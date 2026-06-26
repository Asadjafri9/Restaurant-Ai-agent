import asyncio
import logging
import uuid
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import safe_decode_token
from app.db.redis_client import get_redis, reset_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


async def _redis_forward(pubsub, websocket: WebSocket) -> None:
    """Forward Redis pub/sub messages until cancelled or Redis errors."""
    while True:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        except Exception:
            logger.warning("Redis pubsub read failed; resetting client", exc_info=True)
            reset_redis()
            raise
        if message and message.get("type") == "message":
            await websocket.send_text(message["data"])


@router.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket) -> None:
    subprotocol_header = websocket.headers.get("sec-websocket-protocol", "")
    subprotocols = [p.strip() for p in subprotocol_header.split(",") if p.strip()]
    token = None
    accepted_proto = None
    for p in subprotocols:
        if p.startswith("access."):
            token = p[7:]
            accepted_proto = p
            break
    if not token or not accepted_proto:
        await websocket.close(code=4001)
        return
    payload = safe_decode_token(token)
    if not payload or not payload.get("tenant_id"):
        await websocket.close(code=4001)
        return
    tenant_id = uuid.UUID(payload["tenant_id"])
    # Must echo the client's offered subprotocol exactly (RFC 6455).
    await websocket.accept(subprotocol=accepted_proto)
    _connections[tenant_id].add(websocket)

    channel = f"tenant:{tenant_id}:orders"
    pubsub = None
    listener: asyncio.Task | None = None
    try:
        r = get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        listener = asyncio.create_task(_redis_forward(pubsub, websocket))
        while True:
            try:
                # Detect client disconnect; timeouts keep the loop cancellable on shutdown.
                await asyncio.wait_for(websocket.receive(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket orders session ended", exc_info=True)
    finally:
        _connections[tenant_id].discard(websocket)
        if listener:
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if pubsub:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
