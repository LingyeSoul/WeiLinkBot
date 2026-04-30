"""Symmetric encryption for sensitive config values using Fernet."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

SECRET_KEY_PATH = Path("./data/.secret_key")

_fernet: Fernet | None = None


def _load_or_generate_key() -> bytes:
    """Load Fernet key from disk, or generate and persist a new one."""
    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    SECRET_KEY_PATH.write_bytes(key)
    return key


def get_fernet() -> Fernet:
    """Return a module-level cached Fernet instance."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_generate_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string, return base64-encoded ciphertext."""
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string."""
    return get_fernet().decrypt(ciphertext.encode()).decode()


def is_encrypted(value: str) -> bool:
    """Heuristic check: does this look like a Fernet token?"""
    return bool(value) and value.startswith("gAAAAA") and len(value) > 50
