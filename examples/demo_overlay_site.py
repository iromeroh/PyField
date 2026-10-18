"""Phase 7 groundwork: a new fixed location on Luna with its own terrain (PyFieldOverlayTest.esm).

Builds, under PyField/build/overlay_demo (nothing is written into the game Data folder):

- worldspace PyFieldSiteWorld pinned to Luna at 17.2 N, 68.8 E (EOVR entry in a LunaPlanetData override),
  its location under Luna's surface location, a 3 x 3-cell surface block and terrain file;
- terrain: flat at 0 m with a raised square pad (40 m wide, 6 m high, 12 m smooth ramps) centred at (50, 50);
- a 16 m Akila spaceport tower on the pad, antenna posts on the pad corners and at the foot of the ramps
  (alignment check: posts stand on the ground, nothing floats);
- an enabled map marker "PyField Test Site" linked to a landing heading marker off the pad.

In game: fly to Luna and land at "PyField Test Site" (planet map); repeat in a second, unrelated save.
Expected: the same pad and tower in both, posts on the ground, Apollo Landing Site still listed on Luna.
Fallback without landing: `cow PyFieldSiteWorld 0 0`.

    python examples/demo_overlay_site.py [--data DIR] [--out DIR]
"""
import os
import argparse
import json
import math
from pathlib import Path

from pyfield import FormKey, Plugin
from pyfield.assets.index import AssetIndex
from pyfield.assets.pack import find_archive2, pack
from pyfield.core.loadorder import LoadOrder
from pyfield.games.starfield.assets import RULES
from pyfield.games.starfield.btd import BtdFile
from pyfield.games.starfield.overlay import (APOLLO_BLOCK, APOLLO_TERRAIN, OverlaySite, blank_terrain,
                                             build_overlay, fnam_border_matches, origin_cell, place_map_marker)
from pyfield.games.tes4family import StringTables
from pyfield.scene import ExistingCell, Scene, SceneLock, SceneNode, Transform, compile_scene

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
PLUGIN = 'PyFieldOverlayTest.esm'
SF = 'Starfield.esm'
TOWER = FormKey(SF, 0x17F057)           # AK_spaceport_tower_02 (16 m)
POST = FormKey(SF, 0x06ABDE)            # AntennaTech01 (4 m)
PAD_CENTRE, PAD_HALF, PAD_HEIGHT, RAMP = (50.0, 50.0), 20.0, 6.0, 12.0
LATITUDE, LONGITUDE = 0.30, 1.20        # radians; Apollo is at (-0.0023, 0.379), Nova Galactic (-0.104, -1.070)


def pad_height(x, y):
    d = max(abs(x - PAD_CENTRE[0]), abs(y - PAD_CENTRE[1]))
    if d <= PAD_HALF:
        return PAD_HEIGHT
    t = min(1.0, (d - PAD_HALF) / RAMP)
    return PAD_HEIGHT * (1 - t * t * (3 - 2 * t))


def site_scene(hf) -> Scene:
    s = Scene('pyfield_overlay')
    cx, cy = PAD_CENTRE
    s.add(SceneNode('tower', TOWER, Transform.at(cx, cy, hf.at(cx, cy) - 0.2)))
    for k, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
        x, y = cx + sx * (PAD_HALF - 2), cy + sy * (PAD_HALF - 2)
        s.add(SceneNode(f'pad_post_{k}', POST, Transform.at(x, y, hf.at(x, y) - 0.05)))
        x, y = cx + sx * (PAD_HALF + RAMP + 4), cy + sy * (PAD_HALF + RAMP + 4)
        s.add(SceneNode(f'foot_post_{k}', POST, Transform.at(x, y, hf.at(x, y) - 0.05)))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'overlay_demo'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in (out / PLUGIN, out / f'{PLUGIN}.scene-lock.json'):
        if f.exists():
            f.unlink()
    report = {}
    assets = AssetIndex(a.data, RULES, [], include_loose=False)
    with LoadOrder.open(a.data, [SF]) as lo:
        apollo = BtdFile.parse(assets.read(APOLLO_TERRAIN))
        # the FNAM reading (per-cell corner height) checked on the template before relying on it
        block = lo.resolve(APOLLO_BLOCK).node
        report['fnam_border_matches_apollo'] = fnam_border_matches(apollo, bytes(block.get('FNAM').data), -500.0, 1000.0)
        terrain = blank_terrain(apollo)
        hf = terrain.heightfield(origin_cell(3))
        for k in range(len(hf.values)):
            hf.values[k] = pad_height(*hf.to_world(k % hf.width, k // hf.width))
        terrain.apply_heightfield(hf)
        encoded = terrain.to_bytes()
        hf = BtdFile.parse(encoded).heightfield(origin_cell(3))
        report['terrain'] = {'pad_top': round(hf.at(*PAD_CENTRE), 3), 'outside': round(hf.at(150, 150), 3),
                             'range': [terrain.height_min, terrain.height_max]}

        luna = lo.find_editor_id('LunaPlanetData')[0]
        site = OverlaySite('PyFieldSite', 'PyField Test Site', luna.form_key, LATITUDE, LONGITUDE, cells=3)
        plugin = Plugin.create(PLUGIN, 'starfield', [SF], flags=0x1, author='PyField',
                               description='Overlay location test on Luna: own terrain pad (safe to remove)')
        plugin.set_master_kinds({SF: 'full'})
        with plugin.transaction() as tx:
            tx.strings = StringTables(AssetIndex(a.data, RULES, [SF], include_loose=False))   # de-localize copies
            built = build_overlay(tx, lo, site, terrain)
            place_map_marker(tx, lo, built, site.name, marker_at=(50.0, 24.0, hf.at(50, 24) + 0.1),
                             landing_at=(140.0, 140.0, hf.at(140, 140)), landing_yaw=math.radians(225))
            scene = compile_scene(site_scene(hf), tx, lo, ExistingCell(built.cells[(0, 0)]),
                                  SceneLock(out / f'{PLUGIN}.scene-lock.json', 'pyfield_overlay'))
            check = tx.commit(out / PLUGIN, load_order=LoadOrder(lo.plugins + [plugin]))
        report['overlay'] = built.summary()
        report['markers'] = {k: str(v) for k, v in built.markers.items()}
        report['scene'] = scene.summary()
        report['validation'] = check.summary().splitlines()[0]
        written = Plugin.open(out / PLUGIN)
        report['records'] = dict(written.index.signature_counts())
        written.close()
    archives = pack({built.terrain_path: encoded}, PLUGIN, out, find_archive2(a.data))
    report['archives'] = [Path(p).name for p in archives.archives]
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
