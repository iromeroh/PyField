"""Synthetic plugin bytes for tests: small, deterministic, exercising every container feature.

Built with independent struct code (not PyField's writer) so roundtrip tests are not
self-confirming.
"""
from __future__ import annotations

import struct
import zlib


def sub(sig: str, data: bytes) -> bytes:
    if len(data) > 0xFFFF:
        return b'XXXX' + struct.pack('<HI', 4, len(data)) + sig.encode() + struct.pack('<H', 0) + data
    return sig.encode() + struct.pack('<H', len(data)) + data


def z(text: str) -> bytes:
    return text.encode() + b'\0'


def record(sig: str, fid: int, body: bytes, flags: int = 0, header_size: int = 24, compress_level=None) -> bytes:
    if compress_level is not None:
        flags |= 0x40000
        body = struct.pack('<I', len(body)) + zlib.compress(body, compress_level)
    tail = bytes(header_size - 16)
    if header_size == 24:
        tail = struct.pack('<IHH', 0, 582, 0)
    return struct.pack('<4sIII', sig.encode(), len(body), flags, fid) + tail + body


def group(label: bytes | int, kind: int, content: bytes, header_size: int = 24) -> bytes:
    if isinstance(label, int):
        label = struct.pack('<I', label)
    return b'GRUP' + struct.pack('<I4si', header_size + len(content), label, kind) + bytes(header_size - 16) + content


def starfield_plugin(masters=('Starfield.esm',), flags=0x1, count=None, next_id=0x01000805) -> bytes:
    """A Starfield-shaped plugin: KYWD + STAT groups, a CELL hierarchy, a compressed and an XXXX record."""
    own = len(masters) << 24
    kywd = record('KYWD', own | 0x800, sub('EDID', z('PF_Keyword')))
    stat = record('STAT', own | 0x801, sub('EDID', z('PF_Static')) + sub('OBND', bytes(12)) +
                  sub('MODL', z('Meshes\\pf\\box.nif')))
    big = record('STAT', own | 0x802, sub('EDID', z('PF_Big')) + sub('DATA', bytes(range(256)) * 300))
    packed = record('STAT', own | 0x803, sub('EDID', z('PF_Packed')) + sub('DATA', b'abc' * 500), compress_level=9)
    override = record('STAT', 0x00000034, sub('EDID', z('XMarkerHeading')) + sub('OBND', bytes(12)))
    cell = record('CELL', own | 0x804, sub('EDID', z('PF_Cell')) + sub('DATA', struct.pack('<H', 1)))
    refr = record('REFR', own | 0x805, sub('NAME', struct.pack('<I', own | 0x801)) +
                  sub('DATA', struct.pack('<6f', 1, 2, 3, 0, 0, 0.5)))
    children = group(own | 0x804, 6, group(own | 0x804, 8, refr))
    cells = group(b'CELL', 0, group(0, 2, group(0, 3, cell + children)))
    body = (group(b'KYWD', 0, kywd) + group(b'STAT', 0, override + stat + big + packed) + cells)
    n_records, n_groups = 7, 7
    hedr = struct.pack('<fII', 0.96, n_records + n_groups if count is None else count, next_id)
    tes4 = sub('HEDR', hedr) + sub('CNAM', z('PyField')) + b''.join(sub('MAST', z(m)) for m in masters)
    return record('TES4', 0, tes4, flags) + body


def oblivion_plugin() -> bytes:
    """An Oblivion-shaped plugin: 20-byte headers, MAST+DATA, a compressed record."""
    h = 20
    misc = record('MISC', 0x01000800, sub('EDID', z('PF_Misc')) + sub('DATA', struct.pack('<If', 5, 1.0)), header_size=h)
    packed = record('MISC', 0x01000801, sub('EDID', z('PF_Packed')) + sub('DESC', b'x' * 400), header_size=h,
                    compress_level=6)
    body = group(b'MISC', 0, misc + packed, header_size=h)
    tes4 = (sub('HEDR', struct.pack('<fII', 1.0, 3, 0x802)) + sub('CNAM', z('PyField')) +
            sub('MAST', z('Oblivion.esm')) + sub('DATA', bytes(8)))
    return record('TES4', 0, tes4, 0, header_size=h) + body
