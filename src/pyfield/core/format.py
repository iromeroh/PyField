"""Physical container format of a record/group plugin file, without game semantics.

A `FormatSpec` describes only what the generic reader/writer needs to walk bytes:
header sizes, signatures, the compression flag and the extended-size subrecord.
Concrete specs live with the adapters (e.g. pyfield.games.tes4family).

Fixed assumptions of the core (true for every supported format): each header starts with
a 4-byte signature and a u32 size; record headers continue with u32 flags and u32 FormID;
group headers continue with a 4-byte label and an i32 kind.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class FormatSpec:
    name: str
    record_header_size: int            # bytes; body length at +4 excludes the header
    group_header_size: int             # bytes; group length at +4 includes the header
    plugin_header_signature: bytes     # signature of the file's first (header) record
    group_signature: bytes
    compressed_flag: int               # record header flag: body = u32 size + zlib stream (0: none)
    extended_size_signature: bytes | None  # subrecord carrying the u32 size of the next one
    subrecord_size_format: str = '<H'  # width of the ordinary subrecord length field
    zlib_level: int = 6                # level used for newly compressed bodies
    editor_id_signature: str | None = None  # subrecord holding a record's editor ID

    @property
    def subrecord_header_size(self) -> int:
        return 4 + struct.calcsize(self.subrecord_size_format)

    @property
    def max_subrecord_size(self) -> int:
        """Largest payload the ordinary size field can hold (larger needs the extended field)."""
        return (1 << (8 * struct.calcsize(self.subrecord_size_format))) - 1
