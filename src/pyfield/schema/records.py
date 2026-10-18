"""Record schemas, the schema compiler, and typed record views.

A `RecordSchema` lists the record's *top-level* members in native order. Typed views
are thin: they decode a member's subrecord on attribute access and replace only that
subrecord on assignment, so every other subrecord (known or not) stays byte-identical.

Regions such as component blocks (``BFCB`` … ``BFCE``) are opaque to top-level members:
a signature inside a region is never mistaken for the top-level field of the same name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import keyword
import re
from typing import Iterator

from ..core.formids import FormKey, Unresolved
from ..core.nodes import RecordNode
from ..core.subrecords import Subrecord
from ..errors import SchemaError
from .codecs import Codec, Context


@dataclass
class Member:
    sig: str
    attr: str
    codec: Codec
    repeat: bool = False          # repeated consecutive subrecords -> list
    required: bool = False
    doc: str = ''
    counter: str | None = None    # signature of a member that stores this member's item count
    follows: str | None = None    # when this signature is present, insert directly after it


@dataclass
class Region:
    """Contiguous span of subrecords handled as a unit (opaque to top-level members).

    `after`: signature of the schema member the region follows in native order (None: the
    region precedes every member). Used to place newly inserted members on the right side.
    """
    start: str
    end: str
    name: str
    after: str | None = None


@dataclass
class RecordSchema:
    signature: str
    name: str
    members: list[Member]
    header_flags: dict[int, str] = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)
    evidence: str = ''            # how the layout was verified
    class_name: str | None = None  # Python class name (default: derived from `name`)
    field_order: list | None = None  # observed native order of all top-level signatures (incl. unmodelled)

    def member(self, attr: str) -> Member:
        for m in self.members:
            if m.attr == attr:
                return m
        raise AttributeError(f'{self.signature} has no member {attr!r}')

    def by_sig(self, sig: str) -> Member | None:
        return next((m for m in self.members if m.sig == sig), None)


def attr_name(text: str) -> str:
    name = re.sub(r'[^0-9a-zA-Z]+', '_', text).strip('_').lower() or 'field'
    if name[0].isdigit() or keyword.iskeyword(name):
        name = 'f_' + name
    return name


# -- typed record view ----------------------------------------------------------------------------

class TypedRecord:
    """Typed view over a RecordNode. Subclasses are generated per schema (see compile_schema)."""

    schema: RecordSchema = None

    def __init__(self, node: RecordNode, plugin):
        if self.schema is not None and node.signature != self.schema.signature:
            raise SchemaError(f'{node!r} is not a {self.schema.signature}')
        self.node = node
        self.plugin = plugin

    # identity ------------------------------------------------------------------------------
    @property
    def signature(self) -> str:
        return self.node.signature

    @property
    def form_id(self) -> int:
        return self.node.form_id

    @property
    def form_key(self) -> FormKey | Unresolved:
        return self.plugin.codec.try_decode(self.node.form_id)

    @property
    def editor_id(self) -> str | None:
        return self.node.editor_id

    @property
    def header_flags(self) -> int:
        return self.node.flags

    @header_flags.setter
    def header_flags(self, value: int):
        self.node.flags = value

    def header_flag_names(self) -> list[str]:
        names = self.schema.header_flags if self.schema else {}
        return [names.get(b, f'bit{b}') for b in range(32) if self.node.flags >> b & 1]

    @property
    def context(self) -> Context:
        return Context(self.plugin.codec, self.plugin.is_localized)

    # region-aware field access ---------------------------------------------------------------
    def top_level_positions(self) -> Iterator[int]:
        """Indices of subrecords outside any region of this schema."""
        regions = self.schema.regions if self.schema else []
        starts = {r.start: r.end for r in regions}
        inside = None
        for i, f in enumerate(self.node.fields):
            if inside is None and f.signature in starts:
                inside = starts[f.signature]
                continue
            if inside is not None:
                if f.signature == inside:
                    inside = None
                continue
            yield i

    def _positions(self, sig: str) -> list[int]:
        fields = self.node.fields
        return [i for i in self.top_level_positions() if fields[i].signature == sig]

    def get_value(self, member: Member):
        fields = self.node.fields
        pos = self._positions(member.sig)
        ctx = self.context
        try:
            if member.repeat:
                return [member.codec.decode(fields[i].data, ctx) for i in pos]
            if not pos:
                return None
            if len(pos) > 1:
                raise SchemaError(f'{self.node!r}: {member.sig} occurs {len(pos)} times at top level')
            return member.codec.decode(fields[pos[0]].data, ctx)
        except SchemaError as exc:
            raise SchemaError(f'{self.node!r}.{member.attr} ({member.sig}): {exc}') from None

    def set_value(self, member: Member, value):
        self._set_value(member, value)
        if member.counter:
            count_member = self.schema.by_sig(member.counter)
            n = len(list(value or ()))
            self._set_value(count_member, n if n else None)

    def _set_value(self, member: Member, value):
        fields = self.node.fields
        pos = self._positions(member.sig)
        ctx = self.context
        if member.repeat:
            values = list(value or ())
            new = [Subrecord(member.sig, member.codec.encode(v, ctx)) for v in values]
            if pos:
                if pos != list(range(pos[0], pos[0] + len(pos))):
                    raise SchemaError(f'{member.sig} entries are not contiguous; refusing to rewrite')
                fields[pos[0]:pos[-1] + 1] = new
            elif new:
                at = self._insert_position(member)
                fields[at:at] = new
            return
        if value is None or (member.counter and not list(value)):
            if member.required:
                raise SchemaError(f'{member.attr} is required')
            for i in reversed(pos):
                del fields[i]
            return
        data = member.codec.encode(value, ctx)
        if pos:
            if len(pos) > 1:
                raise SchemaError(f'{member.sig} occurs {len(pos)} times at top level')
            if fields[pos[0]].data != data:
                fields[pos[0]] = Subrecord(member.sig, data)
        else:
            fields.insert(self._insert_position(member), Subrecord(member.sig, data))

    def _insert_position(self, member: Member) -> int:
        """After the last top-level field (or region) that precedes `member` in native order.

        Native order is the schema's observed `field_order` when available (it ranks
        unmodelled signatures too), otherwise the member order of the schema.
        """
        if member.follows:
            anchors = [i for i in self.top_level_positions() if self.node.fields[i].signature == member.follows]
            if anchors:
                return anchors[-1] + 1
        if self.schema.field_order:
            order = {sig: i for i, sig in enumerate(self.schema.field_order)}
        else:
            order = {m.sig: i for i, m in enumerate(self.schema.members)}
        rank = order.get(member.sig)
        if rank is None:                      # never observed: fall back to schema order
            order = {m.sig: i for i, m in enumerate(self.schema.members)}
            rank = order[member.sig]
        regions = {r.start: r for r in self.schema.regions}
        best, inside = 0, None
        for i, f in enumerate(self.node.fields):
            if inside is not None:
                if f.signature == inside.end:
                    region_rank = order.get(inside.after, -1) + 0.5 if inside.after else -0.5
                    if region_rank < rank:
                        best = i + 1
                    inside = None
                continue
            if f.signature in regions:
                inside = regions[f.signature]
                continue
            if f.signature in order and order[f.signature] < rank:
                best = i + 1
        return best

    # whole-record views ----------------------------------------------------------------------
    def unknown_signatures(self) -> list[str]:
        known = {m.sig for m in self.schema.members} if self.schema else {self.node.spec.editor_id_signature}
        fields = self.node.fields
        return [fields[i].signature for i in self.top_level_positions() if fields[i].signature not in known]

    def regions(self) -> list[tuple[str, list[Subrecord]]]:
        """(region name, subrecords) for each region occurrence, in order."""
        out, current, end = [], None, None
        starts = {r.start: r for r in (self.schema.regions if self.schema else [])}
        for f in self.node.fields:
            if current is None and f.signature in starts:
                current, end = (starts[f.signature].name, [f]), starts[f.signature].end
                continue
            if current is not None:
                current[1].append(f)
                if f.signature == end:
                    out.append(current)
                    current = None
        return out

    def links(self) -> Iterator[tuple[str, FormKey | Unresolved]]:
        """(member path, target) for every FormLink in typed top-level members."""
        if not self.schema:
            return
        for m in self.schema.members:
            value = self.get_value(m)
            if m.repeat:
                for i, v in enumerate(value):
                    for path, link in m.codec.links(v):
                        yield f'{m.attr}[{i}]' + (f'.{path}' if path else ''), link
            elif value is not None:
                for path, link in m.codec.links(value):
                    yield m.attr + (f'.{path}' if path else ''), link

    def to_dict(self) -> dict:
        out = {'signature': self.signature, 'form_key': str(self.form_key), 'editor_id': self.editor_id,
               'header_flags': self.header_flag_names()}
        for m in (self.schema.members if self.schema else []):
            try:
                v = self.get_value(m)
            except SchemaError as exc:
                v = f'<error: {exc}>'
            if v is None or v == []:
                continue
            out[m.attr] = _plain(v)
        unknown = self.unknown_signatures()
        if unknown:
            out['_unmodelled'] = unknown
        return out

    def __repr__(self):
        eid = f' {self.editor_id!r}' if self.editor_id else ''
        return f'<{type(self).__name__} {self.form_key}{eid}>'


def _plain(v):
    if hasattr(v, 'to_dict'):
        return v.to_dict()
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, (FormKey, Unresolved)):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()
    return v


class GenericRecord(TypedRecord):
    """Fallback view for record types without a schema: identity and raw fields only."""
    schema = None


# -- schema compiler ------------------------------------------------------------------------------

OVERRIDABLE = {'editor_id'}   # base-class properties a schema member may replace

def _member_property(member: Member):
    def getter(self):
        return self.get_value(member)

    def setter(self, value):
        self.set_value(member, value)
    return property(getter, setter, doc=f'{member.sig}: {member.codec.describe()}' +
                    (f' — {member.doc}' if member.doc else ''))


def compile_schema(schema: RecordSchema, inventory: dict | None = None, module: str | None = None) -> type:
    """Generate the TypedRecord subclass for a schema, after consistency checks.

    With an xEdit inventory, every member must exist in the inventory's member list for the
    record and must not be ambiguous at top level (same signature twice outside regions).
    """
    seen_attrs, seen_sigs = set(), set()
    for m in schema.members:
        if m.attr in seen_attrs or (hasattr(TypedRecord, m.attr) and m.attr not in OVERRIDABLE):
            raise SchemaError(f'{schema.signature}.{m.attr}: duplicate or reserved attribute name')
        if m.sig in seen_sigs:
            raise SchemaError(f'{schema.signature}: {m.sig} declared twice; use a region or a block')
        seen_attrs.add(m.attr)
        seen_sigs.add(m.sig)
    if inventory is not None:
        check_against_inventory(schema, inventory)
    attrs = {'schema': schema, '__doc__': f'{schema.name} ({schema.signature}). {schema.evidence}'.strip(),
             '__slots__': ()}
    for m in schema.members:
        attrs[m.attr] = _member_property(m)
    name = schema.class_name or re.sub(r'[^0-9a-zA-Z]', '', schema.name.title()) or schema.signature
    if module:
        attrs['__module__'] = module
    return type(name, (TypedRecord,), attrs)


def check_against_inventory(schema: RecordSchema, inventory: dict):
    """Every member must be a top-level xEdit member of the record and unambiguous there.

    Inventory entries inside the schema's regions are ignored, as are adjacent duplicates
    from the same helper (xEdit's per-game alternatives, e.g. IsFO4Plus(XOWN struct, XOWN id)).
    """
    entry = inventory.get('records', {}).get(schema.signature)
    if entry is None:
        raise SchemaError(f'{schema.signature} not in xEdit inventory')
    region_macros = {'wbBaseFormComponents'}
    regions = {r.start: r.end for r in schema.regions}
    top, inside, prev = [], None, None
    for m in entry['members']:
        if region_macros & set(m.get('via', [])):
            continue
        if inside is not None:
            if m['sig'] == inside:
                inside = None
            continue
        if m['sig'] in regions:
            inside = regions[m['sig']]
            continue
        key = (m['sig'], tuple(m.get('via', [])))
        if prev == key and m.get('via'):
            continue
        prev = key
        top.append(m)
    counts = {}
    for m in top:
        counts[m['sig']] = counts.get(m['sig'], 0) + 1
    for m in schema.members:
        if m.sig not in counts:
            raise SchemaError(f'{schema.signature}.{m.attr}: {m.sig} is not a top-level member in xEdit')
        if counts[m.sig] > 1 and not m.repeat:
            raise SchemaError(f'{schema.signature}.{m.attr}: {m.sig} is ambiguous at top level '
                              f'({counts[m.sig]} definitions); model it inside a block')


class SchemaSet:
    """Compiled typed classes for one game, keyed by record signature."""

    def __init__(self, schemas: list[RecordSchema], inventory: dict | None = None, module: str | None = None,
                 version: str | None = None):
        self.schemas = {s.signature: s for s in schemas}
        self.classes = {s.signature: compile_schema(s, inventory, module) for s in schemas}
        self.version = version

    def view(self, node: RecordNode, plugin) -> TypedRecord:
        cls = self.classes.get(node.signature, GenericRecord)
        return cls(node, plugin)

    def __contains__(self, sig):
        return sig in self.classes
