"""Validate typed schemas against real plugins.

For every record of a schema'd type, every typed member present at top level is decoded
and re-encoded; the bytes must be identical. Also counts unresolved FormLinks and
top-level ambiguities. Writes a JSON report (default docs/phase2/schema_validation.json).

    python tools/validate_schemas.py "C:/.../Starfield/Data/Starfield.esm" [more plugins] [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import time
from pathlib import Path

from pyfield import open_plugin
from pyfield.core.formids import Unresolved
from pyfield.errors import SchemaError


def validate(path: Path, limit: int | None = None) -> dict:
    t0 = time.perf_counter()
    stats = collections.defaultdict(lambda: collections.Counter())
    examples = collections.defaultdict(list)
    with open_plugin(path) as plugin:
        schemas = plugin.adapter.schemas
        for sig in sorted(schemas.classes):
            entries = list(plugin.index.of_signature(sig))
            if limit:
                entries = entries[:limit]
            for e in entries:
                view = plugin.typed(plugin.node_at(e.offset))
                ctx = view.context
                fields = view.node.fields
                stats[sig]['records'] += 1
                for m in view.schema.members:
                    positions = view._positions(m.sig)
                    if not positions:
                        continue
                    key = f'{sig}.{m.attr}'
                    if len(positions) > 1 and not m.repeat:
                        stats[key]['ambiguous'] += 1
                        if len(examples[key]) < 3:
                            examples[key].append(f'{e.form_id:08X}: {len(positions)} occurrences')
                        continue
                    for i in positions:
                        raw = fields[i].data
                        stats[key]['present'] += 1
                        try:
                            value = m.codec.decode(raw, ctx)
                            again = m.codec.encode(value, ctx)
                        except SchemaError as exc:
                            stats[key]['decode_error'] += 1
                            if len(examples[key]) < 3:
                                examples[key].append(f'{e.form_id:08X}: {exc} [{raw[:24].hex()}]')
                            continue
                        if again != raw:
                            stats[key]['mismatch'] += 1
                            if len(examples[key]) < 3:
                                examples[key].append(f'{e.form_id:08X}: {raw[:24].hex()} -> {again[:24].hex()}')
                            continue
                        for _, link in m.codec.links(value):
                            stats[key]['links'] += 1
                            if isinstance(link, Unresolved):
                                stats[key]['unresolved_links'] += 1
    members = {k: dict(v) for k, v in sorted(stats.items())}
    failures = {k: v for k, v in members.items()
                if v.get('decode_error') or v.get('mismatch') or v.get('ambiguous') or v.get('unresolved_links')}
    return {'file': path.name, 'seconds': round(time.perf_counter() - t0, 2), 'members': members,
            'failures': failures, 'examples': dict(examples)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plugins', nargs='+')
    ap.add_argument('--limit', type=int, help='records per type (default: all)')
    ap.add_argument('--out', default='docs/phase2/schema_validation.json')
    a = ap.parse_args()
    reports = []
    for p in a.plugins:
        r = validate(Path(p), a.limit)
        reports.append(r)
        print(f"{r['file']}: {r['seconds']}s, {sum(v.get('records', 0) for v in r['members'].values())} records, "
              f"{len(r['failures'])} failing members")
        for k, v in r['failures'].items():
            print('  FAIL', k, v, r['examples'].get(k, [])[:2])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    main()
