"""Candidate sites for a transplanted outpost/POI: planet + biome (+ optional point to stay near).

Reads the planet's biome map (games/starfield/biomes.py), skips water and the planet's existing fixed locations,
prefers large uniform patches of gentle biomes, and writes a preview PNG (north hemisphere left, south right;
candidates white, existing locations black). Feed a candidate to the transplant:

    python examples/find_outpost_sites.py --planet NesoiPlanetData --biome Savanna
    python examples/demo_outpost_transplant.py --planet NesoiPlanetData --lat 0.2752 --lon 1.9522
"""
import os
import argparse
import json
import math
from pathlib import Path

from pyfield.assets.index import AssetIndex
from pyfield.core.loadorder import LoadOrder
from pyfield.games.starfield.assets import RULES
from pyfield.games.starfield.biomes import BiomeMap, find_junctions, find_sites, preview_png
from pyfield.games.starfield.overlay import pinned_worlds

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--planet', required=True, help='planet record editor ID, e.g. NesoiPlanetData')
    ap.add_argument('--biome', action='append', default=[], help='biome name part (repeatable), e.g. Savanna')
    ap.add_argument('--near', nargs=2, type=float, metavar=('LAT', 'LON'), help='radians: sort by distance')
    ap.add_argument('--count', type=int, default=5)
    ap.add_argument('--coast', action='store_true', help='a corner where land meets water (shore in the landing area)')
    ap.add_argument('--mix', type=int, default=0, metavar='N', help='a corner where N land biomes meet (mining)')
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'sites'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with LoadOrder.open(a.data, ['Starfield.esm']) as lo:
        planet = lo.find_editor_id(a.planet)[0]
        anam = next(f for f in planet.node.fields if f.signature == 'ANAM')
        name = bytes(anam.data).rstrip(b'\0').decode('latin1')
        bm = BiomeMap.load(AssetIndex(a.data, RULES, [], include_loose=False), name, lo)
        avoid = [(lat, lon) for lat, lon, _ in pinned_worlds(planet)]
        near = tuple(a.near) if a.near else None
        if a.coast or a.mix:
            sites = find_junctions(bm, need=a.biome, min_land_biomes=max(1, a.mix), coast=a.coast, avoid=avoid,
                                   count=a.count, near=near)
        else:
            sites = find_sites(bm, a.biome, avoid=avoid, count=a.count, near=near)
        biomes = sorted({bm.names.get(f, f'{f:08X}') for f in bm.ids})
    png = out / f'{name.lower()}_sites.png'
    preview_png(bm, png, sites, marks=avoid)
    print(json.dumps({'planet': name, 'biomes': biomes, 'existing_locations': len(avoid),
                      'sites': [s.to_dict() for s in sites], 'preview': str(png)}, indent=1))


if __name__ == '__main__':
    main()
