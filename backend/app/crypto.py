"""Encrypts DatabaseConnection passwords at rest in the metadata database.

Symmetric (Fernet) rather than hashing, since the raw password must be
recovered to open real pymysql connections. With ENCRYPTION_KEY unset,
falls back to storing/returning values unchanged (dev-only)."""
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import ENCRYPTION_KEY

logger = logging.getLogger(__name__)

_fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None


def encrypt(value: str | None) -> str | None:
    if not value or not _fernet:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value or not _fernet:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        # Pre-existing plain-text value (e.g. saved before ENCRYPTION_KEY was set).
        logger.warning("decrypt: InvalidToken — treating value as pre-existing plaintext")
        return value
