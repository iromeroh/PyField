"""Demo 5 — rebuild a player ship from a PyFieldCapture ship capture as a new ship form (Phase 7).

    python examples/demo_ship_rebuild.py "<Documents>/My Games/Starfield/PyField/captures/PyField Probe.json"
        [--level 114] [--name "PyField Probe Copy"]

Writes PyField/build/ship_demo/PyFieldShipTest.esm (never into Data) and parts.json (every part: pack-in,
module pick exact/level/tie, ship-local origin, agreement). The ship GBFM copies Constellation_Frontier_Template's
components and replaces its blueprint. With --vendor the New Atlantis ship technician also sells it (its ShipList script property gets a new entry).
"""
import os
import argparse
import json
import struct
from pathlib import Path

from pyfield import FormKey, Plugin
from pyfield.core.subrecords import Subrecord
from pyfield.core.loadorder import LoadOrder
from pyfield.games.vmad import OBJECT, ObjectRef, Property, Struct, Vmad
from pyfield.games.starfield.ships import (FRONTIER_TEMPLATE, blueprint_from_parts, build_ship,
                                           parts_from_capture)
from pyfield.scene.runtime import RuntimeCapture

DATA = os.environ.get('PYFIELD_STARFIELD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data')
TARGET = 'PyFieldShipTest.esm'
VENDOR_LIST = FormKey('Starfield.esm', 0x1EAA10)        # LShip_Vendor_Generic_A_Rambler (layout template)
VENDOR_ACTIVATOR = FormKey('Starfield.esm', 0x1F767B)   # ShipVendorList_NewAtlantis_Always


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('capture')
    ap.add_argument('--level', type=int, default=114, help='player level for picking stat variants')
    ap.add_argument('--name', default=None)
    ap.add_argument('--vendor', action='store_true',
                    help='also sell it at the New Atlantis ship technician ("Always" list; vanilla ships stay)')
    ap.add_argument('--form-id', type=lambda v: int(v, 16), default=0x800,
                    help='local FormID of the ship (hex): use a new one per ship, a save that owned a ship of the '
                         'same ID keeps its own blueprint for it')
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'build' / 'ship_demo'))
    a = ap.parse_args()
    raw = json.loads(Path(a.capture).read_text(encoding='utf-8'))
    cap = RuntimeCapture.from_dict(raw)
    names = cap.full + cap.light + cap.medium
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    with LoadOrder.open(a.data, [n for n in names if n]) as lo:
        parts = parts_from_capture(cap, raw, lo, a.level)
        report = [{'index': p.index, 'packin': str(p.packin), 'module': str(p.module), 'module_edid': p.module_editor_id,
                   'choice': p.choice, 'alternatives': p.alternatives,
                   'origin': p.origin.to_dict(), 'agreement': f'{p.support}/{p.references}'} for p in parts]
        (out / 'parts.json').write_bytes(json.dumps(report, indent=1).encode())
        for r in report:
            print(f"{r['index']:2} {r['choice']:5} {r['module_edid'][:52]:52} {r['origin']['position']} "
                  f"rot {r['origin']['rotation_deg']} ({r['agreement']})")

        blueprint = blueprint_from_parts(parts)
        masters = ['Starfield.esm'] + sorted({lo.plugin(p.module.plugin).name for p in blueprint} - {'Starfield.esm'})
        path = out / TARGET
        if path.exists():
            path.unlink()
        plugin = Plugin.create(TARGET, 'starfield', masters, flags=0x1, author='PyField',
                               description='Ship rebuilt from a runtime capture (test, safe to remove)')
        plugin.set_master_kinds({m: lo.plugin(m).kind for m in masters})
        template = lo.resolve(FRONTIER_TEMPLATE)           # winning version; FormIDs remapped by build_ship
        name = a.name or f'{cap.name} (PyField)'
        with plugin.transaction() as tx:
            tx.allocator.next = max(tx.allocator.next, a.form_id)
            ship = build_ship(tx, template, blueprint, 'PyFieldShip_' + ''.join(c for c in cap.name if c.isalnum()), name,
                              load_order=lo)
            if a.vendor:
                # A new leveled list holding only this ship (layout of the vanilla Rambler list)...
                shiplist = tx.new_record('LVLB', 'PyFieldShip_VendorList')
                entry = struct.pack('<IIi', 1, plugin.raw_form_id(ship.form_key), 1)
                fields = [f for f in lo.resolve(VENDOR_LIST).node.fields if f.signature not in ('EDID', 'LVLO', 'LLCT')]
                at = next(i for i, f in enumerate(fields) if f.signature == 'FLLD')
                shiplist.node.fields = ([shiplist.node.fields[0]] + fields[:at] +
                                        [Subrecord('LLCT', bytes([1])), Subrecord('LVLO', entry)] + fields[at:])
                # ...appended to the New Atlantis "Always" vendor's ShipVendorListScript.ShipList (vanilla ships stay).
                vendor = tx.override(lo.resolve(VENDOR_ACTIVATOR), load_order=lo)
                vm = Vmad.decode(bytes(vendor.node.get('VMAD').data))
                vm.script('ShipVendorListScript').property('ShipList').value.append(
                    Struct([Property('leveledShip', OBJECT, ObjectRef(plugin.raw_form_id(shiplist.form_key)))]))
                vendor.node.fields = [Subrecord('VMAD', vm.encode()) if f.signature == 'VMAD' else f
                                      for f in vendor.node.fields]
                print(f'vendor {VENDOR_ACTIVATOR} ShipList += {shiplist.form_key} ({ship.form_key})')
            rep = tx.commit(path, load_order=LoadOrder(lo.plugins + [plugin]))
        print(rep.summary().splitlines()[0])
        raw_id = plugin.raw_form_id(ship.form_key)
        print(f'\n{len(blueprint)} parts -> {path}\nship form {ship.form_key} "{name}"; in game: '
              f'player.placeatme {raw_id & 0xFFFFFF:06X} prefixed with the plugin\'s load-order index')


if __name__ == '__main__':
    main()
