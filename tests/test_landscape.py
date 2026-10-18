import math
import struct
import zlib

import pytest

from pyfield.games.starfield.btd import CHUNK, SPACING, BtdFile, lod_grid
from pyfield.landscape import Heightfield


def make_btd(cells=3, hmin=0.0, hmax=100.0, height_fn=None) -> bytes:
    """A synthetic BTDB file: heights from height_fn(global sample x, y) in metres, aux = x ^ y."""
    w = cells * CHUNK
    height_fn = height_fn or (lambda x, y: 10 + 5 * math.sin(x / 40) + 3 * math.cos(y / 25))
    scale = (hmax - hmin) / 65535

    def q(h):
        return max(0, min(65535, round((h - hmin) / scale)))
    lod0 = {}
    ranges = []
    for cy in range(cells):
        for cx in range(cells):
            hs, aux = [], []
            for sy in range(CHUNK):
                for sx in range(CHUNK):
                    X, Y = cx * CHUNK + sx, cy * CHUNK + sy
                    hs.append(q(height_fn(X, Y)))
                    aux.append((X ^ Y) & 0x7FFF)
            lod0[(cx, cy)] = (hs, aux)
            ranges.append((hmin + min(hs) * scale, hmin + max(hs) * scale))
    chunks = []
    for k in range(3, -1, -1):
        nx, ny = lod_grid(cells, cells, k)
        f = 2 ** k
        for j in range(ny):
            for i in range(nx):
                hs, aux = [0] * CHUNK * CHUNK, [0] * CHUNK * CHUNK
                for sy in range(CHUNK):
                    for sx in range(CHUNK):
                        X, Y = (i * CHUNK + sx) * f, (j * CHUNK + sy) * f
                        if X < w and Y < w:
                            c = lod0[(X // CHUNK, Y // CHUNK)]
                            hs[sy * CHUNK + sx] = c[0][(Y % CHUNK) * CHUNK + X % CHUNK]
                            aux[sy * CHUNK + sx] = c[1][(Y % CHUNK) * CHUNK + X % CHUNK]
                chunks.append(zlib.compress(struct.pack(f'<{CHUNK * CHUNK}H', *hs) +
                                            struct.pack(f'<{CHUNK * CHUNK}H', *aux), 9))
    out = struct.pack('<4sIffII', b'BTDB', 6, hmin, hmax, w, w) + bytes(16) + struct.pack('<II', 1, 0x10861)
    out += b''.join(struct.pack('<ff', *r) for r in ranges)
    out += bytes(288 * cells * cells)
    off = 0
    for c in chunks:
        out += struct.pack('<II', off, len(c))
        off += len(c)
    return out + b''.join(chunks)


def test_parse_roundtrip_and_decode():
    data = make_btd()
    b = BtdFile.parse(data)
    assert b.cells == (3, 3) and len(b.stored) == 9 + 4 + 1 + 1
    assert b.to_bytes() == data
    hf = b.heightfield((-1, -1))
    assert hf.origin == (-100.0, -100.0) and hf.spacing == SPACING
    x, y = hf.to_world(200, 37)
    assert hf.at(x, y) == pytest.approx(10 + 5 * math.sin(200 / 40) + 3 * math.cos(37 / 25), abs=0.002)


def test_edit_updates_lods_ranges_and_keeps_aux():
    data = make_btd()
    b = BtdFile.parse(data)
    hf = b.heightfield((0, 0))
    changed = hf.raise_((150.0, 150.0), 20.0, 4.0)        # inside cell (1, 1)
    b.apply_heightfield(hf, changed)
    out = BtdFile.parse(b.to_bytes())
    assert len(b._dirty) == 4                              # one cell + three coarser LOD chunks
    before = BtdFile.parse(data)
    for i in range(len(out.stored)):
        assert bytes(out.chunk(i)[32768:]) == bytes(before.chunk(i)[32768:])
    new = out.heightfield((0, 0))
    assert new.at(150, 150) == pytest.approx(hf.at(150, 150), abs=0.002)
    assert new.at(50, 50) == pytest.approx(before.heightfield((0, 0)).at(50, 50), abs=1e-6)
    lo, hi = out.cell_ranges[1 * 3 + 1]
    assert hi == pytest.approx(max(new.values[j * new.width + i] for j in range(128, 256) for i in range(128, 256)),
                               abs=1e-3)
    lod1 = out.chunk_heights_u16(out.lod_layout()[2][1] + 0)    # LOD1 chunk (0, 0) covers cells 0..1
    for sy in range(0, 128, 9):                                 # exact decimation everywhere
        for sx in range(0, 128, 9):
            gx, gy = 2 * sx, 2 * sy
            cell = out.chunk_heights_u16(out.lod0_index(gx // 128, gy // 128))
            assert lod1[sy * 128 + sx] == cell[(gy % 128) * 128 + gx % 128]


def test_edit_beyond_range_requantizes():
    b = BtdFile.parse(make_btd(cells=2, hmax=20.0))
    hf = b.heightfield((0, 0))
    hf.raise_((100.0, 100.0), 30.0, 50.0)
    b.apply_heightfield(hf)
    out = BtdFile.parse(b.to_bytes())
    assert out.height_max > 20.0
    assert out.heightfield((0, 0)).at(100, 100) == pytest.approx(hf.at(100, 100), abs=0.01)


def test_heightfield_brushes_and_analysis():
    hf = Heightfield(64, 64, 1.0, (0.0, 0.0))
    assert hf.flatten((32, 32), 10, 5.0) and hf.at(32, 32) == 5.0
    assert hf.at(32 + 9.9, 32) < 5.0                       # blended toward the original 0 at the rim
    raised = hf.raise_((10, 10), 5, 2.0)
    assert raised and hf.at(10, 10) == pytest.approx(2.0)
    assert hf.slope_deg(50, 50) == pytest.approx(0.0)
    p = hf.profile((0, 32), (63, 32), 63)
    assert max(z for *_, z in p) == pytest.approx(5.0)
    other = Heightfield(64, 64, 1.0, (0.0, 0.0))
    other.values = type(other.values)('f', [9.0] * 64 * 64)
    hf.blend_from(other, lambda x, y: 1.0 if x < 4 else 0.0)
    assert hf.at(1, 1) == 9.0 and hf.at(32, 32) == 5.0
