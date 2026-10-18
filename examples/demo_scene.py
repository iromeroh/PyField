"""Demo 3 — a small structure described in Python, compiled into a new interior cell.

Builds PyFieldSceneTest.esm under PyField/build/scene_demo/ (never into Data):
  floor + COC marker + light, and three instances of a "table stack" blueprint (table,
  table on top, crate on top): upright, yawed 45°, and tilted (pitch 20°, roll 10°). If the
  placement convention were wrong, the upper pieces would visibly float off the lower ones.
Then: recompile unchanged (must be byte-identical with the same FormIDs), move one instance
(only its records may change).

In game: enable the plugin, console `coc PyFieldSceneTest`.
"""
import os
import argparse
import hashlib
from pathlib import Path

from pyfield import FormKey, Plugin
from pyfield.core.loadorder import LoadOrder
from pyfield.diff import diff_plugins
from pyfield.scene import (Blueprint, Link, NewInteriorCell, Scene, SceneLock, SceneNode, SpatialIndex,
                           Transform, compile_scene, diff_scenes)

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
SF = 'Starfield.esm'
FLOOR = FormKey(SF, 0x24CEBE)          # Spaceport_Tarmac_FloorA_Custom_01 (24 x 64 m)
COC = FormKey(SF, 0x000032)            # COCMarkerHeading
LIGHT = FormKey(SF, 0x01D491)          # defaultLight01
TABLE = FormKey(SF, 0x00B027)          # TableCoffeeMod01 (top at z = 0.45 m)
CRATE = FormKey(SF, 0x0058BB)          # Crate_Seafood03
TEMPLATE_CELL = FormKey(SF, 0x0E6E45)  # AACTEST interior (lighting template)
TARGET = 'PyFieldSceneTest.esm'


def table_stack() -> Blueprint:
    return Blueprint('table_stack', [
        SceneNode('table', TABLE, Transform.at(0, 0, 0), children=[
            SceneNode('table_top', TABLE, Transform.at(0, 0, 0.45, yaw_deg=90)),
            SceneNode('crate', CRATE, Transform.at(0.2, 0, 0.90, yaw_deg=30)),
        ]),
    ], description='coffee table with a rotated table and a crate on top', source='demo_scene.py')


def build_scene(set_b_at=(0, 6, 0)) -> Scene:
    s = Scene('pyfield_scene_test')
    s.add(SceneNode('floor', FLOOR, Transform.at(0, 0, 0)))
    s.add(SceneNode('coc', COC, Transform.at(0, -6, 0.1, yaw_deg=0), persistent=True))
    s.add(SceneNode('light', LIGHT, Transform.at(0, 3, 4), links=[Link('set_a/table')]))
    bp = table_stack()
    s.instantiate(bp, 'set_a', Transform.at(-3, 6, 0))
    s.instantiate(bp, 'set_b', Transform.at(*set_b_at, yaw_deg=45))
    tilted = s.instantiate(bp, 'set_c', Transform.at(3, 6, 1.0, yaw_deg=30, pitch_deg=20, roll_deg=10))
    for n, _ in tilted.walk():                 # set_c pieces follow their table's enable state
        if n.id != 'set_c/table' and n.base is not None:
            n.enable_parent = 'set_c/table'
    return s


def compile_to(scene, out_dir: Path, data: str):
    lock = SceneLock.load_or_new(out_dir / f'{TARGET}.scene-lock.json', scene.name)
    path = out_dir / TARGET
    with LoadOrder.open(data, [SF]) as lo:
        plugin = Plugin.open(path) if path.exists() else Plugin.create(
            TARGET, 'starfield', [SF], flags=0x1, author='PyField', description='Scene demo (safe to remove)')
        plugin.set_master_kinds({SF: 'full'})
        with plugin.transaction() as tx:
            result = compile_scene(scene, tx, lo, NewInteriorCell('PyFieldSceneTest', TEMPLATE_CELL, 'PyField Scene Test'),
                                   lock)
            report = tx.commit(path, load_order=LoadOrder(lo.plugins + [plugin]))
        lock.save()
        overlaps = SpatialIndex(scene, lo).overlaps(min_volume=0.01, ignore={'floor'})
    return result, report, overlaps


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'scene_demo'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob('*'):
        f.unlink()                              # fresh demo run
    scene = build_scene()
    table_stack().save(out / 'table_stack.blueprint.json')

    r1, rep1, overlaps = compile_to(scene, out, a.data)
    print('compile 1:', r1.summary(), '|', rep1.summary().splitlines()[0])
    print('  coarse overlaps (excluding floor):', overlaps)
    first, lock1 = (out / TARGET).read_bytes(), (out / f'{TARGET}.scene-lock.json').read_text()

    r2, rep2, _ = compile_to(build_scene(), out, a.data)
    print('compile 2 (unchanged):', r2.summary(), '| identical file:', (out / TARGET).read_bytes() == first,
          '| identical lock:', (out / f'{TARGET}.scene-lock.json').read_text() == lock1)

    before = Plugin.open(out / TARGET, use_mmap=False)
    before_bytes = before.to_bytes()
    moved = build_scene(set_b_at=(0, 9, 0))
    print('scene diff:', diff_scenes(scene, moved).summary().splitlines()[0])
    r3, rep3, _ = compile_to(moved, out, a.data)
    print('compile 3 (set_b moved):', r3.summary())
    old = Plugin.from_bytes(before_bytes, TARGET, 'starfield')
    new = Plugin.open(out / TARGET, use_mmap=False)
    for p in (old, new):
        p.set_master_kinds({SF: 'full'})
    print('plugin diff:', diff_plugins(old, new).summary().splitlines()[0])
    print(f'\nwrote {out / TARGET} ({sha(out / TARGET)}), lock and blueprint JSON alongside')


if __name__ == '__main__':
    main()
