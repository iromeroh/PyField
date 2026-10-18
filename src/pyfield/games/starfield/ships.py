"""Starfield ships: blueprint parts (GBFM `Blueprint_Component`) and ships rebuilt from runtime captures.

Format (docs/formats/starfield-ship-blueprint.md): `BUO4` = 36-byte parts (u32 module GBFM FormID, u32 0,
3 × f32 position in metres, 3 × f32 rotation in radians, u32 part id), `BODM` = part count, one `BODC` colour
block per part (`BODC` u32 slot count, then per slot `BODS` palette name + `BODV` 40 bytes), `BLUF` flags,
`BOID` next part id.

A capture (sfse/PyFieldCapture, kind "ship") gives every spawned reference its part index
(ExtraBlueprintPartOriginData) and pack-in (ExtraSourcePackIn). Here each part gets:
  * origin and rotation: consensus of (ship-local reference transform) ∘ (pack-in-local transform)⁻¹ over the
    references whose base matches the pack-in cell's contents;
  * module: the GBFM whose `FLFM` is that pack-in (winning records of the captured load order). Stat variants
    share one pack-in and look identical; the pick is the highest level <= the player's level, then the plain
    (non-"Experimental") variant, then the editor ID, and is reported as `exact` / `level` / `tie`.
"""
from __future__ import annotations

import collections
import math
import re
import struct
from dataclasses import dataclass, field
from types import SimpleNamespace

from ...core.formids import FormKey
from ...core.subrecords import Subrecord
from ...errors import PyFieldError
from ...scene.capture import cell_references
from ...scene.transform import Transform

PART = struct.Struct('<II3f3fI')
CONVENTION = ('xyz', -1)
EXTRA_SOURCE_PACKIN = 0xD4
EXTRA_PART_ORIGIN = 0xDD
FRONTIER_TEMPLATE = FormKey('Starfield.esm', 0x00B730)     # Constellation_Frontier_Template: own blueprint
DROP_COMPONENTS = ('BGSFormLinkData_Component',)       # pre-built template cells (see build_ship)
DROP_FROM_TEMPLATE = {'NVNM', 'STRD'}                      # stored navmesh/traversals of the template's layout


@dataclass
class BlueprintPart:
    module: FormKey
    position: tuple
    rotation: tuple = (0.0, 0.0, 0.0)
    part_id: int = 0


def decode_buo4(data: bytes, codec) -> list[BlueprintPart]:
    if len(data) % PART.size:
        raise PyFieldError(f'BUO4 size {len(data)} is not a multiple of {PART.size}')
    out = []
    for i in range(0, len(data), PART.size):
        fid, _, x, y, z, rx, ry, rz, pid = PART.unpack_from(data, i)
        out.append(BlueprintPart(codec.decode(fid), (x, y, z), (rx, ry, rz), pid))
    return out


def encode_buo4(parts, codec) -> bytes:
    return b''.join(PART.pack(codec.encode(p.module), 0, *p.position, *p.rotation, p.part_id) for p in parts)


def blueprint_fields(parts, codec, flags: int = 4) -> list[Subrecord]:
    """Blueprint_Component body (between its BFCB/BFCE markers), default colours."""
    fields = [Subrecord('BUO4', encode_buo4(parts, codec)), Subrecord('BODM', struct.pack('<I', len(parts)))]
    fields += [Subrecord('BODC', struct.pack('<I', 0)) for _ in parts]
    fields += [Subrecord('BLUF', bytes([flags])),
               Subrecord('BOID', struct.pack('<I', max((p.part_id for p in parts), default=-1) + 1))]
    return fields


# -- parts from a runtime capture -------------------------------------------------------------------
@dataclass
class CapturedPart:
    index: int
    packin: FormKey
    origin: Transform
    support: int                       # references agreeing with the origin
    references: int
    module: FormKey | None = None
    module_editor_id: str = ''
    choice: str = ''                   # exact | level | tie | none
    alternatives: list = field(default_factory=list)


def _level(edid: str) -> int:
    m = re.search(r'lvl(\d+)', edid, re.I)
    return int(m.group(1)) if m else 0


def module_index(load_order) -> dict:
    """pack-in FormKey -> [(module FormKey, editor ID)] over the winning ship-module GBFMs."""
    index = collections.defaultdict(list)
    for view in load_order.records('GBFM'):
        flfm = view.node.get('FLFM')
        if flfm is None or len(flfm.data) < 4:
            continue
        packin = view.plugin.codec.try_decode(struct.unpack_from('<I', flfm.data, 0)[0])
        if isinstance(packin, FormKey):
            index[packin].append((view.form_key, view.editor_id or ''))
    return index


RETIRED = re.compile(r'(?i)^(xDoNotUse|zz|DEPRECATED|DELETED)|_DoNotUse|_OLD$')


def _clean_angle(a: float) -> float:
    a = math.remainder(a, 2 * math.pi)                   # (-pi, pi]
    return 0.0 if abs(a) < 1e-3 else round(a, 4)


def choose_module(candidates, player_level: int):
    candidates = [c for c in candidates if not RETIRED.search(c[1])] or candidates
    if not candidates:
        return None, 'none'
    if len(candidates) == 1:
        return candidates[0], 'exact'
    usable = [c for c in candidates if _level(c[1]) <= player_level] or candidates

    def rank(c):
        return (_level(c[1]), 'experimental' not in c[1].lower(), c[1])
    ranked = sorted(usable, key=rank, reverse=True)
    tie = len(ranked) > 1 and rank(ranked[0])[:2] == rank(ranked[1])[:2]
    return ranked[0], 'tie' if tie else 'level'


def parts_from_capture(capture, raw: dict, load_order, player_level: int, modules=None) -> list[CapturedPart]:
    """Ship parts of a `pyfield-capture` ship capture (RuntimeCapture + its raw JSON)."""
    if capture.anchor is None:
        raise PyFieldError('capture has no anchor (ship reference)')
    a = capture.anchor
    ship = Transform(a.position, a.rotation, 1.0, CONVENTION)
    spawned = collections.defaultdict(list)
    for d in raw['refs']:
        extras = {x[0]: x for x in d.get('extras', []) if isinstance(x, list)}
        src, origin = extras.get(EXTRA_SOURCE_PACKIN), extras.get(EXTRA_PART_ORIGIN)
        if not src or not origin or len(src) < 3 or not d.get('base'):
            continue
        index = int.from_bytes(bytes.fromhex(origin[1][:8]), 'little')
        packin = capture.form_key(int(src[2], 16))
        base = capture.form_key(int(d['base']['form_id'], 16))
        if packin is None or base is None:
            continue
        world = Transform(tuple(d['pos']), tuple(d['rot']), d.get('scale') or 1.0, CONVENTION)
        spawned[index].append((packin, base, world.relative_to(ship)))

    modules = modules if modules is not None else module_index(load_order)
    contents_cache = {}

    def contents(packin):
        if packin not in contents_cache:
            view = load_order.resolve(packin)
            cnam = view.node.get('CNAM') if view is not None else None
            cell = view.plugin.codec.try_decode(struct.unpack_from('<I', cnam.data, 0)[0]) if cnam else None
            refs = cell_references(load_order, cell) if isinstance(cell, FormKey) else []
            contents_cache[packin] = [(r.base, Transform((r.placement.position.x, r.placement.position.y,
                                                          r.placement.position.z),
                                                         (r.placement.rotation.x, r.placement.rotation.y,
                                                          r.placement.rotation.z), r.scale or 1.0, CONVENTION))
                                      for r in refs]
        return contents_cache[packin]

    parts = []
    for index in sorted(spawned):
        refs = spawned[index]
        packin = refs[0][0]
        votes, samples = collections.Counter(), {}
        for _, base, local in refs:
            for cbase, inner in contents(packin):
                if cbase != base:
                    continue
                t = local.compose(inner.inverse())
                key = tuple(round(v, 1) for v in t.position) + tuple(round(v, 2) for v in t.rotation)
                votes[key] += 1
                samples.setdefault(key, t)
        if not votes:
            continue
        key, support = votes.most_common(1)[0]
        t = samples[key]
        origin = Transform(tuple(round(v, 3) for v in t.position), tuple(_clean_angle(v) for v in t.rotation), 1.0,
                           CONVENTION)
        part = CapturedPart(index, packin, origin, support, len(refs))
        cands = modules.get(packin, [])
        best, part.choice = choose_module(cands, player_level)
        if best is not None:
            part.module, part.module_editor_id = best
        part.alternatives = [e for _, e in cands if best is None or e != best[1]]
        parts.append(part)
    return parts


def blueprint_from_parts(parts) -> list[BlueprintPart]:
    return [BlueprintPart(p.module, p.origin.position, p.origin.rotation, i)
            for i, p in enumerate(p for p in parts if p.module is not None)]


# -- ship record ------------------------------------------------------------------------------------
def build_ship(tx, template_view, parts, editor_id: str, name: str, drop=DROP_FROM_TEMPLATE, load_order=None,
               drop_components=DROP_COMPONENTS):
    """New GBFM in tx's plugin: the template's components with this blueprint and name.

    The template may come from any plugin: its FormIDs are re-encoded for the target (remap.py; an
    override from e.g. BlueprintShips-Starfield.esm numbers its own forms 01xxxxxx, which copied raw
    pointed at the new plugin and hung PlaceShipAtMe on 2026-10-16). Masters are added before the record
    is created. parts=None keeps the template's own blueprint; `drop` lists template subrecords left out
    (stored navmesh/traversals by default: they describe the template's layout). `drop_components` removes whole
    template components: BGSFormLinkData_Component links quest templates to pre-built exterior/interior cells
    (SpaceshipLinkedExterior/Interior), which the game shows instead of the blueprint (2026-10-18: a rebuilt
    ship looked exactly like the Frontier in the world while the ship editor showed its own blueprint).
    """
    from ...remap import plan_remap
    plugin = tx.plugin
    source = template_view.plugin
    fields, component = [], None
    for f in template_view.node.fields:
        if f.signature == 'BFCB':
            component = f.data.rstrip(bytes(1)).decode('ascii', 'replace')
        skip = component in drop_components
        if f.signature == 'BFCE':
            component = None
        if not skip and f.signature != 'EDID' and f.signature not in drop:
            fields.append(f)
    kept = SimpleNamespace(signature='GBFM', form_id=template_view.node.form_id, fields=fields)
    template_fields = plan_remap(source, kept, plugin, load_order=load_order).apply(tx.ensure_master)
    for key in sorted({p.module for p in parts or ()}, key=str):
        if key.plugin != plugin.name.lower():
            name_of = load_order.plugin(key.plugin).name if load_order is not None else key.plugin
            tx.ensure_master(name_of, load_order.plugin(key.plugin).kind if load_order is not None else 'full')
    view = tx.new_record('GBFM', editor_id)
    view.node.header[20:24] = template_view.node.header[20:24]          # form version (+ trailing u16)
    fields, component = [view.node.fields[0]], None
    for f in template_fields:
        if f.signature == 'BFCB':
            component = f.data.rstrip(bytes(1)).decode('ascii', 'replace')
        if parts is not None and component == 'Blueprint_Component' and f.signature not in ('BFCB', 'BFCE'):
            continue
        if parts is not None and f.signature == 'BFCE' and component == 'Blueprint_Component':
            fields += blueprint_fields(parts, plugin.codec)
        if f.signature == 'FULL' and component == 'TESFullName_Component':
            f = Subrecord('FULL', name.encode('utf-8') + bytes(1))
        if f.signature == 'BFCE':
            component = None
        fields.append(Subrecord(f.signature, bytes(f.data)))
    view.node.fields = fields
    return view
