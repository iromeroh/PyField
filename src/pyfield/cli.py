"""Command line: inspection, roundtrip, validation and diff.

    pyfield info      PLUGIN
    pyfield records   PLUGIN [-s SIG ...] [--edid GLOB] [--limit N]
    pyfield show      PLUGIN KEY [--raw]        KEY: 00ABCD:Plugin.esm | raw hex FormID | EditorID
    pyfield roundtrip PLUGIN [--level raw|tree|fields|encode]
    pyfield validate  PLUGIN [--no-load-order]
    pyfield diff      BEFORE AFTER
    pyfield schema    [SIG]                     typed record layouts (--game, default starfield)
    pyfield assets    deps|extract PLUGIN KEY... [--out WORK] | status WORK | pack WORK --plugin-name X --out DIR
    pyfield transplant PLUGIN KEY... [--mode copy|reference] [--out DIR --new NAME.esm]
    pyfield blueprint capture PLUGIN CELL [--out FILE]   cell references -> blueprint JSON
    pyfield runtime   CAPTURE.json [--sections S ...] [--created-only] [--out BLUEPRINT]
    pyfield capabilities [GAME]

The plugin's folder is used as the data folder for masters.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

from . import games
from .core.formids import FormKey
from .core.loadorder import LoadOrder
from .core.plugin import Plugin


def _open_lo(path: Path, game=None) -> LoadOrder:
    return LoadOrder.open(path.parent, [path.name], game)


def cmd_info(a):
    path = Path(a.plugin)
    with Plugin.open(path, a.game) as p:
        p.resolve_master_kinds()
        idx = p.index
        version, count, next_id = p.hedr
        print(f'{p.name}  [{p.adapter.title}]  {path.stat().st_size:,} bytes')
        print(f'  flags {p.flags:08X}  kind={p.kind}  master={p.is_master}  localized={p.is_localized}')
        print(f'  HEDR version {version:.2f}  count {count} ({p.count_convention})  next object {next_id:08X}')
        if p.author:
            print(f'  author {p.author!r}')
        print(f'  masters ({len(p.masters)}):')
        for m in p.codec.masters:
            print(f'    {m.name:40} {m.kind}')
        print(f'  own-ID style: {p.codec.own_style}; own records: {len(p.own_local_ids())}')
        print(f'  {len(idx):,} records in {len(idx.groups):,} groups; top-level: '
              + ' '.join(g.label_signature for g in p.groups))
        for sig, n in idx.signature_counts().items():
            print(f'    {sig} {n:>9,}')


def cmd_records(a):
    path = Path(a.plugin)
    with _open_lo(path, a.game) as lo:
        p = lo.plugin(path.name)
        n = 0
        for view in p.typed_records(*a.signature):
            if a.edid and not (view.editor_id and fnmatch.fnmatch(view.editor_id.lower(), a.edid.lower())):
                continue
            own = 'own' if p.codec.is_own(view.form_id) else 'override'
            print(f'{view.signature} {str(view.form_key):32} {own:8} {view.editor_id or ""}')
            n += 1
            if a.limit and n >= a.limit:
                break


def _find(lo: LoadOrder, plugin: Plugin, key: str):
    try:
        return lo.resolve(FormKey.parse(key))
    except ValueError:
        pass
    try:
        node = plugin.find(int(key, 16))
        if node is not None:
            return lo.resolve(plugin.codec.try_decode(node.form_id))
    except ValueError:
        pass
    hits = lo.find_editor_id(key)
    return hits[0] if hits else None


def cmd_show(a):
    path = Path(a.plugin)
    with _open_lo(path, a.game) as lo:
        view = _find(lo, lo.plugin(path.name), a.key)
        if view is None:
            sys.exit(f'not found: {a.key}')
        out = view.to_dict()
        out['defined_in_and_overrides'] = [p.name for p, _ in lo.overrides(view.form_key)]
        out['winner'] = view.plugin.name
        container = lo.container_of(view)
        if container:
            out['container'] = [container[0], str(container[1])]
        out['placement_path'] = lo.placement_path(view)
        out['references'] = {path_: str(t) for path_, t in view.links()}
        if a.raw:
            out['subrecords'] = [{'sig': f.signature, 'size': len(f.data), 'hex': f.data[:64].hex()}
                                 for f in view.node.fields]
        print(json.dumps(out, indent=1, default=str))


def cmd_roundtrip(a):
    from .testing.roundtrip import roundtrip
    r = roundtrip(a.plugin, a.level, a.game)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r['ok'] else 1)


def cmd_validate(a):
    from .validate import validate_plugin
    path = Path(a.plugin)
    if a.no_load_order:
        with Plugin.open(path, a.game) as p:
            report = validate_plugin(p)
    else:
        with _open_lo(path, a.game) as lo:
            report = validate_plugin(lo.plugin(path.name), load_order=lo)
    print(report.summary())
    print(json.dumps(report.stats))
    sys.exit(0 if report.ok else 1)


def cmd_diff(a):
    from .diff import diff_plugins
    before, after = Path(a.before), Path(a.after)
    with Plugin.open(before, a.game) as x, Plugin.open(after, a.game) as y:
        x.resolve_master_kinds(after.parent)
        y.resolve_master_kinds(after.parent)
        print(diff_plugins(x, y).summary())


def cmd_schema(a):
    adapter = games.get(a.game or 'starfield')
    schemas = adapter.schemas
    if schemas is None:
        sys.exit(f'{adapter.name} has no typed schemas')
    print(f'{adapter.name} schemas, version {adapter.schema_version}')
    if not a.signature:
        for sig, cls in sorted(schemas.classes.items()):
            print(f'  {sig:5} {cls.__name__:22} {len(cls.schema.members)} members')
        return
    cls = schemas.classes.get(a.signature)
    if cls is None:
        sys.exit(f'no schema for {a.signature}; typed: {sorted(schemas.classes)}')
    sch = cls.schema
    print(f'{sch.signature} -> {cls.__name__} ({sch.name}). {sch.evidence}')
    for m in sch.members:
        flags = ' '.join(x for x, on in (('required', m.required), ('repeat', m.repeat),
                                         (f'count in {m.counter}', m.counter)) if on)
        print(f'  {m.sig}  {m.attr:24} {m.codec.describe()}  {flags}  {m.doc}'.rstrip())
    for r in sch.regions:
        print(f'  region {r.name}: {r.start}..{r.end} (opaque, preserved)')
    if sch.header_flags:
        print('  header flags: ' + ', '.join(f'{1 << b:#010x} {n}' for b, n in sorted(sch.header_flags.items())))


def _asset_context(a):
    path = Path(a.plugin)
    lo = _open_lo(path, a.game)
    plugin = lo.plugin(path.name)
    from .assets.index import AssetIndex
    from .assets.deps import DependencyFinder
    rules = plugin.adapter.asset_rules
    if rules is None:
        sys.exit(f'{plugin.adapter.name} has no asset rules')
    idx = AssetIndex(path.parent, rules, [p.name for p in lo.plugins])
    return lo, plugin, idx, DependencyFinder(idx, plugin.adapter.asset_hooks, plugin.name)


def _views(lo, plugin, keys):
    out = []
    for k in keys:
        v = _find(lo, plugin, k)
        if v is None:
            sys.exit(f'not found: {k}')
        out.append(v)
    return out


def _refuse_data_dir(out, data_dir):
    if Path(data_dir).resolve() in Path(out).resolve().parents or Path(out).resolve() == Path(data_dir).resolve():
        sys.exit('refusing to write into the game Data folder; deploy explicitly')


def cmd_assets(a):
    from .assets import pack as P
    if a.action == 'status':
        print(json.dumps(P.status(a.target[0]), indent=1))
        return
    if a.action == 'pack':
        work = Path(a.target[0])
        _refuse_data_dir(a.out, a.data or Path(json.loads((work / P.MANIFEST).read_text(encoding='utf-8'))['data_dir']))
        data_dir = a.data or json.loads((work / P.MANIFEST).read_text(encoding='utf-8'))['data_dir']
        archive2 = None if a.loose else P.find_archive2(data_dir)
        res = P.pack_work_dir(work, a.plugin_name, a.out, archive2, loose=a.loose)
        print(json.dumps(res.archives, indent=1))
        return
    lo, plugin, idx, finder = _asset_context(a)
    with lo:
        closure = finder.for_records(_views(lo, plugin, a.target))
        if a.action == 'deps':
            print(json.dumps(closure.to_dict(), indent=1))
        elif a.action == 'extract':
            _refuse_data_dir(a.out, idx.data_dir)
            cats = {p: r.category for p, r in closure.files.items()}
            wanted = [p for p, c in cats.items() if a.all or c == 'owned']
            m = P.extract(idx, wanted, a.out, cats)
            print(f'extracted {len(m["files"])} file(s) to {a.out}')


def cmd_transplant(a):
    from .transplant import apply_transplant, plan_transplant
    from .assets.pack import find_archive2, pack
    lo, plugin, idx, finder = _asset_context(a)
    with lo:
        roots = [v.form_key for v in _views(lo, plugin, a.target)]
        plan = plan_transplant(lo, plugin, roots, a.mode, accept_unverified=set(a.accept or ()),
                               asset_finder=finder if a.mode == 'copy' else None,
                               null_rebuild_references=a.null_rebuild)
        print(plan.summary())
        if not a.out:
            print('(plan only; pass --out DIR --new NAME.esm to build)')
            sys.exit(0 if plan.ok else 1)
        _refuse_data_dir(a.out, idx.data_dir)
        target = Plugin.create(a.new, plugin.adapter, flags=0x1, author='PyField transplant')
        with target.transaction() as tx:
            result = apply_transplant(plan, tx, editor_id_prefix=a.prefix or '', asset_index=idx,
                                      include_foreign=a.include_foreign)
            report = tx.commit(Path(a.out) / a.new, load_order=LoadOrder([p for p in lo.plugins
                                                                          if p is not plugin] + [target]))
        print(report.summary())
        if result.assets:
            res = pack(result.assets, a.new, a.out, find_archive2(idx.data_dir))
            print(json.dumps(res.archives, indent=1))


def cmd_blueprint(a):
    from .scene import capture_cell
    path = Path(a.plugin)
    with _open_lo(path, a.game) as lo:
        cell = _find(lo, lo.plugin(path.name), a.cell)
        if cell is None or cell.signature != 'CELL':
            sys.exit(f'not a cell: {a.cell}')
        bp = capture_cell(lo, cell.form_key, name=a.name)
        if a.out:
            _refuse_data_dir(a.out, path.parent)
            bp.save(a.out)
            print(f'{len(bp.nodes)} references captured -> {a.out}')
        else:
            print(json.dumps(bp.to_dict(), indent=1))


def cmd_runtime(a):
    from .scene.runtime import ConversionReport, RuntimeCapture
    cap = RuntimeCapture.load(a.capture)
    if not a.out:
        print(json.dumps(cap.summary(), indent=1))
        return
    report = ConversionReport()
    bp = cap.to_blueprint(set(a.sections) if a.sections else None, a.created_only, report=report)
    bp.save(a.out)
    print(f'{report.placed} references -> {a.out}; {len(report.skipped)} skipped')
    reasons = {}
    for _, why in report.skipped:
        reasons[why] = reasons.get(why, 0) + 1
    for why, n in reasons.items():
        print(f'  {n} x {why}')


def cmd_capabilities(a):
    for adapter in games.adapters():
        if a.game_name and adapter.name != a.game_name:
            continue
        print(f'{adapter.name} ({adapter.title})')
        for c in adapter.capabilities:
            print(f'  {c.key:36} {c.status.value:13} {c.note}')


def _fix_assets_args(a):
    if a.action in ('status', 'pack'):
        a.target = [a.plugin]
    return a


def main(argv=None):
    ap = argparse.ArgumentParser(prog='pyfield', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', help='adapter name (default: detected from the plugin header)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('info'); s.add_argument('plugin'); s.set_defaults(fn=cmd_info)
    s = sub.add_parser('records'); s.add_argument('plugin'); s.add_argument('-s', '--signature', nargs='*', default=[])
    s.add_argument('--edid'); s.add_argument('--limit', type=int); s.set_defaults(fn=cmd_records)
    s = sub.add_parser('show'); s.add_argument('plugin'); s.add_argument('key'); s.add_argument('--raw', action='store_true')
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser('roundtrip'); s.add_argument('plugin')
    s.add_argument('--level', default='fields', choices=['raw', 'tree', 'fields', 'encode']); s.set_defaults(fn=cmd_roundtrip)
    s = sub.add_parser('validate'); s.add_argument('plugin'); s.add_argument('--no-load-order', action='store_true')
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser('diff'); s.add_argument('before'); s.add_argument('after'); s.set_defaults(fn=cmd_diff)
    s = sub.add_parser('schema'); s.add_argument('signature', nargs='?'); s.set_defaults(fn=cmd_schema)
    s = sub.add_parser('assets', help='deps|extract PLUGIN KEY...; status WORK; pack WORK')
    s.add_argument('action', choices=['deps', 'extract', 'status', 'pack'])
    s.add_argument('plugin', help='plugin (deps/extract) or work folder (status/pack)')
    s.add_argument('target', nargs='*')
    s.add_argument('--out'); s.add_argument('--all', action='store_true', help='extract vanilla/foreign too')
    s.add_argument('--plugin-name', dest='plugin_name', help='archive name base for pack')
    s.add_argument('--loose', action='store_true'); s.add_argument('--data')
    s.set_defaults(fn=lambda a: cmd_assets(_fix_assets_args(a)))
    s = sub.add_parser('transplant', help='plan (and with --out, build) a copy/reference transplant')
    s.add_argument('plugin'); s.add_argument('target', nargs='+')
    s.add_argument('--mode', choices=['copy', 'reference'], default='copy')
    s.add_argument('--accept', nargs='*', help='subrecord signatures whose unverified references may be remapped')
    s.add_argument('--null-rebuild', action='store_true'); s.add_argument('--prefix')
    s.add_argument('--include-foreign', action='store_true')
    s.add_argument('--out'); s.add_argument('--new', default='Transplant.esm')
    s.set_defaults(fn=cmd_transplant)
    s = sub.add_parser('blueprint', help='capture CELL references into a blueprint JSON')
    s.add_argument('action', choices=['capture']); s.add_argument('plugin'); s.add_argument('cell')
    s.add_argument('--out'); s.add_argument('--name'); s.set_defaults(fn=cmd_blueprint)
    s = sub.add_parser('runtime', help='summarize a PyFieldCapture file, or convert it to a blueprint')
    s.add_argument('capture'); s.add_argument('--sections', nargs='*'); s.add_argument('--created-only', action='store_true')
    s.add_argument('--out'); s.set_defaults(fn=cmd_runtime)
    s = sub.add_parser('capabilities'); s.add_argument('game_name', nargs='?'); s.set_defaults(fn=cmd_capabilities)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == '__main__':
    main()
