import json
import struct

import pytest

from pyfield import FormKey, Plugin, UnsupportedOperation
from pyfield.assets import pack as P
from pyfield.assets.ba2 import Archive, write_gnrl
from pyfield.assets.deps import DependencyFinder, binary_strings
from pyfield.assets.index import AssetIndex
from pyfield.core.loadorder import LoadOrder
from pyfield.games.starfield.assets import RULES, wsed_from_guid
from pyfield.games.tes4family import vmad_formid_offsets
from pyfield.testing import fixtures as fx
from pyfield.transplant import apply_transplant, plan_transplant

sub, z, record, group = fx.sub, fx.z, fx.record, fx.group


def lp(text: str) -> bytes:            # NIF-style length-prefixed string
    return struct.pack('<I', len(text)) + text.encode()


def vmad_with_object(fid: int) -> bytes:
    name, prop = b'MyScript', b'Target'
    return (struct.pack('<hhH', 6, 2, 1) + struct.pack('<H', len(name)) + name + b'\0' + struct.pack('<H', 1) +
            struct.pack('<H', len(prop)) + prop + bytes([1, 1]) + struct.pack('<HhI', 0, -1, fid))


@pytest.fixture
def data(tmp_path):
    d = tmp_path / 'Data'
    d.mkdir()
    # base game archive: a vanilla texture
    write_gnrl(d / 'Starfield - Textures.ba2', {'textures/vanilla/base.dds': b'DDS vanilla'})
    # the mod's archive: nif -> material + geometry, material -> texture
    nif = b'\x00garbage' + lp('Materials\\Mod\\Thing.mat') + b'\x01\x02' + lp('Mod\\Thing') + b'tail'
    mat = json.dumps({'Filename': 'Materials\\Mod\\Thing.mat',
                      'Textures': ['Textures\\Mod\\Thing_color.dds', 'Textures\\Vanilla\\Base.dds',
                                   'Textures\\Mod\\Missing.dds']}).encode()
    write_gnrl(d / 'Mod - Main.ba2', {'meshes/mod/thing.nif': nif, 'materials/mod/thing.mat': mat,
                                      'geometries/mod/thing.mesh': b'MESH', 'textures/mod/thing_color.dds': b'DDS mod'})
    # Mod.esm: KYWD, STAT (model), MISC (keywords + script property -> GLOB, uses PACK), GLOB, PACK
    stat = record('STAT', 0x01000801, sub('EDID', z('Mod_Thing')) + sub('OBND', bytes(24)) +
                  sub('MODL', z('Mod\\Thing.nif')))
    kywd = record('KYWD', 0x01000800, sub('EDID', z('Mod_KW')) + sub('CNAM', bytes(4)) + sub('TNAM', bytes(4)) +
                  sub('FNAM', bytes(4)))
    glob = record('GLOB', 0x01000802, sub('EDID', z('Mod_G')) + sub('FLTV', struct.pack('<f', 1)))
    pack_ = record('PACK', 0x01000803, sub('EDID', z('Mod_Pack')))
    misc = record('MISC', 0x01000804, sub('EDID', z('Mod_Item')) + sub('VMAD', vmad_with_object(0x01000802)) +
                  sub('OBND', bytes(24)) + sub('MODL', z('Mod\\Thing.nif')) +
                  sub('KSIZ', struct.pack('<I', 1)) + sub('KWDA', struct.pack('<I', 0x01000800)) +
                  sub('DATA', struct.pack('<if', 3, 1.0)))
    odd = record('MISC', 0x01000805, sub('EDID', z('Mod_Odd')) + sub('ZZZZ', struct.pack('<II', 7, 0x01000802)))
    npc_pack = record('MISC', 0x01000806, sub('EDID', z('Mod_UsesPack')) + sub('VMAD', vmad_with_object(0x01000803)))
    body = (group(b'KYWD', 0, kywd) + group(b'GLOB', 0, glob) + group(b'MISC', 0, misc + odd + npc_pack) +
            group(b'STAT', 0, stat) + group(b'PACK', 0, pack_))
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 12, 0x01000807)) + sub('MAST', z('Starfield.esm'))
    (d / 'Mod.esm').write_bytes(record('TES4', 0, tes4, 0x1) + body)
    (d / 'Starfield.esm').write_bytes(record('TES4', 0, sub('HEDR', struct.pack('<fII', 0.96, 0, 0x800)), 0x81))
    return d


def setup(data):
    lo = LoadOrder.open(data, ['Mod.esm'], 'starfield')
    idx = AssetIndex(data, RULES, [p.name for p in lo.plugins])
    return lo, idx, DependencyFinder(idx, {}, 'Mod.esm')


# -- archives and asset discovery ----------------------------------------------------------------

def test_gnrl_roundtrip(tmp_path):
    write_gnrl(tmp_path / 'a.ba2', {'meshes/x.nif': b'abc', 'sound/y.wem': b''})
    a = Archive(tmp_path / 'a.ba2')
    assert a.names() == ['meshes/x.nif', 'sound/y.wem'] and a.read('Meshes\\X.nif') == b'abc'


def test_binary_strings_are_length_prefixed():
    assert binary_strings(b'\x00\x00' + lp('Mod\\Thing') + b'K') == ['Mod\\Thing']


def test_dependency_closure_is_verified_and_classified(data):
    lo, idx, finder = setup(data)
    mod = lo.plugin('Mod.esm')
    closure = finder.for_records([mod.typed(mod.find(0x01000801))])
    cats = closure.by_category()
    assert cats['owned'] == ['geometries/mod/thing.mesh', 'materials/mod/thing.mat', 'meshes/mod/thing.nif',
                             'textures/mod/thing_color.dds']
    assert cats['vanilla'] == ['textures/vanilla/base.dds']
    assert [t for _, t in closure.unresolved] == ['Textures\\Mod\\Missing.dds']
    lo.close()


def test_extract_status_roundtrip(data, tmp_path):
    lo, idx, finder = setup(data)
    work = tmp_path / 'work'
    P.extract(idx, ['meshes/mod/thing.nif', 'materials/mod/thing.mat'], work)
    (work / 'materials/mod/thing.mat').write_bytes(b'{}')
    (work / 'textures/new.dds').parent.mkdir(parents=True)
    (work / 'textures/new.dds').write_bytes(b'DDS new')
    st = P.status(work)
    assert st == {'changed': ['materials/mod/thing.mat'], 'added': ['textures/new.dds'], 'removed': [],
                  'unchanged': ['meshes/mod/thing.nif']}
    loose = P.pack_work_dir(work, 'Out.esm', tmp_path / 'loose', None, loose=True)
    assert loose.archives['loose']['members'] == 3 and (tmp_path / 'loose/textures/new.dds').exists()
    lo.close()


def test_wsed_guid_layout():
    assert wsed_from_guid('{BEE09E57-9027-5834-B8EE-ADAF2D7EA25A}') == (0x90275834, 0xBEE09E57, 0x2D7EA25A, 0xB8EEADAF)


def test_vmad_locator():
    v = vmad_with_object(0x01000802)
    offs = vmad_formid_offsets(v)
    assert [struct.unpack_from('<I', v, o)[0] for o in offs] == [0x01000802]
    assert vmad_formid_offsets(b'\x05\x00\x02\x00') is None


# -- transplant ------------------------------------------------------------------------------

def test_copy_plan_closure_and_apply(data, tmp_path):
    lo, idx, finder = setup(data)
    mod = lo.plugin('Mod.esm')
    plan = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x804)], 'copy', asset_finder=finder)
    assert plan.ok, plan.blocking
    assert sorted(n.signature for n in plan.copy.values()) == ['GLOB', 'KYWD', 'MISC']
    assert all(r.known for r in plan.references)                    # KWDA + VMAD located
    target = Plugin.create('New.esm', 'starfield', flags=1)
    with target.transaction() as tx:
        result = apply_transplant(plan, tx, editor_id_prefix='X_', asset_index=idx)
        report = tx.commit(tmp_path / 'New.esm', load_order=LoadOrder(lo.plugins[:-1] + [target]))
    assert report.ok, report.summary()
    out = Plugin.open(tmp_path / 'New.esm')
    out.set_master_kinds({'Starfield.esm': 'full'})
    item = out.typed(next(out.records('MISC')))
    new_kw, new_g = result.mapping[FormKey('Mod.esm', 0x800)], result.mapping[FormKey('Mod.esm', 0x802)]
    assert item.editor_id == 'X_Mod_Item' and item.keywords == [new_kw]
    vmad = item.node.get('VMAD').data
    assert struct.unpack_from('<I', vmad, next(iter(vmad_formid_offsets(vmad))))[0] == out.codec.encode(new_g)
    assert sorted(result.assets) == ['geometries/mod/thing.mesh', 'materials/mod/thing.mat',
                                     'meshes/mod/thing.nif', 'textures/mod/thing_color.dds']
    lo.close()


def test_unknown_position_blocks_until_accepted(data):
    lo, idx, finder = setup(data)
    mod = lo.plugin('Mod.esm')
    plan = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x805)], 'copy')
    assert not plan.ok and any('ZZZZ+4' in b for b in plan.blocking)
    target = Plugin.create('New.esm', 'starfield')
    with target.transaction() as tx, pytest.raises(UnsupportedOperation):
        apply_transplant(plan, tx)
    accepted = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x805)], 'copy', accept_unverified={'ZZZZ'})
    assert accepted.ok
    lo.close()


def test_rebuild_only_reference_blocks_or_nulls(data):
    lo, idx, finder = setup(data)
    mod = lo.plugin('Mod.esm')
    plan = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x806)], 'copy')
    assert not plan.ok and FormKey('Mod.esm', 0x803) in plan.rebuild
    nulled = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x806)], 'copy', null_rebuild_references=True)
    assert nulled.ok
    target = Plugin.create('New.esm', 'starfield')
    with target.transaction() as tx:
        apply_transplant(nulled, tx)
    vmad = next(target.records('MISC')).get('VMAD').data
    assert struct.unpack_from('<I', vmad, next(iter(vmad_formid_offsets(vmad))))[0] == 0
    lo.close()


def test_rebuild_only_root_and_reference_mode(data):
    lo, idx, finder = setup(data)
    mod = lo.plugin('Mod.esm')
    assert not plan_transplant(lo, mod, [FormKey('Mod.esm', 0x803)], 'copy').ok     # PACK root
    ref = plan_transplant(lo, mod, [FormKey('Mod.esm', 0x803)], 'reference')
    target = Plugin.create('New.esm', 'starfield')
    with target.transaction() as tx:
        apply_transplant(ref, tx)
    assert target.masters == ['Starfield.esm', 'Mod.esm']
    lo.close()
