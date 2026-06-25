import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.config.settings import settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    role: str,
    tenant_id: uuid.UUID | None = None,
    tenant_slug: str | None = None,
    portal: str | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "tenant_slug": tenant_slug,
        "portal": portal,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_refresh_token(
    *,
    user_id: uuid.UUID,
    jti: str,
    tenant_id: uuid.UUID | None = None,
    portal: str | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "portal": portal,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


def safe_decode_token(token: str) -> dict | None:
    try:
        return decode_token(token)
    except JWTError:
        return None
