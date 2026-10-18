"""Semantic diff of two versions of a plugin, keyed by FormKey.

Changed records report header-flag changes, group placement changes, typed member
changes (old -> new values) and, for subrecords without a schema, which signatures'
bytes changed. Unchanged records cost one byte comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .core.formids import FormKey, Unresolved
from .errors import SchemaError
from .schema.records import _plain


@dataclass
class RecordChange:
    key: str
    signature: str
    editor_id: str | None
    header_flags: tuple[int, int] | None = None
    placement: tuple[list, list] | None = None
    members: dict = field(default_factory=dict)      # attr -> (before, after)
    raw: list = field(default_factory=list)          # unmodelled signatures whose bytes changed
    order: tuple | None = None                       # (before, after) signature sequences if reordered

    def lines(self):
        head = f'~ {self.signature} {self.key}' + (f' {self.editor_id!r}' if self.editor_id else '')
        out = [head]
        if self.header_flags:
            out.append(f'    header flags {self.header_flags[0]:08X} -> {self.header_flags[1]:08X}')
        if self.placement:
            out.append(f'    moved {self.placement[0]} -> {self.placement[1]}')
        for attr, (a, b) in self.members.items():
            out.append(f'    {attr}: {a!r} -> {b!r}')
        if self.raw:
            out.append(f'    unmodelled subrecords changed: {", ".join(self.raw)}')
        if self.order:
            out.append(f'    subrecord order: {" ".join(self.order[0])} -> {" ".join(self.order[1])}')
        return out


@dataclass
class Diff:
    added: list = field(default_factory=list)       # (signature, key, editor_id)
    removed: list = field(default_factory=list)
    changed: list[RecordChange] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def summary(self) -> str:
        out = [f'{len(self.added)} added, {len(self.removed)} removed, {len(self.changed)} changed']
        out += [f'+ {s} {k}' + (f' {e!r}' if e else '') for s, k, e in self.added]
        out += [f'- {s} {k}' + (f' {e!r}' if e else '') for s, k, e in self.removed]
        for c in self.changed:
            out += c.lines()
        return '\n'.join(out)

    def to_dict(self):
        return {'added': self.added, 'removed': self.removed,
                'changed': [{'key': c.key, 'signature': c.signature, 'editor_id': c.editor_id,
                             'header_flags': c.header_flags, 'placement': c.placement,
                             'members': {k: [_plain(a), _plain(b)] for k, (a, b) in c.members.items()},
                             'raw': c.raw, 'order': c.order} for c in self.changed]}


def _records(plugin):
    out = {}
    for node in plugin.records():
        key = plugin.codec.try_decode(node.form_id)
        out[str(key)] = node
    return out


def _path(plugin, node):
    path, g = [], node.parent
    while g is not None:
        path.append((g.kind, g.label_bytes.hex()))
        g = g.parent
    return path[::-1]


def diff_plugins(before, after) -> Diff:
    a, b = _records(before), _records(after)
    d = Diff()
    for key in b.keys() - a.keys():
        n = b[key]
        d.added.append((n.signature, key, n.editor_id))
    for key in a.keys() - b.keys():
        n = a[key]
        d.removed.append((n.signature, key, n.editor_id))
    for key in sorted(a.keys() & b.keys()):
        na, nb = a[key], b[key]
        if na.to_bytes() == nb.to_bytes() and _path(before, na) == _path(after, nb):
            continue
        change = RecordChange(key, nb.signature, nb.editor_id)
        if na.flags != nb.flags:
            change.header_flags = (na.flags, nb.flags)
        pa, pb = _path(before, na), _path(after, nb)
        if pa != pb:
            change.placement = (pa, pb)
        va, vb = before.typed(na), after.typed(nb)
        modelled = set()
        if vb.schema is not None:
            for m in vb.schema.members:
                modelled.add(m.sig)
                try:
                    x, y = va.get_value(m), vb.get_value(m)
                except SchemaError as exc:
                    change.members[m.attr] = ('<error>', str(exc))
                    continue
                if _comparable(x) != _comparable(y):
                    change.members[m.attr] = (x, y)
        fa = [f for f in na.fields if f.signature not in modelled]
        fb = [f for f in nb.fields if f.signature not in modelled]
        if fa != fb:
            sigs = sorted({f.signature for f in fa} ^ {f.signature for f in fb} |
                          {x.signature for x, y in zip(fa, fb) if x != y} |
                          ({f.signature for f in fa[len(fb):]} | {f.signature for f in fb[len(fa):]}))
            change.raw = sigs
        seq_a, seq_b = [f.signature for f in na.fields], [f.signature for f in nb.fields]
        if seq_a != seq_b and sorted(seq_a) == sorted(seq_b):
            change.order = (seq_a, seq_b)
        d.changed.append(change)
    d.added.sort()
    d.removed.sort()
    return d


def _comparable(v):
    # FormKeys from different files compare equal when they name the same record
    return _plain(v)
