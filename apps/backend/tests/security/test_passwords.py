"""Tests for Argon2id password hashing."""

from __future__ import annotations

import pytest

from ledgerline_backend.security.passwords import (
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_is_not_plaintext() -> None:
    hashed = hash_password("correct horse battery")
    assert "correct horse battery" not in hashed
    assert hashed.startswith("$argon2")


def test_hashes_are_salted_and_unique() -> None:
    a = hash_password("same-password-123")
    b = hash_password("same-password-123")
    assert a != b  # different salts


def test_verify_accepts_correct_password() -> None:
    hashed = hash_password("s3cret-password")
    assert verify_password("s3cret-password", hashed) is True


def test_verify_rejects_wrong_password() -> None:
    hashed = hash_password("s3cret-password")
    assert verify_password("wrong-password", hashed) is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


def test_rejects_too_short_password() -> None:
    with pytest.raises(ValueError, match="length"):
        hash_password("short")


def test_rejects_too_long_password() -> None:
    with pytest.raises(ValueError, match="length"):
        hash_password("x" * 2000)


def test_needs_rehash_false_for_current_hash() -> None:
    assert needs_rehash(hash_password("current-params-pw")) is False


def test_needs_rehash_true_for_invalid_hash() -> None:
    assert needs_rehash("garbage") is True
