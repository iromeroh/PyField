"""Copy record data between plugins whose master layouts differ (`override.remap`).

Raw FormIDs mean "master #i of *this* file", so copying bytes from a plugin with another master list
silently retargets references (2026-10-16: a ship template copied from BlueprintShips-Starfield.esm into a
plugin mastered only on Starfield.esm pointed at the new plugin itself and hung the game).

    plan = plan_remap(source_plugin, node, target_plugin, load_order=lo)
    plan.blocking            # [] when every changed FormID sits at a known position
    fields = plan.apply()    # target-encoded subrecords (masters added to the target first)

Known positions come from transplant.KnownPositions (typed schemas, xEdit whole-FormID members, FormID
arrays, VMAD locator), per component region. Every value there is decoded through the source into a
FormKey and encoded for the target. At other positions a 4-byte value blocks the copy only when it would
change meaning: it decodes in the source to a FormKey, the target encodes that FormKey differently, and
(when a load order is given) a record with that key exists. Numbers and floats rarely satisfy all three; a
subrecord signature can still be accepted explicitly, which remaps its matching values too.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .core.formids import FormKey, canonical_name
from .core.subrecords import Subrecord
from .errors import UnsupportedOperation


@dataclass
class RemapValue:
    signature: str
    occurrence: int            # n-th subrecord with this signature in the record
    offset: int
    raw: int
    key: FormKey
    known: bool


@dataclass
class RemapPlan:
    source: object
    target: object
    node: object
    values: list = field(default_factory=list)        # RemapValue that must be re-encoded
    unverified: list = field(default_factory=list)    # RemapValue at unknown positions
    unresolved: list = field(default_factory=list)    # (signature, offset, raw) not decodable at known positions
    accepted: frozenset = frozenset()

    @property
    def masters(self) -> list:
        """Plugins the target must list as masters for the remapped values (in first-use order)."""
        out, own = [], canonical_name(self.target.name)
        for v in self.values + [u for u in self.unverified if u.signature in self.accepted]:
            if v.key.plugin != own and v.key.plugin not in out:
                out.append(v.key.plugin)
        return out

    @property
    def blocking(self) -> list[str]:
        out = [f'{s}+{o}: {r:08X} does not decode in {self.source.name}' for s, o, r in self.unresolved]
        out += [f'{v.signature}+{v.offset}: {v.raw:08X} = {v.key} at an unknown position (accept {v.signature} '
                f'to remap it)' for v in self.unverified if v.signature not in self.accepted]
        return out

    def apply(self, ensure_master=None) -> list[Subrecord]:
        """Target-encoded copy of the node's fields. ensure_master(name, kind) adds missing masters."""
        if self.blocking:
            raise UnsupportedOperation('override.remap', f'{self.node.signature} {self.node.form_id:08X} from '
                                       f'{self.source.name}: ' + '; '.join(self.blocking[:6]))
        if ensure_master is not None:
            for name in self.masters:
                ensure_master(_display(self.source, name), _kind(self.source, name))
        codec = self.target.codec
        changes = {}
        for v in self.values + [u for u in self.unverified if u.signature in self.accepted]:
            changes.setdefault((v.signature, v.occurrence), []).append(v)
        fields, seen = [], {}
        for f in self.node.fields:
            data = bytearray(f.data)
            index = seen.get(f.signature, 0)
            seen[f.signature] = index + 1
            for v in changes.get((f.signature, index), []):
                struct.pack_into('<I', data, v.offset, codec.encode(v.key))
            fields.append(Subrecord(f.signature, bytes(data)))
        return fields


def _display(source, canonical: str) -> str:
    for name in list(source.masters) + [source.name]:
        if canonical_name(name) == canonical:
            return name
    return canonical


def _kind(source, canonical: str) -> str:
    if canonical == canonical_name(source.name):
        return source.kind
    return source.codec._lookup[canonical][0]


def _is_text(data: bytes) -> bool:
    """Zero-terminated printable text (editor IDs, paths, names): never holds FormIDs."""
    if len(data) < 2 or data[-1] != 0:
        return False
    try:
        text = data[:-1].decode('utf-8')
    except UnicodeDecodeError:
        return False
    return all(c.isprintable() or c in '\t\r\n' for c in text)


def plan_remap(source, node, target, load_order=None, accept=(), known=None) -> RemapPlan:
    """What re-encoding `node` (a record of `source`) for `target` involves; nothing is changed."""
    from .transplant import KnownPositions
    known = known or KnownPositions(source.adapter)
    schemas = source.adapter.schemas
    schema = schemas.schemas.get(node.signature) if schemas else None
    regions = {r.start: r.end for r in schema.regions} if schema else {'BFCB': 'BFCE'}
    plan = RemapPlan(source, target, node, accepted=frozenset(accept))
    src, dst = source.codec, target.codec
    own_target = canonical_name(target.name)
    target_masters = {canonical_name(m) for m in target.masters} | {own_target}

    def changes_meaning(key: FormKey, raw: int) -> bool:
        if key.plugin not in target_masters:
            return True                                      # master will be added: encoding may differ
        return dst.encode(key) != raw

    inside, seen = None, {}
    for f in node.fields:
        top = inside is None and f.signature not in regions
        if inside is None and f.signature in regions:
            inside = regions[f.signature]
        elif inside is not None and f.signature == inside:
            inside = None
        index = seen.get(f.signature, 0)
        seen[f.signature] = index + 1
        data = f.data
        offsets = known.offsets_for(node.signature, f.signature, data, top)
        covered = set()
        for off in sorted(offsets):
            if off + 4 > len(data):
                continue
            covered.update(range(off, off + 4))
            raw = struct.unpack_from('<I', data, off)[0]
            if raw == 0:
                continue
            key = src.try_decode(raw)
            if not isinstance(key, FormKey):
                plan.unresolved.append((f.signature, off, raw))
            elif changes_meaning(key, raw):
                plan.values.append(RemapValue(f.signature, index, off, raw, key, True))
        if not offsets and (f.signature == 'EDID' or _is_text(data)):
            continue
        for off in range(0, len(data) - 3):
            if off in covered or off + 3 in covered:
                continue
            raw = struct.unpack_from('<I', data, off)[0]
            if raw == 0:
                continue
            key = src.try_decode(raw)
            if not isinstance(key, FormKey) or not changes_meaning(key, raw):
                continue
            if load_order is not None and load_order.resolve(key) is None:
                continue
            plan.unverified.append(RemapValue(f.signature, index, off, raw, key, False))
    return plan
