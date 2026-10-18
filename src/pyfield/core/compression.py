"""Record body compression (zlib with a leading u32 decompressed length)."""
from __future__ import annotations

import struct
import zlib

from ..errors import FormatError

# Order to try when looking for a level that reproduces stored bytes exactly.
_LEVEL_SEARCH = (9, 6, 1, 5, 7, 8, 4, 3, 2, 0)


def decompress(stored: bytes | memoryview, offset=None) -> bytes:
    if len(stored) < 4:
        raise FormatError('truncated compressed body', offset)
    expected, = struct.unpack_from('<I', stored)
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(stored[4:]) + decoder.flush()
    except zlib.error as exc:
        raise FormatError(f'invalid zlib body: {exc}', offset) from None
    if len(data) != expected or not decoder.eof:
        raise FormatError(f'decompressed size {len(data)} != declared {expected}', offset)
    return data


def compress(data: bytes, level: int = 6) -> bytes:
    return struct.pack('<I', len(data)) + zlib.compress(data, level)


def detect_level(stored: bytes | memoryview, data: bytes) -> int | None:
    """The zlib level that reproduces `stored` from `data` byte for byte, or None."""
    stored = bytes(stored)
    for level in _LEVEL_SEARCH:
        if compress(data, level) == stored:
            return level
    return None
