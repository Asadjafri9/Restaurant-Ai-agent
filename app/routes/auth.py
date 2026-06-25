import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.config.settings import settings
from app.core.portals import PORTALS, user_matches_portal
from app.core.security import (
    create_access_token,
    create_refresh_token,
    safe_decode_token,
    verify_password,
)
from app.db.central import get_central_session
from app.db.models_central import Tenant, User
from app.db.models_tenant import StaffUser
from app.db.redis_client import get_redis
from app.db.standalone import get_standalone_session
from app.deps.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str
    portal: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_slug: str | None = None


def _effective_portal(requested: str) -> str:
    if settings.service_mode == "admin":
        return "admin"
    if settings.is_standalone_tenant:
        return settings.tenant_slug
    return requested.strip().lower()


def _portal_cookie(portal: str) -> str:
    return f"refresh_token_{portal}"


def _cookie_path() -> str:
    return "/"


def _check_portal_access(
    portal: str,
    role: str,
    tenant_id: uuid.UUID | None,
    tenant_slug: str | None,
) -> None:
    if portal not in PORTALS:
        raise HTTPException(status_code=400, detail="Unknown portal")
    if not user_matches_portal(
        role=role,
        tenant_id=str(tenant_id) if tenant_id else None,
        tenant_slug=tenant_slug,
        portal=portal,
    ):
        raise HTTPException(
            status_code=403,
            detail=f"This account cannot sign in to the {PORTALS[portal].name} portal",
        )


def _set_refresh_cookie(response: Response, portal: str, refresh: str) -> None:
    response.set_cookie(
        key=_portal_cookie(portal),
        value=refresh,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 86400,
        path=_cookie_path(),
    )


async def _store_refresh(portal: str, jti: str, user_id: uuid.UUID) -> None:
    if not settings.redis_url:
        return
    r = get_redis()
    await r.setex(f"refresh:{portal}:{jti}", 7 * 86400, str(user_id))


async def _revoke_refresh(portal: str, jti: str) -> None:
    if not settings.redis_url:
        return
    r = get_redis()
    await r.delete(f"refresh:{portal}:{jti}")


async def _verify_refresh_stored(portal: str, jti: str) -> bool:
    if not settings.redis_url:
        return True
    r = get_redis()
    return bool(await r.get(f"refresh:{portal}:{jti}"))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response) -> TokenResponse:
    email = body.email.strip().lower()
    portal = _effective_portal(body.portal)
    password = body.password

    if settings.is_standalone_tenant:
        tenant_id = uuid.UUID(settings.tenant_id)
        tenant_slug = settings.tenant_slug
        session = await get_standalone_session()
        async with session:
            result = await session.execute(select(StaffUser).where(StaffUser.email == email))
            staff = result.scalar_one_or_none()
            if not staff or not staff.is_active or not verify_password(password, staff.password_hash):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            _check_portal_access(portal, staff.role, tenant_id, tenant_slug)
            jti = secrets.token_hex(16)
            access = create_access_token(
                user_id=staff.id,
                email=staff.email,
                role=staff.role,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                portal=portal,
            )
            refresh = create_refresh_token(
                user_id=staff.id, jti=jti, tenant_id=tenant_id, portal=portal
            )
            await _store_refresh(portal, jti, staff.id)
            _set_refresh_cookie(response, portal, refresh)
            return TokenResponse(access_token=access, role=staff.role, tenant_slug=tenant_slug)

    async for session in get_central_session():
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        tenant_slug = None
        if user.tenant_id:
            tenant = await session.get(Tenant, user.tenant_id)
            tenant_slug = tenant.slug if tenant else None
        _check_portal_access(portal, user.role, user.tenant_id, tenant_slug)
        jti = secrets.token_hex(16)
        access = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
            tenant_slug=tenant_slug,
            portal=portal,
        )
        refresh = create_refresh_token(user_id=user.id, jti=jti, tenant_id=user.tenant_id, portal=portal)
        await _store_refresh(portal, jti, user.id)
        _set_refresh_cookie(response, portal, refresh)
        return TokenResponse(access_token=access, role=user.role, tenant_slug=tenant_slug)
    raise HTTPException(status_code=500, detail="Auth error")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, portal: str = "") -> TokenResponse:
    portal = _effective_portal(portal)
    if portal not in PORTALS:
        raise HTTPException(status_code=400, detail="Unknown portal")
    token = request.cookies.get(_portal_cookie(portal))
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    payload = safe_decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("portal") and payload.get("portal") != portal:
        raise HTTPException(status_code=403, detail="Portal mismatch")
    jti = payload["jti"]
    if not await _verify_refresh_stored(portal, jti):
        raise HTTPException(status_code=401, detail="Refresh token revoked")
    await _revoke_refresh(portal, jti)
    user_id = uuid.UUID(payload["sub"])

    if settings.is_standalone_tenant:
        tenant_id = uuid.UUID(settings.tenant_id)
        tenant_slug = settings.tenant_slug
        session = await get_standalone_session()
        async with session:
            staff = await session.get(StaffUser, user_id)
            if not staff or not staff.is_active:
                raise HTTPException(status_code=401, detail="User inactive")
            _check_portal_access(portal, staff.role, tenant_id, tenant_slug)
            new_jti = secrets.token_hex(16)
            access = create_access_token(
                user_id=staff.id,
                email=staff.email,
                role=staff.role,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                portal=portal,
            )
            new_refresh = create_refresh_token(
                user_id=staff.id, jti=new_jti, tenant_id=tenant_id, portal=portal
            )
            await _store_refresh(portal, new_jti, staff.id)
            _set_refresh_cookie(response, portal, new_refresh)
            return TokenResponse(access_token=access, role=staff.role, tenant_slug=tenant_slug)

    async for session in get_central_session():
        user = await session.get(User, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User inactive")
        tenant_slug = None
        if user.tenant_id:
            tenant = await session.get(Tenant, user.tenant_id)
            tenant_slug = tenant.slug if tenant else None
        _check_portal_access(portal, user.role, user.tenant_id, tenant_slug)
        new_jti = secrets.token_hex(16)
        access = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
            tenant_slug=tenant_slug,
            portal=portal,
        )
        new_refresh = create_refresh_token(
            user_id=user.id, jti=new_jti, tenant_id=user.tenant_id, portal=portal
        )
        await _store_refresh(portal, new_jti, user.id)
        _set_refresh_cookie(response, portal, new_refresh)
        return TokenResponse(access_token=access, role=user.role, tenant_slug=tenant_slug)
    raise HTTPException(status_code=500, detail="Auth error")


@router.post("/logout")
async def logout(request: Request, response: Response, portal: str = "") -> dict:
    portal = _effective_portal(portal)
    token = request.cookies.get(_portal_cookie(portal))
    if token:
        payload = safe_decode_token(token)
        if payload and payload.get("jti"):
            await _revoke_refresh(portal, payload["jti"])
    response.delete_cookie(_portal_cookie(portal), path=_cookie_path())
    return {"status": "ok"}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "tenant_slug": user.tenant_slug,
    }
