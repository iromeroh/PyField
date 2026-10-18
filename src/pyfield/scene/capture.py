"""Capture placed references from existing cells into blueprints (crystallization groundwork).

    bp = capture_cell(lo, FormKey('Starfield.esm', 0x0E6E45), anchor=Transform.at(0, 0, 0))
    bp.save('aactest.blueprint.json')

Every REFR/ACHR physically in the cell (any plugin of the load order; the winning version of
each) becomes a node with its base, transform relative to the anchor, persistence/disabled
flags, and links / enable parents among captured nodes. References pointing outside the
captured set are kept as FormKey text, so recompiling them keeps pointing at the originals.
"""
from __future__ import annotations

import struct

from ..core.formids import FormKey, Unresolved
from .graph import Blueprint, Link, SceneNode
from .transform import Transform


def cell_references(load_order, cell: FormKey) -> list:
    """Typed winning views of every placed reference inside `cell` across the load order."""
    out, seen = [], set()
    for plugin in reversed(load_order.plugins):
        node = plugin.get(cell)
        if node is None:
            continue
        siblings = node.parent.children
        i = siblings.index(node)
        nxt = siblings[i + 1] if i + 1 < len(siblings) else None
        if nxt is None or getattr(nxt, 'kind', None) != 6 or nxt.label_int != node.form_id:
            continue
        for g in nxt.groups():
            for rec in g.records():
                if rec.signature not in ('REFR', 'ACHR'):
                    continue
                key = plugin.codec.try_decode(rec.form_id)
                if key in seen:
                    continue
                seen.add(key)
                out.append(plugin.typed(rec))
    return out


def capture_cell(load_order, cell: FormKey, anchor: Transform | None = None, include=None,
                 name: str | None = None) -> Blueprint:
    """Blueprint of a cell's references, transforms relative to `anchor` (default: cell origin).

    include: optional predicate on the typed reference view (e.g. a radius filter).
    """
    adapter = load_order.plugins[0].adapter
    convention = adapter.rotation_convention
    anchor = anchor or Transform(convention=convention)
    refs = [r for r in cell_references(load_order, cell) if include is None or include(r)]
    ids = {}
    for r in refs:
        ids[r.form_key] = (r.editor_id or f'ref_{r.form_key.local_id:06X}_{r.form_key.plugin}').replace(':', '_')
    nodes = []
    for r in refs:
        p = r.placement
        world = Transform((p.position.x, p.position.y, p.position.z), (p.rotation.x, p.rotation.y, p.rotation.z),
                          r.scale or 1.0, convention)
        local = world.relative_to(anchor)
        links = []
        for lr in r.linked_refs:
            target = ids.get(lr.reference, str(lr.reference) if isinstance(lr.reference, FormKey) else None)
            if target is not None:
                links.append(Link(target, lr.keyword if isinstance(lr.keyword, FormKey) else None))
        ep = r.enable_parent
        enable_parent = None
        if ep is not None and isinstance(ep.reference, FormKey):
            enable_parent = ids.get(ep.reference, str(ep.reference))
        nodes.append(SceneNode(ids[r.form_key], r.base if isinstance(r.base, FormKey) else None, local,
                               persistent=bool(r.header_flags & 0x400), disabled=bool(r.header_flags & 0x800),
                               links=links, enable_parent=enable_parent, tags=(str(r.form_key),)))
    return Blueprint(name or f'cell_{cell.local_id:06X}', nodes,
                     description=f'{len(nodes)} references captured from cell {cell}',
                     source=f'capture_cell({cell}) over {", ".join(p.name for p in load_order.plugins)}')
