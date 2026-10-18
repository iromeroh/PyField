"""Starfield terrain heightfields (`.btd`, "BTDB" versions 4-6) — decoded 2026-10-15.

Layout (docs/formats/starfield-terrain.md):

    0   'BTDB', u32 version (6), f32 height_min, f32 height_max, u32 width, u32 height (samples)
    24  4 × u32 (zero in every file seen)
    40  u32 n_ltex, n_ltex × u32 land texture FormIDs (file-relative to Starfield.esm)
    ..  cells × (f32 min, f32 max)            per-cell height range, cells row-major
    ..  cells × 288 bytes of opaque per-cell data (texture palettes and more; preserved)
    ..  chunks × (u32 offset, u32 size)       directory, offsets relative to the chunk chain
    ..  chunks × zlib stream → 65,536 bytes   128 × 128 u16 heights + 128 × 128 u16 auxiliary

Chunks are ordered coarse LOD first. LOD k has ceil(cells / 2^k) chunks per axis, each covering
2^k × 2^k cells by exact decimation of LOD0 (every 2^k-th sample), zero-padded beyond the edge;
4 levels (k = 3..0). Heights = height_min + u16 / 65535 · (height_max − height_min).
Spatially: 128 samples per 100 m cell, sample i at the cell corner + i · 100/128 m; rows toward +y.
The auxiliary channel's meaning is unknown (probably texture blending) and is preserved.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import math
import struct
import zlib

from ...errors import FormatError
from ...landscape.heightfield import Heightfield

CHUNK = 128
CELL_METRES = 100.0
SPACING = CELL_METRES / CHUNK
LOD_LEVELS = 4
CHUNK_BYTES = 2 * CHUNK * CHUNK * 2
CELL_DATA_BYTES = 288


def lod_grid(cells_x: int, cells_y: int, k: int) -> tuple[int, int]:
    return math.ceil(cells_x / 2 ** k), math.ceil(cells_y / 2 ** k)


@dataclass
class BtdFile:
    version: int
    height_min: float
    height_max: float
    width: int
    height: int
    reserved: bytes                      # 16 bytes after the dimensions
    ltex: list                           # raw u32 FormIDs
    cell_ranges: list                    # [(min, max)] per cell, row-major
    opaque: bytes                        # per-cell data between the range table and the directory
    stored: list                         # compressed chunk bytes, as in the file (coarse LOD first)
    _chunks: dict = field(default_factory=dict, repr=False)     # index -> decompressed bytearray
    _dirty: set = field(default_factory=set, repr=False)

    # -- geometry ---------------------------------------------------------------------------
    @property
    def cells(self) -> tuple[int, int]:
        return self.width // CHUNK, self.height // CHUNK

    @property
    def scale(self) -> float:
        return (self.height_max - self.height_min) / 65535.0

    def lod_layout(self) -> list[tuple[int, int, int, int]]:
        """[(k, first chunk index, chunks_x, chunks_y)] in file order (coarse first)."""
        cx, cy = self.cells
        out, start = [], 0
        for k in range(LOD_LEVELS - 1, -1, -1):
            nx, ny = lod_grid(cx, cy, k)
            out.append((k, start, nx, ny))
            start += nx * ny
        return out

    def lod0_index(self, cell_x: int, cell_y: int) -> int:
        k, first, nx, ny = self.lod_layout()[-1]
        return first + cell_y * nx + cell_x

    # -- parse ----------------------------------------------------------------------------------
    @classmethod
    def parse(cls, data: bytes) -> 'BtdFile':
        if data[:4] != b'BTDB':
            raise FormatError('not a BTDB terrain file')
        _, version, hmin, hmax, w, h = struct.unpack_from('<4sIffII', data, 0)
        if version not in (4, 5, 6) or w % CHUNK or h % CHUNK:        # all share this layout
            raise FormatError(f'unsupported BTDB version {version} or size {w}x{h}')
        reserved = data[24:40]
        ntex, = struct.unpack_from('<I', data, 40)
        ltex = list(struct.unpack_from(f'<{ntex}I', data, 44))
        cx, cy = w // CHUNK, h // CHUNK
        pos = 44 + 4 * ntex
        ranges = [struct.unpack_from('<ff', data, pos + 8 * i) for i in range(cx * cy)]
        pos += 8 * cx * cy
        count = sum(a * b for a, b in (lod_grid(cx, cy, k) for k in range(LOD_LEVELS)))
        dir_at = pos + CELL_DATA_BYTES * cx * cy          # 288 bytes per cell in all 1,999 vanilla files
        if not cls._directory_ok(data, dir_at, count):
            dir_at = cls._find_directory(data, pos, count)
        if dir_at is None:
            raise FormatError(f'chunk directory ({count} entries) not found')
        chain = dir_at + 8 * count
        stored = []
        for i in range(count):
            off, size = struct.unpack_from('<II', data, dir_at + 8 * i)
            stored.append(bytes(data[chain + off:chain + off + size]))
        return cls(version, hmin, hmax, w, h, bytes(reserved), ltex, ranges, bytes(data[pos:dir_at]), stored)

    @staticmethod
    def _directory_ok(data, at: int, count: int) -> bool:
        if at + 8 * count > len(data):
            return False
        end = 0
        for i in range(count):
            off, size = struct.unpack_from('<II', data, at + 8 * i)
            if off != end:
                return False
            end = off + size
        return at + 8 * count + end == len(data)

    @staticmethod
    def _find_directory(data, start: int, count: int):
        limit = len(data) - 8 * count
        for at in range(start, limit + 1, 4):
            off0, size0 = struct.unpack_from('<II', data, at)
            if off0 != 0 or size0 == 0:
                continue
            end = 0
            for i in range(count):
                off, size = struct.unpack_from('<II', data, at + 8 * i)
                if off != end:
                    break
                end = off + size
            else:
                if at + 8 * count + end == len(data):
                    return at
        return None

    # -- chunks ------------------------------------------------------------------------------
    def chunk(self, index: int) -> bytearray:
        if index not in self._chunks:
            raw = zlib.decompress(self.stored[index])
            if len(raw) != CHUNK_BYTES:
                raise FormatError(f'chunk {index} inflates to {len(raw)} bytes')
            self._chunks[index] = bytearray(raw)
        return self._chunks[index]

    def chunk_heights_u16(self, index: int) -> array:
        a = array('H')
        a.frombytes(bytes(self.chunk(index)[:CHUNK * CHUNK * 2]))
        return a

    # -- heightfield ---------------------------------------------------------------------------
    def heightfield(self, origin_cell: tuple[int, int]) -> Heightfield:
        """LOD0 heights as a Heightfield; origin_cell = world grid of the file's first cell."""
        cx, cy = self.cells
        hf = Heightfield(self.width, self.height, SPACING,
                         (origin_cell[0] * CELL_METRES, origin_cell[1] * CELL_METRES))
        vals, scale, hmin = hf.values, self.scale, self.height_min
        for y in range(cy):
            for x in range(cx):
                u16 = self.chunk_heights_u16(self.lod0_index(x, y))
                for sy in range(CHUNK):
                    row = (y * CHUNK + sy) * self.width + x * CHUNK
                    src = sy * CHUNK
                    for sx in range(CHUNK):
                        vals[row + sx] = hmin + u16[src + sx] * scale
        return hf

    def apply_heightfield(self, hf: Heightfield, changed: set | None = None):
        """Write heights back (only cells touched by `changed` sample indices, if given)."""
        if (hf.width, hf.height) != (self.width, self.height):
            raise FormatError('heightfield size differs from the terrain file')
        cx, cy = self.cells
        lo, hi = min(hf.values), max(hf.values)
        requantize = lo < self.height_min - 1e-6 or hi > self.height_max + 1e-6
        if requantize:
            self.height_min, self.height_max = min(lo, self.height_min), max(hi, self.height_max)
            cells = {(x, y) for y in range(cy) for x in range(cx)}
        elif changed is None:
            cells = {(x, y) for y in range(cy) for x in range(cx)}
        else:
            cells = {((k % self.width) // CHUNK, (k // self.width) // CHUNK) for k in changed}
        scale, hmin = self.scale, self.height_min
        for (x, y) in cells:
            index = self.lod0_index(x, y)
            u16 = array('H', bytes(CHUNK * CHUNK * 2))
            cmin, cmax = math.inf, -math.inf
            for sy in range(CHUNK):
                row = (y * CHUNK + sy) * self.width + x * CHUNK
                for sx in range(CHUNK):
                    hgt = hf.values[row + sx]
                    q = max(0, min(65535, int(round((hgt - hmin) / scale)))) if scale > 0 else 0
                    u16[sy * CHUNK + sx] = q
                    v = hmin + q * scale
                    cmin, cmax = min(cmin, v), max(cmax, v)
            chunk = self.chunk(index)
            new = u16.tobytes()
            if bytes(chunk[:len(new)]) != new:
                chunk[:len(new)] = new
                self._dirty.add(index)
            self.cell_ranges[y * cx + x] = (cmin, cmax)
        self._rebuild_lods(cells if not requantize else None)

    def _rebuild_lods(self, cells=None):
        """Regenerate coarse LOD heights by decimation (auxiliary channel untouched)."""
        cx, cy = self.cells
        for k, first, nx, ny in self.lod_layout()[:-1]:
            factor = 2 ** k
            for j in range(ny):
                for i in range(nx):
                    span = {(x, y) for x in range(i * factor, (i + 1) * factor) for y in range(j * factor, (j + 1) * factor)}
                    if cells is not None and not (span & cells):
                        continue
                    index = first + j * nx + i
                    u16 = array('H', bytes(CHUNK * CHUNK * 2))
                    for sy in range(CHUNK):
                        gy = (j * CHUNK + sy) * factor
                        if gy >= self.height:
                            continue
                        src_row = None
                        for sx in range(CHUNK):
                            gx = (i * CHUNK + sx) * factor
                            if gx >= self.width:
                                continue
                            cell_x, cell_y = gx // CHUNK, gy // CHUNK
                            src = self.chunk(self.lod0_index(cell_x, cell_y))
                            o = 2 * ((gy % CHUNK) * CHUNK + gx % CHUNK)
                            u16[sy * CHUNK + sx] = src[o] | src[o + 1] << 8
                    chunk = self.chunk(index)
                    new = u16.tobytes()
                    if bytes(chunk[:len(new)]) != new:
                        chunk[:len(new)] = new
                        self._dirty.add(index)

    # -- serialize --------------------------------------------------------------------------------
    def to_bytes(self, level: int = 9) -> bytes:
        cx, cy = self.cells
        stored = list(self.stored)
        for index in sorted(self._dirty):
            stored[index] = zlib.compress(bytes(self._chunks[index]), level)
        out = bytearray(struct.pack('<4sIffII', b'BTDB', self.version, self.height_min, self.height_max,
                                    self.width, self.height))
        out += self.reserved + struct.pack('<I', len(self.ltex)) + struct.pack(f'<{len(self.ltex)}I', *self.ltex)
        for lo, hi in self.cell_ranges:
            out += struct.pack('<ff', lo, hi)
        out += self.opaque
        off = 0
        for s in stored:
            out += struct.pack('<II', off, len(s))
            off += len(s)
        for s in stored:
            out += s
        return bytes(out)
