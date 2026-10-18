"""Phase 0 baseline: index + roundtrip every plugin in the given data folders.

Writes docs/phase0/baseline.json and prints a table. Read-only on the inputs.

    python tools/phase0_baseline.py --starfield "C:/.../Starfield/Data" --oblivion "C:/.../Oblivion/Data" \
        --extra <path>/SummersetIsle.esp
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pyfield.core.formids import FormKey
from pyfield.core.plugin import Plugin
from pyfield.testing.roundtrip import roundtrip

FIELDS_LIMIT = 600 * 1024 * 1024    # decode-every-record pass only below this size


def describe(path: Path, game: str) -> dict:
    t0 = time.perf_counter()
    with Plugin.open(path, game) as p:
        idx = p.index
        index_seconds = time.perf_counter() - t0
        codec = p.codec
        own = override = unresolved = 0
        for fid in idx.form_ids:
            key = codec.try_decode(fid)
            if not isinstance(key, FormKey):
                unresolved += 1
            elif key.plugin == codec._self:
                own += 1
            else:
                override += 1
        dupes = idx.duplicates()
        return {
            'file': path.name, 'game': game, 'bytes': path.stat().st_size,
            'flags': f'{p.flags:08X}', 'kind': p.kind, 'localized': p.is_localized,
            'hedr': list(p.hedr), 'count_convention': p.count_convention,
            'masters': [{'name': m.name, 'kind': m.kind} for m in codec.masters],
            'own_style': codec.own_style, 'codec_assumptions': codec.assumptions,
            'records': len(idx), 'groups': len(idx.groups), 'record_types': len(idx.signature_counts()),
            'top_signatures': dict(list(idx.signature_counts().items())[:12]),
            'compressed': sum(1 for f in idx.flags if f & p.spec.compressed_flag),
            'own_records': own, 'override_records': override, 'unresolved_header_formids': unresolved,
            'duplicate_formids': len(dupes),
            'index_seconds': round(index_seconds, 3),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--starfield')
    ap.add_argument('--oblivion')
    ap.add_argument('--extra', nargs='*', default=[], help='extra Oblivion plugins (outside Data)')
    ap.add_argument('--out', default='docs/phase0/baseline.json')
    ap.add_argument('--skip-fields-over', type=int, default=FIELDS_LIMIT)
    a = ap.parse_args()
    jobs = []
    if a.starfield:
        jobs += [(p, 'starfield') for p in sorted(Path(a.starfield).iterdir()) if p.suffix.lower() in ('.esm', '.esp', '.esl')]
    if a.oblivion:
        jobs += [(p, 'oblivion') for p in sorted(Path(a.oblivion).iterdir()) if p.suffix.lower() in ('.esm',)]
    jobs += [(Path(p), 'oblivion') for p in a.extra]
    results = []
    for path, game in jobs:
        entry = {}
        try:
            entry = describe(path, game)
            entry['roundtrip_raw'] = roundtrip(path, 'raw', game)['ok']
            if path.stat().st_size <= a.skip_fields_over:
                r = roundtrip(path, 'fields', game)
                entry['roundtrip_fields'] = r['ok']
                entry['fields_seconds'] = r['seconds']
                if not r['ok']:
                    entry['problems'] = r['problems'][:5]
        except Exception as exc:   # report and continue: the baseline must cover every file
            entry.update({'file': path.name, 'game': game, 'error': f'{type(exc).__name__}: {exc}'})
        results.append(entry)
        print(f"{entry.get('file'):45} {entry.get('records', '-'):>9} rec  idx {entry.get('index_seconds', '-'):>6}s  "
              f"raw {entry.get('roundtrip_raw', '-')!s:5} fields {entry.get('roundtrip_fields', '-')!s:5} "
              f"{entry.get('fields_seconds', '')}s {entry.get('error', '')}", flush=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'generated': time.strftime('%Y-%m-%d %H:%M'), 'files': results}, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    main()
