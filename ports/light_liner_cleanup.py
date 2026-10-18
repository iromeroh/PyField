"""PyField port of interstellar_liners/tools/prepare_light_liner_cleanup.py (clean + derive_esm).

Reads a CK-saved last_mile_shuttle.esp (default: the Oct 11 bundle's `before` copy) and the
masters in the game Data folder, all read-only. Writes the cleaned ESP and derived ESM to
PyField/build/port_light_liner_cleanup/ and, if the legacy bundle has `prepared` outputs,
compares the two implementations record by record.

Steps (same rules as the legacy tool):
  1. GBFM Watchdog 0200CB02 / Transpo 0200CB05: clear header bit 0x4 (Unique).
  2. Their generated CELLs (FLFM links): clear header bit 0x4 (Is Unique).
  3. LCTN 003807CF: drop ACUR triplets (GBFM, REFR, LCTN) of those ships; omit ACUR if empty.
  4. In the ships' linked interiors (FLKW 000055E9): containers owned by SLL_SpacelinerFaction
     with rank 1, loose items (ALCH MISC BOOK WEAP ARMO AMMO KEYM LVLI) with rank 0.
  5. ESM = cleaned ESP with header flags 0x401, INCC = interior cell count, HEDR next ID
     prefixed 02.

    python ports/light_liner_cleanup.py [--esp PATH] [--data DIR] [--legacy-bundle DIR] [--out DIR]
"""
import os
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
from pathlib import Path

from pyfield import FormKey, Plugin, Subrecord
from pyfield.core.loadorder import LoadOrder
from pyfield.diff import diff_plugins

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
LEGACY_BUNDLE = WORKSPACE / 'interstellar_liners' / 'build' / 'light_liner_cleanup_20261011_205353'
DATA = Path(os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data'))

OWN = 'last_mile_shuttle.esp'
SHIPS = {FormKey(OWN, 0x00CB02): 'Watchdog', FormKey(OWN, 0x00CB05): 'Transpo'}
LANDING_LOCATION = FormKey('Starfield.esm', 0x3807CF)
INTERIOR_LINK = FormKey('Starfield.esm', 0x0055E9)        # SpaceshipLinkedInterior keyword
UNIQUE = 0x4
ITEMS = {'ALCH', 'MISC', 'BOOK', 'WEAP', 'ARMO', 'AMMO', 'KEYM', 'LVLI'}


def u32(data: bytes) -> int:
    return struct.unpack('<I', data)[0]


def legacy_placement(node):
    """The legacy tool's rule: XOWN/XRNK moved before the first XLYR, XLCN or DATA."""
    moved = [f for f in node.fields if f.signature in ('XOWN', 'XRNK')]
    rest = [f for f in node.fields if f.signature not in ('XOWN', 'XRNK')]
    at = next((i for i, f in enumerate(rest) if f.signature in ('XLYR', 'XLCN', 'DATA')), len(rest))
    node.fields = rest[:at] + moved + rest[at:]


def clean(plugin: Plugin, lo: LoadOrder, legacy: bool = False) -> dict:
    """Apply steps 1-4 inside a transaction; returns the report."""
    codec = plugin.codec
    report = collections.defaultdict(list)
    faction = next(v.form_key for v in lo.query('FACT').editor_id('SLL_SpacelinerFaction'))
    with plugin.transaction() as tx:
        # 1 + 2: ships and their generated cells. FLKW/FLFM pairs live in the GBFM's form-link
        # component; GBFM has no typed schema yet, so read the ordered raw fields.
        interiors, cells = [], []
        for key, name in SHIPS.items():
            ship = plugin.get(key)
            assert ship is not None and ship.signature == 'GBFM', key
            if ship.flags & UNIQUE:
                ship.flags &= ~UNIQUE
                report['gbfm_unique_cleared'].append(f'{ship.form_id:08X} {name}')
            link_kw = None
            for f in ship.fields:
                if f.signature == 'FLKW':
                    link_kw = codec.decode(u32(f.data))
                elif f.signature == 'FLFM':
                    cell_key = codec.decode(u32(f.data))
                    cell = plugin.get(cell_key)
                    assert cell is not None and cell.signature == 'CELL' and cell_key.plugin == codec._self
                    cells.append(cell)
                    if link_kw == INTERIOR_LINK:
                        interiors.append(cell_key)
        for cell in cells:
            if cell.flags & UNIQUE:
                cell.flags &= ~UNIQUE
                report['cell_unique_cleared'].append(f'{cell.form_id:08X}')

        # 3: ACUR is an array of 12-byte (GBFM, REFR, LCTN) triplets without a count.
        lctn = plugin.get(LANDING_LOCATION)
        if lctn is not None:
            ship_raw = {codec.encode(k) for k in SHIPS}
            for i, f in enumerate(list(lctn.fields)):
                if f.signature != 'ACUR':
                    continue
                assert len(f.data) % 12 == 0
                triplets = [f.data[j:j + 12] for j in range(0, len(f.data), 12)]
                keep = [t for t in triplets if u32(t[:4]) not in ship_raw]
                for t in triplets:
                    if t not in keep:
                        report['acur_dropped'].append('/'.join(f'{x:08X}' for x in struct.unpack('<III', t)))
                if len(keep) != len(triplets):
                    if keep:
                        lctn.fields[i] = Subrecord('ACUR', b''.join(keep))
                    else:
                        del lctn.fields[i]
                break

        # 4: ownership of containers and loose items placed in the linked interiors.
        counts, unresolved = collections.Counter(), 0
        for refr in plugin.typed_records('REFR'):
            container = lo.container_of(refr)
            if container is None or container[1] not in interiors:
                continue
            base = lo.resolve(refr.base)
            if base is None:
                unresolved += 1
                continue
            kind = base.signature
            if kind != 'CONT' and kind not in ITEMS:
                continue
            rank = 1 if kind == 'CONT' else 0
            owner = refr.ownership
            if owner is not None and owner.owner == faction and owner.no_crime == 0 and refr.faction_rank == rank:
                counts[kind + ' already'] += 1
                continue
            if owner is None:
                owner = refr.schema.member('ownership').codec.default()
            owner.owner, owner.no_crime = faction, 0
            refr.ownership = owner
            refr.faction_rank = rank
            if legacy:
                legacy_placement(refr.node)
            counts[kind] += 1
        report['ownership'] = dict(counts)
        report['ownership_unresolved_bases'] = unresolved
        report['interiors'] = [f'{codec.encode(k):08X}' for k in interiors]
        report['changes'] = list(tx.log)
    return dict(report)


def derive_esm(esp_path: Path, esm_path: Path, data_dir: Path) -> int:
    """Step 5: same records, master header (flags 0x401, INCC, 02-prefixed next ID)."""
    esm = Plugin.open(esp_path, use_mmap=False)
    esm.name = esm_path.name
    esm.resolve_master_kinds(data_dir)
    interior = sum(1 for c in esm.typed_records('CELL') if (c.cell_flags or 0) & 1)
    fields = esm.header.fields
    for i, f in enumerate(fields):
        if f.signature == 'HEDR':
            version, count, nxt = struct.unpack('<fII', f.data[:12])
            fields[i] = Subrecord('HEDR', struct.pack('<fII', version, count, 0x02000000 | (nxt & 0xFFFFFF)) + f.data[12:])
    fields[:] = [f for f in fields if f.signature != 'INCC'] + [Subrecord('INCC', struct.pack('<I', interior))]
    esm.flags = 0x401
    esm.write(esm_path, update_header=False)   # the ESP's counts are already final
    return interior


def compare(mine: Path, legacy: Path, data_dir: Path) -> dict:
    a, b = Plugin.open(legacy, use_mmap=False), Plugin.open(mine, use_mmap=False)
    for p in (a, b):
        p.resolve_master_kinds(data_dir)
    ia, ib = a.index, b.index
    raw_a = {fid: i for i, fid in enumerate(ia.form_ids)}
    identical = differ = 0
    differing = []
    for i, fid in enumerate(ib.form_ids):
        j = raw_a.get(fid)
        if j is None:
            differing.append(f'{fid:08X} only in PyField output')
            continue
        ra = a._data[ia.offsets[j]:ia.offsets[j] + 24 + ia.sizes[j]]
        rb = b._data[ib.offsets[i]:ib.offsets[i] + 24 + ib.sizes[i]]
        if bytes(ra) == bytes(rb):
            identical += 1
        else:
            differ += 1
            differing.append(f'{ib.entry(i).signature} {fid:08X}')
    d = diff_plugins(a, b)
    return {'file_identical': Path(mine).read_bytes() == Path(legacy).read_bytes(),
            'records': len(ib), 'records_byte_identical': identical, 'records_differing': differ,
            'differing_examples': differing[:20], 'semantic_diff': d.summary().splitlines()[:40],
            'semantic_diff_empty': d.empty}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--esp', default=str(LEGACY_BUNDLE / 'before' / 'Data' / OWN))
    ap.add_argument('--data', default=str(DATA))
    ap.add_argument('--legacy-bundle', default=str(LEGACY_BUNDLE))
    ap.add_argument('--out', default=str(ROOT / 'build' / 'port_light_liner_cleanup'))
    ap.add_argument('--legacy-placement', action='store_true',
                    help="place new XOWN/XRNK like the legacy tool (before XLYR/XLCN/DATA) instead of the "
                         "vanilla-majority order; for byte-level regression comparison")
    a = ap.parse_args()
    out, data = Path(a.out), Path(a.data)
    out.mkdir(parents=True, exist_ok=True)
    src = Plugin.open(a.esp, use_mmap=False)
    assert src.name == OWN
    lo = LoadOrder.around(src, data)
    report = clean(src, lo, a.legacy_placement)
    esp_out = out / OWN
    validation = src.transaction().commit(esp_out, load_order=lo)     # nothing pending; validated write
    report['validation'] = {'errors': [str(i) for i in validation.errors],
                            'warnings': [str(i) for i in validation.warnings][:10], 'stats': validation.stats}
    # idempotence: cleaning the output again must change nothing
    again = Plugin.open(esp_out, use_mmap=False)
    lo2 = LoadOrder(lo.plugins[:-1] + [again])
    second = clean(again, lo2, a.legacy_placement)
    report['idempotent'] = not any(second.get(k) for k in ('gbfm_unique_cleared', 'cell_unique_cleared',
                                                           'acur_dropped')) and \
        not {k: v for k, v in second['ownership'].items() if 'already' not in k} and \
        again.to_bytes() == esp_out.read_bytes()
    esm_out = out / 'last_mile_shuttle.esm'
    report['esm_interior_cells'] = derive_esm(esp_out, esm_out, data)
    report['outputs'] = {p.name: sha(p) for p in (esp_out, esm_out)}
    legacy = Path(a.legacy_bundle) / 'prepared'
    if legacy.exists():
        report['vs_legacy'] = {name: compare(out / name, legacy / name, data)
                               for name in (OWN, 'last_mile_shuttle.esm')}
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
