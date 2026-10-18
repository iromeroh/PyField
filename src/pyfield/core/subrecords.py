"""Ordered subrecord lists.

A record body is a sequence of (signature, payload) fields. Order and repetition carry
meaning, so the canonical representation is a list, never a dict. Payloads larger than
the ordinary size field are preceded by an extended-size field (`XXXX`, u32 size) and
written with a zero ordinary size.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import FormatError
from .format import FormatSpec


@dataclass(slots=True)
class Subrecord:
    signature: str
    data: bytes

    def __repr__(self):
        preview = self.data[:16].hex()
        return f'Subrecord({self.signature}, {len(self.data)}B {preview}{"…" if len(self.data) > 16 else ""})'


def parse(body: bytes | memoryview, spec: FormatSpec, offset=None) -> list[Subrecord]:
    out = []
    pos, end = 0, len(body)
    size_fmt = spec.subrecord_size_format
    head = spec.subrecord_header_size
    ext = spec.extended_size_signature
    while pos < end:
        if pos + head > end:
            raise FormatError(f'truncated subrecord header (field {len(out)})', offset)
        sig = bytes(body[pos:pos + 4])
        size, = struct.unpack_from(size_fmt, body, pos + 4)
        pos += head
        if ext is not None and sig == ext:
            if size != 4 or pos + 4 + head > end:
                raise FormatError('malformed extended-size field', offset)
            size, = struct.unpack_from('<I', body, pos)
            sig = bytes(body[pos + 4:pos + 8])
            pos += 4 + head   # the following header's own size field is ignored (written as 0)
            if sig == ext:
                raise FormatError('nested extended-size field', offset)
        if pos + size > end:
            raise FormatError(f'subrecord {sig!r} exceeds body', offset)
        out.append(Subrecord(sig.decode('latin-1'), bytes(body[pos:pos + size])))
        pos += size
    return out


def encode(fields, spec: FormatSpec) -> bytes:
    out = bytearray()
    size_fmt = spec.subrecord_size_format
    limit = spec.max_subrecord_size
    for field in fields:
        sig = field.signature.encode('latin-1')
        if len(sig) != 4:
            raise FormatError(f'subrecord signature must be 4 bytes: {field.signature!r}')
        data = field.data
        if len(data) > limit and spec.extended_size_signature is None:
            raise FormatError(f'subrecord {field.signature} too large ({len(data)} bytes) for this format')
        if len(data) > limit:
            out += spec.extended_size_signature + struct.pack(size_fmt, 4) + struct.pack('<I', len(data))
            out += sig + struct.pack(size_fmt, 0) + data
        else:
            out += sig + struct.pack(size_fmt, len(data)) + data
    return bytes(out)
