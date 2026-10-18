"""Outpost/POI transplant: a runtime capture rebuilt as a fixed location with its own fitted terrain.

    plan = plan_outpost(capture, load_order)                     # classify, fit terrain, apply policies
    with plugin.transaction() as tx:
        tx.strings = StringTables(...)
        built = build_outpost(tx, load_order, plan, site, lock_dir)
    pack({built.overlay.terrain_path: built.terrain.to_bytes()}, ...)

Steps (docs/formats/starfield-planet-locations.md, landscape/fit.py):
1. select the captured references (placed, not deleted, not far below the outpost: hidden storage) and
   resolve their bases in the capture's load order; save-created bases cannot be copied and are reported;
2. classify each for the ground fit: natural (rocks, flora), structure (physical objects with bounds), or
   none (lights, sounds, markers, volumes: placed, but give no ground samples);
3. recentre on the overlay block, fit the terrain, then apply each object's policy: `terrain` (the ground
   adapted to it), `snap` (moved onto the fitted ground: grounded loose objects), `keep` (as captured);
4. build the overlay location from a template pinned on the target planet (biome, ground textures) and
   place every reference in its exterior cell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import statistics
import struct

from ...core.formids import FormKey
from ...landscape.fit import (KEEP, NATURAL, SNAP, STRUCTURE, SUPPORT, TERRAIN, fit_terrain, ground_samples,
                              snap_to_ground)
from ...scene.spatial import local_bounds
from ...scene.transform import Transform
from .overlay import (APOLLO_WORLD, OverlaySite, OverlayTemplate, blank_terrain, build_overlay, origin_cell,
                      place_map_marker, template_for_planet)

PHYSICAL = {'STAT', 'FLOR', 'TREE', 'FURN', 'CONT', 'DOOR', 'PKIN', 'ACTI', 'MSTT', 'BNDS'}
NATURAL_NAME = re.compile(r'rock|boulder|crater|flora|plant|tree|bush|grass|shrub|cliff|debris|stone|coral|fung|mushroom', re.I)
SUPPORT_NAME = re.compile(r'Foundation|Pillar|Support|Leg|Stilt', re.I)   # columns built down to the ground
NO_GROUND_NAME = re.compile(r'^(LP_|LGT_)|Marker|Dummy|Trigger|Volume|Light', re.I)


@dataclass
class Rules:
    """Classification and policy rules; override fields to tune a transplant."""
    natural_name: re.Pattern = NATURAL_NAME
    support_name: re.Pattern = SUPPORT_NAME
    ship_name: re.Pattern = re.compile(r'^(ShipPI_|SMOD_|LMOD_|PackInShip)')   # landed ship modules
    include_ships: bool = False               # WIP (2026-10-18): a landed ship copied as static modules falls apart
                                              # (havok pieces); copy ships with the ship pipeline + GiveShip instead
    pad_function_name: re.Pattern = re.compile(r'^(ShipLandingMarker|landingZoneTrigger|OutpostShipbuilderActivator)', re.I)
    no_ground_name: re.Pattern = NO_GROUND_NAME
    max_structure_size: float = 50.0          # m; larger bounds are volumes, not objects
    snap_natural_below: float = 3.0           # m footprint diagonal: rocks/flora that snap (tilted to the slope)
    snap_loose_below: float = 1.5             # m: small grounded objects that snap (no tilt)
    snap_outlier_below: float = 4.0           # m: outliers this small snap, larger ones are kept and reported
    snap_max: float = 1.5                     # m: a snap moving an object farther keeps it instead (attached)
    segment_name: str = r'_Mid'               # repeatable column segments (OutpostHarvester..._Foundation_Mid01)
    column_embed: float = 0.3                 # m an extended column reaches into the ground
    max_segments: int = 12
    far_below: float = 100.0                  # m below/above the outpost's median height: hidden storage
    policy: dict = field(default_factory=dict)   # editor-ID regex -> policy, checked first
    # how closely the ground follows the objects (owner 2026-10-17: stricter, steeper slopes are acceptable)
    natural_band: tuple = (0.25, 0.5)         # m below/above a rock or plant origin that still fits
    fit: dict = field(default_factory=lambda: {'fine_sigma': 2.0, 'max_slope_deg': 50.0, 'outlier_gap': 3.0})


@dataclass
class PlannedRef:
    ref: object                               # RuntimeRef
    base: object                              # FormKey
    view: object                              # base record view
    world: Transform                          # as captured (landing-world frame)
    placed: Transform | None = None           # in the overlay frame, after the policy
    ground: str | None = None                 # NATURAL / STRUCTURE / SUPPORT / None (no samples)
    policy: str = TERRAIN
    extension: int = 0                        # > 0: added column segment (copy k below the column's lowest)
    ship: bool = False                        # piece of a landed ship copied as decoration: kept as captured

    @property
    def node_id(self) -> str:
        return f'r{self.ref.form_id:08X}' + (f'x{self.extension}' if self.extension else '')

    @property
    def label(self) -> str:
        return f'{self.view.editor_id or self.base} {self.ref.form_id:08X}'


@dataclass
class OutpostPlan:
    name: str
    refs: list = field(default_factory=list)          # PlannedRef
    skipped: dict = field(default_factory=dict)       # reason -> [labels]
    offset: tuple = (0.0, 0.0)                         # added to captured x, y
    cells: int = 3
    fit: object = None
    extended: int = 0                                  # column segments added down to the ground
    capture: object = None                             # RuntimeCapture the plan was made from
    policies: dict = field(default_factory=dict)
    sea_level: float | None = None            # island: water height in the plan's frame

    def summary(self) -> dict:
        fit = self.fit.report(limit=8) if self.fit else {}
        return {'name': self.name, 'refs': len(self.refs), 'cells': self.cells, 'column_segments_added': self.extended,
                'offset': [round(v, 2) for v in self.offset], 'policies': self.policies,
                'skipped': {k: len(v) for k, v in self.skipped.items()},
                'fit': {k: fit[k] for k in ('samples', 'within_interval', 'floating', 'buried', 'outlier_objects', 'attached_objects', 'embedded_objects',
                                            'p95_violation_m', 'max_violation_m') if k in fit},
                'outliers': fit.get('outliers', [])}


def _diag(box, scale) -> float:
    return math.hypot(box.max[0] - box.min[0], box.max[1] - box.min[1]) * scale if box else 0.0


def _ground_kind(view, rules: Rules, box, scale):
    ed, sig = view.editor_id or '', view.signature
    if sig not in PHYSICAL or rules.no_ground_name.search(ed):
        return None
    if sig in ('FLOR', 'TREE') or (sig == 'STAT' and rules.natural_name.search(ed)):
        return NATURAL
    if box is None or max(b - a for a, b in zip(box.min, box.max)) * scale > rules.max_structure_size:
        return None
    if rules.support_name.search(ed) and box.min[2] * scale < -0.5:
        return SUPPORT
    return STRUCTURE


def plan_outpost(capture, load_order, rules: Rules | None = None, cells: int | None = None,
                 margin: float = 50.0, include_actors: bool = False) -> OutpostPlan:
    """Select, classify, recentre and fit (see module doc). `cells` defaults to the smallest block that holds
    the footprint plus `margin` metres on every side."""
    rules = rules or Rules()
    plan = OutpostPlan(capture.name)
    plan.capture = capture
    placeable = load_order.plugins[0].adapter.placeable_types
    refs = capture.select()
    z_med = statistics.median(r.position[2] for r in refs) if refs else 0.0

    def skip(reason, label):
        plan.skipped.setdefault(reason, []).append(label)
    for r in refs:
        label = f'{(r.base.editor_id if r.base else "") or "?"} {r.form_id:08X}'
        if abs(r.position[2] - z_med) > rules.far_below:
            skip('far from the outpost (storage)', label)
            continue
        key = capture.form_key(r.base.form_id) if r.base else None
        if key is None:
            skip('base created in save' if r.base and r.base.form_id >> 24 == 0xFF else 'base not resolvable', label)
            continue
        view = load_order.resolve(key)
        if view is None:
            skip('base not in load order', f'{key} {r.form_id:08X}')
            continue
        if view.signature not in placeable or view.signature == 'GBFM':
            skip(f'not placeable ({view.signature})', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        if not rules.include_ships and 'workshop_items' not in r.sections and rules.ship_name.search(view.editor_id or ''):
            skip('part of a landed ship', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        if rules.include_ships and rules.pad_function_name.search(view.editor_id or ''):
            # the copied ship is decoration standing on the pad: the pad must not take ships
            skip('landing function (pad holds the decorative ship)', f'{view.editor_id} {r.form_id:08X}')
            continue
        if rules.include_ships and view.signature == 'PKIN' and rules.ship_name.search(view.editor_id or ''):
            skip('ship pack-in (its pieces are copied instead)', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        packin = getattr(r, 'source_packin', None)
        ship_piece = False
        if packin and rules.include_ships:
            src = capture.form_key(packin)
            src_view = load_order.resolve(src) if src else None
            if src_view is not None and rules.ship_name.search(src_view.editor_id or ''):
                packin = None                   # a ship piece: kept as a static copy (decorative ship)
                ship_piece = True
                if (view.editor_id or '').startswith('SMOD_FX'):
                    skip('ship engine effect', f'{view.editor_id} {r.form_id:08X}')
                    continue
        if not ship_piece and set(r.sections) <= {'outpost_cells'} and view.signature in ('MSTT', 'BMMO'):
            skip('effect or vehicle near the outpost (not part of it)', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        if 'workshop_items' not in r.sections and packin:
            # spawned by a pack-in (ship module parts, pad crews, pack-in contents): the copied pack-in respawns them
            skip('spawned by a pack-in (ship, pad crew)', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        if placeable[view.signature] == 'ACHR' and not include_actors:
            skip('actor (crew, creatures: not copied)', f'{view.editor_id or key} {r.form_id:08X}')
            continue
        world = Transform(tuple(r.position), tuple(r.rotation), r.scale or 1.0)
        plan.refs.append(PlannedRef(r, key, view, world, ship=ship_piece))
    if not plan.refs:
        return plan
    xs = [p.world.position[0] for p in plan.refs]
    ys = [p.world.position[1] for p in plan.refs]
    size = max(max(xs) - min(xs), max(ys) - min(ys)) + 2 * margin
    plan.cells = cells or max(1, math.ceil(size / 100.0))
    ox, oy = origin_cell(plan.cells)
    centre = ((ox + plan.cells / 2) * 100.0, (oy + plan.cells / 2) * 100.0)
    plan.offset = (centre[0] - (min(xs) + max(xs)) / 2, centre[1] - (min(ys) + max(ys)) / 2)

    items, boxes, carriers = [], {}, []
    for p in plan.refs:
        x, y, z = p.world.position
        p.placed = Transform((x + plan.offset[0], y + plan.offset[1], z), p.world.rotation, p.world.scale)
        box = local_bounds(p.view)
        if box is not None and all(abs(a - b) < 1e-6 for a, b in zip(box.min, box.max)):
            box = None
        boxes[id(p)] = box
        p.ground = None if p.ship else _ground_kind(p.view, rules, box, p.world.scale)
        if p.ground is not None:
            items.append((p.placed, box, p.ground, id(p)))
        elif box is not None and p.view.signature in PHYSICAL and not rules.no_ground_name.search(p.view.editor_id or ''):
            carriers.append((p.placed, box))          # too large to sample (landing pads) but carries objects
    x0, y0 = ox * 100.0, oy * 100.0
    extent = (x0, y0, x0 + plan.cells * 100.0, y0 + plan.cells * 100.0)

    def fit_once(with_supports=True):
        use = items if with_supports else [i for i in items if i[2] != SUPPORT]
        samples = ground_samples(use, natural_band=rules.natural_band, carriers=carriers)
        return fit_terrain(samples, extent, border=min(30.0, margin * 0.6), **rules.fit)
    # columns are measured against the ground without their own pull, then extended down to it
    added = _extend_columns(plan, boxes, fit_once(with_supports=False).surface, rules)
    fit = None
    for p in added:                             # extended columns reach the ground: fit with them
        items.append((p.placed, boxes[id(p)], SUPPORT, id(p)))
    fit = fit_once()
    plan.extended = len(added)
    plan.fit = fit
    attached = {fit.samples[i].ref for i in fit.attached}
    grounded = {s.ref for s in fit.samples if s.kind in (NATURAL, STRUCTURE)} - attached
    outliers = {fit.samples[i].ref for i in fit.outliers}
    counts = {}
    for p in plan.refs:
        box, d = boxes[id(p)], _diag(boxes[id(p)], p.world.scale)
        ed = p.view.editor_id or ''
        forced = next((pol for pattern, pol in rules.policy.items() if re.search(pattern, ed)), None)
        if forced:
            p.policy = forced
        elif id(p) not in grounded:
            p.policy = KEEP
        elif p.extension or p.ship:
            p.policy = KEEP
        elif p.ground == NATURAL and d < rules.snap_natural_below:
            p.policy = SNAP
        elif box is not None and d < rules.snap_loose_below:
            p.policy = SNAP
        elif id(p) in outliers:
            p.policy = SNAP if d < rules.snap_outlier_below else KEEP
        else:
            p.policy = TERRAIN
        if p.policy == SNAP:
            moved = snap_to_ground(p.placed, box, fit.surface, align=p.ground == NATURAL)
            if abs(moved.position[2] - p.placed.position[2]) <= rules.snap_max:
                p.placed = moved
            else:                               # far from the ground: attached to something (stair landing)
                p.policy = KEEP
                plan.skipped.setdefault('not snapped (too far from the ground: attached)', []).append(p.label)
        counts[p.policy] = counts.get(p.policy, 0) + 1
    plan.policies = counts
    # outlier labels for the report
    for s in fit.samples:
        if not isinstance(s.ref, str):
            match = next((p for p in plan.refs if id(p) == s.ref), None)
            s.ref = match.label if match else s.ref
    return plan


def _extend_columns(plan: OutpostPlan, boxes: dict, surface, rules: Rules) -> list:
    """Copies of a column's repeatable segment (`..._Mid..`) below it until it reaches the fitted ground, as
    the game builds outpost foundations; returns the added PlannedRefs (also appended to plan.refs)."""
    columns = []
    for p in plan.refs:
        if p.ground != SUPPORT or boxes.get(id(p)) is None:
            continue
        x, y = p.placed.position[:2]
        for col in columns:
            if math.hypot(col[0].placed.position[0] - x, col[0].placed.position[1] - y) <= 1.5:
                col.append(p)
                break
        else:
            columns.append([p])
    added = []
    for col in columns:
        def bottom(p):
            return p.placed.position[2] + boxes[id(p)].min[2] * p.placed.scale
        lowest = min(col, key=bottom)
        if not re.search(rules.segment_name, lowest.view.editor_id or ''):
            continue
        box = boxes[id(lowest)]
        seg = (box.max[2] - box.min[2]) * lowest.placed.scale
        x, y, z = lowest.placed.position
        gap = bottom(lowest) - (surface.at(x, y) - rules.column_embed)
        if seg < 0.2 or gap <= rules.column_embed:
            continue
        for k in range(1, min(rules.max_segments, math.ceil(gap / seg)) + 1):
            t = Transform((x, y, z - k * seg), lowest.placed.rotation, lowest.placed.scale, lowest.placed.convention)
            copy = PlannedRef(lowest.ref, lowest.base, lowest.view, lowest.world, t, SUPPORT, KEEP, extension=k)
            boxes[id(copy)] = box
            added.append(copy)
    plan.refs.extend(added)
    return added


def _restore_links(plan: OutpostPlan, build, load_order) -> dict:
    """Captured links between copied references (pack-in groups, mod frameworks) as scene links, per node id.

    Targets outside the copy are dropped, except the original workshop (the capture anchor), which maps to the home
    activator when there is one. Keywords resolve through the captured load order. Report in build.links.
    """
    from ...scene.graph import Link
    capture = plan.capture
    by_runtime = {p.ref.form_id: p.node_id for p in plan.refs if not p.extension}
    anchor = capture.anchor.form_id if capture is not None and capture.anchor is not None else None
    out, stats = {}, {'restored': 0, 'to_home': 0, 'dropped_target_not_copied': 0, 'dropped_keyword': 0}
    for p in plan.refs:
        if p.extension:
            continue
        for kw, target in getattr(p.ref, 'linked_refs', ()):
            keyword = capture.form_key(kw) if kw else None
            if kw and (keyword is None or load_order.resolve(keyword) is None):
                stats['dropped_keyword'] += 1
                continue
            if target in by_runtime:
                out.setdefault(p.node_id, []).append(Link(by_runtime[target], keyword))
                stats['restored'] += 1
            elif target == anchor and build.home is not None:
                if keyword != KW_WORKSHOP_ITEM:                  # the workshop-item link is added separately
                    out.setdefault(p.node_id, []).append(Link(str(build.home.activator), keyword))
                stats['to_home'] += 1
            else:
                stats['dropped_target_not_copied'] += 1
    build.links = stats
    return out


def fitted_terrain(plan: OutpostPlan, template_btd):
    """The template's terrain file (textures, size) with the plan's fitted heights."""
    terrain = blank_terrain(template_btd)
    if terrain.cells != (plan.cells, plan.cells):
        raise ValueError(f'template terrain is {terrain.cells} cells, the plan needs {plan.cells}')
    hf = terrain.heightfield(origin_cell(plan.cells))
    surface = plan.fit.surface
    for k in range(len(hf.values)):
        hf.values[k] = surface.at(*hf.to_world(k % hf.width, k // hf.width))
    terrain.apply_heightfield(hf)
    return terrain


def landing_spot(plan: OutpostPlan, clearance: float = 40.0, edge: float = 35.0):
    """The point closest to the outpost with at least `clearance` m to every placed object (and `edge` m from
    the block border); the most open point when none qualifies. Returns ((x, y), clearance)."""
    ox, oy = origin_cell(plan.cells)
    x0, y0, size = ox * 100.0, oy * 100.0, plan.cells * 100.0
    pts = [p.placed.position[:2] for p in plan.refs]
    cx, cy = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
    best, best_key, step = None, None, 5.0
    y = y0 + edge
    while y <= y0 + size - edge:
        x = x0 + edge
        while x <= x0 + size - edge:
            d = min(math.hypot(x - px, y - py) for px, py in pts)
            surface = plan.fit.surface if plan.fit else None
            dry = plan.sea_level is None or surface is None or (
                surface.at(x, y) > plan.sea_level + 1.0 and surface.slope_deg(x, y) < 15.0)
            key = (0, math.hypot(x - cx, y - cy)) if d >= clearance and dry else (1 if dry else 2, -d)
            if best_key is None or key < best_key:
                best, best_key = ((x, y), d), key
            x += step
        y += step
    return best


# Player-home workshop (the builder menu without an outpost), as vanilla homes and Creations wire it
# (Dream Home LC171StarterHome, sfta05 Seokguh villa): the house activator, a power generator marker linked
# with WorkshopItemKeyword, and EmptyTrigger box primitives linked with WorkshopLinkedPrimitive (build area).
HOUSE_ACTIVATOR = FormKey('Starfield.esm', 0x024DC7)     # OutpostPlayerHouseActivator
POWER_MARKER = FormKey('Starfield.esm', 0x08C54A)        # OutpostPowerGeneratorMarker
EMPTY_TRIGGER = FormKey('Starfield.esm', 0x00573F)
KW_WORKSHOP_ITEM = FormKey('Starfield.esm', 0x054BA6)    # WorkshopItemKeyword
KW_LINKED_PRIMITIVE = FormKey('Starfield.esm', 0x0B91E6)  # WorkshopLinkedPrimitive


@dataclass
class HomeWorkshop:
    activator: FormKey
    power: FormKey
    primitives: list
    linked_items: int = 0


def add_home_workshop(tx, overlay, plan: OutpostPlan, margin: float = 15.0, height: float = 60.0,
                      enabled: bool = True) -> HomeWorkshop:
    """House activator + power marker + one build-area box over the outpost footprint, in the worldspace's
    persistent cell. `enabled=False` leaves the activator disabled for a purchase quest to enable."""
    from ...core.nodes import RecordNode
    from ...core.subrecords import Subrecord
    from ...scene.compile import _children_group
    plugin = tx.plugin
    group = _children_group(plugin, plugin.get(overlay.persistent_cell), 8)
    tail = plugin.adapter.header_tail()
    surface = plan.fit.surface
    xs = [p.placed.position[0] for p in plan.refs]
    ys = [p.placed.position[1] for p in plan.refs]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    ground = surface.at(cx, cy)

    def ref(base, pos, flags=0x400, extra=()):
        key = tx.allocator.allocate()
        fields = [Subrecord('NAME', plugin.codec.encode(base).to_bytes(4, 'little')), *extra,
                  Subrecord('DATA', struct.pack('<6f', *pos, 0.0, 0.0, 0.0))]
        group.append(RecordNode.new(plugin.spec, 'REFR', plugin.codec.encode(key), fields, flags, tail))
        return key

    def link(keyword, target):
        return Subrecord('XLKR', plugin.codec.encode(keyword).to_bytes(4, 'little') +
                         plugin.codec.encode(target).to_bytes(4, 'little'))
    activator = ref(HOUSE_ACTIVATOR, (cx, cy, ground + 0.5), 0x400 | (0 if enabled else 0x800))
    power = ref(POWER_MARKER, (cx, cy + 2.0, ground + 0.5), extra=[link(KW_WORKSHOP_ITEM, activator)])
    half = ((max(xs) - min(xs)) / 2 + margin, (max(ys) - min(ys)) / 2 + margin, height / 2)
    xprm = struct.pack('<3f3ffI', *half, 0.6157, 0.2706, 0.7294, 0.3, 1)          # box, editor colour as vanilla
    box = ref(EMPTY_TRIGGER, (cx, cy, ground + half[2] - 10.0),
              extra=[Subrecord('XPRM', xprm), link(KW_LINKED_PRIMITIVE, activator)])
    return HomeWorkshop(activator, power, [box])


@dataclass
class OutpostBuild:
    overlay: object
    terrain: object
    scenes: dict = field(default_factory=dict)          # cell grid -> CompileResult
    landing: tuple = ()
    landing_clearance: float = 0.0
    home: object = None                                  # HomeWorkshop when built as a player home
    links: dict = field(default_factory=dict)             # captured links restored / dropped


def build_outpost(tx, load_order, plan: OutpostPlan, site: OverlaySite, assets, lock_dir, biome=None,
                  home: bool = False, link_sections=('workshop_items',)) -> OutpostBuild:
    """Overlay location + fitted terrain + every planned reference, one scene per exterior cell."""
    from pathlib import Path
    from ...scene import ExistingCell, Scene, SceneLock, SceneNode, compile_scene
    from ...scene.graph import Link
    from .btd import BtdFile
    planet = load_order.resolve(site.planet)
    look = template_for_planet(load_order, planet, plan.cells)       # biome, surface location, ground textures
    if look.cells != plan.cells:
        raise ValueError(f'template {look.world.editor_id} has {look.cells} cells, the plan {plan.cells}:'
                         f' plan with cells={look.cells}')
    template = OverlayTemplate.from_world(load_order, APOLLO_WORLD)  # record structure verified in game
    terrain = fitted_terrain(plan, BtdFile.parse(assets.read(look.terrain_path)))
    site.cells = plan.cells
    # every master first, in load order: adding one after own records exist would shift their FormIDs
    needed = {p.view.plugin.name.lower() for p in plan.refs}
    needed |= {v.plugin.name.lower() for v in (planet, template.world, template.location, template.block,
                                               look.world, look.location)}
    for source in load_order.plugins:
        if source.name.lower() in needed:
            for m in source.masters:
                tx.ensure_master(load_order.plugin(m).name, load_order.plugin(m).kind)
            tx.ensure_master(source.name, source.kind)
    overlay = build_overlay(tx, load_order, site, terrain, template=template, look=look,
                            water_height=plan.sea_level, biome=biome)
    build = OutpostBuild(overlay, terrain)
    (lx, ly), build.landing_clearance = landing_spot(plan)
    surface = plan.fit.surface
    place_map_marker(tx, load_order, overlay, site.name, marker_at=(lx + 6.0, ly, surface.at(lx + 6.0, ly) + 0.1),
                     landing_at=(lx, ly, surface.at(lx, ly)))
    build.landing = (lx, ly)
    if home:
        build.home = add_home_workshop(tx, overlay, plan)
    restored = _restore_links(plan, build, load_order)
    by_cell = {}
    for p in plan.refs:
        x, y = p.placed.position[:2]
        by_cell.setdefault((math.floor(x / 100.0), math.floor(y / 100.0)), []).append(p)
    # FormIDs up front: restored links cross exterior cells (one scene per cell), so they name FormKeys
    keys = {p.node_id: tx.allocator.allocate() for p in plan.refs}
    for node_id, links in restored.items():
        for l in links:
            if l.target in keys:
                l.target = str(keys[l.target])
    for grid, refs in sorted(by_cell.items()):
        if grid not in overlay.cells:
            raise ValueError(f'{len(refs)} references fall outside the block in cell {grid}')
        scene = Scene(f'{plan.name}_{grid[0]}_{grid[1]}')
        for p in refs:
            links = []
            if build.home is not None and set(getattr(p.ref, 'sections', ()) or ()) & set(link_sections):
                links = [Link(str(build.home.activator), KW_WORKSHOP_ITEM)]      # builder item, powered by the home
                build.home.linked_items += 1
            links += restored.get(p.node_id, [])
            scene.add(SceneNode(p.node_id, p.base, p.placed, disabled=p.ref.disabled, links=links))
        lock = SceneLock(Path(lock_dir) / f'{scene.name}.lock.json', scene.name)
        for p in refs:
            lock.nodes[p.node_id] = str(keys[p.node_id])
        build.scenes[grid] = compile_scene(scene, tx, load_order, ExistingCell(overlay.cells[grid]), lock)
    return build


def make_island(plan: OutpostPlan, sea_level: float, freeboard: float = 2.0, shore: float = 60.0,
                pad: float = 8.0, low_quantile: float = 0.1) -> dict:
    """Lift the outpost and its ground above `sea_level` (metres, in the plan's frame) as an island.

    The lift brings the low ground (`low_quantile` of the fitted ground under the outpost's footprint,
    bounding box + `pad` m) to
    `freeboard` m above the sea; it fades to zero over `shore` m outside the footprint (smoothstep), so the
    ground slopes back to the original seabed before the block border. Measure the sea level in game: a
    fixed location is set onto the local surface, so `player.getpos z` at the water surface minus the game
    height of a placed reference plus its plugin height (Selene on Nesoi: -176.5 - (-196.4) + 0.7 = 20.6).
    """
    xs = [p.placed.position[0] for p in plan.refs]
    ys = [p.placed.position[1] for p in plan.refs]
    box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    hf = plan.fit.surface
    under = [hf.values[k] for k in range(len(hf.values))
             if box[0] <= hf.origin[0] + (k % hf.width) * hf.spacing <= box[2]
             and box[1] <= hf.origin[1] + (k // hf.width) * hf.spacing <= box[3]]
    under.sort()
    base = under[int(len(under) * low_quantile)]              # isolated pits (pillar footings) do not drive it
    lift = max(0.0, sea_level + freeboard - base)

    def weight(x, y):
        dx = max(box[0] - x, 0.0, x - box[2])
        dy = max(box[1] - y, 0.0, y - box[3])
        t = min(1.0, math.hypot(dx, dy) / shore)
        return 1.0 - t * t * (3 - 2 * t)
    for k in range(len(hf.values)):
        x, y = hf.to_world(k % hf.width, k // hf.width)
        hf.values[k] += lift * weight(x, y)
    for p in plan.refs:
        x, y, z = p.placed.position
        p.placed = Transform((x, y, z + lift), p.placed.rotation, p.placed.scale, p.placed.convention)
    plan.sea_level = sea_level
    ox, oy = origin_cell(plan.cells)
    edge = min(box[0] - ox * 100.0, box[1] - oy * 100.0, (ox + plan.cells) * 100.0 - box[2],
               (oy + plan.cells) * 100.0 - box[3])
    wet = [p.label for p in plan.refs if p.policy != KEEP and hf.at(*p.placed.position[:2]) < sea_level]
    return {'lift_m': round(lift, 2), 'sea_level': sea_level, 'footprint': [round(v, 1) for v in box],
            'ground_below_sea_after_lift': len(wet), 'wet_examples': wet[:6],
            'shore_m': shore, 'room_to_border_m': round(edge, 1),
            'shore_fits': edge >= shore}
