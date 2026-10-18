"""Transactional editing: allocation, record creation, overrides, removal, validated commits.

    with plugin.transaction() as tx:
        kw = tx.new_record('KYWD', 'PF_MyKeyword')
        stat = tx.override(load_order.resolve('000034:Starfield.esm'))
        stat.model = 'Meshes\\\\pf\\\\marker.nif'
    tx.commit('Data/MyMod.esm', load_order=lo)    # validated; source untouched on failure

Leaving the `with` block by an exception rolls the plugin back to its state at `begin`.
"""
from __future__ import annotations

import os
import shutil
import struct
import time
from pathlib import Path

from .core.formids import FULL, MEDIUM, SMALL, FormKey, Unresolved, canonical_name
from .core.nodes import GroupNode, RecordNode
from .core.subrecords import Subrecord
from .errors import ResolutionError, TransactionError, UnsupportedOperation, ValidationError

LOCAL_LIMIT = {FULL: 0xFFFFFF, MEDIUM: 0xFFFF, SMALL: 0xFFF}


class FormIdAllocator:
    """Collision-free local IDs: above HEDR's next ID *and* above every own record (the CK
    can leave HEDR stale), never reusing an ID reserved in this session."""

    def __init__(self, plugin):
        self.plugin = plugin
        hedr_next = plugin.hedr[2] & 0xFFFFFF
        own = plugin.own_local_ids()
        self.next = max(hedr_next, max(own) + 1 if own else 0, plugin.adapter.first_object_id)
        self.reserved: set[int] = set()
        self.limit = LOCAL_LIMIT[plugin.kind]    # small/medium plugins must stay addressable

    def allocate(self) -> FormKey:
        local = self.next
        if local > self.limit:
            raise ResolutionError(f'{self.plugin.name}: no free object IDs below {self.limit:#x}')
        self.next += 1
        self.reserved.add(local)
        return FormKey(self.plugin.name, local)


def _snapshot(plugin):
    """Copy of the mutable tree; unexpanded groups share their (immutable) source bytes."""
    def clone(node, parent):
        if isinstance(node, RecordNode):
            c = RecordNode(node.spec, bytes(node.header), node._stored, parent, node.offset)
            c._orig_header = node._orig_header
            if node._fields is not None:
                c._fields = [Subrecord(f.signature, f.data) for f in node._fields]
            return c
        g = GroupNode(node.spec, bytes(node.header), node._raw, parent, node.offset)
        if node._children is not None:
            g._children = [clone(ch, g) for ch in node._children]
        return g
    plugin.header.fields   # decode so the clone carries the header fields
    return clone(plugin.header, None), [clone(g, None) for g in plugin.groups], dict(plugin._master_kinds)


class Transaction:
    def __init__(self, plugin):
        self.plugin = plugin
        self._state = 'open'
        self._snapshot = _snapshot(plugin)
        self.strings = None          # StringTables-like (lookup(plugin, id) -> bytes) for de-localizing copies
        self.allocator = FormIdAllocator(plugin)
        self.log: list[str] = []

    # -- lifecycle ----------------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and self._state == 'open':
            self.rollback()
        return False

    def _check(self):
        if self._state != 'open':
            raise TransactionError(f'transaction is {self._state}')

    def rollback(self):
        self._check()
        header, groups, kinds = self._snapshot
        self.plugin.header = header
        self.plugin.groups = groups
        self.plugin._master_kinds = kinds
        self.plugin._codec = None
        self._state = 'rolled back'

    # -- masters ------------------------------------------------------------------------------
    def ensure_master(self, name: str, kind: str):
        if canonical_name(name) == canonical_name(self.plugin.name):
            return
        if canonical_name(name) not in map(canonical_name, self.plugin.masters):
            self.plugin.add_master(name, kind)
            self.log.append(f'added master {name}')

    # -- creation -----------------------------------------------------------------------------
    def new_record(self, signature: str, editor_id: str | None = None, flags: int = 0, **values):
        """Create a record with a freshly allocated FormID in its top-level group."""
        self._check()
        key = self.allocator.allocate()
        plugin = self.plugin
        node = RecordNode.new(plugin.spec, signature, plugin.codec.encode(key), [], flags,
                              plugin.adapter.header_tail())
        if editor_id is not None:
            sig = plugin.spec.editor_id_signature
            if sig is None:
                raise UnsupportedOperation('editor_id', f'{plugin.adapter.name} records have no editor IDs')
            node.fields.append(Subrecord(sig, editor_id.encode('utf-8') + b'\0'))
        plugin.top_group(signature, create=True).append(node)
        view = plugin.typed(node)
        for attr, value in values.items():
            setattr(view, attr, value)
        self.log.append(f'new {signature} {key} {editor_id or ""}'.rstrip())
        return view

    def override(self, source_view, load_order=None, accept_unverified=()):
        """Copy a record (and, for CELL/WRLD/DIAL/QUST children, its owner chain) into this plugin.

        Raw bytes are copied when every FormID in the record means the same thing in both files.
        Otherwise top-level records are remapped (remap.py): FormIDs at known positions are re-encoded
        through FormKeys; values at unknown positions that would change meaning raise
        UnsupportedOperation('override.remap') unless their subrecord is in accept_unverified.
        """
        self._check()
        src_plugin, src_node = source_view.plugin, source_view.node
        if src_plugin is self.plugin:
            return source_view
        key = source_view.form_key
        if isinstance(key, Unresolved):
            raise ResolutionError(f'cannot override unresolved {key}')
        existing = self.plugin.get(key)
        if existing is not None:
            return self.plugin.typed(existing)
        if self._layout_compatible(src_plugin):
            self._require_compatible(src_plugin)
            self._require_same_strings(src_plugin, src_node)
            parent = self._ensure_path(src_plugin, src_node)
            copy = self._copy(src_plugin, src_node)
        else:
            copy, parent = self._remapped_copy(src_plugin, src_node, key, load_order, accept_unverified)
        parent.append(copy)
        self.log.append(f'override {source_view.signature} {key}')
        return self.plugin.typed(copy)

    def _layout_compatible(self, src) -> bool:
        """True when src's raw FormIDs mean the same in this plugin (masters at the same per-kind
        indexes, src itself next in its namespace) or can be made to by appending masters."""
        theirs, mine = src.codec, self.plugin.codec
        for kind, names in theirs._by_kind.items():
            ours = mine._by_kind.get(kind, [])
            for i, name in enumerate(names):
                if i < len(ours) and canonical_name(ours[i]) != canonical_name(name):
                    return False
                if i >= len(ours) and canonical_name(name) in mine._lookup:
                    return False
            if len(ours) > len(names):
                own_kind = FULL if theirs.own_style == 'ordinal' else theirs.self_kind
                if kind == own_kind and canonical_name(ours[len(names)]) != canonical_name(src.name):
                    return False
        return True

    def _remapped_copy(self, src_plugin, src_node, key, load_order, accept_unverified):
        """Copy of a top-level record with every FormID re-encoded for this plugin (remap.py)."""
        from .remap import plan_remap
        if src_node.parent is None or src_node.parent.kind != self.plugin.adapter.groups.top_kind:
            raise UnsupportedOperation('override.remap', f'{src_node.signature} {key} sits in a container '
                                       f'(cell/world/topic/quest children are not remapped yet)')
        self._require_same_strings(src_plugin, src_node)
        plan = plan_remap(src_plugin, src_node, self.plugin, load_order=load_order, accept=accept_unverified)
        fields = plan.apply(self.ensure_master)
        if key.plugin != canonical_name(self.plugin.name):
            self.ensure_master(_display_name(src_plugin, key.plugin), _master_kind(src_plugin, key.plugin))
        temp = _copy_node(src_node)
        temp._orig_header = None
        temp.fields = fields
        copy = self._copy(src_plugin, temp)
        copy._orig_header = None
        copy.form_id = self.plugin.codec.encode(key)
        self.log.append(f'override {src_node.signature} {key}: remapped {len(plan.values)} FormID(s) '
                        f'from {src_plugin.name}')
        return copy, self.plugin.top_group(src_node.signature, create=True)

    def _require_compatible(self, src):
        """Source master namespaces must be a prefix-compatible view of ours."""
        theirs = src.codec
        for name in src.masters:      # same relative order as in the source
            self.ensure_master(name, theirs._lookup[canonical_name(name)][0])
        # the source's own records are addressed through its own index in its namespace
        own_kind = FULL if theirs.own_style == 'ordinal' else theirs.self_kind
        self.ensure_master(src.name, src.kind)
        mine = self.plugin.codec
        for kind, names in theirs._by_kind.items():
            for i, name in enumerate(names):
                if mine._lookup.get(canonical_name(name)) != (kind, i):
                    raise UnsupportedOperation(
                        'override.remap', f'{name} is {kind} master #{i} in {src.name} but not in '
                        f'{self.plugin.name}; raw FormIDs would change meaning (schema-wide remap not implemented)')
        expect = (own_kind, len(theirs._by_kind[own_kind]))
        if mine._lookup.get(canonical_name(src.name)) != expect:
            raise UnsupportedOperation(
                'override.remap', f'{src.name} must be {expect[0]} master #{expect[1]} of {self.plugin.name} '
                f'for its records to keep their raw FormIDs')

    def _require_same_strings(self, src_plugin, node):
        """Localized string ids cannot be copied raw into a non-localized plugin (or back)."""
        if src_plugin.is_localized == self.plugin.is_localized:
            return
        lstrings = self.plugin.adapter.lstring_signatures(node.signature)
        present = sorted({f.signature for f in node.fields} & lstrings)
        if present and src_plugin.is_localized and self.strings is not None:
            if self._delocalized_fields(src_plugin, node) is not None:
                return
        if present:
            raise UnsupportedOperation(
                'strings.localized', f'{node.signature} {node.form_id:08X} has localized fields {present}; '
                f'{src_plugin.name} localized={src_plugin.is_localized}, '
                f'{self.plugin.name} localized={self.plugin.is_localized}')

    def _delocalized_fields(self, src_plugin, node):
        """node.fields with every 4-byte localized field replaced by its text, or None if any id is unknown."""
        lstrings = self.plugin.adapter.lstring_signatures(node.signature)
        out = []
        for f in node.fields:
            if f.signature in lstrings and len(f.data) == 4:
                sid = int.from_bytes(f.data, 'little')
                text = self.strings.lookup(src_plugin.name, sid) if sid else b''
                if text is None:
                    return None
                out.append(Subrecord(f.signature, text + b'\0'))
            else:
                out.append(Subrecord(f.signature, f.data))
        return out

    def _copy(self, src_plugin, node) -> RecordNode:
        copy = _copy_node(node)
        strip = self.plugin.adapter.override_strip.get(node.signature, frozenset())
        if strip and any(f.signature in strip for f in node.fields):
            copy._orig_header = None
            copy.fields = [Subrecord(f.signature, f.data) for f in node.fields if f.signature not in strip]
            self.log.append(f'override {node.signature} {node.form_id:08X}: dropped {sorted(strip)}')
            node = copy                    # de-localization below works on the stripped fields
        if src_plugin.is_localized and not self.plugin.is_localized and self.strings is not None:
            fields = self._delocalized_fields(src_plugin, node)
            if fields is not None and [f.data for f in fields] != [f.data for f in node.fields]:
                copy._orig_header = None
                copy.fields = fields
                self.log.append(f'de-localized {node.signature} {node.form_id:08X}')
        return copy

    def _ensure_path(self, src_plugin, src_node) -> GroupNode:
        """Find or create the group chain (and owner records) leading to src_node's position."""
        chain = []
        g = src_node.parent
        while g is not None:
            chain.append(g)
            g = g.parent
        chain.reverse()
        siblings_owner = None   # container whose children list we search
        current = None
        layout = self.plugin.adapter.groups
        for src_group in chain:
            if src_group.kind == layout.top_kind:
                current = self.plugin.top_group(src_group.label_signature, create=True)
                continue
            children = current.children
            match = next((c for c in children if isinstance(c, GroupNode) and c.kind == src_group.kind
                          and c.label_bytes == src_group.label_bytes), None)
            if match is None:
                match = GroupNode.new(self.plugin.spec, src_group.label_bytes, src_group.kind,
                                      bytes(src_group.header[16:]))
                if src_group.kind in layout.owner_kinds:
                    owner_raw = src_group.label_int
                    owner = next((c for c in children if isinstance(c, RecordNode) and c.form_id == owner_raw), None)
                    if owner is None:
                        src_owner = _owner_record(src_group)
                        if src_owner is None:
                            raise UnsupportedOperation('override.container', f'owner {owner_raw:08X} not found')
                        self._require_same_strings(src_plugin, src_owner)
                        owner = self._copy(src_plugin, src_owner)
                        current.append(owner)
                        self.log.append(f'override container {owner.signature} {owner_raw:08X}')
                    current.insert(current.children.index(owner) + 1, match)
                else:
                    current.append(match)
            current = match
        return current

    def remove(self, view):
        self._check()
        parent = view.node.parent
        if parent is None:
            raise TransactionError(f'{view!r} is not attached')
        parent.remove(view.node)
        self.log.append(f'remove {view.signature} {view.form_key}')

    # -- commit -------------------------------------------------------------------------------
    def commit(self, path=None, *, load_order=None, validate: bool = True, backup_dir=None):
        """Write to a temporary file, reparse and validate it, then replace the target.

        On validation errors the temporary file is deleted, the target is untouched and
        ValidationError carries the report. Returns the report.
        """
        self._check()
        from .validate import validate_plugin
        target = Path(path) if path else self.plugin.path
        if target is None:
            raise TransactionError('no output path')
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f'.{target.name}.pyfield-{os.getpid()}-{int(time.time() * 1000)}.tmp')
        with open(tmp, 'wb') as out:
            for chunk in self.plugin.iter_chunks(update_header=True):
                out.write(chunk)
        report = None
        try:
            from .core.plugin import Plugin
            with Plugin.open(tmp, self.plugin.adapter, use_mmap=False) as written:
                written.name = target.name
                written.set_master_kinds(self.plugin._master_kinds)
                report = validate_plugin(written, load_order=load_order,
                                         baseline_order=self.plugin.source_group_order) if validate else None
            if report is not None and report.errors:
                raise ValidationError(report)
            if backup_dir and target.exists():
                stamp = time.strftime('%Y%m%d_%H%M%S')
                Path(backup_dir).mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, Path(backup_dir) / f'{target.stem}.{stamp}{target.suffix}')
            if self.plugin.path is not None and target == self.plugin.path.resolve():
                self.plugin.close()   # release a memory map before replacing the file
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        self._state = 'committed'
        return report


def _owner_record(group):
    """The record a children-group belongs to: the record just before it among its siblings."""
    parent = group.parent
    if parent is None:
        return None
    sibs = parent.children
    i = sibs.index(group)
    for node in reversed(sibs[:i]):
        if isinstance(node, RecordNode):
            return node if node.form_id == group.label_int else None
    return None


def _copy_node(node: RecordNode) -> RecordNode:
    """Detached copy that serializes to the source's exact bytes until edited."""
    c = RecordNode(node.spec, bytes(node.header), bytes(node._stored), None, None)
    c._orig_header = node._orig_header if node._orig_header is not None else None
    if node._fields is not None or node._orig_header is None:
        c._fields = [Subrecord(f.signature, f.data) for f in node.fields]
    if node.is_modified():
        c._orig_header = None          # carries unsaved edits: treat as new content
        c._fields = [Subrecord(f.signature, f.data) for f in node.fields]
    return c


def transaction(plugin) -> Transaction:
    return Transaction(plugin)


def _display_name(src_plugin, canonical: str) -> str:
    for name in list(src_plugin.masters) + [src_plugin.name]:
        if canonical_name(name) == canonical:
            return name
    return canonical


def _master_kind(src_plugin, canonical: str) -> str:
    if canonical == canonical_name(src_plugin.name):
        return src_plugin.kind
    return src_plugin.codec._lookup[canonical][0]
