"""BA2 archives (Fallout 4 / Starfield "BTDX"): read GNRL and DX10, write uncompressed GNRL.

Reader adapted from the workspace's proven bolero/ScreenSFSE `ba2.py` (GNRL v1-3, DX10 with
LZ4 block or zlib chunks, DDS header reconstruction for textures).

The writer is for tests and an experimental fallback only: production archives are built
with the game's Archive2.exe (see pyfield.assets.pack). Member names are stored as given
(normalized to backslashes); name/directory hashes are zero, which PyField's reader does not
need but the game does — never ship archives from this writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

from ..errors import FormatError


def normalize(name: str) -> str:
    """Archive member key: forward slashes, lower case, no leading 'data/'."""
    name = name.replace('\\', '/').lstrip('/').lower()
    return name[5:] if name.startswith('data/') else name


def lz4_block(src: bytes, size: int) -> bytes:
    """Decode one LZ4 block (no frame header) to `size` bytes."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - offset
        if offset >= ml:
            out += out[start:start + ml]
        else:
            for k in range(ml):
                out.append(out[start + k])
    if len(out) != size:
        raise FormatError(f'LZ4 block decoded to {len(out)} bytes, expected {size}')
    return bytes(out)


BLOCK_BYTES = {70: 8, 71: 8, 72: 8, 79: 8, 80: 8, 81: 8, 73: 16, 74: 16, 75: 16, 76: 16, 77: 16, 78: 16,
               82: 16, 83: 16, 84: 16, 94: 16, 95: 16, 96: 16, 97: 16, 98: 16, 99: 16}
PIXEL_BYTES = {28: 4, 29: 4, 87: 4, 91: 4, 61: 1, 49: 2, 10: 8, 2: 16, 24: 4, 56: 2}


def dds_header(width, height, mips, dxgi, cubemap) -> bytes:
    if dxgi in BLOCK_BYTES:
        pitch = max(1, (width + 3) // 4) * BLOCK_BYTES[dxgi] * max(1, (height + 3) // 4)
        flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    else:
        pitch = width * PIXEL_BYTES.get(dxgi, 4)
        flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8
    caps = 0x1000 | (0x400008 if mips > 1 else 0) | (0x8 if cubemap else 0)
    caps2 = 0xFE00 if cubemap else 0
    head = struct.pack('<4sIIIIIII44x', b'DDS ', 124, flags, height, width, pitch, 0, mips)
    pf = struct.pack('<II4s20x', 32, 0x4, b'DX10')
    head += pf + struct.pack('<IIII4x', caps, caps2, 0, 0)
    return head + struct.pack('<IIIII', dxgi, 3, 0x4 if cubemap else 0, 1, 0)


@dataclass
class Member:
    name: str                 # normalized key
    stored_name: str          # as written in the archive's name table
    kind: str                 # 'GNRL' or 'DX10'
    info: tuple


class Archive:
    """One BA2 file. `members` maps normalized names to Member."""

    def __init__(self, path):
        self.path = Path(path)
        self.members: dict[str, Member] = {}
        with open(self.path, 'rb') as f:
            head = f.read(36)
            if len(head) < 24 or head[:4] != b'BTDX':
                raise FormatError(f'{self.path.name}: not a BA2 archive')
            _, self.version, kind, count, table = struct.unpack_from('<4sI4sIQ', head)
            self.kind = kind.decode('latin-1')
            header = 24 + (8 if self.version >= 2 else 0) + (4 if self.version == 3 else 0)
            self.compression = struct.unpack_from('<I', head, 32)[0] if self.version == 3 else 0
            f.seek(header)
            records = []
            if self.kind == 'GNRL':
                for _ in range(count):
                    _, _, _, _, offset, packed, size, _ = struct.unpack('<I4sIIQIII', f.read(36))
                    records.append(('GNRL', (offset, packed, size)))
            elif self.kind == 'DX10':
                for _ in range(count):
                    _, _, _, _, nchunks, _, h, w, mips, fmt, cube, _ = struct.unpack('<I4sIBBHHHBBBB', f.read(24))
                    chunks = [struct.unpack('<QIIHHI', f.read(24)) for _ in range(nchunks)]
                    records.append(('DX10', ((w, h, mips, fmt, cube), chunks)))
            else:
                raise FormatError(f'{self.path.name}: unsupported BA2 type {self.kind}')
            f.seek(table)
            for kind_, info in records:
                n, = struct.unpack('<H', f.read(2))
                stored = f.read(n).decode('utf-8', 'replace')
                key = normalize(stored)
                self.members[key] = Member(key, stored, kind_, info)

    def __contains__(self, name):
        return normalize(name) in self.members

    def names(self) -> list[str]:
        return sorted(self.members)

    def _unpack(self, f, offset, packed, size):
        f.seek(offset)
        if not packed:
            return f.read(size)
        data = f.read(packed)
        if self.compression == 3:
            return lz4_block(data, size)
        return zlib.decompress(data)

    def read(self, name: str) -> bytes:
        m = self.members[normalize(name)]
        with open(self.path, 'rb') as f:
            if m.kind == 'GNRL':
                return self._unpack(f, *m.info)
            (w, h, mips, fmt, cube), chunks = m.info
            body = b''.join(self._unpack(f, off, packed, size) for off, packed, size, _, _, _ in chunks)
            return dds_header(w, h, mips, fmt, cube) + body

    def __repr__(self):
        return f'<Archive {self.path.name} {self.kind} {len(self.members)} members>'


def write_gnrl(path, files: dict[str, bytes], version: int = 2):
    """Experimental: uncompressed GNRL archive (tests/fallback only; hashes are zero)."""
    names = sorted(files)
    header_size = 24 + (8 if version >= 2 else 0) + (4 if version == 3 else 0)
    data_offset = header_size + 36 * len(names)
    entries, blobs, offset = [], [], data_offset
    for name in names:
        data = files[name]
        ext = (name.rsplit('.', 1)[-1] if '.' in name else '').encode('latin-1')[:4].ljust(4, b'\0')
        entries.append(struct.pack('<I4sIIQIII', 0, ext, 0, 0, offset, 0, len(data), 0xBAADF00D))
        blobs.append(data)
        offset += len(data)
    table = offset
    out = bytearray(struct.pack('<4sI4sIQ', b'BTDX', version, b'GNRL', len(names), table))
    if version >= 2:
        out += struct.pack('<II', 1, 0)
    if version == 3:
        out += struct.pack('<I', 0)
    for e in entries:
        out += e
    for b in blobs:
        out += b
    for name in names:
        stored = name.replace('/', '\\').encode('utf-8')
        out += struct.pack('<H', len(stored)) + stored
    Path(path).write_bytes(bytes(out))
