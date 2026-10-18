"""Plugin file: header record + lazily expanded top-level groups.

`Plugin` is game-agnostic; an adapter object (see pyfield.games.base.GameAdapter) supplies
the format and the meaning of header flags.
"""
from __future__ import annotations

from bisect import bisect_left
import mmap
import os
from pathlib import Path
import struct
from typing import Iterable, Iterator

from ..errors import FormatError, PyFieldError, ResolutionError
from .formids import FULL, UNKNOWN, FormIdCodec, FormKey, MasterRef, canonical_name
from .index import RecordIndex
from .nodes import GroupNode, RecordNode, parse_nodes
from .subrecords import Subrecord

MMAP_THRESHOLD = 256 * 1024 * 1024

# Header record-count conventions observed in real files (docs/formats/starfield-formids.md)
COUNT_RECORDS_AND_GROUPS = 'records+groups'     # Creation Kit
COUNT_RECORDS_PLUS_HEADER = 'records+1'         # Bethesda-built masters


class Plugin:
    def __init__(self, adapter, name: str, data, path: Path | None = None, closer=None):
        self.adapter = adapter
        self.spec = spec = adapter.format
        self.name = name
        self.path = path
        self._data = data
        self._closer = closer
        if bytes(data[:4]) != spec.plugin_header_signature:
            raise FormatError(f'{name}: not a plugin (no {spec.plugin_header_signature!r} header)', 0)
        nodes = parse_nodes(spec, data, 0, len(data))
        try:
            self.header: RecordNode = next(nodes)
        except StopIteration:
            raise FormatError(f'{name}: empty file', 0) from None
        if not isinstance(self.header, RecordNode):
            raise FormatError(f'{name}: header is not a record', 0)
        self._header_end = len(self.header.header) + len(self.header._stored)
        self.groups: list[GroupNode] = []
        for node in nodes:
            if not isinstance(node, GroupNode):
                raise FormatError(f'{name}: record {node!r} outside any group', node.offset)
            self.groups.append(node)
        self.source_group_order = [g.label_signature for g in self.groups]   # as opened, for validation
        self._index = None
        self._master_kinds: dict[str, str] = {}
        self._codec = None
        self._count_convention = None
        self._fresh_header = False

    # -- opening ------------------------------------------------------------------------------
    @classmethod
    def open(cls, path, adapter=None, use_mmap: bool | None = None) -> 'Plugin':
        path = Path(path)
        if adapter is None:
            from ..games import detect_file
            adapter = detect_file(path)
        elif isinstance(adapter, str):
            from ..games import get
            adapter = get(adapter)
        size = path.stat().st_size
        if use_mmap is None:
            use_mmap = size >= MMAP_THRESHOLD
        if use_mmap and size:
            with open(path, 'rb') as handle:
                mm = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            view = memoryview(mm)

            def closer():
                try:
                    view.release()
                    mm.close()
                except BufferError:
                    pass   # nodes still reference the map; it is released when they are collected
            return cls(adapter, path.name, view, path, closer)
        return cls(adapter, path.name, memoryview(path.read_bytes()), path)

    @classmethod
    def from_bytes(cls, data: bytes, name: str, adapter) -> 'Plugin':
        if isinstance(adapter, str):
            from ..games import get
            adapter = get(adapter)
        return cls(adapter, name, memoryview(bytes(data)))

    @classmethod
    def create(cls, name: str, adapter, masters: Iterable[str] = (), *, flags: int = 0,
               author: str = '', description: str = '') -> 'Plugin':
        """A new, empty plugin with a Creation-Kit-style header."""
        if isinstance(adapter, str):
            from ..games import get
            adapter = get(adapter)
        spec = adapter.format
        fields = adapter.header.new_fields(masters, author, description, adapter.default_header_version,
                                           adapter.first_object_id)
        header = RecordNode.new(spec, spec.plugin_header_signature.decode('latin-1'), 0, fields, flags,
                                adapter.header_tail())
        plugin = cls(adapter, name, memoryview(header.to_bytes()))
        plugin._count_convention = COUNT_RECORDS_AND_GROUPS
        plugin._fresh_header = True
        return plugin

    def close(self):
        if self._closer:
            self._closer()
            self._closer = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f'<Plugin {self.name} ({self.adapter.name})>'

    # -- header semantics ---------------------------------------------------------------------
    @property
    def flags(self) -> int:
        return self.header.flags

    @flags.setter
    def flags(self, value: int):
        self.header.flags = value
        self._codec = None

    @property
    def is_master(self) -> bool:
        return bool(self.flags & self.adapter.master_flag)

    @property
    def kind(self) -> str:
        """full / medium / small, as other plugins see this file when it is their master."""
        return self.adapter.master_kind(self.flags)

    @property
    def is_localized(self) -> bool:
        return self.adapter.is_localized(self.flags)

    @property
    def masters(self) -> list[str]:
        return self.adapter.header.masters(self.header.fields)

    @property
    def author(self) -> str | None:
        return self.adapter.header.author(self.header.fields)

    @property
    def description(self) -> str | None:
        return self.adapter.header.description(self.header.fields)

    @property
    def header_counts(self) -> tuple[float, int, int]:
        """(header version, stored record count, next object ID)."""
        return self.adapter.header.counts(self.header.fields)

    hedr = header_counts   # TES4-family name, kept for convenience

    def add_master(self, name: str, kind: str | None = None):
        """Append a master. Refused when it would change how this plugin's own FormIDs are
        encoded while own records exist (e.g. a full master shifts the ordinal own prefix):
        PyField does not rewrite raw FormIDs it cannot locate."""
        if canonical_name(name) in map(canonical_name, self.masters):
            return
        before = self.codec.encode(FormKey(self.name, 1)) if self._has_own_records() else None
        fields_before = list(self.header.fields)
        self.adapter.header.add_master(self.header.fields, name)
        if kind is not None:
            self._master_kinds[canonical_name(name)] = kind
        self._codec = None
        if before is not None and self.codec.encode(FormKey(self.name, 1)) != before:
            self.header.fields = fields_before
            self._master_kinds.pop(canonical_name(name), None)
            self._codec = None
            from ..errors import UnsupportedOperation
            raise UnsupportedOperation('masters.add_shifts_own_ids',
                                       f'adding {kind or "full"} master {name} to {self.name} would change the '
                                       f'prefix of its existing own records; add masters before creating records')

    def _has_own_records(self) -> bool:
        if any(n.offset is None for n in self._expanded_records()):
            return True
        own = self.codec
        return any(own.is_own(fid) for fid in self.index.form_ids)

    # -- FormID context -----------------------------------------------------------------------
    def set_master_kinds(self, kinds: dict[str, str]):
        self._master_kinds.update({canonical_name(k): v for k, v in kinds.items()})
        self._codec = None

    def resolve_master_kinds(self, data_dir=None):
        """Read each master's header flags from `data_dir` (default: this plugin's folder)."""
        folder = Path(data_dir) if data_dir else (self.path.parent if self.path else None)
        for m in self.masters:
            key = canonical_name(m)
            if key in self._master_kinds or folder is None:
                continue
            candidate = folder / m
            if not candidate.exists():
                # case-insensitive lookup (Windows paths are, other systems are not)
                matches = [p for p in folder.iterdir() if p.name.lower() == key] if folder.is_dir() else []
                candidate = matches[0] if matches else None
            if candidate is not None:
                with open(candidate, 'rb') as handle:
                    flags = struct.unpack_from('<I', handle.read(12), 8)[0]
                self._master_kinds[key] = self.adapter.master_kind(flags)
        self._codec = None

    @property
    def codec(self) -> FormIdCodec:
        if self._codec is None:
            if any(canonical_name(m) not in self._master_kinds for m in self.masters):
                self.resolve_master_kinds()
            refs = [MasterRef(m, self._master_kinds.get(canonical_name(m), UNKNOWN)) for m in self.masters]
            if len(self.adapter.namespaces) == 1:
                refs = [MasterRef(r.name, FULL) for r in refs]
            self._codec = FormIdCodec(self.name, refs, self.kind, self._own_style(refs),
                                      self.adapter.namespaces)
        return self._codec

    def _own_style(self, refs) -> str:
        """'compact' if own records use the namespace of this file's own kind (Bethesda style)."""
        kind = self.kind
        if kind == FULL:
            return 'ordinal'
        prefix = 0xFE if kind == 'small' else 0xFD
        own_index = sum(1 for r in refs if r.kind == kind)
        shift = 12 if kind == 'small' else 16
        mask = 0xFFF if kind == 'small' else 0xFF
        for fid in self.index.form_ids:
            if fid >> 24 == prefix and (fid >> shift) & mask == own_index:
                return 'compact'
        return 'ordinal'

    def form_key(self, raw: int) -> FormKey | None:
        return self.codec.decode(raw)

    def raw_form_id(self, key: FormKey | None) -> int:
        return self.codec.encode(key)

    # -- indexing -----------------------------------------------------------------------------
    @property
    def index(self) -> RecordIndex:
        """Header-only index of the *source* bytes (does not see unsaved structural edits)."""
        if self._index is None:
            self._index = RecordIndex.scan(self.spec, self._data, self._header_end)
        return self._index

    @property
    def count_convention(self) -> str:
        if self._count_convention is None:
            stored = self.hedr[1]
            idx = self.index
            if stored == len(idx) + 1 and stored != len(idx) + len(idx.groups):
                self._count_convention = COUNT_RECORDS_PLUS_HEADER
            else:
                self._count_convention = COUNT_RECORDS_AND_GROUPS
        return self._count_convention

    # -- tree navigation ----------------------------------------------------------------------
    def node_at(self, offset: int):
        """The node starting at source `offset`, expanding only the groups on its path."""
        siblings = self.groups
        while True:
            node = _find_containing(siblings, offset, self.spec)
            if node is None:
                raise PyFieldError(f'{self.name}: no node at {offset:#x} (removed or never existed)')
            if node.offset == offset:
                return node
            if not isinstance(node, GroupNode):
                raise PyFieldError(f'{self.name}: {offset:#x} is inside record {node!r}')
            siblings = node.children

    def top_group(self, signature: str, create: bool = False) -> GroupNode | None:
        for g in self.groups:
            if g.kind == self.adapter.groups.top_kind and g.label_signature == signature:
                return g
        if not create:
            return None
        top = self.adapter.groups.top_kind
        group = GroupNode.new(self.spec, signature.encode('latin-1'), top, bytes(self.spec.group_header_size - 16))
        self.groups.insert(self._group_insert_position(signature), group)
        return group

    def _group_insert_position(self, signature: str) -> int:
        """Index for a new top-level group: fewest native-order violations against the existing
        groups (which may already be out of order), ties broken by the earliest native slot."""
        rank = self.adapter.group_rank(signature)
        ranks = [self.adapter.group_rank(g.label_signature) for g in self.groups]
        best, best_cost = len(ranks), None
        for at in range(len(ranks) + 1):
            cost = sum(1 for r in ranks[:at] if r > rank) + sum(1 for r in ranks[at:] if r < rank)
            if best_cost is None or cost < best_cost:
                best, best_cost = at, cost
        return best

    def walk(self) -> Iterator:
        for g in self.groups:
            yield g
            yield from g.walk()

    def records(self, *signatures: str) -> Iterator[RecordNode]:
        """Records in document order (optionally filtered), including unsaved additions.

        Top-level groups the source index proves irrelevant are skipped without expanding.
        """
        wanted = set(signatures)
        relevant = self._top_groups_containing(wanted) if wanted and self._index_matches_tree() else None
        for g in self.groups:
            if relevant is not None and g.offset is not None and g.offset not in relevant and not g.is_expanded:
                continue
            for node in g.walk():
                if isinstance(node, RecordNode) and (not wanted or node.signature in wanted):
                    yield node

    def _index_matches_tree(self) -> bool:
        return True   # index offsets are source offsets; unexpanded groups are unmodified by definition

    def _top_groups_containing(self, wanted) -> set[int]:
        idx = self.index
        top = []
        for g in idx.groups:
            top.append(len(top) if g.parent == -1 else top[g.parent])
        wanted_ints = {int.from_bytes(s.encode('latin-1'), 'little') for s in wanted}
        found = set()
        for sig, parent in zip(idx.sigs, idx.parents):
            if sig in wanted_ints and parent != -1:
                found.add(idx.groups[top[parent]].offset)
        return found

    def find(self, form_id: int) -> RecordNode | None:
        """Record by raw (file-relative) FormID, searching the source index then additions."""
        for pos in self.index.positions(form_id):
            try:
                node = self.node_at(self.index.offsets[pos])
            except PyFieldError:
                continue   # removed from the tree
            if node.form_id == form_id and node.parent is not None and _attached(node, self):
                return node
        for node in self._expanded_records():
            if node.form_id == form_id and node.offset is None:
                return node
        return None

    def get(self, key: FormKey) -> RecordNode | None:
        try:
            raw = self.codec.encode(key)
        except ResolutionError:
            return None
        return self.find(raw)

    def _expanded_records(self) -> Iterator[RecordNode]:
        def visit(nodes):
            for n in nodes:
                if isinstance(n, RecordNode):
                    yield n
                elif n.is_expanded:
                    yield from visit(n.children)
        return visit(self.groups)

    # -- editing ------------------------------------------------------------------------------
    def transaction(self):
        """Begin a Transaction (see pyfield.edit); use as a context manager for rollback on error."""
        from ..edit import Transaction
        return Transaction(self)

    def modified_records(self) -> list[RecordNode]:
        """Records added or changed since opening (removals are visible in pyfield.diff)."""
        return [n for n in self._expanded_records() if n.is_modified()]

    # -- typed views --------------------------------------------------------------------------
    def typed(self, node: RecordNode):
        """Typed view of a record node (generic view when the adapter has no schema for it)."""
        schemas = self.adapter.schemas
        if schemas is None:
            from ..schema.records import GenericRecord
            return GenericRecord(node, self)
        return schemas.view(node, self)

    def typed_records(self, *signatures: str):
        return (self.typed(n) for n in self.records(*signatures))

    def own_local_ids(self) -> set[int]:
        codec = self.codec
        own = set()
        for fid in self.index.form_ids:
            key = codec.try_decode(fid)
            if isinstance(key, FormKey) and key.plugin == codec._self:
                own.add(key.local_id)
        for node in self._expanded_records():
            key = codec.try_decode(node.form_id)
            if isinstance(key, FormKey) and key.plugin == codec._self:
                own.add(key.local_id)
        return own

    # -- serialization ------------------------------------------------------------------------
    def node_count(self) -> int:
        """Records + groups that will be written (excluding the header record)."""
        idx = self.index
        group_offsets = [g.offset for g in idx.groups]

        def count(node):
            if isinstance(node, RecordNode):
                return 1
            if not node.is_expanded:
                lo, hi = node.offset, node.offset + len(node._raw)
                records = bisect_left(idx.offsets, hi) - bisect_left(idx.offsets, lo)
                groups = bisect_left(group_offsets, hi) - bisect_left(group_offsets, lo)
                return records + groups
            return 1 + sum(count(c) for c in node.children)
        return sum(count(g) for g in self.groups)

    def record_count(self) -> int:
        idx = self.index

        def count(node):
            if isinstance(node, RecordNode):
                return 1
            if not node.is_expanded:
                lo, hi = node.offset, node.offset + len(node._raw)
                return bisect_left(idx.offsets, hi) - bisect_left(idx.offsets, lo)
            return sum(count(c) for c in node.children)
        return sum(count(g) for g in self.groups)

    def update_header(self):
        """Adjust the header's record count and next object ID for the edits made since opening.

        The stored count is shifted by the change in node count (in the file's own
        convention), so files whose stored count was already unusual stay unusual and an
        unedited plugin keeps its header byte for byte. The next object ID only advances
        past own records that were added or renumbered.
        """
        version, stored_count, next_id = self.header_counts
        idx = self.index
        if self.count_convention == COUNT_RECORDS_PLUS_HEADER:
            delta = self.record_count() - len(idx)
        else:
            delta = self.node_count() - (len(idx) + len(idx.groups))
        count = max(0, stored_count + delta)
        codec = self.codec
        needed = 0
        for node in self._expanded_records():
            if node.offset is None or node.form_id != struct.unpack_from('<I', node._orig_header, 12)[0]:
                key = codec.try_decode(node.form_id)
                if isinstance(key, FormKey) and key.plugin == codec._self:
                    needed = max(needed, key.local_id + 1)
        local_bits = 0xFFFFFF
        if self._fresh_header and self.adapter.next_id_has_own_prefix:
            # Creation Kit style: high byte = own ordinal (e.g. 0x01000800 with one full master)
            next_id = (len(codec._by_kind['full']) << 24) | (next_id & local_bits)
        if needed > next_id & local_bits:
            next_id = (next_id & ~local_bits & 0xFFFFFFFF) | needed
        self.adapter.header.set_counts(self.header.fields, count, next_id)

    def iter_chunks(self, update_header: bool = True) -> Iterator[bytes]:
        if update_header:
            self.update_header()
        try:
            yield from self.header.iter_chunks()
            for g in self.groups:
                g.nbytes()
                yield from g.iter_chunks()
        finally:
            self.header.end_save()
            for g in self.groups:
                g.end_save()

    def to_bytes(self, update_header: bool = True) -> bytes:
        return b''.join(self.iter_chunks(update_header))

    def write(self, path, update_header: bool = True):
        """Write to `path` via a temporary file in the same folder (no validation; see pyfield.edit)."""
        path = Path(path)
        tmp = path.with_name(path.name + '.pyfield-tmp')
        with open(tmp, 'wb') as out:
            for chunk in self.iter_chunks(update_header):
                out.write(chunk)
        os.replace(tmp, path)


def _attached(node, plugin) -> bool:
    while node.parent is not None:
        node = node.parent
    return node in plugin.groups


def _find_containing(siblings, offset, spec):
    """Sibling whose source byte range contains `offset` (siblings keep source order)."""
    lo, hi = 0, len(siblings)
    # Binary search over siblings that have source offsets; new nodes (offset None) are skipped.
    while lo < hi:
        mid = (lo + hi) // 2
        probe = mid
        while probe < hi and siblings[probe].offset is None:
            probe += 1
        if probe == hi:
            hi = mid
            continue
        node = siblings[probe]
        if node.offset > offset:
            hi = mid
        else:
            end = node.offset + (len(node._raw) if isinstance(node, GroupNode)
                                 else len(node.header) + len(node._stored))
            if offset < end:
                return node
            lo = probe + 1
    return None
