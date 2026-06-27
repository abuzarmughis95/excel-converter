"""Password hashing using Argon2id.

Argon2id is the current OWASP-recommended password hashing algorithm. We use the
``argon2-cffi`` low-level hasher with its safe defaults. The verify function is
constant-time within the algorithm and reports when a stored hash should be
re-hashed (e.g. after a parameter upgrade).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# A single configured hasher instance (thread-safe).
_hasher = PasswordHasher()

# Reject absurdly long inputs to avoid CPU-exhaustion via giant passwords.
MAX_PASSWORD_LENGTH = 1024
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash a plaintext password, returning the encoded Argon2id string."""
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        msg = f"Password length must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH}"
        raise ValueError(msg)
    return _hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a plaintext password against an encoded Argon2id hash.

    Returns False on mismatch or malformed hash rather than raising, so callers
    have a single boolean to branch on. Never leaks which part failed.
    """
    try:
        _hasher.verify(encoded_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(encoded_hash: str) -> bool:
    """Whether a stored hash should be upgraded to current parameters."""
    try:
        return _hasher.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        return True
