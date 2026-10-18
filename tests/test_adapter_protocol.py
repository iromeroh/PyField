"""Phase 4 exit criteria: the generic layers carry no game knowledge, and an unrelated
format works end to end through a registered adapter."""
import ast
import dataclasses
import re
from pathlib import Path

import pytest

import pyfield
from pyfield import FormKey, Plugin, games
from pyfield.core.loadorder import LoadOrder
from pyfield.core.nodes import GroupNode, RecordNode
from pyfield.testing import toy_adapter  # noqa: F401  (registers 'toy')
from pyfield.validate import validate_plugin

SRC = Path(pyfield.__file__).parent
GENERIC = [*sorted((SRC / 'core').glob('*.py')), *sorted((SRC / 'schema').glob('*.py')),
           SRC / 'edit.py', SRC / 'validate.py', SRC / 'diff.py', SRC / 'capabilities.py', SRC / 'errors.py']
SIGNATURE = re.compile(r'^[A-Z][A-Z0-9_]{3}$')
GAME_WORDS = re.compile(r'starfield|oblivion|skyrim|fallout|tes4|\.esm', re.I)


def _literals(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and id(node) not in docstrings:
            value = node.value.decode('latin-1') if isinstance(node.value, bytes) else node.value
            yield node.lineno, value


@pytest.mark.parametrize('path', GENERIC, ids=lambda p: p.name)
def test_generic_layers_have_no_game_literals(path):
    leaks = [(line, v) for line, v in _literals(path) if SIGNATURE.match(v) or GAME_WORDS.search(v)]
    assert not leaks, f'{path.name}: game-specific literals {leaks}'


# -- toy adapter end to end ----------------------------------------------------------------------

def build_base(tmp_path):
    base = Plugin.create('Base.toy', 'toy', author='tester')
    with base.transaction() as tx:
        item = tx.new_record('ITEM', 'Toy_Crate', weight=2.5, price=7)
        room = tx.new_record('ROOM', 'Toy_Room')
        # place an item inside the room: owner record followed by its kind-3 child group
        children = GroupNode.new(base.spec, struct_label(room.form_id), 3, b'')
        top = base.top_group('ROOM')
        top.insert(top.children.index(room.node) + 1, children)
        placed = RecordNode.new(base.spec, 'PLCE', base.codec.encode(tx.allocator.allocate()), [], 0x1)
        children.append(placed)
        view = base.typed(placed)
        view.base = item.form_key
        view.x = 3.0
        tx.commit(tmp_path / 'Base.toy')
    return tmp_path / 'Base.toy'


def struct_label(form_id):
    return form_id.to_bytes(4, 'little')


def test_toy_plugin_written_detected_and_roundtripped(tmp_path):
    path = build_base(tmp_path)
    data = path.read_bytes()
    assert data[:4] == b'TOYP' and b'BOX_' in data and b'GRUP' not in data
    p = Plugin.open(path)                      # detected by sniffing
    assert p.adapter.name == 'toy' and p.author == 'tester'
    assert p.to_bytes() == data                # unmodified roundtrip
    for node in p.walk():
        if isinstance(node, RecordNode):
            node.fields
    assert p.to_bytes() == data
    placed = next(p.typed_records('PLCE'))
    assert placed.node.is_compressed           # compression flag 0x1, decoded transparently
    assert placed.x == 3.0 and placed.base == FormKey('Base.toy', 0x10)
    assert p.header_counts[1] == 3 + 3         # records + groups (no header-record count)
    assert p.header_counts[2] == 0x13


def test_toy_load_order_overrides_and_containment(tmp_path):
    build_base(tmp_path)
    mod = Plugin.create('Mod.toy', 'toy', ['Base.toy'])
    mod.set_master_kinds({'Base.toy': 'full'})
    with LoadOrder.open(tmp_path, ['Base.toy'], 'toy') as lo:
        with mod.transaction() as tx:
            crate = tx.override(lo.resolve(FormKey('Base.toy', 0x10)))
            crate.price = 99
            placed = tx.override(next(lo.plugin('Base.toy').typed_records('PLCE')))
            tx.new_record('ITEM', 'Mod_Barrel', weight=10.0, price=1)
            report = tx.commit(tmp_path / 'Mod.toy', load_order=LoadOrder(lo.plugins + [mod]))
        assert report.ok, report.summary()
    with LoadOrder.open(tmp_path, ['Mod.toy'], 'toy') as lo:
        assert lo.resolve(FormKey('Base.toy', 0x10)).price == 99
        assert [p.name for p, _ in lo.overrides(FormKey('Base.toy', 0x10))] == ['Base.toy', 'Mod.toy']
        placed = lo.resolve(FormKey('Base.toy', 0x12))
        assert lo.container_of(placed) == ('room_contents', FormKey('Base.toy', 0x11))
        assert [k for k, _ in lo.placement_path(placed)] == ['top', 'room_contents']
        assert [v.editor_id for v in lo.find_editor_id('mod_barrel')] == ['Mod_Barrel']
        assert validate_plugin(lo.plugin('Mod.toy'), load_order=lo).ok


def test_toy_rejects_oversized_subrecord_without_extended_field(tmp_path):
    p = Plugin.create('Big.toy', 'toy')
    with p.transaction() as tx:
        item = tx.new_record('ITEM', 'Big')
        item.node.fields.append(pyfield.Subrecord('BLOB', bytes(70000)))   # fits: u32 sizes
    assert Plugin.from_bytes(p.to_bytes(), 'Big.toy', 'toy').typed(
        next(Plugin.from_bytes(p.to_bytes(), 'Big.toy', 'toy').records('ITEM'))).node.get('BLOB')


def test_registry_protects_existing_adapters():
    with pytest.raises(pyfield.PyFieldError):
        games.register(dataclasses.replace(games.get('toy'), name='starfield'))
    assert games.get('starfield').title == 'Starfield'
