"""Calibrate the lat/lon -> cell mapping of planet biome maps (planetdata/biomemaps/*.biom).

Every vanilla fixed location has a known (latitude, longitude) in its planet's CNAM list and a worldspace biome
(the WRLD's top-level BNAM). For each candidate projection, count how many locations land on a grid cell holding
their own biome (or within `--radius` cells of one). The right projection scores far above the rest.

    python tools/calibrate_biome_maps.py [--data DIR] [--radius 1]
"""
import os
import argparse
import math
import struct
from collections import Counter

from pyfield.assets.index import AssetIndex
from pyfield.core.loadorder import LoadOrder
from pyfield.games.starfield.assets import RULES

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')


def read_biom(data: bytes):
    magic, n = struct.unpack_from('<HI', data, 0)
    ids = struct.unpack_from(f'<{n}I', data, 6)
    o = 6 + 4 * n
    count = struct.unpack_from('<I', data, o)[0]
    o += 4
    grids = []
    for _ in range(count):
        w, h, cells = struct.unpack_from('<3I', data, o)
        o += 12
        biomes = struct.unpack_from(f'<{cells}I', data, o)
        o += 4 * cells
        rc = struct.unpack_from('<I', data, o)[0]
        o += 4 + rc
        grids.append((w, h, biomes))
    return ids, grids


def top_level(node, sig):
    inside = False
    for f in node.fields:
        if f.signature == 'BFCB':
            inside = True
        elif f.signature == 'BFCE':
            inside = False
        elif not inside and f.signature == sig:
            return f
    return None


# candidate projections: (lat, lon) -> (grid index, x, y) in [0, 1) or None
def equirect_hemi(flip_x, flip_y, lon0, south_first):
    def f(lat, lon):
        g = (0 if lat >= 0 else 1) ^ south_first
        u = ((lon + lon0) / (2 * math.pi)) % 1.0
        v = 1 - abs(lat) / (math.pi / 2)            # 0 at the pole, 1 at the equator
        if flip_x:
            u = 1 - u
        if flip_y:
            v = 1 - v
        return g, u, v
    return f


def polar_hemi(sx, sy, lon0, south_first, swap):
    def f(lat, lon):
        g = (0 if lat >= 0 else 1) ^ south_first
        r = (1 - abs(lat) / (math.pi / 2)) / 2      # 0 at the pole, 0.5 at the equator
        a = lon + lon0
        u, v = 0.5 + sx * r * math.cos(a), 0.5 + sy * r * math.sin(a)
        if swap:
            u, v = v, u
        return g, u, v
    return f


def lambert_hemi(sx, sy, lon0, south_first, swap):
    def f(lat, lon):
        g = (0 if lat >= 0 else 1) ^ south_first
        colat = math.pi / 2 - abs(lat)
        r = math.sin(colat / 2) / math.sin(math.pi / 4) / 2   # equal-area, 0.5 at the equator
        a = lon + lon0
        u, v = 0.5 + sx * r * math.cos(a), 0.5 + sy * r * math.sin(a)
        if swap:
            u, v = v, u
        return g, u, v
    return f


def east_west(flip_x, flip_y, lon0, swap):
    def f(lat, lon):
        a = (lon + lon0) % (2 * math.pi)
        g = 0 if a < math.pi else 1
        u = (a % math.pi) / math.pi
        v = 0.5 - lat / math.pi
        if flip_x:
            u = 1 - u
        if flip_y:
            v = 1 - v
        if swap:
            u, v = v, u
        return g, u, v
    return f


def candidates():
    quarter = [0.0, math.pi / 2, math.pi, -math.pi / 2]
    for fx in (0, 1):
        for fy in (0, 1):
            for l0 in quarter:
                for sf in (0, 1):
                    yield f'equirect fx{fx} fy{fy} lon0 {l0:.2f} south_first {sf}', equirect_hemi(fx, fy, l0, sf)
                for sw in (0, 1):
                    yield f'east_west fx{fx} fy{fy} lon0 {l0:.2f} swap {sw}', east_west(fx, fy, l0, sw)
    for sx in (1, -1):
        for sy in (1, -1):
            for l0 in quarter:
                for sf in (0, 1):
                    for sw in (0, 1):
                        yield f'polar sx{sx} sy{sy} lon0 {l0:.2f} south_first {sf} swap {sw}', polar_hemi(sx, sy, l0, sf, sw)
                        yield f'lambert sx{sx} sy{sy} lon0 {l0:.2f} south_first {sf} swap {sw}', lambert_hemi(sx, sy, l0, sf, sw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--radius', type=int, default=1)
    a = ap.parse_args()
    assets = AssetIndex(a.data, RULES, [], include_loose=False)
    lo = LoadOrder.open(a.data, ['Starfield.esm'])
    sf = lo.plugin('Starfield.esm')
    points = []                                       # (planet, lat, lon, biome id, ids, grids)
    for node in sf.records('PNDT'):
        anam = top_level(node, 'ANAM')
        if anam is None:
            continue
        name = bytes(anam.data).rstrip(b'\0').decode('latin1')
        path = f'planetdata/biomemaps/{name.lower()}.biom'
        if not assets.exists(path):
            continue
        ids, grids = None, None
        for f in node.fields:
            d = bytes(f.data)
            if f.signature != 'CNAM' or not d or len(d) % 20:
                continue
            for i in range(0, len(d), 20):
                lat, lon, raw = struct.unpack_from('<ddI', d, i)
                world = sf.find(raw)
                if world is None:
                    continue
                bnam = top_level(world, 'BNAM')
                if bnam is None:
                    continue
                biome = int.from_bytes(bnam.data[:4], 'little')
                if ids is None:
                    ids, grids = read_biom(assets.read(path))
                if biome in ids:
                    points.append((name, lat, lon, biome, ids, grids))
    print(len(points), 'fixed locations whose worldspace biome is in their planet biome map,',
          len({p[0] for p in points}), 'planets')
    # baseline: chance of hitting the biome by luck
    rarity = {}
    for name, lat, lon, biome, ids, grids in points:
        total = sum(len(c) for _, _, c in grids)
        share = sum(c.count(biome) for _, _, c in grids) / total
        rarity[(name, biome)] = -math.log(max(share, 1e-6))
    scores = []
    for label, proj in candidates():
        hits, info = 0, 0.0
        for name, lat, lon, biome, ids, grids in points:
            g, u, v = proj(lat, lon)
            w, h, cells = grids[g]
            cx, cy = int(u * w), int(v * h)
            ok = False
            for dy in range(-a.radius, a.radius + 1):
                for dx in range(-a.radius, a.radius + 1):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < w and 0 <= y < h and cells[y * w + x] == biome:
                        ok = True
            hits += ok
            info += rarity[(name, biome)] if ok else 0.0
        scores.append((round(info, 1), hits, label))
    scores.sort(reverse=True)
    for info, hits, label in scores[:12]:
        print(f'info {info:6.1f}  hits {hits:3d} / {len(points)}  {label}')
    print('median candidate:', scores[len(scores) // 2][:2], 'max possible info', round(sum(rarity.values()), 1))


if __name__ == '__main__':
    main()
