"""Entity transplant: pick records (and their assets) from one plugin into another.

    plan = plan_transplant(lo, 'star_radio.esm', [FormKey('star_radio.esm', 0xB9A)], mode='copy')
    print(plan.summary())                     # copy set, rebuild-only references, unverified positions, assets
    with target.transaction() as tx:
        result = apply_transplant(plan, tx)   # new FormIDs, remapped references, asset bytes to pack
        tx.commit(...)

Modes
  reference  the target uses the entities through the source as a master; nothing is copied.
  copy       records are copied with new FormIDs; references among them are rewritten; the
             assets the source owns are returned for packing into the target's archives.

Safety rules (docs/design/entity-transplant-and-assets.md): only record types whose adapter
policy is 'copy' are copied; references at known positions are remapped; source-own FormIDs
found at unknown positions block the copy unless their subrecord signature is explicitly
accepted; master references keep their raw values, so master layouts must match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import functools
import inspect
import struct

from .core.formids import FormKey, Unresolved, canonical_name
from .core.nodes import RecordNode
from .core.subrecords import Subrecord
from .errors import PyFieldError, ResolutionError, UnsupportedOperation
from .schema.codecs import Array, FormLink, Struct


# -- known FormID positions -------------------------------------------------------------------

def codec_formid_offsets(codec, length: int) -> set[int] | None:
    """Byte offsets of FormLinks inside a payload of `length` bytes for this codec (None: unknown)."""
    if isinstance(codec, FormLink):
        return {0} if length == 4 else None
    if isinstance(codec, Array) and isinstance(codec.element, FormLink) and codec.count == 'rest':
        return set(range(0, length - length % 4, 4)) if length % 4 == 0 else None
    if isinstance(codec, Struct):
        offsets, pos = set(), 0
        for _, sub in codec.fields:
            if sub.size is None:
                inner = codec_formid_offsets(sub, length - pos) if sub is codec.fields[-1][1] else None
                if inner is None:
                    return offsets if not _has_formlink(sub) else None
                return offsets | {pos + o for o in inner}
            if pos + sub.size > length:
                break
            inner = codec_formid_offsets(sub, sub.size) if _has_formlink(sub) else set()
            if inner is None:
                return None
            offsets |= {pos + o for o in inner}
            pos += sub.size
        return offsets
    return set() if not _has_formlink(codec) else None


def _has_formlink(codec) -> bool:
    if isinstance(codec, FormLink):
        return True
    if isinstance(codec, Array):
        return _has_formlink(codec.element)
    if isinstance(codec, Struct):
        return any(_has_formlink(c) for _, c in codec.fields)
    return False


@functools.lru_cache(maxsize=None)
def _takes_record_sig(locator) -> bool:
    """Locators may take (data) or (data, record_signature)."""
    try:
        return len(inspect.signature(locator).parameters) >= 2
    except (TypeError, ValueError):
        return False


class KnownPositions:
    """Where FormIDs are known to be, per record type and subrecord signature."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.schemas = adapter.schemas
        self._inventory = None
        self._cache = {}

    STRING_KINDS = {'zstring'}

    def _whole_formid_sigs(self, record_sig: str, top_level: bool) -> set[str]:
        """Signatures that are a single FormID wherever they occur in this part of the record.

        A signature xEdit types as FormID in one place and as a plain string elsewhere still
        counts for 4-byte payloads (a 3-character string is not a model or editor path).
        """
        if self._inventory is None:
            loader = self.adapter.inventory_loader
            self._inventory = loader() if callable(loader) else {}
        entry = (self._inventory or {}).get('records', {}).get(record_sig, {})
        kinds = {}
        for m in entry.get('members', []):
            in_component = 'wbBaseFormComponents' in m.get('via', [])
            if in_component == (not top_level):
                kinds.setdefault(m['sig'], set()).add(m['kind'])
        return {sig for sig, k in kinds.items() if 'formid' in k and k <= {'formid'} | self.STRING_KINDS}

    def offsets(self, record_sig: str, sub_sig: str, length: int, top_level: bool) -> set[int]:
        key = (record_sig, sub_sig, length, top_level)
        if key in self._cache:
            return self._cache[key]
        found = set()
        schema = self.schemas.schemas.get(record_sig) if self.schemas else None
        member = schema.by_sig(sub_sig) if schema and top_level else None
        if member is not None:
            found = codec_formid_offsets(member.codec, length) or set()
        if not found and length == 4 and sub_sig in self._whole_formid_sigs(record_sig, top_level):
            found = {0}
        if not found and sub_sig in self.adapter.formid_array_signatures and length % 4 == 0:
            found = set(range(0, length, 4))
        self._cache[key] = found
        return found

    def offsets_for(self, record_sig: str, sub_sig: str, data: bytes, top_level: bool) -> set[int]:
        locator = self.adapter.formid_locators.get(sub_sig)
        if locator is not None:
            located = locator(data, record_sig) if _takes_record_sig(locator) else locator(data)
            if located is not None:
                return located
        return self.offsets(record_sig, sub_sig, len(data), top_level)


# -- plan -------------------------------------------------------------------------------------

@dataclass
class Reference:
    source: FormKey            # record containing the reference
    signature: str             # subrecord
    offset: int
    target: FormKey
    known: bool


@dataclass
class TransplantPlan:
    mode: str
    source: object                                   # Plugin
    roots: list
    copy: dict = field(default_factory=dict)         # FormKey -> RecordNode (source-own, to copy)
    references: list = field(default_factory=list)   # Reference (source-own targets)
    rebuild: dict = field(default_factory=dict)      # FormKey -> (signature, [referencing record keys])
    unverified: list = field(default_factory=list)   # Reference at unknown positions
    accepted: frozenset = frozenset()
    problems: list = field(default_factory=list)
    assets: object = None                            # AssetClosure (copy set)
    masters: list = field(default_factory=list)

    null_rebuild: bool = False                       # null known-position references to rebuild-only records

    @property
    def blocking(self) -> list[str]:
        out = list(self.problems)
        if self.mode == 'copy':
            for ref in self.unverified:
                if ref.signature not in self.accepted:
                    out.append(f'unverified reference {ref.source} {ref.signature}+{ref.offset} -> {ref.target}')
            for key, (sig, by) in self.rebuild.items():
                refs = [r for r in self.references if r.target == key]
                if self.null_rebuild and all(r.known for r in refs):
                    continue
                out.append(f'{sig} {key} is rebuild-only but referenced by {", ".join(map(str, by[:3]))}')
        return out

    @property
    def ok(self) -> bool:
        return not self.blocking

    def summary(self) -> str:
        lines = [f'{self.mode} transplant from {self.source.name}: {len(self.copy)} record(s) '
                 f'({", ".join(sorted({n.signature for n in self.copy.values()}))})']
        for key, node in sorted(self.copy.items()):
            lines.append(f'  copy {node.signature} {key} {node.editor_id or ""}')
        if self.rebuild:
            lines.append('  rebuild-only records referenced (not copied' +
                         ('; known-position references will be nulled' if self.null_rebuild else '') + '):')
            for key, (sig, by) in sorted(self.rebuild.items()):
                lines.append(f'    {sig} {key} <- {", ".join(map(str, by[:3]))}')
        if self.unverified:
            lines.append('  references at unverified positions:')
            for r in self.unverified[:20]:
                mark = 'accepted' if r.signature in self.accepted else 'BLOCKING'
                lines.append(f'    {r.source} {r.signature}+{r.offset} -> {r.target} [{mark}]')
        if self.assets is not None:
            cats = self.assets.by_category()
            lines.append('  assets: ' + ', '.join(f'{k} {len(v)}' for k, v in sorted(cats.items())) +
                         f'; external/unverified {len(self.assets.external)}; unresolved {len(self.assets.unresolved)}')
        lines.append(f'  masters needed: {", ".join(self.masters) or "-"}')
        for b in self.blocking:
            lines.append(f'  BLOCKING: {b}')
        return '\n'.join(lines)


def scan_references(node: RecordNode, plugin, own_raw: dict, known: KnownPositions, regions) -> list[Reference]:
    """Source-own FormIDs inside a record (every byte offset), marked known/unknown position."""
    codec = plugin.codec
    src_key = codec.try_decode(node.form_id)
    refs, inside = [], None
    for f in node.fields:
        top = inside is None and f.signature not in regions
        if inside is None and f.signature in regions:
            inside = regions[f.signature]
        elif inside is not None and f.signature == inside:
            inside = None
        data = f.data
        known_offsets = known.offsets_for(node.signature, f.signature, data, top)
        for off in range(0, len(data) - 3):
            value = struct.unpack_from('<I', data, off)[0]
            target = own_raw.get(value)
            if target is None:
                continue
            if value == node.form_id and off not in known_offsets:
                continue          # the record's own ID echoed in data is not a reference
            refs.append(Reference(src_key, f.signature, off, target, off in known_offsets))
    return refs


def plan_transplant(load_order, source, roots, mode: str = 'copy', accept_unverified=(),
                    asset_finder=None, null_rebuild_references: bool = False) -> TransplantPlan:
    if mode not in ('copy', 'reference'):
        raise ValueError("mode must be 'copy' or 'reference'")
    plugin = load_order.plugin(source) if isinstance(source, str) else source
    roots = [FormKey.parse(r) if isinstance(r, str) else r for r in roots]
    plan = TransplantPlan(mode, plugin, roots, accepted=frozenset(accept_unverified),
                          null_rebuild=null_rebuild_references)
    own = canonical_name(plugin.name)
    for r in roots:
        if r.plugin != own:
            plan.problems.append(f'{r} is not defined by {plugin.name}')
        elif plugin.get(r) is None:
            plan.problems.append(f'{r} not found in {plugin.name}')
    plan.masters = list(plugin.masters) + ([plugin.name] if mode == 'reference' else [])
    if mode == 'reference' or plan.problems:
        return plan

    adapter = plugin.adapter
    policy = adapter.transplant_policy
    known = KnownPositions(adapter)
    own_raw = {}
    for fid in plugin.index.form_ids:
        key = plugin.codec.try_decode(fid)
        if isinstance(key, FormKey) and key.plugin == own:
            own_raw[fid] = key
    schemas = adapter.schemas
    queue = list(roots)
    while queue:
        key = queue.pop(0)
        if key in plan.copy:
            continue
        node = plugin.get(key)
        if policy.get(node.signature, 'rebuild') != 'copy':
            if key in roots:
                plan.problems.append(f'{node.signature} {key}: record type is rebuild-only (policy)')
            continue
        plan.copy[key] = node
        schema = schemas.schemas.get(node.signature) if schemas else None
        regions = {r.start: r.end for r in schema.regions} if schema else {'BFCB': 'BFCE'}
        for ref in scan_references(node, plugin, own_raw, known, regions):
            plan.references.append(ref)
            if not ref.known:
                plan.unverified.append(ref)
            target_node = plugin.get(ref.target)
            if target_node is None or ref.target in plan.copy:
                continue
            if policy.get(target_node.signature, 'rebuild') == 'copy':
                queue.append(ref.target)
            else:
                entry = plan.rebuild.setdefault(ref.target, (target_node.signature, []))
                entry[1].append(ref.source)
    # localization boundary
    if plugin.is_localized:
        for key, node in plan.copy.items():
            present = {f.signature for f in node.fields} & adapter.lstring_signatures(node.signature)
            if present:
                plan.problems.append(f'{node.signature} {key}: localized fields {sorted(present)} '
                                     f'cannot be copied without string tables')
    if asset_finder is not None:
        plan.assets = asset_finder.for_records([plugin.typed(n) for n in plan.copy.values()])
    return plan


# -- apply ----------------------------------------------------------------------------------------

@dataclass
class TransplantResult:
    mapping: dict = field(default_factory=dict)     # old FormKey -> new FormKey
    records: list = field(default_factory=list)     # typed views in the target
    assets: dict = field(default_factory=dict)      # path -> bytes to pack into the target's archives
    remapped: int = 0
    dropped: int = 0                                # nulled list entries removed


def apply_transplant(plan: TransplantPlan, tx, editor_id_prefix: str = '', asset_index=None,
                     include_foreign: bool = False, include_loose: bool = False) -> TransplantResult:
    if not plan.ok:
        raise UnsupportedOperation('transplant', '; '.join(plan.blocking[:5]))
    target = tx.plugin
    result = TransplantResult()
    src = plan.source
    if plan.mode == 'reference':
        for name in plan.masters:
            kind = src.kind if canonical_name(name) == canonical_name(src.name) else \
                src.codec._lookup.get(canonical_name(name), ('full',))[0]
            tx.ensure_master(name, kind)
        result.mapping = {r: r for r in plan.roots}
        return result

    # master layout must address master records identically (raw values are kept)
    for name in src.masters:
        tx.ensure_master(name, src.codec._lookup[canonical_name(name)][0])
    mine, theirs = target.codec, src.codec
    for name in src.masters:
        if mine._lookup.get(canonical_name(name)) != theirs._lookup.get(canonical_name(name)):
            raise UnsupportedOperation('override.remap', f'{name} has a different master position in '
                                       f'{target.name} than in {src.name}')
    for key in sorted(plan.copy):
        result.mapping[key] = tx.allocator.allocate()
    raw_map = {theirs.encode(k): mine.encode(v) for k, v in result.mapping.items()}
    if plan.null_rebuild:
        raw_map.update({theirs.encode(k): 0 for k in plan.rebuild})
    positions = {}
    for ref in plan.references:
        if ref.known or ref.signature in plan.accepted:
            positions.setdefault(ref.source, []).append((ref.signature, ref.offset))
    edid_sig = target.spec.editor_id_signature
    for key, node in sorted(plan.copy.items()):
        fields = [Subrecord(f.signature, f.data) for f in node.fields]
        wanted = positions.get(key, [])
        for i, f in enumerate(fields):
            offs = sorted(o for s, o in wanted if s == f.signature)
            if not offs:
                continue
            data = bytearray(f.data)
            for off in offs:
                value = struct.unpack_from('<I', data, off)[0]
                if value in raw_map:
                    struct.pack_into('<I', data, off, raw_map[value])
                    result.remapped += 1
            fields[i] = Subrecord(f.signature, bytes(data))
        if plan.null_rebuild:
            # a nulled entry of a repeated single-FormID list (e.g. NPC_ PKID packages) is dropped
            counts = {}
            for f in fields:
                counts[f.signature] = counts.get(f.signature, 0) + 1
            kept = []
            for f, o in zip(fields, node.fields):
                if (len(f.data) == 4 and f.data == bytes(4) and o.data != bytes(4)
                        and counts[f.signature] > 1 and (f.signature, 0) in wanted):
                    result.dropped += 1
                    continue
                kept.append(f)
            fields = kept
        if editor_id_prefix and edid_sig:
            for i, f in enumerate(fields):
                if f.signature == edid_sig:
                    fields[i] = Subrecord(edid_sig, editor_id_prefix.encode() + f.data)
        new = RecordNode.new(target.spec, node.signature, mine.encode(result.mapping[key]), fields,
                             node.flags, node.header_tail)
        target.top_group(node.signature, create=True).append(new)
        result.records.append(target.typed(new))
    tx.log.append(f'transplant {len(plan.copy)} record(s) from {src.name}, {result.remapped} reference(s) '
                  f'remapped, {result.dropped} nulled list entr(ies) dropped')
    if plan.assets is not None and asset_index is not None:
        wanted_categories = {'owned'} | ({'foreign'} if include_foreign else set()) | ({'loose'} if include_loose else set())
        for path, ref in plan.assets.files.items():
            if ref.category in wanted_categories:
                result.assets[path] = asset_index.read(path)
    return result
