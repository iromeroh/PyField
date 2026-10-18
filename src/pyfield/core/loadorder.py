"""Load order: several plugins resolved together.

- Master kinds come from the loaded plugins' own headers, so every FormIdCodec is exact.
- Override chains: a record can only be overridden by plugins that list its defining
  plugin as a master, so lookups touch only those plugins' indexes.
- Containment (which CELL/WRLD/DIAL/QUST owns a record) is physical and is reported
  separately from references (FormLinks inside typed members).
"""
from __future__ import annotations

import fnmatch
import re
import struct
from pathlib import Path
from typing import Callable, Iterable, Iterator

from ..errors import PyFieldError, ResolutionError
from . import compression
from .formids import FormKey, Unresolved, canonical_name
from .nodes import GroupNode, RecordNode
from .plugin import Plugin

class LoadOrder:
    def __init__(self, plugins: Iterable[Plugin]):
        self.plugins: list[Plugin] = list(plugins)
        self._by_name = {canonical_name(p.name): p for p in self.plugins}
        if len(self._by_name) != len(self.plugins):
            raise PyFieldError('duplicate plugin names in load order')
        kinds = {canonical_name(p.name): p.kind for p in self.plugins}
        for i, p in enumerate(self.plugins):
            missing = [m for m in p.masters if canonical_name(m) not in kinds]
            if missing:
                raise ResolutionError(f'{p.name}: masters not loaded: {missing}')
            late = [m for m in p.masters if self.position(m) > i]
            if late:
                raise ResolutionError(f'{p.name}: masters load after it: {late}')
            p.set_master_kinds({m: kinds[canonical_name(m)] for m in p.masters})
        self._dependents = {name: [q for q in self.plugins
                                   if name in map(canonical_name, q.masters) or canonical_name(q.name) == name]
                            for name in self._by_name}
        self._edid_index = {}
        self._reverse = None

    # -- construction -------------------------------------------------------------------------
    @classmethod
    def open(cls, data_dir, names: Iterable[str], game=None, with_masters: bool = True) -> 'LoadOrder':
        """Open plugins from `data_dir`; with_masters adds missing masters (recursively, first)."""
        data_dir = Path(data_dir)
        lookup = {p.name.lower(): p for p in data_dir.iterdir()}
        ordered, opened = [], {}

        def add(name, stack=()):
            key = name.lower()
            if key in opened:
                return
            if key in stack:
                raise ResolutionError(f'master cycle through {name}')
            path = lookup.get(key)
            if path is None:
                raise ResolutionError(f'{name} not found in {data_dir}')
            plugin = Plugin.open(path, game)
            if with_masters:
                for m in plugin.masters:
                    add(m, stack + (key,))
            opened[key] = plugin
            ordered.append(plugin)
        for n in names:
            add(n)
        return cls(ordered)

    @classmethod
    def around(cls, plugin: Plugin, data_dir, game=None) -> 'LoadOrder':
        """Load order for a plugin kept outside the data folder (e.g. a staging copy):
        its masters are opened from `data_dir`, then the plugin itself is appended."""
        masters = cls.open(data_dir, plugin.masters, game or plugin.adapter) if plugin.masters else None
        return cls((masters.plugins if masters else []) + [plugin])

    def close(self):
        for p in self.plugins:
            p.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def plugin(self, name: str) -> Plugin:
        try:
            return self._by_name[canonical_name(name)]
        except KeyError:
            raise ResolutionError(f'{name} is not in the load order') from None

    def position(self, name: str) -> int:
        target = canonical_name(name)
        return next((i for i, p in enumerate(self.plugins) if canonical_name(p.name) == target), -1)

    # -- resolution ---------------------------------------------------------------------------
    def overrides(self, key: FormKey) -> list[tuple[Plugin, RecordNode]]:
        """Every version of a record, in load order (first = defining plugin)."""
        out = []
        for p in self._dependents.get(key.plugin, []):
            node = p.get(key)
            if node is not None:
                out.append((p, node))
        return out

    def winner(self, key: FormKey) -> tuple[Plugin, RecordNode] | None:
        chain = self.overrides(key)
        return chain[-1] if chain else None

    def resolve(self, key: FormKey | str | None):
        """Typed view of the winning version of a record (None if absent)."""
        if key is None or isinstance(key, Unresolved):
            return None
        if isinstance(key, str):
            key = FormKey.parse(key)
        hit = self.winner(key)
        return hit[0].typed(hit[1]) if hit else None

    # -- localized text -------------------------------------------------------------------------
    def strings(self, language: str = 'en', data_dir=None):
        """String tables (`strings/<plugin>_<language>.*`, loose or in each plugin's archives), cached."""
        cache = self.__dict__.setdefault('_string_tables', {})
        if language not in cache:
            from ..assets.index import AssetIndex
            from ..games.tes4family import StringTables
            folder = Path(data_dir) if data_dir else next((p.path.parent for p in self.plugins if p.path), None)
            if folder is None:
                raise ResolutionError('no data folder known for string tables (pass data_dir)')
            rules = self.plugins[0].adapter.asset_rules
            cache[language] = StringTables(AssetIndex(folder, rules, [p.name for p in self.plugins]), language)
        return cache[language]

    def text(self, view, signature: str | None = None, language: str = 'en') -> str | None:
        """A localized (or plain) string subrecord of a record as text; None if absent or not in the tables.

        Works on any record view (typed or generic) by reading the raw subrecord: a 4-byte string id in
        localized plugins, a zero-terminated string otherwise. signature defaults to the adapter's
        name_signature (the display name)."""
        field = view.node.get(signature or view.plugin.adapter.name_signature)
        if field is None:
            return None
        data = bytes(field.data)
        if view.plugin.is_localized and len(data) == 4:
            sid = int.from_bytes(data, 'little')
            raw = self.strings(language).lookup(view.plugin.name, sid) if sid else b''
        else:
            raw = data.split(bytes(1), 1)[0]
        return None if raw is None else raw.decode('utf-8', 'replace')

    def display_name(self, view, language: str = 'en') -> str | None:
        return self.text(view, None, language)

    def key_of(self, plugin: Plugin, node: RecordNode) -> FormKey | Unresolved:
        return plugin.codec.try_decode(node.form_id)

    # -- iteration ----------------------------------------------------------------------------
    def records(self, *signatures: str, winners_only: bool = True) -> Iterator:
        """Typed views across the load order. With winners_only, each FormKey once (last version)."""
        if not winners_only:
            for p in self.plugins:
                yield from p.typed_records(*signatures)
            return
        seen = set()
        for p in reversed(self.plugins):
            for node in p.records(*signatures):
                key = p.codec.try_decode(node.form_id)
                if key in seen:
                    continue
                seen.add(key)
                yield p.typed(node)

    def query(self, *signatures: str) -> 'Query':
        return Query(self, signatures)

    # -- editor IDs ---------------------------------------------------------------------------
    def editor_id_index(self, plugin: Plugin) -> dict[str, list[int]]:
        """editor ID -> raw FormIDs for one plugin, read straight from record bytes (cached)."""
        name = canonical_name(plugin.name)
        if name not in self._edid_index:
            self._edid_index[name] = build_editor_id_index(plugin)
        return self._edid_index[name]

    def find_editor_id(self, editor_id: str, signature: str | None = None):
        """Typed winning record(s) with this editor ID (case-insensitive)."""
        target = editor_id.lower()
        found, seen = [], set()
        for p in reversed(self.plugins):
            for raw in self.editor_id_index(p).get(target, ()):
                key = p.codec.try_decode(raw)
                if key in seen:
                    continue
                seen.add(key)
                view = self.resolve(key)
                if view is not None and (signature is None or view.signature == signature):
                    found.append(view)
        return found

    # -- references ---------------------------------------------------------------------------
    def references_from(self, view) -> list[tuple[str, FormKey | Unresolved]]:
        return list(view.links())

    def build_reverse_index(self, signatures: Iterable[str] | None = None,
                            progress: Callable[[str], None] | None = None) -> dict[FormKey, list]:
        """target FormKey -> [(source FormKey, member path)] over typed members of winning records."""
        sigs = tuple(signatures) if signatures else tuple(self.plugins[0].adapter.schemas.classes)
        reverse: dict[FormKey, list] = {}
        for view in self.records(*sigs):
            if progress:
                progress(view.signature)
            source = view.form_key
            for path, target in view.links():
                if isinstance(target, FormKey):
                    reverse.setdefault(target, []).append((source, path))
        self._reverse = reverse
        return reverse

    def referenced_by(self, key: FormKey) -> list:
        if self._reverse is None:
            raise PyFieldError('call build_reverse_index() first (it decodes every typed record)')
        return self._reverse.get(key, [])

    # -- containment --------------------------------------------------------------------------
    def container_of(self, view) -> tuple[str, FormKey | Unresolved] | None:
        """(group kind name, owner FormKey) of the record physically containing this one."""
        layout = view.plugin.adapter.groups
        group = view.node.parent
        while group is not None:
            if group.kind in layout.owner_kinds:
                return layout.name(group.kind), view.plugin.codec.try_decode(group.label_int)
            group = group.parent
        return None

    def placement_path(self, view) -> list[tuple[str, str]]:
        """Group chain from the top level to the record, with readable labels."""
        layout = view.plugin.adapter.groups
        path = []
        group = view.node.parent
        while group is not None:
            kind = layout.name(group.kind)
            if group.kind == layout.top_kind:
                label = group.label_signature
            elif group.kind in layout.formid_label_kinds:
                label = str(view.plugin.codec.try_decode(group.label_int))
            elif group.kind in layout.grid_kinds:
                y, x = struct.unpack('<hh', group.label_bytes)
                label = f'({x}, {y})'
            else:
                label = str(group.label_int)
            path.append((kind, label))
            group = group.parent
        return path[::-1]


def build_editor_id_index(plugin: Plugin) -> dict[str, list[int]]:
    """Editor ID of each record without materializing nodes (it is the first field when present)."""
    spec = plugin.spec
    if spec.editor_id_signature is None:
        return {}
    eid_sig = spec.editor_id_signature.encode('latin-1')
    size_fmt, head = spec.subrecord_size_format, spec.subrecord_header_size
    data = plugin._data
    rh = spec.record_header_size
    out: dict[str, list[int]] = {}
    idx = plugin.index
    flag = spec.compressed_flag
    for i in range(len(idx)):
        off, size, flags = idx.offsets[i], idx.sizes[i], idx.flags[i]
        if flags & flag:
            body = compression.decompress(data[off + rh:off + rh + size], off)[:600]
        else:
            body = data[off + rh:off + rh + min(size, 600)]
        if len(body) < head or bytes(body[:4]) != eid_sig:
            continue
        n, = struct.unpack_from(size_fmt, body, 4)
        eid = bytes(body[head:head + n]).split(b'\0', 1)[0].decode('utf-8', 'replace').lower()
        out.setdefault(eid, []).append(idx.form_ids[i])
    return out


class Query:
    """Lazy, chainable filter over winning records of a load order."""

    def __init__(self, load_order: LoadOrder, signatures):
        self.lo = load_order
        self.signatures = tuple(signatures)
        self.filters: list[Callable] = []
        self._plugins = None

    def _add(self, fn):
        q = Query(self.lo, self.signatures)
        q.filters = self.filters + [fn]
        q._plugins = self._plugins
        return q

    def editor_id(self, pattern: str) -> 'Query':
        """Glob (case-insensitive) on the editor ID, or a regex if prefixed with 're:'."""
        if pattern.startswith('re:'):
            rx = re.compile(pattern[3:], re.I)
            return self._add(lambda v: v.editor_id is not None and rx.search(v.editor_id))
        pat = pattern.lower()
        return self._add(lambda v: v.editor_id is not None and fnmatch.fnmatchcase(v.editor_id.lower(), pat))

    def where(self, predicate: Callable) -> 'Query':
        def safe(v):
            try:
                return predicate(v)
            except (AttributeError, PyFieldError):
                return False
        return self._add(safe)

    def field(self, attr: str, value) -> 'Query':
        return self.where(lambda v: getattr(v, attr) == value)

    def references(self, key: FormKey) -> 'Query':
        return self._add(lambda v: any(t == key for _, t in v.links()))

    def in_plugins(self, *names: str) -> 'Query':
        q = self._add(lambda v: True)
        q._plugins = {canonical_name(n) for n in names}
        return q

    def __iter__(self):
        for view in self.lo.records(*self.signatures):
            if self._plugins is not None and canonical_name(view.plugin.name) not in self._plugins:
                continue
            if all(f(view) for f in self.filters):
                yield view

    def first(self):
        return next(iter(self), None)

    def list(self, limit: int | None = None) -> list:
        out = []
        for v in self:
            out.append(v)
            if limit and len(out) >= limit:
                break
        return out

    def count(self) -> int:
        return sum(1 for _ in self)
