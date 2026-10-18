"""Planet biome maps (planetdata/biomemaps/<planet>.biom) and outpost site candidates.

Format (2026-10-17): u16 0x0105, u32 n, n x u32 biome FormIDs; u32 grids (2); per grid: u32 width, u32 height,
u32 count, count x u32 biome FormID, u32 count, count x u8 resource. Grid 0 is the northern hemisphere, grid 1
the southern, each a stereographic disc around its pole:

    r = 0.52 * tan(colatitude / 2)          (fraction of the grid width; the equator near the disc edge)
    north: x = 0.5 + r cos(lon), y = 0.5 - r sin(lon)
    south: x = 0.5 - r cos(lon), y = 0.5 - r sin(lon)      (seen from the south pole: mirrored)

Calibrated with the 61 vanilla fixed locations whose worldspace biome appears in their planet's map
(tools/calibrate_biome_maps.py, refine_biome_projection.py): 56 land on a cell of their own biome
(information 57 of 65 nats; a typical wrong projection scores 14).

    bm = BiomeMap.load(assets, 'Nesoi', load_order)
    bm.biome_at(lat, lon)                    # editor ID of the biome there
    find_sites(bm, ['Savanna'], avoid=[(lat, lon), ...], count=5)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
import zlib

SCALE = 0.52
FLAT_HINT = ('Savanna', 'Desert', 'Field', 'Plain', 'Grass', 'Tundra', 'Wetland', 'Swamp')
STEEP_HINT = ('Mountain', 'Cliff', 'Canyon', 'Volcanic', 'Crater')
WATER_HINT = ('Ocean',)


@dataclass
class BiomeMap:
    planet: str
    ids: list                                     # biome FormIDs (as stored)
    grids: list                                   # [(width, height, cells)] north, south
    names: dict = field(default_factory=dict)     # FormID -> editor ID

    @classmethod
    def parse(cls, planet: str, data: bytes, names: dict | None = None) -> 'BiomeMap':
        magic, n = struct.unpack_from('<HI', data, 0)
        if magic != 0x105:
            raise ValueError(f'{planet}: not a biome map (magic {magic:#x})')
        ids = list(struct.unpack_from(f'<{n}I', data, 6))
        o = 6 + 4 * n
        count = struct.unpack_from('<I', data, o)[0]
        o += 4
        grids = []
        for _ in range(count):
            w, h, cells = struct.unpack_from('<3I', data, o)
            o += 12
            grids.append((w, h, struct.unpack_from(f'<{cells}I', data, o)))
            o += 4 * cells
            rc = struct.unpack_from('<I', data, o)[0]
            o += 4 + rc
        return cls(planet, ids, grids, dict(names or {}))

    @classmethod
    def load(cls, assets, planet_name: str, load_order=None) -> 'BiomeMap':
        """`planet_name` is the PNDT ANAM name (e.g. 'Nesoi'); names resolve through Starfield.esm when given."""
        bm = cls.parse(planet_name, assets.read(f'planetdata/biomemaps/{planet_name.lower()}.biom'))
        if load_order is not None:
            sf = load_order.plugins[0]
            for fid in bm.ids:
                node = sf.find(fid)
                edid = node.get('EDID') if node is not None else None
                bm.names[fid] = bytes(edid.data).rstrip(b'\0').decode('latin1') if edid is not None else f'{fid:08X}'
        return bm

    # -- projection --------------------------------------------------------------------------------
    @staticmethod
    def to_cell(lat: float, lon: float, w: int = 256, h: int = 256):
        g = 0 if lat >= 0 else 1
        r = SCALE * math.tan((math.pi / 2 - abs(lat)) / 2)
        sx = 1 if g == 0 else -1
        return g, int((0.5 + sx * r * math.cos(lon)) * w), int((0.5 - r * math.sin(lon)) * h)

    @staticmethod
    def to_latlon(g: int, x: float, y: float, w: int = 256, h: int = 256):
        """Centre of a cell -> (lat, lon) radians; None outside the hemisphere disc."""
        u, v = (x + 0.5) / w - 0.5, (y + 0.5) / h - 0.5
        if g == 1:
            u = -u
        r = math.hypot(u, v)
        colat = 2 * math.atan(r / SCALE)
        if colat > math.pi / 2:
            return None
        lat = math.pi / 2 - colat
        return (lat if g == 0 else -lat), math.atan2(-v, u)

    def biome_id(self, lat: float, lon: float) -> int:
        g, x, y = self.to_cell(lat, lon)
        w, h, cells = self.grids[g]
        return cells[min(h - 1, max(0, y)) * w + min(w - 1, max(0, x))]

    def biome_at(self, lat: float, lon: float) -> str:
        fid = self.biome_id(lat, lon)
        return self.names.get(fid, f'{fid:08X}')

    def is_water(self, fid: int) -> bool:
        return any(k in self.names.get(fid, '') for k in WATER_HINT)


def _hint(name: str) -> str:
    if any(k in name for k in WATER_HINT):
        return 'water'
    if any(k in name for k in STEEP_HINT):
        return 'steep'
    if any(k in name for k in FLAT_HINT):
        return 'gentle'
    return 'mixed'


def angular_distance(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    c = math.sin(la1) * math.sin(la2) + math.cos(la1) * math.cos(la2) * math.cos(lo1 - lo2)
    return math.acos(max(-1.0, min(1.0, c)))


@dataclass
class Site:
    latitude: float
    longitude: float
    biome: str
    hint: str                                     # gentle / mixed / steep / water (from the biome name)
    uniform_cells: int                            # radius (cells) of same-biome ground around it
    shore_cells: int                              # distance to the nearest water cell (cells; 99 = none near)

    def to_dict(self) -> dict:
        return {'lat': round(self.latitude, 4), 'lon': round(self.longitude, 4),
                'deg': [round(math.degrees(self.latitude), 2), round(math.degrees(self.longitude), 2)],
                'biome': self.biome, 'terrain_hint': self.hint, 'uniform_radius_cells': self.uniform_cells,
                'cells_to_water': self.shore_cells}


def find_sites(bm: BiomeMap, biomes=(), avoid=(), min_separation: float = 0.05, count: int = 5,
               near=None, max_lat_deg: float = 70.0, coast: bool = False) -> list:
    """Candidate (lat, lon) sites inside large uniform patches of the wanted biomes (substring match on the
    editor ID; empty = any land biome), away from water and from `avoid` points (radians), optionally sorted
    by distance to `near`. Polar regions beyond `max_lat_deg` are skipped (stretched cells). `coast` keeps land
    within 1-2 cells of water instead (a cell spans tens of km: coastal region, not the exact shoreline,
    which is generated on landing)."""
    picks = []
    for g, (w, h, cells) in enumerate(bm.grids):
        for y in range(2, h - 2, 2):
            for x in range(2, w - 2, 2):
                fid = cells[y * w + x]
                name = bm.names.get(fid, '')
                if bm.is_water(fid) or (biomes and not any(b.lower() in name.lower() for b in biomes)):
                    continue
                ll = bm.to_latlon(g, x, y, w, h)
                if ll is None or abs(math.degrees(ll[0])) > max_lat_deg:
                    continue
                if coast:
                    near_water = any(bm.is_water(cells[yy * w + xx]) for yy in range(max(0, y - 2), min(h, y + 3))
                                     for xx in range(max(0, x - 2), min(w, x + 3)))
                    if not near_water:
                        continue
                uniform = 0
                for r in range(1, 8):
                    ring = [cells[yy * w + xx] for yy in range(max(0, y - r), min(h, y + r + 1))
                            for xx in range(max(0, x - r), min(w, x + r + 1))]
                    if any(c != fid for c in ring):
                        break
                    uniform = r
                if uniform < (0 if coast else 2):
                    continue
                shore = 99
                for r in range(1, 12):
                    if any(bm.is_water(cells[yy * w + xx]) for yy in range(max(0, y - r), min(h, y + r + 1))
                           for xx in range(max(0, x - r), min(w, x + r + 1))):
                        shore = r
                        break
                picks.append(Site(ll[0], ll[1], name, _hint(name), uniform, shore))
    picks = [s for s in picks if all(angular_distance((s.latitude, s.longitude), a) >= min_separation for a in avoid)]
    rank = {'gentle': 0, 'mixed': 1, 'steep': 2, 'water': 3}
    if near is not None:
        picks.sort(key=lambda s: (angular_distance((s.latitude, s.longitude), near), -s.uniform_cells))
    else:
        picks.sort(key=lambda s: (rank[s.hint], -s.uniform_cells, -min(s.shore_cells, 20)))
    chosen = []
    for s in picks:
        if all(angular_distance((s.latitude, s.longitude), (c.latitude, c.longitude)) >= min_separation for c in chosen):
            chosen.append(s)
        if len(chosen) >= count:
            break
    return chosen


def preview_png(bm: BiomeMap, path, sites=(), marks=(), size: int = 256):
    """Both hemispheres side by side (north left), one grey level per biome; sites white, marks black."""
    shades = {fid: 60 + (i * 160) // max(1, len(bm.ids) - 1) for i, fid in enumerate(bm.ids)}
    for fid in bm.ids:
        if bm.is_water(fid):
            shades[fid] = 25
    w = size * 2
    px = bytearray(w * size)
    for g, (gw, gh, cells) in enumerate(bm.grids):
        for y in range(size):
            for x in range(size):
                px[y * w + g * size + x] = shades.get(cells[(y * gh // size) * gw + x * gw // size], 128)

    def dot(lat, lon, value):
        g, x, y = BiomeMap.to_cell(lat, lon, size, size)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if abs(dx) + abs(dy) <= 4 and 0 <= x + dx < size and 0 <= y + dy < size:
                    px[(y + dy) * w + g * size + x + dx] = value
    for lat, lon in marks:
        dot(lat, lon, 0)
    for s in sites:
        dot(s.latitude, s.longitude, 255)
    raw = b''.join(b'\0' + bytes(px[y * w:(y + 1) * w]) for y in range(size))

    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, size, 8, 0, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


@dataclass
class Junction:
    latitude: float
    longitude: float
    biomes: list                                  # distinct biome editor IDs of the (up to 4) cells meeting here
    water: bool

    def to_dict(self) -> dict:
        return {'lat': round(self.latitude, 4), 'lon': round(self.longitude, 4),
                'deg': [round(math.degrees(self.latitude), 2), round(math.degrees(self.longitude), 2)],
                'biomes': self.biomes, 'coast': self.water}


def find_junctions(bm: BiomeMap, need=(), min_land_biomes: int = 2, coast: bool = False, avoid=(),
                   min_separation: float = 0.05, count: int = 5, near=None, max_lat_deg: float = 70.0) -> list:
    """Cell corners where different biomes meet: a landing there takes in all of them (the game blends biomes
    across cell borders). `coast` wants water among them (a shore inside the landing area), `min_land_biomes`
    the number of distinct land biomes, `need` biome name parts that must all be present (e.g. Savanna,
    Mountain). Ranked by the number of distinct biomes, or by distance to `near`."""
    picks = []
    for g, (w, h, cells) in enumerate(bm.grids):
        for y in range(1, h):
            for x in range(1, w):
                four = {cells[(y - 1) * w + x - 1], cells[(y - 1) * w + x], cells[y * w + x - 1], cells[y * w + x]}
                land = [f for f in four if not bm.is_water(f)]
                water = len(land) < len(four)
                if len(land) < min_land_biomes or (coast and not water) or not land:
                    continue
                names = sorted(bm.names.get(f, f'{f:08X}') for f in four)
                if need and not all(any(n.lower() in b.lower() for b in names) for n in need):
                    continue
                ll = bm.to_latlon(g, x - 0.5, y - 0.5, w, h)       # the shared corner of the four cells
                if ll is None or abs(math.degrees(ll[0])) > max_lat_deg:
                    continue
                if any(angular_distance(ll, a) < min_separation for a in avoid):
                    continue
                picks.append(Junction(ll[0], ll[1], names, water))
    if near is not None:
        picks.sort(key=lambda j: angular_distance((j.latitude, j.longitude), near))
    else:
        picks.sort(key=lambda j: (-len(j.biomes), abs(j.latitude)))
    chosen = []
    for j in picks:
        if all(angular_distance((j.latitude, j.longitude), (c.latitude, c.longitude)) >= min_separation for c in chosen):
            chosen.append(j)
        if len(chosen) >= count:
            break
    return chosen
