import json
import logging
import uuid
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import safe_decode_token
from app.db.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


@router.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket) -> None:
    subprotocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    token = None
    for p in subprotocols:
        p = p.strip()
        if p.startswith("access."):
            token = p[7:]
            break
    if not token:
        await websocket.close(code=4001)
        return
    payload = safe_decode_token(token)
    if not payload or not payload.get("tenant_id"):
        await websocket.close(code=4001)
        return
    tenant_id = uuid.UUID(payload["tenant_id"])
    await websocket.accept(subprotocol=f"access.{token[:8]}")
    _connections[tenant_id].add(websocket)
    r = get_redis()
    pubsub = r.pubsub()
    channel = f"tenant:{tenant_id}:orders"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        _connections[tenant_id].discard(websocket)
        await pubsub.unsubscribe(channel)
        await pubsub.close()
