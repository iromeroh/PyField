import math
import struct

import pytest

from pyfield import FormKey, Plugin, PyFieldError
from pyfield.core.loadorder import LoadOrder
from pyfield.scene import (Blueprint, ExistingCell, Link, NewInteriorCell, Scene, SceneLock, SceneNode,
                           SpatialIndex, Transform, compile_scene, diff_scenes, euler_to_matrix, matrix_to_euler)
from pyfield.testing import fixtures as fx

sub, z, record, group = fx.sub, fx.z, fx.record, fx.group
M = 'Master.esm'


# -- transforms ----------------------------------------------------------------------------------

def test_convention_matches_starfield_reference_group_example():
    # Starfield.esm reference group 00027970: root yaw 180 at content origin; child local (0, -1.05, 0)
    root = Transform((67.906, 24.901, -7.49), (0.0, 0.0, math.pi))
    assert root.apply((0, -1.05, 0)) == pytest.approx((67.906, 25.951, -7.49), abs=1e-3)
    # negated angles: +90 deg yaw maps local +X to world -Y (clockwise seen from above)
    assert Transform.at(yaw_deg=90).apply((1, 0, 0)) == pytest.approx((0, -1, 0), abs=1e-9)


def test_compose_inverse_and_euler_roundtrip():
    t = Transform((1, 2, 3), (0.3, 0.2, 1.1), 1.5)
    l = Transform((0.5, -2, 1), (0.1, 0.4, 2.0), 0.8)
    assert t.compose(l).relative_to(t).close_to(l)
    assert t.compose(t.inverse()).close_to(Transform())
    for angles in [(0, 0, 0), (1, 2, 3), (0.5, math.pi / 2, 0.2), (6.2, 0.01, 4)]:
        m = euler_to_matrix(angles)
        m2 = euler_to_matrix(matrix_to_euler(m))
        assert all(abs(m[i][j] - m2[i][j]) < 1e-9 for i in range(3) for j in range(3))


# -- fixtures -------------------------------------------------------------------------------------

@pytest.fixture
def data(tmp_path):
    stat = record('STAT', 0x800, sub('EDID', z('Box')) + sub('OBND', struct.pack('<6f', -1, -1, 0, 1, 1, 1)))
    npc = record('NPC_', 0x801, sub('EDID', z('Guy')) + sub('RNAM', struct.pack('<I', 0x900)))
    kw = record('KYWD', 0x802, sub('EDID', z('LinkKW')) + sub('CNAM', bytes(4)) + sub('TNAM', bytes(4)) +
                sub('FNAM', bytes(4)))
    interior = record('CELL', 0x803, sub('EDID', z('TplCell')) + sub('DATA', struct.pack('<I', 1)) +
                      sub('LTMP', struct.pack('<I', 0)))
    ext = record('CELL', 0x804, sub('EDID', z('Ext')) + sub('DATA', struct.pack('<I', 0)) +
                 sub('XCLC', struct.pack('<iiI', 2, -1, 0)))
    wrld = record('WRLD', 0x805, sub('EDID', z('World')) + sub('RNAM', bytes(16)) + sub('OFST', bytes(32)) +
                  sub('CLSZ', bytes(32)))
    cells = group(b'CELL', 0, group(3, 2, group(0, 3, interior)))
    pcell = record('CELL', 0x806, sub('DATA', struct.pack('<I', 0x2)))      # worldspace persistent cell
    worlds = group(b'WRLD', 0, wrld + group(0x805, 1, pcell + group(0, 4, group(0, 5, ext))))
    body = (group(b'KYWD', 0, kw) + group(b'STAT', 0, stat) + group(b'NPC_', 0, npc) + cells + worlds)
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 14, 0x807))
    (tmp_path / M).write_bytes(record('TES4', 0, tes4, 0x1) + body)
    return tmp_path


def run(data, scene, target, lock, path=None):
    path = path or data / 'Out.esm'
    with LoadOrder.open(data, [M], 'starfield') as lo:
        plugin = Plugin.open(path) if path.exists() else Plugin.create('Out.esm', 'starfield', [M], flags=1)
        plugin.set_master_kinds({M: 'full'})
        with plugin.transaction() as tx:
            result = compile_scene(scene, tx, lo, target, lock)
            report = tx.commit(path, load_order=LoadOrder(lo.plugins + [plugin]))
    assert report.ok, report.summary()
    return result, Plugin.open(path)


def small_scene():
    s = Scene('test')
    s.add(SceneNode('a', FormKey(M, 0x800), Transform.at(1, 2, 0, yaw_deg=30), links=[Link('b', FormKey(M, 0x802))]))
    grp = s.add(SceneNode('grp', None, Transform.at(5, 0, 0, yaw_deg=90)))
    grp.add(SceneNode('b', FormKey(M, 0x800), Transform.at(1, 0, 0), enable_parent='a'))
    s.add(SceneNode('npc', FormKey(M, 0x801), Transform.at(0, 0, 0)))
    return s


# -- compile ---------------------------------------------------------------------------------------

def test_new_interior_cell_compile_and_identity(data):
    lock = SceneLock(None, 'test')
    target = NewInteriorCell('PF_Cell', FormKey(M, 0x803), 'PF Cell')
    result, out = run(data, small_scene(), target, lock)
    assert sorted(result.created) == ['a', 'b', 'npc'] and result.cell == FormKey('Out.esm', 0x800)
    cell = out.typed(out.get(result.cell))
    assert cell.editor_id == 'PF_Cell' and cell.name == 'PF Cell' and cell.cell_flags & 1
    path = [g.kind for g in _parents(cell.node)]
    assert path == [0, 2, 3]                                       # CELL > block > sub-block
    b = out.typed(out.get(lock.get('b')))
    assert b.placement.position.x == pytest.approx(5) and b.placement.position.y == pytest.approx(-1)
    assert b.enable_parent.reference == lock.get('a')
    a = out.typed(out.get(lock.get('a')))
    assert a.linked_refs[0].reference == lock.get('b') and a.header_flags & 0x400  # linked -> persistent
    assert out.get(lock.get('npc')).signature == 'ACHR'
    first = (data / 'Out.esm').read_bytes()
    again, _ = run(data, small_scene(), target, lock)                    # unchanged rebuild
    assert again.created == [] and sorted(again.unchanged) == ['a', 'b', 'npc']
    assert (data / 'Out.esm').read_bytes() == first


def _parents(node):
    out, g = [], node.parent
    while g is not None:
        out.append(g)
        g = g.parent
    return out[::-1]


def test_removed_and_renamed_nodes(data):
    lock = SceneLock(None, 'test')
    target = NewInteriorCell('PF_Cell', FormKey(M, 0x803))
    run(data, small_scene(), target, lock)
    ids = dict(lock.nodes)
    s = small_scene()
    s.nodes = [n for n in s.nodes if n.id != 'npc']
    result, out = run(data, s, target, lock)
    assert result.removed == ['npc'] and out.get(FormKey.parse(ids['npc'])) is None
    assert lock.nodes['a'] == ids['a'] and lock.nodes['b'] == ids['b']


def test_existing_exterior_cell_and_grid_check(data):
    lock = SceneLock(None, 'ext')
    s = Scene('ext')
    s.add(SceneNode('box', FormKey(M, 0x800), Transform.at(250, -50, 3)))      # inside cell (2, -1)
    result, out = run(data, s, ExistingCell(FormKey(M, 0x804)), lock)
    refr = out.get(lock.get('box'))
    assert [g.kind for g in _parents(refr)] == [0, 1, 4, 5, 6, 9]              # world children ... temporary
    assert out.get(FormKey(M, 0x804)) is not None                              # cell container copied
    world = out.get(FormKey(M, 0x805))
    assert [f.signature for f in world.fields] == ['EDID']                     # RNAM/OFST/CLSZ stripped
    bad = Scene('ext')
    bad.add(SceneNode('far', FormKey(M, 0x800), Transform.at(10, 10, 0)))
    with pytest.raises(PyFieldError, match='outside exterior cell'):
        run(data, bad, ExistingCell(FormKey(M, 0x804)), SceneLock(None, 'ext'), data / 'Out2.esm')


def test_scene_problems_are_reported(data):
    s = Scene('bad')
    s.add(SceneNode('kw', FormKey(M, 0x802), Transform()))                     # keywords are not placeable
    s.add(SceneNode('x', FormKey(M, 0x800), Transform(), links=[Link('nowhere')]))
    with pytest.raises(PyFieldError) as err:
        run(data, s, NewInteriorCell('C', FormKey(M, 0x803)), SceneLock(None, 'bad'))
    assert 'not placeable' in str(err.value) and 'unknown node' in str(err.value)


# -- blueprints, diff, spatial ---------------------------------------------------------------------

def test_blueprint_json_and_instantiation(tmp_path):
    bp = Blueprint('pair', [SceneNode('one', FormKey(M, 0x800), Transform.at(1, 0, 0), links=[Link('two')]),
                            SceneNode('two', FormKey(M, 0x800), Transform.at(-1, 0, 0, yaw_deg=45))])
    bp.save(tmp_path / 'pair.json')
    loaded = Blueprint.load(tmp_path / 'pair.json')
    s = Scene('s')
    s.instantiate(loaded, 'p1', Transform.at(10, 0, 0, yaw_deg=90))
    nodes = {n.id: (n, t) for n, t in s.walk()}
    assert nodes['p1/one'][0].links[0].target == 'p1/two'
    assert nodes['p1/one'][1].position == pytest.approx((10, -1, 0), abs=1e-9)


def test_scene_diff_and_spatial(data):
    a, b = small_scene(), small_scene()
    b.nodes[0].transform = Transform.at(1, 3, 0, yaw_deg=30)
    b.nodes[2].base = FormKey(M, 0x800)
    d = diff_scenes(a, b)
    assert [m[0] for m in d.moved] == ['a'] and [r[0] for r in d.rebased] == ['npc']
    with LoadOrder.open(data, [M], 'starfield') as lo:
        idx = SpatialIndex(a, lo)
        assert idx.within((5, -1, 0), 0.5) == ['b']
        assert idx.nearest((0, 0, 0))[0][0] == 'npc'


def test_exterior_persistent_nodes_go_to_world_persistent_cell(data):
    lock = SceneLock(None, 'ext')
    s = Scene('ext')
    s.add(SceneNode('temp', FormKey(M, 0x800), Transform.at(250, -50, 3)))
    s.add(SceneNode('marker', FormKey(M, 0x800), Transform.at(260, -50, 3), persistent=True,
                    properties={'editor_id': 'PF_Marker'}))
    result, out = run(data, s, ExistingCell(FormKey(M, 0x804)), lock)
    temp, marker = out.get(lock.get('temp')), out.get(lock.get('marker'))
    assert [g.kind for g in _parents(temp)] == [0, 1, 4, 5, 6, 9]
    assert [g.kind for g in _parents(marker)] == [0, 1, 6, 8]
    assert _parents(marker)[-1].label_int == out.codec.encode(FormKey(M, 0x806))
    assert out.get(FormKey(M, 0x806)) is not None and marker.editor_id == 'PF_Marker'


def test_copy_from_localized_master_resolves_strings(tmp_path):
    from pyfield.assets.index import AssetIndex
    from pyfield.games.starfield.assets import RULES
    from pyfield.games.tes4family import StringTables
    cell = record('CELL', 0x800, sub('EDID', z('LocCell')) + sub('FULL', struct.pack('<I', 0x10)) +
                  sub('DATA', struct.pack('<I', 1)))
    body = group(b'CELL', 0, group(0, 2, group(0, 3, cell)))
    (tmp_path / M).write_bytes(record('TES4', 0, sub('HEDR', struct.pack('<fII', 0.96, 4, 0x801)), 0x81) + body)
    text = b'My Cell\0'
    (tmp_path / 'strings').mkdir()
    (tmp_path / 'strings' / 'master_en.strings').write_bytes(struct.pack('<IIII', 1, len(text), 0x10, 0) + text)
    with LoadOrder.open(tmp_path, [M], 'starfield') as lo:
        target = Plugin.create('Out.esm', 'starfield', [M])
        target.set_master_kinds({M: 'full'})
        with target.transaction() as tx:
            with pytest.raises(Exception, match='strings.localized'):
                tx.override(lo.resolve(FormKey(M, 0x800)))                # no tables -> refused
            tx.strings = StringTables(AssetIndex(tmp_path, RULES, [M]))
            copy = tx.override(lo.resolve(FormKey(M, 0x800)))
        assert copy.name == 'My Cell'
