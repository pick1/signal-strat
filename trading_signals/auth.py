"""
Authentication for TRADING SIGNALS.

SHA256-gated password access, same pattern as the original SIGNAL project.
"""

import hashlib
import os
from pathlib import Path

from trading_signals.config import PASSWORD_FILE


def is_password_set() -> bool:
    """Check if a password hash file exists."""
    return PASSWORD_FILE.is_file() and PASSWORD_FILE.read_text().strip() != ""


def verify_password(password: str) -> bool:
    """Verify a password against the stored SHA256 hash."""
    if not is_password_set():
        return True
    stored = PASSWORD_FILE.read_text().strip()
    return hashlib.sha256(password.encode()).hexdigest() == stored


def set_password(password: str) -> bool:
    """Set a new password (hashed)."""
    if len(password) < 4:
        return False
    PASSWORD_FILE.write_text(hashlib.sha256(password.encode()).hexdigest())
    return True
