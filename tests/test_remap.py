"""Overrides across different master layouts (override.remap): FormIDs re-encoded through FormKeys."""
import struct

import pytest

from pyfield import FormKey, Plugin, UnsupportedOperation
from pyfield.core.loadorder import LoadOrder
from pyfield.remap import plan_remap
from pyfield.testing import fixtures as fx

from test_records_and_editing import master_bytes

sub, z, record, group = fx.sub, fx.z, fx.record, fx.group


def source_bytes(extra=b''):
    """Src.esp (master: Master.esm): own keyword 0x900 and a static keyed with both keywords."""
    kywd = record('KYWD', 0x01000900, sub('EDID', z('Src_Keyword_ord')) + sub('CNAM', bytes(4)) +
                  sub('TNAM', bytes(4)) + sub('FNAM', bytes(4)))
    stat = record('STAT', 0x01000901, sub('EDID', z('Src_Static')) + sub('OBND', bytes(24)) + sub('ODTY', bytes(4)) +
                  sub('KSIZ', struct.pack('<I', 2)) + sub('KWDA', struct.pack('<II', 0x00000800, 0x01000900)) +
                  sub('MODL', z('Meshes\\src\\box.nif')) + sub('FLLD', bytes(4)) + sub('DNAM', bytes(8)) + extra)
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 4, 0x01000902)) + sub('MAST', z('Master.esm'))
    return record('TES4', 0, tes4) + group(b'KYWD', 0, kywd) + group(b'STAT', 0, stat)


@pytest.fixture
def setup(tmp_path):
    def make(extra=b''):
        (tmp_path / 'Master.esm').write_bytes(master_bytes())
        (tmp_path / 'Src.esp').write_bytes(source_bytes(extra))
        return LoadOrder.open(tmp_path, ['Src.esp'], 'starfield')
    return make


def reversed_target():
    """Masters in the opposite order: raw indexes of both change meaning."""
    target = Plugin.create('Patch.esp', 'starfield', ['Src.esp', 'Master.esm'])
    target.set_master_kinds({'Src.esp': 'full', 'Master.esm': 'full'})
    return target


def test_known_positions_are_reencoded(setup):
    with setup() as lo:
        target = reversed_target()
        with target.transaction() as tx:
            stat = tx.override(lo.resolve(FormKey('Src.esp', 0x901)), load_order=lo)
            assert stat.node.form_id == 0x00000901                         # Src.esp is master #0 here
            assert struct.unpack('<II', stat.node.get('KWDA').data) == (0x01000800, 0x00000900)
            assert stat.node.get('MODL').data == b'Meshes\\src\\box.nif\0'
            assert any('remapped 2 FormID' in line for line in tx.log)


def test_master_added_when_missing(setup):
    with setup() as lo:
        target = Plugin.create('Patch.esp', 'starfield', ['Src.esp'])
        target.set_master_kinds({'Src.esp': 'full'})
        with target.transaction() as tx:
            stat = tx.override(lo.resolve(FormKey('Src.esp', 0x901)), load_order=lo)
            assert target.masters == ['Src.esp', 'Master.esm']
            assert [target.form_key(v) for v in struct.unpack('<II', stat.node.get('KWDA').data)] == \
                [FormKey('Master.esm', 0x800), FormKey('Src.esp', 0x900)]


def test_unknown_position_blocks_until_accepted(setup):
    extra = sub('XTST', struct.pack('<II', 0x01000900, 0x3F800000))      # a FormID and a float, unknown layout
    with setup(extra) as lo:
        with reversed_target().transaction() as tx:
            with pytest.raises(UnsupportedOperation) as err:
                tx.override(lo.resolve(FormKey('Src.esp', 0x901)), load_order=lo)
            assert err.value.capability == 'override.remap' and 'XTST+0' in str(err.value)
        target = reversed_target()
        with target.transaction() as tx:
            stat = tx.override(lo.resolve(FormKey('Src.esp', 0x901)), load_order=lo, accept_unverified={'XTST'})
            assert struct.unpack('<II', stat.node.get('XTST').data) == (0x00000900, 0x3F800000)


def test_text_is_not_mistaken_for_formids(setup):
    with setup() as lo:
        src = lo.plugin('Src.esp')
        plan = plan_remap(src, src.find(0x01000900), reversed_target())       # no load order: no existence check
        assert plan.blocking == [] and plan.values == []                       # "…_ord\0" in EDID is text


def test_container_records_still_need_compatible_layouts(setup):
    with setup() as lo:
        target = Plugin.create('Patch.esp', 'starfield', ['Src.esp', 'Master.esm'])
        target.set_master_kinds({'Src.esp': 'full', 'Master.esm': 'full'})
        with target.transaction() as tx:
            with pytest.raises(UnsupportedOperation, match='container'):
                tx.override(lo.plugin('Master.esm').typed(lo.plugin('Master.esm').find(0x803)), load_order=lo)
