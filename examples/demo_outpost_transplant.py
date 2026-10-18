"""Phase 7: a captured outpost rebuilt as a fixed location with its own fitted terrain (PyFieldSeleneHome.esm).

Reads a PyFieldCapture outpost capture (default: Selene), resolves it in the captured load order, fits terrain
to its objects (landscape/fit.py), applies the object policies (terrain / snap / keep) and builds, under
PyField/build/outpost_demo (nothing is written into the game Data folder):

- an overlay location "Selene Home" on Nesoi, seeded from Nesoi's own overlay location (biome, ground textures);
- its terrain file (fitted heights) in `PyFieldSeleneHome - Main.ba2`;
- every captured reference that can be copied (save-created bases are listed in report.json), re-using the
  plugins that defined them as masters;
- a map marker linked to a landing spot clear of the outpost.

This is a static copy: the workshop (beacon, builder edits, resources) is the next step.

    python examples/demo_outpost_transplant.py [--capture PATH] [--planet NesoiPlanetData] [--lat 0.35 --lon -0.8]
"""
import argparse
import ctypes
import json
import os
from pathlib import Path

from pyfield import Plugin
from pyfield.assets.index import AssetIndex
from pyfield.assets.pack import find_archive2, pack
from pyfield.core.loadorder import LoadOrder
from pyfield.games.starfield.assets import RULES
from pyfield.games.starfield.outpost import Rules, build_outpost, make_island, plan_outpost
from pyfield.games.starfield.overlay import OverlaySite, template_for_planet
from pyfield.games.tes4family import StringTables
from pyfield.scene.runtime import RuntimeCapture

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
PLUGIN = 'PyFieldSeleneHome.esm'
SF = 'Starfield.esm'


def documents() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
    return Path(buf.value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--capture', default=str(documents() / 'My Games/Starfield/PyField/captures/Selene.json'))
    ap.add_argument('--planet', default='NesoiPlanetData')
    ap.add_argument('--name', default='Selene Home')
    ap.add_argument('--lat', type=float, default=0.35)          # radians; Nesoi's own LC171 is at (-0.52, 2.24)
    ap.add_argument('--lon', type=float, default=-0.80)
    ap.add_argument('--world-biome', default=None, help='biome editor ID for the location (default: the biome of the planet template location)')
    ap.add_argument('--keep-ships', action='store_true', help='WIP: copy a landed ship as static modules (falls apart in game); default leaves ships out')
    ap.add_argument('--home', action='store_true', help='player home: builder menu, power, items linked (claimed)')
    ap.add_argument('--island', type=float, default=None, metavar='SEA_LEVEL',
                    help='lift the outpost above this sea level (plan frame, measured in game) as an island')
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'outpost_demo'))
    a = ap.parse_args()
    out = Path(a.out)
    (out / 'locks').mkdir(parents=True, exist_ok=True)
    for f in [out / PLUGIN, *(out / 'locks').glob('*.json')]:
        f.unlink(missing_ok=True)
    capture = RuntimeCapture.load(a.capture)
    plugins_txt = Path(os.environ.get('LOCALAPPDATA', '')) / 'Starfield' / 'Plugins.txt'
    order = [l.strip().lstrip('*') for l in plugins_txt.read_text(encoding='utf-8', errors='replace').splitlines()
             if l.strip() and not l.startswith('#')] if plugins_txt.exists() else None
    names = capture.plugin_files(order)
    present = [f for f in names if (Path(a.data) / f).exists() and f.lower() != PLUGIN.lower()]   # never build from itself
    missing = [f for f in names if not (Path(a.data) / f).exists()]
    report = {'capture': a.capture, 'missing_plugins': missing}
    with LoadOrder.open(a.data, present) as lo:
        planet = lo.find_editor_id(a.planet)[0]
        template = template_for_planet(lo, planet)
        report['template'] = f'{template.world.editor_id} ({template.cells} x {template.cells} cells)'
        plan = plan_outpost(capture, lo, cells=template.cells, rules=Rules(include_ships=a.keep_ships))
        if a.island is not None:
            report['island'] = make_island(plan, a.island)
        report['plan'] = plan.summary()
        report['skipped'] = plan.skipped
        plugin = Plugin.create(PLUGIN, 'starfield', [SF], flags=0x1, author='PyField',
                               description=f'{a.name}: outpost "{capture.name}" transplanted with PyField (static copy)')
        plugin.set_master_kinds({SF: 'full'})
        assets = AssetIndex(a.data, RULES, [], include_loose=False)
        site = OverlaySite('PyFieldSeleneHome', a.name, planet.form_key, a.lat, a.lon, cells=plan.cells)
        with plugin.transaction() as tx:
            tx.strings = StringTables(AssetIndex(a.data, RULES, [SF], include_loose=False))
            biome = lo.find_editor_id(a.world_biome)[0].form_key if a.world_biome else None
            built = build_outpost(tx, lo, plan, site, assets, out / 'locks', biome=biome, home=a.home)
            check = tx.commit(out / PLUGIN, load_order=LoadOrder(lo.plugins + [plugin]))
        report['overlay'] = built.overlay.summary()
        if built.home is not None:
            report['home'] = {'activator': str(built.home.activator), 'power': str(built.home.power),
                              'primitives': [str(k) for k in built.home.primitives],
                              'linked_items': built.home.linked_items}
        report['links'] = built.links
        report['landing'] = {'at': [round(v, 1) for v in built.landing], 'clearance_m': round(built.landing_clearance, 1)}
        report['scenes'] = {f'{k[0]},{k[1]}': v.summary() for k, v in built.scenes.items()}
        report['validation'] = check.summary().splitlines()[:6]
        written = Plugin.open(out / PLUGIN)
        report['masters'] = written.masters
        report['records'] = dict(written.index.signature_counts())
        written.close()
        encoded = built.terrain.to_bytes()
    archives = pack({built.overlay.terrain_path: encoded}, PLUGIN, out, find_archive2(a.data))
    report['archives'] = [Path(p).name for p in archives.archives]
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
    brief = {k: report.get(k) for k in ('template', 'island', 'home', 'links', 'plan', 'overlay', 'landing', 'validation', 'masters', 'records', 'archives')}
    print(json.dumps(brief, indent=1, default=str))


if __name__ == '__main__':
    main()
