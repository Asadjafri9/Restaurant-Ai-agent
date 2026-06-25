import uuid
from dataclasses import dataclass

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portals import PORTALS, user_matches_portal
from app.core.security import safe_decode_token
from app.db.central import get_central_session
from app.db.models_central import Tenant, User

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: uuid.UUID
    email: str
    role: str
    tenant_id: uuid.UUID | None
    tenant_slug: str | None
    portal: str | None = None


def _validate_portal(request: Request, user: CurrentUser) -> None:
    portal = request.headers.get("X-Portal-Id", "").strip().lower()
    if not portal:
        return
    if portal not in PORTALS:
        raise HTTPException(status_code=403, detail="Invalid portal")
    if user.portal and user.portal != portal:
        raise HTTPException(status_code=403, detail="Portal token mismatch")
    if not user_matches_portal(
        role=user.role,
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
        tenant_slug=user.tenant_slug,
        portal=portal,
    ):
        raise HTTPException(status_code=403, detail="Portal access denied")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = safe_decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    tenant_id = payload.get("tenant_id")
    user = CurrentUser(
        id=uuid.UUID(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        tenant_slug=payload.get("tenant_slug"),
        portal=payload.get("portal"),
    )
    _validate_portal(request, user)
    return user


def require_role(*roles: str):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return checker


def subdomain_of(request: Request) -> str | None:
    host = request.headers.get("host", "").split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] not in ("www", "api", "admin"):
        return parts[0]
    return None


@dataclass
class TenantContext:
    tenant_id: uuid.UUID
    tenant_slug: str
    session: AsyncSession


async def get_tenant_ctx(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> AsyncGenerator[TenantContext, None]:
    from app.config.settings import settings

    if user.tenant_id is None:
        raise HTTPException(status_code=403, detail="No tenant scope")
    host_slug = subdomain_of(request)
    if host_slug and user.tenant_slug and host_slug != user.tenant_slug:
        raise HTTPException(status_code=403, detail="Tenant/host mismatch")

    if settings.is_standalone_tenant:
        from app.db.standalone import get_standalone_session

        session = await get_standalone_session()
        slug = settings.tenant_slug
        tenant_id = uuid.UUID(settings.tenant_id)
    else:
        from app.db.tenant_router import get_tenant_session

        session = await get_tenant_session(user.tenant_id)
        slug = user.tenant_slug or ""
        tenant_id = user.tenant_id
        if not slug:
            async for cs in get_central_session():
                t = await cs.get(Tenant, user.tenant_id)
                slug = t.slug if t else ""
    try:
        yield TenantContext(tenant_id=tenant_id, tenant_slug=slug, session=session)
    finally:
        await session.close()
