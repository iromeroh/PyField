"""Scene compiler: a Scene -> placed reference records in a target plugin.

    lock = SceneLock.load_or_new('build/MyMod.esm.camp.lock.json', 'camp')
    with plugin.transaction() as tx:
        result = compile_scene(scene, tx, load_order, NewInteriorCell('PF_Camp', template=...), lock)
        tx.commit('build/MyMod.esm', load_order=...)
    lock.save()

Stable identity: the lock maps node ids to FormKeys. Recompiling an unchanged scene reuses
every FormID and leaves the plugin byte-identical; changed nodes update only their record;
nodes removed from the scene have their records removed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

from ..core.formids import FormKey, canonical_name
from ..core.nodes import GroupNode, RecordNode
from ..core.subrecords import Subrecord
from ..errors import PyFieldError, ResolutionError
from .graph import Scene
from .transform import Transform

PERSISTENT_FLAG = 0x400
DISABLED_FLAG = 0x800
CELL_KEY = '__cell__'


@dataclass
class ExistingCell:
    cell: FormKey                     # interior or exterior cell to place into (overridden if needed)


@dataclass
class NewInteriorCell:
    editor_id: str
    template: FormKey                 # vanilla interior cell whose lighting/data fields are copied
    name: str | None = None


@dataclass
class SceneLock:
    path: Path | None
    scene: str
    nodes: dict = field(default_factory=dict)    # node id -> FormKey text

    @classmethod
    def load_or_new(cls, path, scene: str) -> 'SceneLock':
        path = Path(path)
        if path.exists():
            d = json.loads(path.read_text(encoding='utf-8'))
            if d.get('scene') != scene:
                raise PyFieldError(f'{path} locks scene {d.get("scene")!r}, not {scene!r}')
            return cls(path, scene, dict(d.get('nodes', {})))
        return cls(path, scene)

    def get(self, node_id) -> FormKey | None:
        text = self.nodes.get(node_id)
        return FormKey.parse(text) if text else None

    def save(self, path=None):
        path = Path(path or self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'format': 'pyfield-scene-lock', 'scene': self.scene,
                                    'nodes': dict(sorted(self.nodes.items()))}, indent=1), encoding='utf-8')


@dataclass
class CompileResult:
    cell: FormKey | None = None
    refs: dict = field(default_factory=dict)        # node id -> typed view
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    masters_added: list = field(default_factory=list)

    def summary(self) -> str:
        return (f'cell {self.cell}: {len(self.created)} created, {len(self.updated)} updated, '
                f'{len(self.unchanged)} unchanged, {len(self.removed)} removed'
                + (f'; masters added {self.masters_added}' if self.masters_added else ''))


# -- helpers ------------------------------------------------------------------------------------

def _children_group(plugin, cell_node: RecordNode, kind: int) -> GroupNode:
    """The cell's persistent (8) or temporary (9) child group, created after the CELL if missing."""
    container = cell_node.parent
    siblings = container.children
    i = siblings.index(cell_node)
    nxt = siblings[i + 1] if i + 1 < len(siblings) else None
    tail = bytes(plugin.spec.group_header_size - 16)
    label = cell_node.form_id.to_bytes(4, 'little')
    if not (isinstance(nxt, GroupNode) and nxt.kind == 6 and nxt.label_bytes == label):
        nxt = GroupNode.new(plugin.spec, label, 6, tail)
        container.insert(i + 1, nxt)
    sub = next((g for g in nxt.groups() if g.kind == kind), None)
    if sub is None:
        sub = GroupNode.new(plugin.spec, label, kind, tail)
        if kind == 8:
            nxt.insert(0, sub)
        else:
            nxt.append(sub)
    return sub


def _new_interior_cell(tx, target: NewInteriorCell, load_order, key: FormKey | None) -> RecordNode:
    plugin = tx.plugin
    tpl = load_order.resolve(target.template)
    if tpl is None or tpl.signature != 'CELL':
        raise ResolutionError(f'template {target.template} is not a CELL')
    src = tpl.plugin
    for name in src.masters + [src.name]:      # raw FormIDs copied from the template must keep their meaning
        probe = FormKey(name, 1)
        try:
            same = plugin.codec.encode(probe) == src.codec.encode(probe)
        except ResolutionError:
            same = False
        if not same:
            raise ResolutionError(f'template plugin {src.name}: {name} is addressed differently in {plugin.name}')
    if not (tpl.cell_flags or 0) & 1:
        raise ResolutionError(f'template {target.template} is not an interior cell')
    key = key or tx.allocator.allocate()
    raw = plugin.codec.encode(key)
    edid = plugin.spec.editor_id_signature
    fields = [Subrecord(edid, target.editor_id.encode() + b'\0')]
    fields += [Subrecord(f.signature, f.data) for f in tpl.node.fields if f.signature not in (edid, 'FULL', 'XOWN', 'XRNK', 'XLCN')]
    node = RecordNode.new(plugin.spec, 'CELL', raw, fields, tpl.node.flags & ~0x4, tpl.node.header_tail)
    top = plugin.top_group('CELL', create=True)
    local = key.local_id
    tail = bytes(plugin.spec.group_header_size - 16)

    def child_group(parent, kind, label):
        g = next((c for c in parent.groups() if c.kind == kind and c.label_int == label), None)
        if g is None:
            g = GroupNode.new(plugin.spec, label.to_bytes(4, 'little', signed=True), kind, tail)
            parent.append(g)
        return g
    block = child_group(top, 2, local % 10)
    sub = child_group(block, 3, (local // 10) % 10)
    sub.append(node)
    view = plugin.typed(node)
    if target.name and not plugin.is_localized:
        view.name = target.name
    return node


def _resolve_cell(tx, target, load_order, lock: SceneLock, result: CompileResult) -> RecordNode:
    plugin = tx.plugin
    if isinstance(target, NewInteriorCell):
        key = lock.get(CELL_KEY)
        node = plugin.get(key) if key else None
        if node is None:
            node = _new_interior_cell(tx, target, load_order, key)
            lock.nodes[CELL_KEY] = str(plugin.codec.decode(node.form_id))
        result.cell = plugin.codec.decode(node.form_id)
        return node
    key = target.cell
    node = plugin.get(key)
    if node is None:
        view = load_order.resolve(key)
        if view is None or view.signature != 'CELL':
            raise ResolutionError(f'{key} is not a CELL in the load order')
        node = tx.override(view).node
    result.cell = key
    return node


def _world_persistent_cell(tx, load_order, cell_node: RecordNode) -> RecordNode:
    """The persistent cell of the worldspace containing an exterior cell, overridden if needed.

    Vanilla keeps every persistent exterior reference there (New Atlantis: 1,613 of 1,613): the
    CELL record that sits directly in the world-children group, outside the block groups.
    """
    plugin = tx.plugin
    layout = plugin.adapter.groups
    group = cell_node.parent
    while group is not None and group.kind != layout.world_kind:
        group = group.parent
    if group is None:
        raise ResolutionError('exterior cell is not inside a worldspace children group')
    world_key = plugin.codec.decode(group.label_int)
    for source in [plugin] + list(reversed(load_order.plugins)):       # the target first: it may own the world
        world_node = source.get(world_key)
        if world_node is None:
            continue
        siblings = world_node.parent.children
        i = siblings.index(world_node)
        children = siblings[i + 1] if i + 1 < len(siblings) else None
        if not isinstance(children, GroupNode) or children.kind != 1:
            continue
        cell = next(children.records(), None)
        if cell is not None and cell.signature == 'CELL':
            key = source.codec.decode(cell.form_id)
            existing = plugin.get(key)
            return existing if existing is not None else tx.override(source.typed(cell)).node
    raise ResolutionError(f'no persistent cell found for worldspace {world_key}')


def _exterior_grid(plugin, cell_node: RecordNode):
    grid = cell_node.get('XCLC')
    if grid is None or len(grid.data) < 8:
        return None
    import struct
    return struct.unpack_from('<ii', grid.data)


def _raise_problems(problems, limit=25):
    if problems:
        more = f'\n  ... and {len(problems) - limit} more' if len(problems) > limit else ''
        raise PyFieldError(f'{len(problems)} scene problem(s):\n  ' + '\n  '.join(problems[:limit]) + more)


# -- compile ------------------------------------------------------------------------------------

def compile_scene(scene: Scene, tx, load_order, target, lock: SceneLock) -> CompileResult:
    plugin = tx.plugin
    adapter = plugin.adapter
    problems = scene.check()
    placeable = adapter.placeable_types
    placed = scene.placed()
    bases = {}
    for node, _ in placed:
        view = load_order.resolve(node.base)
        if view is None:
            problems.append(f'{node.id}: base {node.base} not found')
        elif view.signature not in placeable:
            problems.append(f'{node.id}: {view.signature} {node.base} is not placeable')
        else:
            bases[node.id] = view
    _raise_problems(problems)
    result = CompileResult()
    # masters first: adding masters after own records exist is refused (it would shift own IDs)
    needed = [view.plugin.name for view in bases.values()]
    if isinstance(target, ExistingCell):
        cell_view = load_order.resolve(target.cell)
        if cell_view is not None:
            needed.append(cell_view.plugin.name)
    elif isinstance(target, NewInteriorCell):
        tpl = load_order.resolve(target.template)
        if tpl is not None:
            needed.append(tpl.plugin.name)
    for name in dict.fromkeys(needed):
        if canonical_name(name) != canonical_name(plugin.name) and \
                canonical_name(name) not in map(canonical_name, plugin.masters):
            src = load_order.plugin(name)
            for m in src.masters:
                if canonical_name(m) not in map(canonical_name, plugin.masters):
                    tx.ensure_master(m, load_order.plugin(m).kind)
                    result.masters_added.append(m)
            tx.ensure_master(name, src.kind)
            result.masters_added.append(name)
    cell_node = _resolve_cell(tx, target, load_order, lock, result)
    grid = _exterior_grid(plugin, cell_node)
    size = adapter.exterior_cell_size
    if grid is not None and size:
        for node, world in placed:
            x, y = world.position[:2]
            if (math.floor(x / size), math.floor(y / size)) != grid:
                problems.append(f'{node.id} at ({x:.1f}, {y:.1f}) lies outside exterior cell {grid}')
    _raise_problems(problems)

    # identities: reuse locked FormIDs, allocate the rest
    keys = {}
    for node, _ in placed:
        key = lock.get(node.id)
        existing = plugin.get(key) if key else None
        if key is None or (existing is not None and existing.signature not in ('REFR', 'ACHR')):
            key = tx.allocator.allocate()
        keys[node.id] = key
    for node_id in list(lock.nodes):
        if node_id != CELL_KEY and node_id not in keys:
            old = plugin.get(lock.get(node_id))
            if old is not None and old.parent is not None:
                old.parent.remove(old)
                result.removed.append(node_id)
            del lock.nodes[node_id]

    def resolve_target(text):
        if text in keys:
            return keys[text]
        return FormKey.parse(text)

    persistent_cell = None

    for node, world in placed:
        key = keys[node.id]
        base = bases[node.id]
        sig = adapter.placeable_types[base.signature]
        raw = plugin.codec.encode(key)
        flags = (PERSISTENT_FLAG if node.persistent or node.links or any(
            n.enable_parent == node.id or any(l.target == node.id for l in n.links) for n, _ in placed) else 0) \
            | (DISABLED_FLAG if node.disabled else 0)
        if flags & PERSISTENT_FLAG:
            # exterior persistent references live in the worldspace's persistent cell (as in vanilla)
            if grid is not None and persistent_cell is None:
                persistent_cell = _world_persistent_cell(tx, load_order, cell_node)
            group = _children_group(plugin, persistent_cell if grid is not None else cell_node, 8)
        else:
            group = _children_group(plugin, cell_node, 9)
        rec = plugin.get(key)
        if rec is not None and rec.signature != sig:
            rec.parent.remove(rec)
            rec = None
        status = 'unchanged'
        if rec is None:
            rec = RecordNode.new(plugin.spec, sig, raw, [], flags, adapter.header_tail())
            group.append(rec)
            status = 'created'
        else:
            keep = rec.flags & ~(PERSISTENT_FLAG | DISABLED_FLAG)
            if rec.flags != keep | flags:
                rec.flags = keep | flags
            if rec.parent is not group:
                rec.parent.remove(rec)
                group.append(rec)
        view = plugin.typed(rec)
        before = None if status == 'created' else rec.to_bytes()
        view.base = base.form_key
        for attr, value in node.properties.items():
            setattr(view, attr, FormKey.parse(value) if isinstance(value, str) and ':' in value else value)
        view.linked_refs = [view.schema.member('linked_refs').codec.make(
            keyword=l.keyword, reference=resolve_target(l.target)) for l in node.links]
        if node.enable_parent:
            ep = view.schema.member('enable_parent').codec.make(reference=resolve_target(node.enable_parent))
            current = view.enable_parent
            if current is None or current.reference != ep.reference:
                view.enable_parent = ep
        elif view.enable_parent is not None:
            view.enable_parent = None
        view.scale = None if abs(world.scale - 1.0) < 1e-9 else world.scale
        view.placement = view.schema.member('placement').codec.make(
            position=dict(zip('xyz', world.position)), rotation=dict(zip('xyz', world.rotation)))
        if status != 'created' and rec.to_bytes() != before:
            status = 'updated'
        getattr(result, status).append(node.id)
        result.refs[node.id] = view
        lock.nodes[node.id] = str(key)
    return result
