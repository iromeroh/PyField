"""VMAD decode/encode: scripts, properties, structs, arrays, opaque fragment suffix."""
import struct

from pyfield.games.vmad import (ARRAY, BOOL, FLOAT, INT, OBJECT, STRING, STRUCT, ObjectRef, Property, Script,
                                Struct, Vmad, formid_offsets)


def ws(text):
    data = text.encode()
    return struct.pack('<H', len(data)) + data


def vendor_list_vmad(suffix=b''):
    """ShipVendorListScript.ShipList: array of structs {leveledShip: object, count: int}."""
    member = lambda fid, n: (struct.pack('<I', 2) + ws('leveledShip') + bytes([OBJECT, 1]) +
                             struct.pack('<HhI', 0, -1, fid) + ws('count') + bytes([INT, 1]) + struct.pack('<i', n))
    body = (struct.pack('<hhH', 6, 2, 1) + ws('ShipVendorListScript') + b'\x00' + struct.pack('<H', 2) +
            ws('ShipList') + bytes([STRUCT + ARRAY, 1]) + struct.pack('<I', 2) + member(0x1EAA10, 1) +
            member(0x1EAA7F, 2) + ws('Enabled') + bytes([BOOL, 1]) + b'\x01')
    return body + suffix


def test_roundtrip_and_access():
    data = vendor_list_vmad(suffix=b'\x02fragments')
    vm = Vmad.decode(data)
    assert vm.encode() == data and vm.suffix == b'\x02fragments'
    ships = vm.script('ShipVendorListScript').property('ShipList')
    assert ships.type_name == 'struct[]' and len(ships.value) == 2
    assert ships.value[1].member('leveledShip').value.form_id == 0x1EAA7F
    assert [r.form_id for r in vm.object_refs()] == [0x1EAA10, 0x1EAA7F]


def test_struct_formids_are_located():
    data = vendor_list_vmad()
    offsets = formid_offsets(data)
    assert {struct.unpack_from('<I', data, o)[0] for o in offsets} == {0x1EAA10, 0x1EAA7F}


def test_edit_and_reencode():
    vm = Vmad.decode(vendor_list_vmad())
    ships = vm.script('ShipVendorListScript').property('ShipList')
    ships.value.append(Struct([Property('leveledShip', OBJECT, ObjectRef(0x01000800)), Property('count', INT, 1)]))
    vm.scripts.append(Script('MyScript', 0, [Property('Label', STRING, 'Probe'), Property('Rate', FLOAT, 0.5)]))
    again = Vmad.decode(vm.encode())
    assert [r.form_id for r in again.object_refs()] == [0x1EAA10, 0x1EAA7F, 0x01000800]
    assert again.script('myscript').property('label').value == 'Probe'


def quest_vmad():
    """A quest: one script, one stage fragment, and one alias with a script property (Starfield layout)."""
    scripts = struct.pack('<hhH', 6, 2, 1) + ws('MyQuestScript') + b'\x00' + struct.pack('<H', 0)
    frag_script = ws('Fragments:Quests:QF_Test') + b'\x00' + struct.pack('<H', 0)
    fragment = struct.pack('<HhiB', 100, 0, 0, 1) + ws('Fragments:Quests:QF_Test') + ws('Fragment_Stage_0100_Item_00')
    alias = (struct.pack('<HhI', 0, 3, 0x000013DD) + struct.pack('<hhH', 6, 2, 1) + ws('DefaultAliasScript') + b'\x00' +
             struct.pack('<H', 1) + ws('SQ_Parent') + bytes([OBJECT, 1]) + struct.pack('<HhI', 0, -1, 0x00072C09))
    suffix = struct.pack('<BH', 3, 1) + frag_script + fragment + struct.pack('<H', 1) + alias
    return scripts + suffix


def test_quest_fragments_and_aliases():
    data = quest_vmad()
    vm = Vmad.decode(data, 'QUST')
    fr = vm.fragments
    assert fr is not None and vm.encode() == data
    assert [(f.header[0], f.name) for f in fr.fragments] == [(100, 'Fragment_Stage_0100_Item_00')]
    qa = fr.aliases[0]
    assert qa.alias.alias == 3 and qa.alias.form_id == 0x13DD
    assert qa.script('defaultaliasscript').property('SQ_Parent').value.form_id == 0x72C09
    assert {struct.unpack_from('<I', data, o)[0] for o in formid_offsets(data, 'QUST')} == {0x13DD, 0x72C09}
    assert formid_offsets(data) == set()                                  # without the record type: scripts only
    qa.script('DefaultAliasScript').property('SQ_Parent').value.form_id = 0x01000800      # edit an alias ref
    assert Vmad.decode(vm.encode(), 'QUST').fragments.aliases[0].scripts[0].properties[0].value.form_id == 0x01000800


def test_info_fragment_flags_and_unknown_suffix():
    info = (struct.pack('<hhH', 6, 2, 0) + struct.pack('<BB', 3, 2) + ws('Fragments:TopicInfos:TIF_X') + b'\x00' +
            struct.pack('<H', 0) + b'\x01' + ws('Fragments:TopicInfos:TIF_X') + ws('Fragment_End'))
    vm = Vmad.decode(info, 'INFO')
    assert vm.fragments.fragments[0].name == 'Fragment_End' and vm.encode() == info
    odd = struct.pack('<hhH', 6, 2, 0) + b'\x09garbage'
    vm = Vmad.decode(odd, 'QUST')
    assert vm.fragments is None and vm.suffix == b'\x09garbage' and vm.encode() == odd   # kept verbatim
