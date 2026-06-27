"""Tests for UUIDv7 generation."""

from __future__ import annotations

from ledgerline_backend.db.ids import uuid7, uuid7_str


def test_uuid7_has_version_7() -> None:
    assert uuid7().version == 7


def test_uuid7_has_rfc4122_variant() -> None:
    # RFC 4122 variant is encoded as 0b10 in the high bits of the variant byte.
    assert uuid7().variant == "specified in RFC 4122"


def test_uuid7_encodes_timestamp_in_high_bits() -> None:
    ts = 0x0190_0000_0000  # arbitrary fixed millisecond value
    value = uuid7(_timestamp_ms=ts, _rand=bytes(range(10)))
    extracted = value.int >> 80
    assert extracted == ts


def test_uuid7_is_time_ordered() -> None:
    earlier = uuid7(_timestamp_ms=1000, _rand=bytes(10))
    later = uuid7(_timestamp_ms=2000, _rand=bytes(10))
    assert earlier < later


def test_uuid7_unique_across_calls() -> None:
    ids = {uuid7() for _ in range(1000)}
    assert len(ids) == 1000


def test_uuid7_str_is_canonical() -> None:
    value = uuid7_str()
    assert len(value) == 36
    assert value.count("-") == 4


def test_uuid7_rejects_wrong_random_length() -> None:
    try:
        uuid7(_rand=b"too-short")
    except ValueError:
        return
    raise AssertionError("expected ValueError for wrong random byte length")
