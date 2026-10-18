import struct

import pytest

from pyfield import FormatError, Plugin, Subrecord
from pyfield.core import compression, subrecords as sr
from pyfield.games.tes4family import MODERN_FORMAT, TES4_FORMAT
from pyfield.core.nodes import GroupNode, RecordNode
from pyfield.testing import fixtures as fx


def sf(data=None, **kw):
    p = Plugin.from_bytes(data or fx.starfield_plugin(**kw), 'Test.esm', 'starfield')
    p.set_master_kinds({'Starfield.esm': 'full'})
    return p


# -- subrecords -------------------------------------------------------------------------------

def test_subrecord_roundtrip_with_extended_size():
    fields = [Subrecord('EDID', b'a\0'), Subrecord('DATA', bytes(70000)), Subrecord('DATA', b'')]
    body = sr.encode(fields, MODERN_FORMAT)
    assert body[:4] == b'EDID' and b'XXXX' in body
    assert sr.parse(body, MODERN_FORMAT) == fields


def test_subrecord_truncation_is_reported():
    with pytest.raises(FormatError):
        sr.parse(b'EDID\x05\x00ab', MODERN_FORMAT)


def test_compression_level_detection():
    data = b'hello world ' * 100
    assert compression.detect_level(compression.compress(data, 9), data) == 9
    assert compression.decompress(compression.compress(data, 1)) == data
    with pytest.raises(FormatError):
        compression.decompress(struct.pack('<I', 5) + b'garbage')


# -- reading ----------------------------------------------------------------------------------

def test_header_and_index():
    p = sf()
    assert p.masters == ['Starfield.esm'] and p.author == 'PyField' and p.is_master
    assert len(p.index) == 7 and len(p.index.groups) == 7
    assert p.index.signature_counts() == {'STAT': 4, 'KYWD': 1, 'CELL': 1, 'REFR': 1}
    path = [g.kind for g in p.index.group_path(p.index.entry(6).group)]
    assert path == [0, 2, 3, 6, 8]


def test_lazy_expansion_and_lookup():
    p = sf()
    assert not any(g.is_expanded for g in p.groups)
    refr = p.find(0x01000805)
    assert refr.signature == 'REFR'
    cell_group = p.top_group('CELL')
    assert cell_group.is_expanded and not p.top_group('KYWD').is_expanded
    assert refr.parent.kind == 8 and refr.parent.parent.kind == 6
    assert p.find(0x0BADF00D) is None


def test_records_filter_skips_irrelevant_groups():
    p = sf()
    assert [r.editor_id for r in p.records('KYWD')] == ['PF_Keyword']
    assert not p.top_group('STAT').is_expanded and not p.top_group('CELL').is_expanded
    assert [r.signature for r in p.records()] == ['KYWD', 'STAT', 'STAT', 'STAT', 'STAT', 'CELL', 'REFR']


def test_compressed_and_extended_records_decode():
    p = sf()
    packed = p.find(0x01000803)
    assert packed.is_compressed and packed.get('DATA').data == b'abc' * 500
    assert len(p.find(0x01000802).get('DATA').data) == 76800


# -- preservation -----------------------------------------------------------------------------

@pytest.mark.parametrize('touch', ['nothing', 'expand', 'decode'])
def test_unmodified_roundtrip_is_identical(touch):
    data = fx.starfield_plugin()
    p = sf(data)
    if touch in ('expand', 'decode'):
        for node in p.walk():
            if touch == 'decode' and isinstance(node, RecordNode):
                node.fields
    assert p.to_bytes() == data


def test_odd_stored_count_is_preserved_when_unmodified():
    data = fx.starfield_plugin(count=999)
    assert sf(data).to_bytes() == data


def test_edit_changes_only_that_record():
    data = fx.starfield_plugin()
    p = sf(data)
    stat = p.find(0x01000801)
    stat.get('MODL').data = b'Meshes\\pf\\other.nif\0'
    out = p.to_bytes()
    q = sf(out)
    assert q.find(0x01000801).get('MODL').data == b'Meshes\\pf\\other.nif\0'
    # every other record's bytes are untouched
    for e in sf(data).index:
        if e.form_id != 0x01000801:
            before = data[e.offset:e.offset + 24 + e.size]
            pos = q.index.offsets[q.index.positions(e.form_id)[0]]
            assert out[pos:pos + 24 + e.size] == before
    assert q.hedr == sf(data).hedr


def test_edit_compressed_record_recompresses():
    p = sf()
    packed = p.find(0x01000803)
    packed.get('DATA').data = b'xyz' * 600
    q = sf(p.to_bytes())
    r = q.find(0x01000803)
    assert r.is_compressed and r.get('DATA').data == b'xyz' * 600


def test_add_record_creates_group_in_native_order_and_updates_header():
    p = sf()
    spec = p.spec
    glob = RecordNode.new(spec, 'GLOB', 0x01000806, [Subrecord('EDID', b'PF_Glob\0'),
                                                     Subrecord('FNAM', b'f'), Subrecord('FLTV', bytes(4))],
                          header_tail=p.adapter.header_tail())
    p.top_group('GLOB', create=True).append(glob)
    assert [g.label_signature for g in p.groups] == ['KYWD', 'GLOB', 'STAT', 'CELL']
    q = sf(p.to_bytes())
    version, count, next_id = q.hedr
    assert count == 7 + 7 + 2 and next_id == 0x01000807
    assert q.find(0x01000806).editor_id == 'PF_Glob'


def test_remove_record():
    p = sf()
    refr = p.find(0x01000805)
    refr.parent.remove(refr)
    q = sf(p.to_bytes())
    assert q.find(0x01000805) is None
    assert q.hedr[1] == 13


def test_records_plus_header_count_convention():
    # Bethesda-built masters store records + 1 (no groups)
    data = fx.starfield_plugin(count=8)
    p = sf(data)
    assert p.count_convention == 'records+1'
    stat = p.find(0x01000801)
    stat.parent.remove(stat)
    assert sf(p.to_bytes()).hedr[1] == 7


def test_create_new_plugin():
    p = Plugin.create('New.esm', 'starfield', ['Starfield.esm'], flags=0x1, author='me')
    p.set_master_kinds({'Starfield.esm': 'full'})
    kw = RecordNode.new(p.spec, 'KYWD', 0x01000800, [Subrecord('EDID', b'K\0')], header_tail=p.adapter.header_tail())
    p.top_group('KYWD', create=True).append(kw)
    q = sf(p.to_bytes())
    assert q.masters == ['Starfield.esm'] and q.hedr[1] == 2 and q.hedr[2] == 0x01000801
    assert q.find(0x01000800).header_tail == struct.pack('<IHH', 0, 582, 0)


def test_group_boundary_errors():
    data = bytearray(fx.starfield_plugin())
    # corrupt the KYWD group size so it overruns the file
    pos = data.index(b'GRUP')
    struct.pack_into('<I', data, pos + 4, len(data))
    with pytest.raises(FormatError):
        Plugin.from_bytes(bytes(data), 'Bad.esm', 'starfield').index


# -- oblivion (20-byte headers) ------------------------------------------------------------------

def test_oblivion_format_roundtrip_and_edit():
    data = fx.oblivion_plugin()
    p = Plugin.from_bytes(data, 'Test.esp', 'oblivion')
    assert p.spec is TES4_FORMAT and p.masters == ['Oblivion.esm']
    assert p.to_bytes() == data
    misc = p.find(0x01000800)
    assert misc.editor_id == 'PF_Misc'
    misc.get('DATA').data = struct.pack('<If', 9, 2.0)
    q = Plugin.from_bytes(p.to_bytes(), 'Test.esp', 'oblivion')
    assert struct.unpack('<If', q.find(0x01000800).get('DATA').data) == (9, 2.0)
    assert q.find(0x01000801).get('DESC').data == b'x' * 400


def test_add_master_oblivion_writes_data():
    from pyfield import UnsupportedOperation
    populated = Plugin.from_bytes(fx.oblivion_plugin(), 'Test.esp', 'oblivion')
    with pytest.raises(UnsupportedOperation):          # would shift own IDs 01xxxxxx -> 02xxxxxx
        populated.add_master('Knights.esp')
    p = Plugin.create('New.esp', 'oblivion', ['Oblivion.esm'], author='me')
    p.add_master('Knights.esp')
    sigs = [f.signature for f in p.header.fields]
    assert sigs == ['HEDR', 'CNAM', 'MAST', 'DATA', 'MAST', 'DATA']
    assert p.masters == ['Oblivion.esm', 'Knights.esp']


def test_header_only_edit_keeps_compressed_body_verbatim():
    data = fx.starfield_plugin()
    p = sf(data)
    packed = p.find(0x01000803)
    stored = bytes(packed._stored)
    packed.flags |= 0x4                          # e.g. clearing/setting a header bit
    q = sf(p.to_bytes())
    r = q.find(0x01000803)
    assert r.flags & 0x4 and r.is_compressed and bytes(r._stored) == stored
    packed.fields                                # decoding alone still changes nothing
    assert sf(p.to_bytes()).find(0x01000803)._stored == stored
