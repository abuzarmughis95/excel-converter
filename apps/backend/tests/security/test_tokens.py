"""Tests for access (JWT) and refresh token helpers."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from ledgerline_backend.config import Settings
from ledgerline_backend.security.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", jwt_secret="test-secret-key", access_token_ttl_seconds=900)


def test_access_token_round_trips(settings: Settings) -> None:
    user_id = uuid.uuid4()
    token = create_access_token(settings, user_id)
    assert decode_access_token(settings, token) == user_id


def test_expired_access_token_is_rejected(settings: Settings) -> None:
    user_id = uuid.uuid4()
    past = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=1)
    token = create_access_token(settings, user_id, now=past)
    with pytest.raises(TokenError):
        decode_access_token(settings, token)


def test_token_signed_with_other_key_is_rejected(settings: Settings) -> None:
    other = Settings(environment="test", jwt_secret="a-different-secret")
    token = create_access_token(other, uuid.uuid4())
    with pytest.raises(TokenError):
        decode_access_token(settings, token)


def test_malformed_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(TokenError):
        decode_access_token(settings, "not.a.jwt")


def test_refresh_tokens_are_unique_and_hashable() -> None:
    a = generate_refresh_token()
    b = generate_refresh_token()
    assert a != b
    assert len(hash_refresh_token(a)) == 64  # hex sha-256
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != hash_refresh_token(b)
