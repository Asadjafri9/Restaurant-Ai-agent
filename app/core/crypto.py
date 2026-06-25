from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings


def _fernet() -> Fernet | None:
    if not settings.fernet_key:
        return None
    return Fernet(settings.fernet_key.encode() if isinstance(settings.fernet_key, str) else settings.fernet_key)


def encrypt_secret(plaintext: str) -> bytes:
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY not configured")
    return f.encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY not configured")
    try:
        return f.decrypt(ciphertext).decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt secret") from None
