"""Demo 4 — a controlled terrain modification in New Atlantis, validated and packaged.

Raises a smooth 10 m hill (radius 30 m) on open ground at (-140, -460) in the NewAtlantis
worldspace (no placed object within 45 m), re-encodes terrain/newatlantis.btd, validates the
result, writes before/after preview PNGs, and packages the file in
`PyFieldTerrainTest - Main.ba2` next to an empty carrier plugin under PyField/build/terrain_demo.
Nothing is written into the game Data folder.

The plugin also places, at the decoded heights of the EDITED terrain (terrain-to-scene alignment):
a 16 m Akila spaceport tower on the summit, 8 antenna posts on the rim, and a persistent marker
`PyFieldHillMarker` 12 m south of the summit facing it. The console does not resolve reference
editor IDs: run `help PyFieldHillMarker` to get its runtime ID (load slot + local 000809), then
`player.moveto <that id>`.
Do not use `coc NewAtlantis`: that name is the worldspace, not a cell.
"""
import os
import argparse
import json
import math
import struct
import zlib
from pathlib import Path

from pyfield import FormKey, Plugin
from pyfield.core.loadorder import LoadOrder
from pyfield.scene import ExistingCell, Scene, SceneLock, SceneNode, Transform, compile_scene
from pyfield.assets.index import AssetIndex
from pyfield.assets.pack import find_archive2, pack
from pyfield.games.starfield.assets import RULES
from pyfield.games.tes4family import StringTables
from pyfield.games.starfield.btd import CHUNK, BtdFile

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
TERRAIN = 'terrain/newatlantis.btd'
ORIGIN_CELL = (-7, -7)                 # -floor(14 / 2), calibrated with ground objects
CENTER, RADIUS, AMOUNT = (-140.0, -460.0), 30.0, 10.0
PLUGIN = 'PyFieldTerrainTest.esm'
SF = 'Starfield.esm'
HILL_CELL = FormKey(SF, 0x012597)       # NewAtlantis exterior cell (-2, -5)
TOWER = FormKey(SF, 0x17F057)           # AK_spaceport_tower_02 (16 m)
POST = FormKey(SF, 0x06ABDE)            # AntennaTech01 (4 m)
MARKER = FormKey(SF, 0x000034)          # XMarkerHeading


def hill_scene(hf) -> Scene:
    """Objects at the edited terrain height: alignment is read from the heightfield, not guessed."""
    s = Scene('pyfield_hill')
    cx, cy = CENTER
    s.add(SceneNode('tower', TOWER, Transform.at(cx, cy, hf.at(cx, cy) - 0.2)))
    for k in range(8):
        a = k * math.pi / 4
        x, y = cx + RADIUS * math.cos(a), cy + RADIUS * math.sin(a)
        s.add(SceneNode(f'post_{k}', POST, Transform.at(x, y, hf.at(x, y) - 0.05)))
    mx, my = cx, cy - 12
    s.add(SceneNode('marker', MARKER, Transform.at(mx, my, hf.at(mx, my) + 0.1, yaw_deg=0), persistent=True,
                    properties={'editor_id': 'PyFieldHillMarker'}))
    return s


def png(path, width, height, pixels):
    """8-bit greyscale PNG (no dependencies)."""
    raw = b''.join(b'\0' + bytes(pixels[y * width:(y + 1) * width]) for y in range(height))

    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def preview(hf, center, half, path, lo, hi):
    """Top-down height map of a square around center (north = up)."""
    n = 256
    px = []
    for row in range(n):
        y = center[1] + half - 2 * half * row / (n - 1)
        for col in range(n):
            x = center[0] - half + 2 * half * col / (n - 1)
            px.append(max(0, min(255, int((hf.at(x, y) - lo) / (hi - lo) * 255))))
    png(path, n, n, px)


def validate(before: BtdFile, after: BtdFile, hf_before, hf_after, changed) -> dict:
    report = {}
    # 1. only samples within the brush radius changed
    w = hf_after.width
    outside = [k for k in changed if math.dist(hf_after.to_world(k % w, k // w), CENTER) > RADIUS + 1e-6]
    report['changed_samples'] = len(changed)
    report['changed_outside_radius'] = len(outside)
    diff = max(abs(a - b) for a, b in zip(hf_before.values, hf_after.values))
    report['max_height_change_m'] = round(diff, 3)
    # 2. every chunk: auxiliary channel identical; LOD heights equal decimated LOD0
    aux_changed = sum(bytes(before.chunk(i)[32768:]) != bytes(after.chunk(i)[32768:]) for i in range(len(after.stored)))
    report['aux_channel_chunks_changed'] = aux_changed
    bad_lod = 0
    for k, first, nx, ny in after.lod_layout()[:-1]:
        f = 2 ** k
        for j in range(ny):
            for i in range(nx):
                u16 = after.chunk_heights_u16(first + j * nx + i)
                for sy in range(0, CHUNK, 7):
                    for sx in range(0, CHUNK, 7):
                        gx, gy = (i * CHUNK + sx) * f, (j * CHUNK + sy) * f
                        if gx < after.width and gy < after.height:
                            cell = after.lod0_index(gx // CHUNK, gy // CHUNK)
                            if u16[sy * CHUNK + sx] != after.chunk_heights_u16(cell)[(gy % CHUNK) * CHUNK + gx % CHUNK]:
                                bad_lod += 1
    report['lod_samples_not_decimated'] = bad_lod
    # 3. per-cell min/max ranges match the decoded heights
    cx, cy = after.cells
    bad_ranges = 0
    for y in range(cy):
        for x in range(cx):
            u16 = after.chunk_heights_u16(after.lod0_index(x, y))
            lo, hi = after.height_min + min(u16) * after.scale, after.height_min + max(u16) * after.scale
            r = after.cell_ranges[y * cx + x]
            bad_ranges += abs(r[0] - lo) > 1e-3 or abs(r[1] - hi) > 1e-3
    report['cell_ranges_wrong'] = bad_ranges
    # 4. rim continuity: the steepest slope around the rim stays moderate
    rim = [hf_after.slope_deg(CENTER[0] + RADIUS * math.cos(a), CENTER[1] + RADIUS * math.sin(a))
           for a in [i * math.pi / 36 for i in range(72)]]
    report['rim_max_slope_deg'] = round(max(rim), 2)
    peak = hf_after.at(*CENTER)
    report['peak_height_m'] = round(peak, 2)
    report['ok'] = not (outside or aux_changed or bad_lod or bad_ranges)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'terrain_demo'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    idx = AssetIndex(a.data, RULES, [], include_loose=False)
    original = idx.read(TERRAIN)
    before, after = BtdFile.parse(original), BtdFile.parse(original)
    hf_before = before.heightfield(ORIGIN_CELL)
    hf = after.heightfield(ORIGIN_CELL)
    print(f'{TERRAIN}: {after.cells} cells, ground at centre {hf.at(*CENTER):.2f} m')
    changed = hf.raise_(CENTER, RADIUS, AMOUNT)
    after.apply_heightfield(hf, changed)
    encoded = after.to_bytes()
    reparsed = BtdFile.parse(encoded)
    hf_after = reparsed.heightfield(ORIGIN_CELL)
    report = validate(before, reparsed, hf_before, hf_after, changed)
    report['chunks_reencoded'] = len(after._dirty)
    print(json.dumps(report, indent=1))
    lo, hi = hf_before.at(*CENTER) - 5, hf_before.at(*CENTER) + AMOUNT + 5
    preview(hf_before, CENTER, 60, out / 'before.png', lo, hi)
    preview(hf_after, CENTER, 60, out / 'after.png', lo, hi)
    profile = hf_after.profile((CENTER[0] - 60, CENTER[1]), (CENTER[0] + 60, CENTER[1]), 24)
    report['profile_west_east'] = [round(z, 2) for _, _, z in profile]
    if not report['ok']:
        raise SystemExit('validation failed; nothing packaged')
    for f in (out / PLUGIN, out / f'{PLUGIN}.scene-lock.json'):
        if f.exists():
            f.unlink()
    plugin = Plugin.create(PLUGIN, 'starfield', [SF], flags=0x1, author='PyField',
                           description='Terrain test: 10 m hill near the New Atlantis spaceport (safe to remove)')
    plugin.set_master_kinds({SF: 'full'})
    with LoadOrder.open(a.data, [SF]) as lo:
        with plugin.transaction() as tx:
            tx.strings = StringTables(AssetIndex(a.data, RULES, [SF], include_loose=False))   # de-localize copies
            scene = compile_scene(hill_scene(hf_after), tx, lo, ExistingCell(HILL_CELL),
                                  SceneLock(out / f'{PLUGIN}.scene-lock.json', 'pyfield_hill'))
            check = tx.commit(out / PLUGIN, load_order=LoadOrder(lo.plugins + [plugin]))
        written = Plugin.open(out / PLUGIN)
        written.set_master_kinds({SF: 'full'})
        containers = {}
        for key in (HILL_CELL, FormKey(SF, 0x01251C)):            # grid cell and world persistent cell
            mine, theirs = written.get(key), lo.plugin(SF).get(key)
            containers[str(key)] = mine is not None and mine.to_bytes() == theirs.to_bytes()
        world = written.typed(written.get(FormKey(SF, 0x01251B)))
        containers['world_name_delocalized'] = world.name
    report['scene'] = scene.summary()
    report['scene_validation'] = check.summary().splitlines()[0]
    report['overridden_cells_identical_to_vanilla'] = containers
    report['tower_z_vs_terrain'] = round(scene.refs['tower'].placement.position.z - hf_after.at(*CENTER), 3)
    archives = pack({TERRAIN: encoded}, PLUGIN, out, find_archive2(a.data))
    report['archives'] = archives.archives
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print('profile W->E:', report['profile_west_east'])
    print('packaged:', [Path(p).name for p in archives.archives], '+', PLUGIN, 'in', out)


if __name__ == '__main__':
    main()
