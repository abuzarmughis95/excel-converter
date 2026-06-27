"""UUIDv7 generation (RFC 9562).

UUIDv7 is time-ordered: the first 48 bits are a Unix millisecond timestamp,
which makes primary keys monotonically increasing (good for B-tree locality)
while remaining globally unique. This lets the offline desktop mint ids that
will not collide on sync, yet still sort by creation time.

``uuid.uuid7`` only exists in CPython 3.14+, so we implement the layout here to
support the 3.12 baseline. Both code paths are exercised by tests.
"""

from __future__ import annotations

import os
import time
from uuid import UUID


def uuid7(*, _timestamp_ms: int | None = None, _rand: bytes | None = None) -> UUID:
    """Generate a UUIDv7.

    Args:
        _timestamp_ms: Override the millisecond timestamp (testing only).
        _rand: Override the 10 random bytes (testing only).

    Returns:
        A version-7, RFC 4122 variant UUID.
    """
    timestamp_ms = _timestamp_ms if _timestamp_ms is not None else time.time_ns() // 1_000_000
    rand = _rand if _rand is not None else os.urandom(10)
    if len(rand) != 10:
        msg = "uuid7 requires exactly 10 random bytes"
        raise ValueError(msg)

    # 48-bit timestamp, big-endian.
    value = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    # 4-bit version (7) + 12 bits of randomness.
    value |= 0x7 << 76
    value |= (rand[0] & 0x0F) << 72
    value |= rand[1] << 64
    # 2-bit variant (0b10) + remaining randomness.
    value |= 0b10 << 62
    value |= (rand[2] & 0x3F) << 56
    for i in range(3, 10):
        value |= rand[i] << (56 - (i - 2) * 8)

    return UUID(int=value)


def uuid7_str() -> str:
    """Generate a UUIDv7 as its canonical string form."""
    return str(uuid7())
