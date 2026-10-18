"""Derive the majority subrecord order of every record type from Bethesda-built masters.

Starfield's on-disk subrecord order is not strictly fixed (e.g. vanilla REFR XOWN follows XLYR
17,389 times and precedes it 1,258 times), so the order is learned: for each record type,
count for every pair of top-level signatures (first occurrences, component blocks skipped)
which one comes first, then order them topologically along majority edges (weight = margin);
cycles are broken at the weakest margin, ties by mean relative position. The
result guides where PyField inserts a new subrecord; it is not a validity rule.

    python tools/derive_subrecord_order.py "<Starfield>/Data" -o src/pyfield/games/starfield/data/subrecord_order.json
"""
from __future__ import annotations

import argparse
import collections
import json
import time
from pathlib import Path

from pyfield import open_plugin

BETHESDA = ['Starfield.esm', 'ShatteredSpace.esm', 'SFBGS00D.esm', 'SFBGS050.esm', 'SFBGS003.esm',
            'SFBGS006.esm', 'SFBGS007.esm', 'SFBGS008.esm', 'SFBGS004.esm', 'SFBGS047.esm', 'Constellation.esm',
            'sfbgs00c.esm', 'sfbgs021.esm', 'sfbgs023.esm'] + [f'sfta0{i}.esm' for i in range(1, 7)]
REGIONS = {'BFCB': 'BFCE'}
MAX_PER_TYPE = 200_000      # enough statistics; keeps the run to a few minutes


def top_level_sequence(fields):
    seq, seen, inside = [], set(), None
    for f in fields:
        sig = f.signature
        if inside:
            if sig == inside:
                inside = None
            continue
        if sig in REGIONS:
            inside = REGIONS[sig]
            continue
        if sig not in seen:
            seen.add(sig)
            seq.append(sig)
    return seq


def derive(data: Path) -> dict:
    pairs = collections.defaultdict(collections.Counter)      # type -> (a, b) -> count
    seen_counts = collections.defaultdict(collections.Counter)
    position = collections.defaultdict(collections.Counter)    # type -> sig -> summed relative position
    per_type = collections.Counter()
    for name in BETHESDA:
        path = data / name
        if not path.exists():
            continue
        t0 = time.perf_counter()
        with open_plugin(path) as p:
            for e in p.index:
                if per_type[e.signature] >= MAX_PER_TYPE:
                    continue
                per_type[e.signature] += 1
                seq = top_level_sequence(p.node_at(e.offset).fields)
                seen_counts[e.signature].update(seq)
                for i, sig in enumerate(seq):
                    position[e.signature][sig] += i / max(1, len(seq) - 1)
                for i, a in enumerate(seq):
                    for b in seq[i + 1:]:
                        pairs[e.signature][(a, b)] += 1
        print(f'{name}: {time.perf_counter() - t0:.1f}s', flush=True)
    out = {}
    for sig, counter in sorted(pairs.items()):
        sigs = sorted(seen_counts[sig])
        mean = {s: position[sig][s] / seen_counts[sig][s] for s in sigs}
        incoming = {s: {} for s in sigs}          # b -> {a: margin} for majority edges a -> b
        contested = []
        for i, a in enumerate(sigs):
            for b in sigs[i + 1:]:
                ab, ba = counter[(a, b)], counter[(b, a)]
                if ab > ba:
                    incoming[b][a] = ab - ba
                elif ba > ab:
                    incoming[a][b] = ba - ab
                if ab and ba:
                    contested.append([a, b, ab, ba])
        order, remaining = [], set(sigs)
        while remaining:
            free = [s for s in remaining if not (incoming[s].keys() & remaining)]
            if not free:   # cycle: release the node whose remaining incoming evidence is weakest
                free = [min(remaining, key=lambda s: (sum(m for a, m in incoming[s].items() if a in remaining), mean[s]))]
            nxt = min(free, key=lambda s: (mean[s], s))
            order.append(nxt)
            remaining.discard(nxt)
        out[sig] = {'order': order, 'records': per_type[sig],
                    'contested': sorted(contested, key=lambda c: -min(c[2], c[3]))[:20]}
    for sig in per_type:
        out.setdefault(sig, {'order': sorted(seen_counts[sig]), 'records': per_type[sig], 'contested': []})
    return {'source': 'Bethesda masters, majority pairwise order of first occurrences (component blocks skipped)',
            'generated': time.strftime('%Y-%m-%d'), 'types': out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    result = derive(Path(a.data))
    Path(a.out).write_text(json.dumps(result, indent=0), encoding='utf-8')
    t = result['types']
    print(f"{len(t)} record types -> {a.out}")
    print('REFR:', t['REFR']['order'])
    print('REFR contested (top):', t['REFR']['contested'][:6])


if __name__ == '__main__':
    main()
