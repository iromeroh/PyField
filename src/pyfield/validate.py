"""Validation reports for a plugin (optionally against a load order).

Checks are deterministic and each finding carries a stable code, so reports can be
diffed and gated in CI. Errors block `Transaction.commit`; warnings do not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .core.formids import FormKey, Unresolved, canonical_name
from .core.nodes import GroupNode, RecordNode
from .core.plugin import COUNT_RECORDS_PLUS_HEADER
from .errors import PyFieldError, SchemaError

ERROR, WARNING, INFO = 'error', 'warning', 'info'


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    record: str = ''

    def __str__(self):
        return f'[{self.severity}] {self.code}: {self.message}' + (f' ({self.record})' if self.record else '')


@dataclass
class Report:
    plugin: str
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, severity, code, message, record=''):
        self.issues.append(Issue(severity, code, message, record))

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        head = f'{self.plugin}: {len(self.errors)} error(s), {len(self.warnings)} warning(s)'
        return '\n'.join([head] + [f'  {i}' for i in self.issues if i.severity != INFO][:50])

    def to_dict(self):
        return {'plugin': self.plugin, 'ok': self.ok, 'stats': self.stats,
                'issues': [i.__dict__ for i in self.issues]}


def validate_plugin(plugin, load_order=None, typed: bool = True, baseline_order=None) -> Report:
    """Validate a plugin.

    baseline_order: top-level group order of the file before editing. Ordering problems
    already present there are reported as warnings ('groups.order_preexisting'); only
    problems the edit introduced are errors ('groups.order').
    """
    report = Report(plugin.name)
    adapter = plugin.adapter
    idx = plugin.index
    codec = plugin.codec
    report.stats.update(records=len(idx), groups=len(idx.groups))

    # header ---------------------------------------------------------------------------------
    version, count, next_id = plugin.hedr
    expected = (len(idx) + 1) if plugin.count_convention == COUNT_RECORDS_PLUS_HEADER else len(idx) + len(idx.groups)
    if count != expected:
        report.add(WARNING, 'header.count', f'HEDR count {count} != {expected} ({plugin.count_convention})')
    if not codec.certain:
        report.add(ERROR, 'masters.unknown_kind', '; '.join(codec.assumptions))

    # ids --------------------------------------------------------------------------------------
    dupes = idx.duplicates()
    for fid, positions in list(dupes.items())[:20]:
        report.add(ERROR, 'formid.duplicate', f'{fid:08X} appears {len(positions)} times')
    own_max = 0
    limit = {'small': 0xFFF, 'medium': 0xFFFF}.get(plugin.kind, 0xFFFFFF)
    for fid in idx.form_ids:
        key = codec.try_decode(fid)
        if isinstance(key, Unresolved):
            report.add(ERROR, 'formid.unresolved', f'record header FormID {fid:08X} maps to no master')
            continue
        if key.plugin == codec._self:
            own_max = max(own_max, key.local_id)
            if key.local_id > limit:
                report.add(ERROR, 'formid.range', f'{key} exceeds the {plugin.kind} plugin limit {limit:#x}')
    if own_max and own_max >= next_id & 0xFFFFFF:
        report.add(WARNING, 'header.next_id', f'HEDR next object ID {next_id:08X} <= highest own ID {own_max:06X}')

    # overrides carrying fields that only make sense in the defining file -------------------------
    for sig, fields in adapter.override_strip.items():
        for e in idx.of_signature(sig):
            if codec.is_own(e.form_id):
                continue
            present = sorted({f.signature for f in plugin.node_at(e.offset).fields} & fields)
            if present:
                report.add(ERROR, 'override.foreign_offsets',
                           f'{sig} override carries {present}, which index the defining plugin', f'{e.form_id:08X}')

    # structure --------------------------------------------------------------------------------
    layout = adapter.groups
    order = [g.label_signature for g in plugin.groups if g.kind == layout.top_kind]
    base_pos = {sig: i for i, sig in enumerate(baseline_order or ())}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if adapter.group_rank(a) <= adapter.group_rank(b):
                continue
            if a in base_pos and b in base_pos and base_pos[a] < base_pos[b]:
                report.add(WARNING, 'groups.order_preexisting', f'{a} before {b} (already so in the source file)')
            else:
                report.add(ERROR, 'groups.order', f'{a} placed before {b}, against native order')
    if len(set(order)) != len(order):
        report.add(ERROR, 'groups.duplicate', f'duplicate top-level groups: {order}')
    for g in plugin.groups:
        if g.kind != layout.top_kind:
            report.add(ERROR, 'groups.top_kind', f'top-level group of kind {g.kind}')
            continue
        if g.label_signature not in adapter.native_group_order and adapter.native_group_order:
            report.add(WARNING, 'groups.unknown', f'unknown top-level group {g.label_signature}')
        if g.nbytes() == plugin.spec.group_header_size:
            report.add(WARNING, 'groups.empty', f'empty top-level group {g.label_signature}')
        g.end_save()   # nbytes() caches sizes for a save pass
    for i, sig_int in enumerate(idx.sigs):
        parent = idx.parents[i]
        if parent == -1:
            continue
        top = parent
        while idx.groups[top].parent != -1:
            top = idx.groups[top].parent
        label = idx.groups[top].label.decode('latin-1')
        sig = sig_int.to_bytes(4, 'little').decode('latin-1')
        if label not in layout.nested_top_groups and sig != label:
            report.add(ERROR, 'groups.misplaced', f'{sig} {idx.form_ids[i]:08X} inside top-level {label} group')
    for i in range(len(idx)):
        try:
            plugin.node_at(idx.offsets[i]).fields
        except PyFieldError as exc:
            report.add(ERROR, 'record.decode', str(exc), f'{idx.form_ids[i]:08X}')

    # typed members and references --------------------------------------------------------------
    schemas = adapter.schemas if typed else None
    if schemas is not None:
        links = unresolved = missing = wrong_type = 0
        for sig in schemas.classes:
            for e in idx.of_signature(sig):
                view = plugin.typed(plugin.node_at(e.offset))
                rec = f'{sig} {view.form_key}'
                for m in view.schema.members:
                    if m.required and not view._positions(m.sig):
                        report.add(ERROR, 'member.required', f'{m.attr} ({m.sig}) missing', rec)
                try:
                    found = list(view.links())
                except SchemaError as exc:
                    report.add(ERROR, 'member.decode', str(exc), rec)
                    continue
                for path, target in found:
                    links += 1
                    if isinstance(target, Unresolved):
                        unresolved += 1
                        report.add(ERROR, 'link.unresolved', f'{path} -> {target}', rec)
                        continue
                    if load_order is None:
                        continue
                    hit = _lookup(load_order, plugin, target)
                    if hit is None:
                        missing += 1
                        report.add(ERROR, 'link.missing', f'{path} -> {target} not found in load order', rec)
                        continue
                    allowed = _allowed_targets(view, path)
                    if allowed and hit.signature not in allowed:
                        wrong_type += 1
                        report.add(WARNING, 'link.type', f'{path} -> {target} is {hit.signature}, '
                                                         f'expected {"|".join(allowed)}', rec)
        report.stats.update(links=links, unresolved_links=unresolved, missing_links=missing,
                            wrong_type_links=wrong_type)

    # masters ------------------------------------------------------------------------------------
    if load_order is not None:
        names = [canonical_name(p.name) for p in load_order.plugins]
        for m in plugin.masters:
            if canonical_name(m) not in names:
                report.add(ERROR, 'masters.missing', f'master {m} is not in the load order')
    return report


def _lookup(load_order, plugin, key: FormKey):
    if key.plugin == canonical_name(plugin.name):
        node = plugin.get(key)
        return node if node is not None else load_order.winner(key) and load_order.winner(key)[1]
    hit = load_order.winner(key)
    return hit[1] if hit else None


def _allowed_targets(view, path: str):
    attr = path.split('[')[0].split('.')[0]
    member = view.schema.member(attr)
    codec = member.codec
    for part in path.replace('[', '.[').split('.')[1:]:
        if part.startswith('['):
            codec = getattr(codec, 'element', codec)
            continue
        if hasattr(codec, 'fields'):
            codec = dict(codec.fields)[part]
    return getattr(codec, 'targets', ())
