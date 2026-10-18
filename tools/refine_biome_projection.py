"""Refine the polar biome-map projection found by calibrate_biome_maps.py (fine lon0, radial function, scale).

    python tools/refine_biome_projection.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_biome_maps import DATA, read_biom, top_level  # noqa: E402

import struct  # noqa: E402

from pyfield.assets.index import AssetIndex  # noqa: E402
from pyfield.core.loadorder import LoadOrder  # noqa: E402
from pyfield.games.starfield.assets import RULES  # noqa: E402

RADIAL = {
    'linear': lambda c: c / (math.pi / 2),
    'lambert': lambda c: math.sin(c / 2) / math.sin(math.pi / 4),
    'stereo': lambda c: math.tan(c / 2) / math.tan(math.pi / 4),
    'ortho': lambda c: math.sin(c),
}


def load_points():
    assets = AssetIndex(DATA, RULES, [], include_loose=False)
    lo = LoadOrder.open(DATA, ['Starfield.esm'])
    sf = lo.plugin('Starfield.esm')
    points = []
    for node in sf.records('PNDT'):
        anam = top_level(node, 'ANAM')
        if anam is None:
            continue
        name = bytes(anam.data).rstrip(b'\0').decode('latin1')
        path = f'planetdata/biomemaps/{name.lower()}.biom'
        if not assets.exists(path):
            continue
        cache = None
        for f in node.fields:
            d = bytes(f.data)
            if f.signature != 'CNAM' or not d or len(d) % 20:
                continue
            for i in range(0, len(d), 20):
                lat, lon, raw = struct.unpack_from('<ddI', d, i)
                world = sf.find(raw)
                bnam = top_level(world, 'BNAM') if world is not None else None
                if bnam is None:
                    continue
                biome = int.from_bytes(bnam.data[:4], 'little')
                cache = cache or read_biom(assets.read(path))
                ids, grids = cache
                if biome in ids:
                    total = sum(len(c) for _, _, c in grids)
                    share = sum(c.count(biome) for _, _, c in grids) / total
                    points.append((name, lat, lon, biome, grids, -math.log(max(share, 1e-6))))
    return points


def score(points, radial, scale, lon0, sx, sy, swap, radius=0):
    info, hits = 0.0, 0
    for name, lat, lon, biome, grids, rare in points:
        g = 0 if lat >= 0 else 1
        r = RADIAL[radial](math.pi / 2 - abs(lat)) * scale
        a = lon + lon0
        u, v = 0.5 + sx * r * math.cos(a), 0.5 + sy * r * math.sin(a)
        if swap:
            u, v = v, u
        w, h, cells = grids[g]
        cx, cy = int(u * w), int(v * h)
        ok = any(0 <= cx + dx < w and 0 <= cy + dy < h and cells[(cy + dy) * w + cx + dx] == biome
                 for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1))
        hits += ok
        info += rare if ok else 0.0
    return info, hits


def main():
    points = load_points()
    print(len(points), 'points; max info', round(sum(p[5] for p in points), 1))
    results = []
    for radial in RADIAL:
        for scale in (0.5, 0.5 * math.sqrt(2)):
            for step in range(72):
                lon0 = math.radians(step * 5)
                for sx, sy, swap in ((1, -1, 0), (1, 1, 1), (-1, 1, 0), (1, 1, 0), (1, -1, 1), (-1, -1, 0)):
                    info, hits = score(points, radial, scale, lon0, sx, sy, swap)
                    results.append((round(info, 1), hits, radial, round(scale, 3), step * 5, sx, sy, swap))
    results.sort(reverse=True)
    for r in results[:10]:
        print(r)


if __name__ == '__main__':
    main()
