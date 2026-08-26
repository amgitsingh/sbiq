from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import settings

# Ported from IndMatchmaking (D:\Python\IndMatchmaking\src\app\lib\security.py)
# as part of docs/PLAN.md Phase 8. JWT + password hashing landed in Task 55;
# encrypt_credential/decrypt_credential (below) were originally deferred to
# Task 60, but pulled forward while porting Task 57's registrations domain -
# activate_registration can't function without decrypting an admin's stored
# SMTP password to send the activation email.

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain text password."""
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plain text password against a hash."""
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Create a signed access token."""
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": subject, "exp": expires_at}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a signed access token."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def _credential_cipher() -> Fernet:
    if settings.SMTP_ENCRYPTION_KEY:
        return Fernet(settings.SMTP_ENCRYPTION_KEY.encode())
    digest = hashlib.sha256(settings.JWT_SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credential(value: str) -> str:
    """Encrypt a reversible service credential (e.g. SmtpMaster.password_encrypted) for database storage."""
    return _credential_cipher().encrypt(value.encode()).decode()


def decrypt_credential(value: str) -> str:
    """Decrypt a stored service credential."""
    try:
        return _credential_cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored credential cannot be decrypted") from exc
