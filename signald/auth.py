"""Password-based authentication for SIGNAL."""

import hashlib
import secrets
from pathlib import Path

from signald.config import PASSWORD_FILE


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (salt, hex_hash)."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt, h


def is_password_set() -> bool:
    """Check if a password has been configured."""
    return PASSWORD_FILE.exists()


def verify_password(password: str) -> bool:
    """Check password against stored hash."""
    if not is_password_set():
        return True
    stored = PASSWORD_FILE.read_text().strip()
    salt, expected = stored.split(":", 1)
    _, actual = _hash_password(password, salt)
    return actual == expected


def set_password(password: str):
    """Hash and persist a new password."""
    salt, h = _hash_password(password)
    PASSWORD_FILE.write_text(f"{salt}:{h}")
