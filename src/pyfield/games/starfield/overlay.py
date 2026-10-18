"""Overlay locations: a small handcrafted worldspace pinned to a planet position, with its own terrain.

The game's fixed locations (Cydonia, Apollo Landing Site) and Creations (sfta05 villa) are built this way
(docs/formats/starfield-planet-locations.md):

- WRLD with `BGSWorldSpaceOverlay_Component` (`BNAM` -> SFBK surface block) and its location in `XLCN`;
- LCTN whose `PNAM` is the planet's `<...>_Surface` location;
- SFBK `OverlayBlock<World>`: `ANAM` = `Data\\Terrain\\<World>.btd`, `DNAM` size in cells, `ENAM` height range,
  `FNAM` one u16 per cell (mean height, quantized in the `ENAM` range);
- one `EOVR` entry (f64 latitude, f64 longitude in radians, u32 world, u8 1) in an override of the planet's
  PNDT; the list is additive, an override carries only its own entries.

The terrain file's first cell is (-floor(n/2), -floor(n/2)) and its heights are absolute worldspace Z, so
objects and terrain share one frame (calibrated on Cydonia).

    site = OverlaySite('PF_Site', 'My Site', planet=lo.find_editor_id('LunaPlanetData')[0].form_key,
                       latitude=0.3, longitude=1.2, cells=3)
    with plugin.transaction() as tx:
        tx.strings = StringTables(...)              # templates are localized; names are written as text
        built = build_overlay(tx, lo, site, terrain)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
from types import SimpleNamespace

from ...core.formids import FormKey
from ...core.nodes import GroupNode, RecordNode
from ...core.subrecords import Subrecord
from ...errors import PyFieldError
from .btd import BtdFile, CHUNK

SF = 'Starfield.esm'
# Apollo Landing Site (Luna): the smallest vanilla overlay location, used as the template.
APOLLO_WORLD = FormKey(SF, 0x2F3D06)            # LC159World
APOLLO_PERSISTENT_CELL = FormKey(SF, 0x08E836)
APOLLO_GRID_CELL = FormKey(SF, 0x1B2B81)        # (1, 1): plain exterior cell (no editor ID, no XTV2)
APOLLO_LOCATION = FormKey(SF, 0x3807DA)         # LC159WorldLocation
APOLLO_BLOCK = FormKey(SF, 0x2F3D0D)            # OverlayBlockLC159World
APOLLO_TERRAIN = 'terrain/lc159world.btd'
APOLLO_MAP_MARKER = FormKey(SF, 0x15EB88)       # linked (no keyword) to its landing heading marker
XMARKER_HEADING = FormKey(SF, 0x000034)

WORLD_DROP = {'EDID', 'RNAM', 'OFST', 'CLSZ'}  # large-reference grid and offset tables describe the template's refs
LOCATION_KEEP = {'KSIZ', 'KWDA', 'DATA', 'PNAM', 'RNAM', 'ANAM', 'TNAM', 'XNAM', 'YNAM'}
EOVR_ENTRY = struct.Struct('<ddIB')
FORM_VERSION_EOVR = 582


@dataclass
class OverlaySite:
    editor_id: str                       # prefix: <id>World, <id>Location, OverlayBlock<id>World
    name: str
    planet: FormKey                      # PNDT
    latitude: float                      # radians
    longitude: float
    cells: int = 3                       # terrain block size (n x n cells, 100 m each)


@dataclass
class OverlayResult:
    world: object = None
    location: object = None
    block: object = None
    planet: object = None
    persistent_cell: FormKey | None = None
    cells: dict = field(default_factory=dict)          # (x, y) -> FormKey
    terrain_path: str = ''                              # archive path of the .btd
    markers: dict = field(default_factory=dict)        # name -> FormKey

    def summary(self) -> str:
        return (f'world {self.world.form_key} ({self.world.editor_id}), location {self.location.form_key}, '
                f'block {self.block.form_key}, {len(self.cells)} exterior cells, terrain {self.terrain_path}')


def origin_cell(cells: int) -> tuple[int, int]:
    """World grid of the terrain file's first cell."""
    return -(cells // 2), -(cells // 2)


def block_heights_fnam(terrain: BtdFile, low: float, high: float) -> bytes:
    """SFBK FNAM: each cell's first-corner height quantized in the block's ENAM range, row-major.

    Vanilla blocks match this exactly along their borders (Cydonia: every edge cell); interior cells
    differ where the terrain was sculpted after the block was generated.
    """
    cx, cy = terrain.cells
    out = bytearray()
    for y in range(cy):
        for x in range(cx):
            corner = terrain.height_min + terrain.chunk_heights_u16(terrain.lod0_index(x, y))[0] * terrain.scale
            out += struct.pack('<H', max(0, min(65535, round((corner - low) / (high - low) * 65535))))
    return bytes(out)


def fnam_border_matches(terrain: BtdFile, fnam: bytes, low: float, high: float) -> bool:
    """True when a block's FNAM equals block_heights_fnam on every border cell (template check)."""
    cx, cy = terrain.cells
    ours = block_heights_fnam(terrain, low, high)
    return all(ours[2 * i:2 * i + 2] == fnam[2 * i:2 * i + 2] for i in range(cx * cy)
               if i % cx in (0, cx - 1) or i // cx in (0, cy - 1))


def _copy_fields(tx, view, drop=(), load_order=None):
    """The template's subrecords with FormIDs re-encoded for tx's plugin (masters added as needed)."""
    from ...remap import plan_remap
    kept = SimpleNamespace(signature=view.signature, form_id=view.node.form_id,
                           fields=[f for f in view.node.fields if f.signature not in drop])
    return [Subrecord(f.signature, bytes(f.data))
            for f in plan_remap(view.plugin, kept, tx.plugin, load_order=load_order).apply(tx.ensure_master)]


def _text(value: str) -> bytes:
    return value.encode('utf-8') + b'\0'


def _new_like(tx, view, editor_id, fields):
    new = tx.new_record(view.signature, editor_id)
    new.node.header[20:24] = view.node.header[20:24]          # form version
    new.node.fields = [new.node.fields[0]] + fields if editor_id else fields
    return new


def _component_replace(fields, component: str, signature: str, data: bytes):
    """Replace `signature` inside the named BFCB/BFCE component block."""
    inside = False
    for i, f in enumerate(fields):
        if f.signature == 'BFCB':
            inside = f.data.rstrip(b'\0').decode('ascii', 'replace') == component
        elif f.signature == 'BFCE':
            inside = False
        elif inside and f.signature == signature:
            fields[i] = Subrecord(signature, data)
            return
    raise PyFieldError(f'{component} {signature} not found in template')


def _replace_first(fields, signature: str, data: bytes, after_component=True):
    """Replace the first top-level `signature` outside any component (or append it)."""
    inside = False
    for i, f in enumerate(fields):
        if f.signature == 'BFCB':
            inside = True
        elif f.signature == 'BFCE':
            inside = False
        elif not inside and f.signature == signature:
            fields[i] = Subrecord(signature, data)
            return
    fields.append(Subrecord(signature, data))


def _formid_field(tx, view, signature: str, top_level: bool = False) -> bytes | None:
    """A FormID subrecord of `view` re-encoded for tx's plugin (first outside components when top_level)."""
    inside = False
    for f in view.node.fields:
        if f.signature == 'BFCB':
            inside = True
        elif f.signature == 'BFCE':
            inside = False
        elif f.signature == signature and not (top_level and inside):
            key = view.plugin.codec.decode(int.from_bytes(f.data[:4], 'little'))
            if key.plugin != tx.plugin.name.lower():
                src = next((n for n in view.plugin.masters + [view.plugin.name] if n.lower() == key.plugin), key.plugin)
                tx.ensure_master(src, 'full' if src.lower() == 'starfield.esm' else view.plugin.kind)
            return tx.plugin.codec.encode(key).to_bytes(4, 'little')
    return None


def _group(spec, label: bytes, kind: int) -> GroupNode:
    return GroupNode.new(spec, label, kind, bytes(spec.group_header_size - 16))


def _child(parent: GroupNode, spec, label: bytes, kind: int) -> GroupNode:
    g = next((c for c in parent.groups() if c.kind == kind and c.label_bytes == label), None)
    if g is None:
        g = _group(spec, label, kind)
        parent.append(g)
    return g


def _new_cell(tx, template, grid, persistent: bool) -> RecordNode:
    plugin = tx.plugin
    key = tx.allocator.allocate()
    fields = []
    for f in template.node.fields:
        if f.signature in ('EDID', 'FULL', 'XTV2', 'XLCN'):
            continue
        data = bytes(f.data)
        if f.signature == 'XCLC':
            gx, gy = (0x7FFFFFFF, 0x7FFFFFFF) if persistent else grid
            data = struct.pack('<ii', gx, gy) + data[8:]
        fields.append(Subrecord(f.signature, data))
    node = RecordNode.new(plugin.spec, 'CELL', plugin.codec.encode(key), fields, template.node.flags,
                          template.node.header_tail)
    node.header[20:24] = template.node.header[20:24]
    return node


def defining(load_order, key):
    """The record as its defining plugin wrote it (typed), not the load-order winner.

    Templates are copied from it: newer overrides can be partial deltas the engine merges (SFBGS050.esm
    overrides LC159WorldLocation with only ACSR/ACID/ACEP; planet EOVR lists are additive the same way).
    """
    found = load_order.overrides(key)
    if not found:
        return None
    source, node = found[0]
    return source.typed(node)


@dataclass
class OverlayTemplate:
    """A vanilla (or any loaded) overlay location whose records seed a new one: biome, lighting, keywords,
    terrain textures and size come from it."""
    world: object
    location: object
    block: object
    persistent_cell: object
    grid_cell: object
    terrain_path: str                   # archive path of its .btd ('terrain/<world>.btd')
    cells: int

    @classmethod
    def from_world(cls, load_order, world_key) -> 'OverlayTemplate':
        world = defining(load_order, world_key)
        if world is None or world.signature != 'WRLD':
            raise PyFieldError(f'{world_key} is not a worldspace')
        codec = world.plugin.codec
        fields = world.node.fields
        block_raw = None
        inside = False
        for f in fields:
            if f.signature == 'BFCB':
                inside = f.data.rstrip(b'\0').decode('ascii', 'replace') == 'BGSWorldSpaceOverlay_Component'
            elif f.signature == 'BFCE':
                inside = False
            elif inside and f.signature == 'BNAM':
                block_raw = int.from_bytes(f.data[:4], 'little')
        loc = next((f for f in fields if f.signature == 'XLCN'), None)
        if block_raw is None or loc is None:
            raise PyFieldError(f'{world.editor_id} is not an overlay worldspace (no overlay block or location)')
        block = defining(load_order, codec.decode(block_raw))
        location = defining(load_order, codec.decode(int.from_bytes(loc.data[:4], 'little')))
        anam = bytes(block.node.get('ANAM').data).rstrip(b'\0').decode('ascii')
        path = anam.replace('\\', '/').lower()
        path = path[5:] if path.startswith('data/') else path
        n = struct.unpack('<II', bytes(block.node.get('DNAM').data))[0]
        # cells come from the defining plugin (overrides may carry only some cells, and cell fields are
        # copied without FormID remapping)
        source, node = load_order.overrides(world.form_key)[0]
        siblings = node.parent.children
        children = siblings[siblings.index(node) + 1]
        persistent = grid = None
        for c in _records_under(children):
            if c.signature != 'CELL' or c.get('XCLC') is None:
                continue
            gx, gy = struct.unpack_from('<ii', c.get('XCLC').data)
            if gx == 0x7FFFFFFF and persistent is None:
                persistent = c
            elif gx != 0x7FFFFFFF and grid is None:
                grid = c
        if persistent is None or grid is None:
            raise PyFieldError(f'{world.editor_id}: persistent or exterior cell missing')
        typed = source.typed
        return cls(world, location, block, typed(persistent), typed(grid), path, n)


def _records_under(group):
    for c in group.children:
        if isinstance(c, GroupNode):
            yield from _records_under(c)
        else:
            yield c


def pinned_worlds(planet_view) -> list:
    """(latitude, longitude, world FormKey) of the fixed locations of a planet record (CNAM list, EOVR)."""
    codec = planet_view.plugin.codec
    out = []
    for f in planet_view.node.fields:
        data = bytes(f.data)
        if f.signature == 'CNAM' and data and len(data) % 20 == 0:
            for i in range(0, len(data), 20):
                lat, lon, raw = struct.unpack_from('<ddI', data, i)
                out.append((lat, lon, codec.decode(raw)))
        elif f.signature == 'EOVR' and len(data) % EOVR_ENTRY.size == 0:
            for i in range(0, len(data), EOVR_ENTRY.size):
                lat, lon, raw, _ = EOVR_ENTRY.unpack_from(data, i)
                out.append((lat, lon, codec.decode(raw)))
    return out


def template_for_planet(load_order, planet_view, cells: int | None = None) -> OverlayTemplate:
    """An overlay location already pinned on this planet (right biome and ground textures), preferring the
    smallest block with at least `cells` cells; Apollo Landing Site when the planet has none."""
    found = []
    for _, _, key in pinned_worlds(planet_view):
        try:
            found.append(OverlayTemplate.from_world(load_order, key))
        except (PyFieldError, AttributeError, IndexError, ValueError):
            continue
    fitting = [t for t in found if cells is None or t.cells >= cells]
    if fitting:
        return min(fitting, key=lambda t: t.cells)
    return OverlayTemplate.from_world(load_order, APOLLO_WORLD)


def build_overlay(tx, load_order, site: OverlaySite, terrain: BtdFile, cells=None,
                  template: OverlayTemplate | None = None, look: OverlayTemplate | None = None,
                  water_height: float | None = None, biome=None) -> OverlayResult:
    """Create the worldspace, its persistent cell and exterior cells, location, surface block and pin.

    `template` gives the record structure (default Apollo Landing Site, verified in game); `look` (an overlay
    location on the target planet, see template_for_planet) gives only what is planet-specific: the biome
    (world BNAM) and the location's parent (the planet's surface location). The overlay component's SNAM is
    always cleared: vanilla values point at unrelated references (editor leftovers).

    `cells` lists the exterior grid cells to create (default: the terrain block's cells). The terrain bytes
    are not written here: archive `terrain.to_bytes()` at `result.terrain_path`.
    """
    plugin = tx.plugin
    if plugin.is_localized:
        raise PyFieldError('overlay names are written as text: the target plugin must not be localized')
    n = site.cells
    if terrain.cells != (n, n):
        raise PyFieldError(f'terrain is {terrain.cells} cells, the site needs {n} x {n}')
    template = template or OverlayTemplate.from_world(load_order, APOLLO_WORLD)
    world_t, block_t, loc_t = template.world, template.block, template.location
    planet_v = load_order.resolve(site.planet)
    if planet_v is None or planet_v.signature != 'PNDT':
        raise PyFieldError(f'{site.planet} is not a planet (PNDT)')
    result = OverlayResult()
    world_id, location_id, block_id = f'{site.editor_id}World', f'{site.editor_id}Location', f'OverlayBlock{site.editor_id}World'
    result.terrain_path = f'terrain/{world_id.lower()}.btd'

    # location: keywords, parent (planet surface), type; the template's ref lists describe its own refs
    drop = {f.signature for f in loc_t.node.fields} - LOCATION_KEEP
    fields = [Subrecord('FULL', _text(site.name))] + _copy_fields(tx, loc_t, drop=drop, load_order=load_order)
    if look is not None:
        parent = _formid_field(tx, look.location, 'PNAM')
        if parent is not None:
            _replace_first(fields, 'PNAM', parent)
    result.location = _new_like(tx, loc_t, location_id, fields)

    # surface block
    fields = _copy_fields(tx, block_t, drop={'EDID'}, load_order=load_order)
    low, high = struct.unpack('<ff', next(f.data for f in fields if f.signature == 'ENAM'))
    for i, f in enumerate(fields):
        if f.signature == 'ANAM':
            fields[i] = Subrecord('ANAM', _text('Data\\Terrain\\' + world_id + '.btd'))
        elif f.signature == 'DNAM':
            fields[i] = Subrecord('DNAM', struct.pack('<II', n, n))
        elif f.signature == 'FNAM':
            fields[i] = Subrecord('FNAM', block_heights_fnam(terrain, low, high))
        elif f.signature == 'WHGT' and water_height is not None:   # block water level (Neon City: 195)
            fields[i] = Subrecord('WHGT', struct.pack('<f', water_height))
    result.block = _new_like(tx, block_t, block_id, fields)

    # worldspace
    fields = _copy_fields(tx, world_t, drop=WORLD_DROP, load_order=load_order)
    _component_replace(fields, 'BGSWorldSpaceOverlay_Component', 'BNAM', plugin.codec.encode(result.block.form_key).to_bytes(4, 'little'))
    _replace_first(fields, 'FULL', _text(site.name))
    _replace_first(fields, 'XLCN', plugin.codec.encode(result.location.form_key).to_bytes(4, 'little'))
    _component_replace(fields, 'BGSWorldSpaceOverlay_Component', 'SNAM', bytes(4))
    if biome is not None:                         # explicit biome (FormKey), e.g. the one at the chosen spot
        if biome.plugin != plugin.name.lower():
            tx.ensure_master(load_order.plugin(biome.plugin).name, load_order.plugin(biome.plugin).kind)
        _replace_first(fields, 'BNAM', plugin.codec.encode(biome).to_bytes(4, 'little'))
    elif look is not None:
        look_biome = _formid_field(tx, look.world, 'BNAM', top_level=True)
        if look_biome is not None:
            _replace_first(fields, 'BNAM', look_biome)
    result.world = world = _new_like(tx, world_t, world_id, fields)

    # children: persistent cell first, then exterior blocks (label i16 y, i16 x) and sub-blocks
    spec = plugin.spec
    top = world.node.parent
    children = _group(spec, world.node.form_id.to_bytes(4, 'little'), 1)
    top.insert(top.children.index(world.node) + 1, children)
    pcell = _new_cell(tx, template.persistent_cell, None, persistent=True)
    children.append(pcell)
    result.persistent_cell = plugin.codec.decode(pcell.form_id)
    grid_t = template.grid_cell
    ox, oy = origin_cell(n)
    wanted = cells if cells is not None else [(ox + i, oy + j) for j in range(n) for i in range(n)]
    for gx, gy in wanted:
        block = _child(children, spec, struct.pack('<hh', gy // 32, gx // 32), 4)
        sub = _child(block, spec, struct.pack('<hh', gy // 8, gx // 8), 5)
        cell = _new_cell(tx, grid_t, (gx, gy), persistent=False)
        sub.append(cell)
        result.cells[(gx, gy)] = plugin.codec.decode(cell.form_id)

    # pin: the planet override carries only our EOVR entry (additive list, as Creations write it)
    planet = tx.override(planet_v, load_order=load_order)
    entry = EOVR_ENTRY.pack(site.latitude, site.longitude, plugin.codec.encode(world.form_key), 1)
    fields = list(planet.node.fields)
    existing = next((i for i, f in enumerate(fields) if f.signature == 'EOVR'), None)
    array = next((i for i, f in enumerate(fields) if f.signature == 'CNAM' and f.data and len(f.data) % 20 == 0), None)
    if existing is not None:                      # another plugin's entries stay in that plugin (additive)
        fields[existing] = Subrecord('EOVR', entry)
    elif array is not None:
        fields[array] = Subrecord('EOVR', entry)             # vanilla CNAM list stays in the master
    else:
        anchor = next(i for i, f in enumerate(fields) if f.signature == 'PPBD')
        fields.insert(anchor, Subrecord('EOVR', entry))
    planet.node.fields = fields
    planet.node.header[20:22] = FORM_VERSION_EOVR.to_bytes(2, 'little')
    result.planet = planet
    return result


def place_map_marker(tx, load_order, result: OverlayResult, name: str, marker_at, landing_at, landing_yaw=0.0):
    """Map marker (copied from Apollo's, enabled) linked to a heading marker where the ship lands.

    Both are persistent references in the worldspace's persistent cell. Positions are (x, y, z) metres.
    """
    plugin = tx.plugin
    pcell = plugin.get(result.persistent_cell)
    from ...scene.compile import _children_group
    group = _children_group(plugin, pcell, 8)
    marker_t = defining(load_order, APOLLO_MAP_MARKER)

    def ref(fields, flags):
        key = tx.allocator.allocate()
        node = RecordNode.new(plugin.spec, 'REFR', plugin.codec.encode(key), fields, flags,
                              marker_t.node.header_tail)
        node.header[20:24] = marker_t.node.header[20:24]
        group.append(node)
        return key

    def data(pos, yaw=0.0):
        return struct.pack('<6f', *pos, 0.0, 0.0, yaw)

    landing = ref([Subrecord('NAME', plugin.codec.encode(XMARKER_HEADING).to_bytes(4, 'little')),
                   Subrecord('DATA', data(landing_at, landing_yaw))], 0x400)
    fields = []
    for f in _copy_fields(tx, marker_t, load_order=load_order):
        if f.signature == 'FULL':
            f = Subrecord('FULL', _text(name))
        elif f.signature == 'XLKR':
            f = Subrecord('XLKR', bytes(4) + plugin.codec.encode(landing).to_bytes(4, 'little'))
        elif f.signature == 'DATA':
            f = Subrecord('DATA', data(marker_at))
        fields.append(f)
    marker = ref(fields, 0x400)                                  # persistent, not initially disabled
    result.markers.update(map_marker=marker, landing=landing)
    return marker, landing


def blank_terrain(template: BtdFile, height: float = 0.0) -> BtdFile:
    """A copy of a terrain file with every sample at `height` (same size, textures and auxiliary data)."""
    t = BtdFile.parse(template.to_bytes())
    hf = t.heightfield((0, 0))
    for k in range(len(hf.values)):
        hf.values[k] = height
    t.apply_heightfield(hf)
    return t
