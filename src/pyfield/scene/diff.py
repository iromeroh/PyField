"""Scene diff by stable node id: added, removed, moved, rebased and otherwise changed nodes."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SceneDiff:
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    moved: list = field(default_factory=list)       # (id, before Transform, after Transform) in cell space
    rebased: list = field(default_factory=list)     # (id, before base, after base)
    changed: list = field(default_factory=list)     # (id, {attribute: (before, after)})

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.moved or self.rebased or self.changed)

    def summary(self) -> str:
        out = [f'{len(self.added)} added, {len(self.removed)} removed, {len(self.moved)} moved, '
               f'{len(self.rebased)} rebased, {len(self.changed)} changed']
        out += [f'+ {i}' for i in self.added] + [f'- {i}' for i in self.removed]
        for i, a, b in self.moved:
            out.append(f'~ {i}: {[round(v, 3) for v in a.position]} -> {[round(v, 3) for v in b.position]}')
        out += [f'~ {i}: base {a} -> {b}' for i, a, b in self.rebased]
        out += [f'~ {i}: {c}' for i, c in self.changed]
        return '\n'.join(out)


def _props(node):
    return {'persistent': node.persistent, 'disabled': node.disabled, 'enable_parent': node.enable_parent,
            'links': [(l.target, str(l.keyword)) for l in node.links], 'properties': node.properties}


def diff_scenes(before, after) -> SceneDiff:
    a = {n.id: (n, t) for n, t in before.walk()}
    b = {n.id: (n, t) for n, t in after.walk()}
    d = SceneDiff(added=sorted(b.keys() - a.keys()), removed=sorted(a.keys() - b.keys()))
    for i in sorted(a.keys() & b.keys()):
        (na, ta), (nb, tb) = a[i], b[i]
        if not ta.close_to(tb):
            d.moved.append((i, ta, tb))
        if na.base != nb.base:
            d.rebased.append((i, na.base, nb.base))
        pa, pb = _props(na), _props(nb)
        changes = {k: (pa[k], pb[k]) for k in pa if pa[k] != pb[k]}
        if changes:
            d.changed.append((i, changes))
    return d
