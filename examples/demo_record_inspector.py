"""Demo 1 — Record Inspector: load a plugin with its masters, inspect records, follow references.

    python examples/demo_record_inspector.py [PLUGIN] [--data DIR]

Read-only.
"""
import os
import argparse
from pathlib import Path

from pyfield.core.loadorder import LoadOrder

DEFAULT_DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plugin', nargs='?', default='last_mile_shuttle.esm')
    ap.add_argument('--data', default=DEFAULT_DATA)
    a = ap.parse_args()
    with LoadOrder.open(Path(a.data), [a.plugin]) as lo:
        mod = lo.plugin(a.plugin)
        print('load order:', ', '.join(f'{p.name}[{p.kind}]' for p in lo.plugins))
        print(f'{mod.name}: {len(mod.index):,} records; types:', dict(list(mod.index.signature_counts().items())[:8]))

        print('\n-- first placed objects, their bases and containers --')
        for refr in list(mod.typed_records('REFR'))[:5]:
            base = lo.resolve(refr.base)
            kind, owner = lo.container_of(refr)
            cell = lo.resolve(owner)
            pos = refr.placement.position
            print(f'{refr.form_key} -> base {base.signature} {base.editor_id!r}; '
                  f'in {cell.signature} {cell.editor_id!r}; at ({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f})'
                  f'{"  scale %.2f" % refr.scale if refr.scale else ""}')

        print('\n-- records this plugin overrides (first 5) --')
        n = 0
        for node in mod.records():
            key = mod.codec.try_decode(node.form_id)
            if key.plugin != mod.codec._self:
                chain = [p.name for p, _ in lo.overrides(key)]
                print(f'{node.signature} {key} {node.editor_id or ""}: {" -> ".join(chain)}')
                n += 1
                if n == 5:
                    break

        print('\n-- query: keywords defined by this plugin --')
        for kw in lo.query('KYWD').in_plugins(mod.name).list(10):
            print(f'{kw.form_key} {kw.editor_id} type={kw.keyword_type}')


if __name__ == '__main__':
    main()
