"""Demo 5/6 groundwork — transplant entities with their assets into a self-contained plugin.

Copies, from Dogs & Cats' mesh-probe plugin (read-only), the pet water bowl static and the
test cat (race, skin, keyword, global, meow/purr Wwise events) into a NEW plugin with its own
archives, all under PyField/build/. The cat's AI packages and menu messages are relationships
(rebuild-only); this demo opts in to nulling those references, so the copied cat has none.

    python examples/demo_transplant.py [--data DIR] [--out DIR]
"""
import os
import argparse
import json
from pathlib import Path

from pyfield import Plugin
from pyfield.assets.deps import DependencyFinder
from pyfield.assets.index import AssetIndex
from pyfield.assets.pack import find_archive2, pack
from pyfield.core.loadorder import LoadOrder
from pyfield.transplant import apply_transplant, plan_transplant

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
SOURCE = 'dogsncatsmeshprobe.esm'
TARGET = 'PyFieldTransplantDemo.esm'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'transplant_demo'))
    a = ap.parse_args()
    out = Path(a.out)
    if Path(a.data).resolve() in out.resolve().parents:
        raise SystemExit('refusing to write into the game Data folder')
    with LoadOrder.open(a.data, [SOURCE]) as lo:
        src = lo.plugin(SOURCE)
        assets = AssetIndex(a.data, src.adapter.asset_rules, [p.name for p in lo.plugins])
        finder = DependencyFinder(assets, src.adapter.asset_hooks, src.name)
        roots = [v.form_key for eid in ('DNC_PetBowlWaterContents', 'DNC_TestCat')
                 for v in lo.find_editor_id(eid) if v.plugin is src]
        plan = plan_transplant(lo, src, roots, 'copy', asset_finder=finder, null_rebuild_references=True)
        print(plan.summary())
        target = Plugin.create(TARGET, 'starfield', flags=0x1, author='PyField',
                               description='Transplant demo: Dogs & Cats bowl + cat (safe to remove)')
        with target.transaction() as tx:
            result = apply_transplant(plan, tx, editor_id_prefix='PFT_', asset_index=assets)
            report = tx.commit(out / TARGET, load_order=LoadOrder(lo.plugins[:-1] + [target]))
        print('\n' + report.summary(), report.stats)
        archives = pack(result.assets, TARGET, out, find_archive2(a.data))
        mapping = {str(k): str(v) for k, v in result.mapping.items()}
        summary = {'records': mapping, 'remapped_references': result.remapped,
                   'assets_packed': len(result.assets), 'archives': archives.archives,
                   'external_unverified': plan.assets.external, 'vanilla_dependencies': plan.assets.by_category().get('vanilla', [])}
        (out / 'transplant_report.json').write_text(json.dumps(summary, indent=1, default=str), encoding='utf-8')
        print(f"\n{len(mapping)} records copied, {result.remapped} references rewritten, "
              f"{len(result.assets)} owned asset files packed:")
        for path, info in archives.archives.items():
            print(f'  {Path(path).name}: {info}')


if __name__ == '__main__':
    main()
