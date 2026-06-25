import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config.settings import settings
from app.db.redis_client import get_redis, redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

SESSION_TTL = 6 * 3600  # 6 hours


def phone_hash(phone: str) -> str:
  return hmac.new(
      settings.phone_hash_pepper.encode(),
      phone.encode(),
      hashlib.sha256,
  ).hexdigest()


def _session_key(phone: str) -> str:
  return f"conv:{phone_hash(phone)}"


@dataclass
class CustomerSession:
  phone: str
  history: list[dict[str, Any]] = field(default_factory=list)
  confirmed_orders: list[dict[str, Any]] = field(default_factory=list)
  active_tenant_id: str | None = None
  active_tenant_slug: str | None = None
  state: str = "greeting"
  updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _session_to_dict(session: CustomerSession) -> dict[str, Any]:
  return {
      "phone": session.phone,
      "history": session.history,
      "confirmed_orders": session.confirmed_orders,
      "active_tenant_id": session.active_tenant_id,
      "active_tenant_slug": session.active_tenant_slug,
      "state": session.state,
      "updated_at": session.updated_at.isoformat(),
  }


def _dict_to_session(data: dict[str, Any]) -> CustomerSession:
  updated = data.get("updated_at")
  if isinstance(updated, str):
    updated_at = datetime.fromisoformat(updated)
  else:
    updated_at = datetime.now(timezone.utc)
  return CustomerSession(
      phone=data["phone"],
      history=data.get("history", []),
      confirmed_orders=data.get("confirmed_orders", []),
      active_tenant_id=data.get("active_tenant_id"),
      active_tenant_slug=data.get("active_tenant_slug"),
      state=data.get("state", "greeting"),
      updated_at=updated_at,
  )


def _save_session(session: CustomerSession) -> None:
  session.updated_at = datetime.now(timezone.utc)
  try:
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
      asyncio.create_task(redis_set_json(_session_key(session.phone), _session_to_dict(session), SESSION_TTL))
    else:
      loop.run_until_complete(
          redis_set_json(_session_key(session.phone), _session_to_dict(session), SESSION_TTL)
      )
  except RuntimeError:
    pass


async def get_session_async(phone: str) -> CustomerSession:
  data = await redis_get_json(_session_key(phone))
  if data:
    session = _dict_to_session(data)
    session.phone = phone
    return session
  session = CustomerSession(phone=phone)
  await redis_set_json(_session_key(phone), _session_to_dict(session), SESSION_TTL)
  return session


async def save_session_async(session: CustomerSession) -> None:
  session.updated_at = datetime.now(timezone.utc)
  await redis_set_json(_session_key(session.phone), _session_to_dict(session), SESSION_TTL)


async def reset_session_async(phone: str) -> None:
  try:
    r = get_redis()
    await r.delete(_session_key(phone))
  except Exception:
    logger.exception("Failed to reset session for %s", phone_hash(phone))


def get_session(phone: str) -> CustomerSession:
  """Sync wrapper — prefer async in new code."""
  import asyncio

  try:
    loop = asyncio.get_running_loop()
  except RuntimeError:
    return asyncio.run(get_session_async(phone))

  # In async context, use in-memory fallback for sync callers (legacy agent)
  if not hasattr(get_session, "_fallback"):
    get_session._fallback = {}  # type: ignore[attr-defined]
  fb: dict[str, CustomerSession] = get_session._fallback  # type: ignore[attr-defined]
  if phone not in fb:
    fb[phone] = CustomerSession(phone=phone)
  session = fb[phone]
  session.updated_at = datetime.now(timezone.utc)
  # Also try to persist async
  loop.create_task(save_session_async(session))
  return session


def reset_session(phone: str) -> None:
  import asyncio

  if hasattr(get_session, "_fallback"):
    get_session._fallback.pop(phone, None)  # type: ignore[attr-defined]
  try:
    loop = asyncio.get_running_loop()
    loop.create_task(reset_session_async(phone))
  except RuntimeError:
    asyncio.run(reset_session_async(phone))


def save_confirmed_order(phone: str, order: dict[str, Any]) -> None:
  session = get_session(phone)
  session.confirmed_orders.append(order)
  import asyncio

  try:
    loop = asyncio.get_running_loop()
    loop.create_task(save_session_async(session))
  except RuntimeError:
    asyncio.run(save_session_async(session))
