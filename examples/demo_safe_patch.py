"""Demo 2 — Safe Patch Generator: build a small new plugin, validate it against the
installed load order, write it via a temporary file, and print a semantic diff.

    python examples/demo_safe_patch.py [--out build/PyFieldDemo.esm] [--data DIR]

Writes only the output file (default inside this repository). Nothing in the game's Data
folder is modified. To test in game, copy the output to Data and enable it, then in the
console: `help PyFieldDemo 4` (lists the three records), then
`GetGlobalValue <FormID of PyFieldDemo_Answer>` (expects 42). `show <name>` does not work:
Starfield does not keep global editor IDs at runtime.
"""
import os
import argparse
from pathlib import Path

from pyfield import FormKey, Plugin
from pyfield.core.loadorder import LoadOrder
from pyfield.diff import diff_plugins

DEFAULT_DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
XMARKER_HEADING = FormKey('Starfield.esm', 0x34)


def build(out: Path, data: Path):
    with LoadOrder.open(data, ['Starfield.esm']) as lo:
        plugin = Plugin.create(out.name, 'starfield', ['Starfield.esm'], flags=0x1,
                               author='PyField', description='PyField demo plugin (safe to remove)')
        plugin.set_master_kinds({'Starfield.esm': lo.plugin('Starfield.esm').kind})
        assert lo.resolve(XMARKER_HEADING).editor_id == 'XMarkerHeading'
        with plugin.transaction() as tx:
            kw = tx.new_record('KYWD', 'PyFieldDemo_Keyword', color={'r': 0, 'g': 160, 'b': 255, 'a': 0},
                               keyword_type=0, unknown_fnam=bytes(4))
            answer = tx.new_record('GLOB', 'PyFieldDemo_Answer', value=41.0)
            answer.value = 42.0                                   # edit through a typed property
            tx.new_record('FLST', 'PyFieldDemo_List', forms=[kw.form_key, XMARKER_HEADING])
            out.parent.mkdir(parents=True, exist_ok=True)
            report = tx.commit(out, load_order=LoadOrder(lo.plugins + [plugin]))
        print(report.summary())
        print('stats:', report.stats)

    written = Plugin.open(out)
    written.set_master_kinds({'Starfield.esm': 'full'})
    print(f'\n{out} ({out.stat().st_size} bytes), HEDR {written.hedr}')
    for view in written.typed_records():
        print(' ', view.to_dict())
    empty = Plugin.create(out.name, 'starfield', ['Starfield.esm'])
    empty.set_master_kinds({'Starfield.esm': 'full'})
    print('\n' + diff_plugins(empty, written).summary())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'PyFieldDemo.esm'))
    ap.add_argument('--data', default=DEFAULT_DATA)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if Path(a.data).resolve() in out.parents:
        raise SystemExit('refusing to write into the game Data folder from a demo; copy it manually')
    build(out, Path(a.data))


if __name__ == '__main__':
    main()
