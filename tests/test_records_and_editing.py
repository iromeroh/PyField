import struct

import pytest

from pyfield import FormKey, Plugin, SchemaError, UnsupportedOperation, ValidationError
from pyfield.core.loadorder import LoadOrder
from pyfield.diff import diff_plugins
from pyfield.testing import fixtures as fx
from pyfield.validate import validate_plugin

sub, z, record, group = fx.sub, fx.z, fx.record, fx.group


def master_bytes():
    kywd = record('KYWD', 0x800, sub('EDID', z('M_Keyword')) + sub('CNAM', bytes(4)) + sub('TNAM', bytes(4)) +
                  sub('FNAM', bytes(4)))
    stat = record('STAT', 0x801, sub('EDID', z('M_Static')) + sub('OBND', struct.pack('<6f', -1, -1, -1, 1, 1, 1)) +
                  sub('ODTY', bytes(4)) + sub('MODL', z('Meshes\\m\\box.nif')) + sub('FLLD', bytes(4)) +
                  sub('DNAM', struct.pack('<ff', 90.0, 0.0)))
    misc = record('MISC', 0x805, sub('EDID', z('M_Misc')) + sub('OBND', bytes(24)) + sub('ODTY', bytes(4)) +
                  sub('FULL', z('Thing')) + sub('MODL', z('m.nif')) + sub('FLLD', bytes(4)) +
                  sub('DATA', struct.pack('<if', 10, 0.5)))
    glob = record('GLOB', 0x804, sub('EDID', z('M_Global')) + sub('FLTV', struct.pack('<f', 3.0)))
    cell = record('CELL', 0x802, sub('EDID', z('M_Cell')) + sub('DATA', struct.pack('<I', 1)))
    refr = record('REFR', 0x803, sub('NAME', struct.pack('<I', 0x801)) + sub('XSCL', struct.pack('<f', 2.0)) +
                  sub('DATA', struct.pack('<6f', 1, 2, 3, 0, 0, 0)))
    cells = group(b'CELL', 0, group(0, 2, group(0, 3, cell + group(0x802, 6, group(0x802, 8, refr)))))
    body = (group(b'KYWD', 0, kywd) + group(b'GLOB', 0, glob) + group(b'MISC', 0, misc) +
            group(b'STAT', 0, stat) + cells)
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 6 + 9, 0x806)) + sub('CNAM', z('test'))
    return record('TES4', 0, tes4, 0x1) + body


def mod_bytes():
    stat = record('STAT', 0x00000801, sub('EDID', z('M_Static')) + sub('OBND', bytes(24)) + sub('ODTY', bytes(4)) +
                  sub('MODL', z('Meshes\\mod\\box.nif')) + sub('FLLD', bytes(4)) + sub('DNAM', bytes(8)))
    kywd = record('KYWD', 0x01000900, sub('EDID', z('Mod_Keyword')) + sub('CNAM', bytes(4)) + sub('TNAM', bytes(4)) +
                  sub('FNAM', bytes(4)))
    body = group(b'KYWD', 0, kywd) + group(b'STAT', 0, stat)
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 4, 0x01000901)) + sub('MAST', z('Master.esm'))
    return record('TES4', 0, tes4, 0) + body


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / 'Master.esm').write_bytes(master_bytes())
    (tmp_path / 'Mod.esp').write_bytes(mod_bytes())
    return tmp_path


@pytest.fixture
def lo(data_dir):
    with LoadOrder.open(data_dir, ['Mod.esp'], 'starfield') as order:
        yield order


# -- typed views ------------------------------------------------------------------------------

def test_typed_view_reads_members(lo):
    stat = lo.plugin('Master.esm').typed(lo.plugin('Master.esm').find(0x801))
    assert type(stat).__name__ == 'Static'
    assert stat.editor_id == 'M_Static' and stat.model == 'Meshes\\m\\box.nif'
    assert stat.bounds.max.x == 1.0 and stat.direction_material.max_angle == 90.0
    assert stat.direction_material.leaf_amplitude is None      # optional trailing fields absent
    assert stat.name is None


def test_setting_member_changes_only_that_subrecord(lo):
    m = lo.plugin('Master.esm')
    stat = m.typed(m.find(0x801))
    before = [f.data for f in stat.node.fields]
    stat.model = 'Meshes\\m\\other.nif'
    after = [f.data for f in stat.node.fields]
    assert [i for i, (x, y) in enumerate(zip(before, after)) if x != y] == [3]
    stat.name = 'A Box'       # FULL is inserted in native order (after FLLD, before DNAM)
    assert [f.signature for f in stat.node.fields] == ['EDID', 'OBND', 'ODTY', 'MODL', 'FLLD', 'FULL', 'DNAM']
    stat.name = None
    assert 'FULL' not in [f.signature for f in stat.node.fields]


def test_struct_assignment_and_counters(lo):
    m = lo.plugin('Master.esm')
    misc = m.typed(m.find(0x805))
    data = misc.data
    data.value = 99
    misc.data = data
    assert m.typed(m.find(0x805)).data.value == 99
    misc.keywords = [FormKey('Master.esm', 0x800)]
    assert misc.keyword_count == 1
    sigs = [f.signature for f in misc.node.fields]
    assert sigs.index('KSIZ') + 1 == sigs.index('KWDA') and sigs.index('KWDA') < sigs.index('DATA')
    misc.keywords = []
    assert misc.keyword_count is None and 'KWDA' not in [f.signature for f in misc.node.fields]


def test_links_and_unknown_fields(lo):
    m = lo.plugin('Master.esm')
    refr = m.typed(m.find(0x803))
    assert dict(refr.links()) == {'base': FormKey('Master.esm', 0x801)}
    assert refr.placement.position.z == 3.0 and refr.scale == 2.0
    with pytest.raises(SchemaError):
        refr.base = 'not a key'


# -- load order ---------------------------------------------------------------------------------

def test_override_chain_and_winner(lo):
    key = FormKey('Master.esm', 0x801)
    assert [p.name for p, _ in lo.overrides(key)] == ['Master.esm', 'Mod.esp']
    assert lo.resolve(key).model == 'Meshes\\mod\\box.nif'
    assert lo.resolve('000801:Master.esm').plugin.name == 'Mod.esp'
    assert lo.resolve(FormKey('Mod.esp', 0x900)).editor_id == 'Mod_Keyword'


def test_containment_is_separate_from_references(lo):
    refr = lo.resolve(FormKey('Master.esm', 0x803))
    assert lo.container_of(refr) == ('cell_children', FormKey('Master.esm', 0x802))
    assert [k for k, _ in lo.placement_path(refr)] == ['top', 'interior_block', 'interior_subblock',
                                                       'cell_children', 'cell_persistent']
    assert FormKey('Master.esm', 0x802) not in dict(refr.links()).values()


def test_queries_and_editor_ids(lo):
    assert [v.editor_id for v in lo.query('KYWD').editor_id('*keyword').list()] == ['Mod_Keyword', 'M_Keyword']
    assert lo.query('STAT').field('model', 'Meshes\\mod\\box.nif').count() == 1
    assert lo.query('REFR').references(FormKey('Master.esm', 0x801)).count() == 1
    assert lo.find_editor_id('m_global')[0].value == 3.0
    lo.build_reverse_index()
    assert lo.referenced_by(FormKey('Master.esm', 0x801)) == [(FormKey('Master.esm', 0x803), 'base')]


# -- transactions -------------------------------------------------------------------------------

def test_new_records_get_safe_ids_and_commit(lo, data_dir):
    mod = lo.plugin('Mod.esp')
    with mod.transaction() as tx:
        kw = tx.new_record('KYWD', 'Mod_New', color={'r': 1, 'g': 2, 'b': 3, 'a': 0},
                           keyword_type=0, unknown_fnam=bytes(4))
        assert kw.form_key == FormKey('Mod.esp', 0x901)
        g = tx.new_record('GLOB', 'Mod_Glob', value=1.5)
        assert g.form_key.local_id == 0x902
        report = tx.commit(data_dir / 'Mod.esp', load_order=lo)
    assert report.ok, report.summary()
    written = Plugin.open(data_dir / 'Mod.esp')
    assert written.hedr[2] & 0xFFFFFF == 0x903
    assert [g.label_signature for g in written.groups] == ['KYWD', 'GLOB', 'STAT']


def test_rollback_on_exception(lo):
    mod = lo.plugin('Mod.esp')
    before = mod.to_bytes()
    with pytest.raises(RuntimeError):
        with mod.transaction() as tx:
            tx.new_record('GLOB', 'Doomed')
            mod.typed(mod.find(0x01000900)).notes = 'changed'
            raise RuntimeError('boom')
    assert mod.to_bytes() == before


def test_override_into_new_patch(lo, data_dir):
    patch = Plugin.create('Patch.esp', 'starfield')
    with patch.transaction() as tx:
        src = lo.resolve(FormKey('Master.esm', 0x803))      # REFR inside a CELL
        src_master = lo.plugin('Master.esm').typed(src.node)
        refr = tx.override(src_master)
        refr.scale = 3.0
        tx.commit(data_dir / 'Patch.esp')
    p = Plugin.open(data_dir / 'Patch.esp')
    assert p.masters == ['Master.esm']
    cell = p.find(0x802)
    assert cell is not None and cell.get('EDID').data == b'M_Cell\0'     # container copied unchanged
    r = p.typed(p.find(0x803))
    assert r.scale == 3.0 and r.base == FormKey('Master.esm', 0x801)
    assert [k for k, _ in LoadOrder([Plugin.open(data_dir / 'Master.esm'), p]).placement_path(r)][-2:] == \
        ['cell_children', 'cell_persistent']


def test_override_remaps_incompatible_master_layout(lo, data_dir):
    other = Plugin.create('Other.esp', 'starfield', ['Mod.esp', 'Master.esm'])
    other.set_master_kinds({'Mod.esp': 'full', 'Master.esm': 'full'})
    with other.transaction() as tx:
        kywd = tx.override(lo.resolve(FormKey('Mod.esp', 0x900)), load_order=lo)      # re-encoded (test_remap.py)
        assert kywd.node.form_id == 0x00000900 and kywd.form_key == FormKey('Mod.esp', 0x900)


def test_failed_validation_does_not_touch_target(lo, data_dir):
    target = data_dir / 'Mod.esp'
    original = target.read_bytes()
    mod = lo.plugin('Mod.esp')
    tx = mod.transaction()
    misc = tx.new_record('FLST', 'Mod_List')
    misc.forms = [FormKey('Master.esm', 0xDEAD)]          # dangling reference
    with pytest.raises(ValidationError) as err:
        tx.commit(target, load_order=lo)
    assert any(i.code == 'link.missing' for i in err.value.report.errors)
    assert target.read_bytes() == original
    assert not [p for p in data_dir.iterdir() if p.name.endswith('.tmp')]


def test_validation_flags_group_order(data_dir):
    p = Plugin.open(data_dir / 'Mod.esp')
    p.groups.reverse()
    q = Plugin.from_bytes(p.to_bytes(), 'Mod.esp', 'starfield')
    q.set_master_kinds({'Master.esm': 'full'})
    codes = {i.code for i in validate_plugin(q).errors}
    assert 'groups.order' in codes


def test_semantic_diff(lo, data_dir):
    before = Plugin.open(data_dir / 'Mod.esp')
    before.set_master_kinds({'Master.esm': 'full'})
    after = Plugin.open(data_dir / 'Mod.esp')
    after.set_master_kinds({'Master.esm': 'full'})
    with after.transaction() as tx:
        after.typed(after.find(0x00000801)).model = 'x.nif'
        tx.new_record('GLOB', 'Mod_G', value=2.0)
        tx.remove(after.typed(after.find(0x01000900)))
    d = diff_plugins(before, after)
    assert [a[1] for a in d.added] == ['000901:mod.esp'] and [r[1] for r in d.removed] == ['000900:mod.esp']
    assert len(d.changed) == 1 and d.changed[0].members['model'][1] == 'x.nif'
    assert 'model' in d.summary()


def test_override_refuses_localized_strings_into_unlocalized_plugin(lo, data_dir):
    m = Plugin.open(data_dir / 'Master.esm')
    m.flags |= 0x80                               # pretend the master is localized
    data = m.to_bytes()
    (data_dir / 'Master.esm').write_bytes(data)
    with LoadOrder.open(data_dir, ['Master.esm'], 'starfield') as order:
        patch = Plugin.create('Patch2.esp', 'starfield')
        with patch.transaction() as tx:
            with pytest.raises(UnsupportedOperation, match='strings.localized'):
                tx.override(order.resolve(FormKey('Master.esm', 0x805)))   # MISC with FULL
            ok = tx.override(order.resolve(FormKey('Master.esm', 0x804)))  # GLOB: no strings
            assert ok.value == 3.0


def test_missing_required_member_blocks_commit(lo, data_dir):
    tx = lo.plugin('Mod.esp').transaction()
    tx.new_record('KYWD', 'Mod_Incomplete')
    with pytest.raises(ValidationError) as err:
        tx.commit(data_dir / 'Mod.esp', load_order=lo)
    assert {i.code for i in err.value.report.errors} == {'member.required'}


def test_preexisting_group_order_is_a_warning_new_disorder_an_error(data_dir):
    p = Plugin.open(data_dir / 'Mod.esp')
    p.groups.reverse()                       # STAT before KYWD: wrong, but "already so"
    (data_dir / 'Odd.esp').write_bytes(p.to_bytes())

    def odd():
        q = Plugin.open(data_dir / 'Odd.esp')
        q.set_master_kinds({'Master.esm': 'full'})
        return q

    q = odd()
    with q.transaction() as tx:
        tx.new_record('GMST', 'fOdd')                      # GMST sorts first: fits cleanly
        report = tx.commit(data_dir / 'Odd2.esp')
    assert report.ok and 'groups.order_preexisting' in [i.code for i in report.warnings]
    assert [g.label_signature for g in Plugin.open(data_dir / 'Odd2.esp').groups] == ['GMST', 'STAT', 'KYWD']

    q = odd()
    tx = q.transaction()
    tx.new_record('GLOB', 'Odd_G', value=1.0)              # between KYWD and STAT: no clean slot
    with pytest.raises(ValidationError) as err:
        tx.commit(data_dir / 'Odd3.esp')
    assert 'groups.order' in [i.code for i in err.value.report.errors]


def test_new_fields_use_observed_order_and_follow_anchors(lo):
    m = lo.plugin('Master.esm')
    refr = m.typed(m.find(0x803))
    refr.node.fields.insert(1, pyfield_sub('XWPK', b''))          # unmodelled field after NAME
    own = refr.schema.member('ownership').codec.make(owner=FormKey('Master.esm', 0x800))
    refr.ownership = own
    refr.faction_rank = 1
    sigs = [f.signature for f in refr.node.fields]
    assert sigs.index('XRNK') == sigs.index('XOWN') + 1          # rank follows owner
    assert sigs.index('XOWN') > sigs.index('XWPK')               # not jammed after NAME
    assert sigs[-1] == 'DATA'


def pyfield_sub(sig, data):
    from pyfield import Subrecord
    return Subrecord(sig, data)


def test_adding_full_master_after_own_records_is_refused(lo):
    from pyfield import UnsupportedOperation
    mod = lo.plugin('Mod.esp')                       # has own records with prefix 01
    with pytest.raises(UnsupportedOperation, match='masters.add_shifts_own_ids'):
        mod.add_master('Other.esm', 'full')
    assert mod.masters == ['Master.esm']
    mod.add_master('Tiny.esm', 'small')              # small masters do not shift the prefix
    assert mod.masters == ['Master.esm', 'Tiny.esm']
