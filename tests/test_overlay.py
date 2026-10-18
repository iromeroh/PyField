"""Overlay locations: surface block heights, terrain origin, and a full site built against Starfield.esm."""
import math
import os
import struct
from pathlib import Path

import pytest

from pyfield import Plugin
from pyfield.games.starfield.btd import CHUNK, BtdFile
from pyfield.games.starfield.overlay import (APOLLO_TERRAIN, EOVR_ENTRY, OverlaySite, blank_terrain,
                                             block_heights_fnam, build_overlay, fnam_border_matches, origin_cell,
                                             place_map_marker)
from test_landscape import make_btd

SF = Path(os.environ.get('PYFIELD_STARFIELD_DATA',
                         r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data'))


def test_origin_cell_matches_vanilla_blocks():
    assert origin_cell(3) == (-1, -1)          # Apollo
    assert origin_cell(10) == (-5, -5)         # Cydonia (calibrated with 3,456 ground objects)
    assert origin_cell(14) == (-7, -7)         # New Atlantis


def test_fnam_is_each_cells_corner_height():
    t = BtdFile.parse(make_btd(3, -500.0, 1000.0, lambda x, y: x * 0.1 + y * 0.05))
    fnam = block_heights_fnam(t, -500.0, 1000.0)
    assert len(fnam) == 2 * 9
    for i, (u,) in enumerate(struct.iter_unpack('<H', fnam)):
        x, y = i % 3, i // 3
        corner = x * CHUNK * 0.1 + y * CHUNK * 0.05
        assert abs(-500 + u / 65535 * 1500 - corner) < 0.05
    assert fnam_border_matches(t, fnam, -500.0, 1000.0)
    other = bytearray(fnam)
    other[0:2] = b'\0\0'
    assert not fnam_border_matches(t, bytes(other), -500.0, 1000.0)


def test_blank_terrain_keeps_size_and_aux():
    src = BtdFile.parse(make_btd(3, -500.0, 1000.0))
    t = blank_terrain(src, 2.5)
    hf = t.heightfield((0, 0))
    assert t.cells == src.cells and max(abs(v - 2.5) for v in hf.values) < 0.03
    assert bytes(t.chunk(0)[CHUNK * CHUNK * 2:]) == bytes(src.chunk(0)[CHUNK * CHUNK * 2:])


@pytest.mark.corpus
def test_build_site_on_luna(tmp_path):
    if not (SF / 'Starfield.esm').exists():
        pytest.skip('Starfield not installed')
    from pyfield.assets.index import AssetIndex
    from pyfield.core.loadorder import LoadOrder
    from pyfield.games.starfield.assets import RULES
    from pyfield.games.tes4family import StringTables
    assets = AssetIndex(SF, RULES, [], include_loose=False)
    terrain = blank_terrain(BtdFile.parse(assets.read(APOLLO_TERRAIN)))
    with LoadOrder.open(SF, ['Starfield.esm']) as lo:
        luna = lo.find_editor_id('LunaPlanetData')[0]
        site = OverlaySite('PFTest', 'PF Test', luna.form_key, 0.3, 1.2, cells=3)
        plugin = Plugin.create('PFOverlayUnit.esm', 'starfield', ['Starfield.esm'], flags=0x1)
        plugin.set_master_kinds({'Starfield.esm': 'full'})
        with plugin.transaction() as tx:
            tx.strings = StringTables(AssetIndex(SF, RULES, ['Starfield.esm'], include_loose=False))
            built = build_overlay(tx, lo, site, terrain)
            place_map_marker(tx, lo, built, site.name, (0.0, 0.0, 0.0), (20.0, 20.0, 0.0))
            report = tx.commit(tmp_path / 'PFOverlayUnit.esm', load_order=LoadOrder(lo.plugins + [plugin]))
        assert not report.errors
        written = Plugin.open(tmp_path / 'PFOverlayUnit.esm')
        counts = written.index.signature_counts()
        assert (counts['WRLD'], counts['LCTN'], counts['SFBK'], counts['PNDT'], counts['CELL']) == (1, 1, 1, 1, 10)
        planet = next(written.records('PNDT'))
        lat, lon, world, flag = EOVR_ENTRY.unpack(bytes(planet.get('EOVR').data))
        assert (lat, lon, flag) == (0.3, 1.2, 1) and world == next(written.records('WRLD')).form_id
        assert not any(f.signature == 'CNAM' and len(f.data) % 20 == 0 and f.data for f in planet.fields)
        vanilla = lo.plugin('Starfield.esm').find(planet.form_id)
        assert [f.signature for f in planet.fields] == \
            ['EOVR' if f.signature == 'CNAM' and len(f.data) == 40 else f.signature for f in vanilla.fields]
        block = next(written.records('SFBK'))
        assert bytes(block.get('ANAM').data) == b'Data\\Terrain\\PFTestWorld.btd\0'
        written.close()


def test_landing_spot_is_closest_clear_point():
    from types import SimpleNamespace
    from pyfield.games.starfield.outpost import OutpostPlan, landing_spot
    from pyfield.scene.transform import Transform
    refs = [SimpleNamespace(placed=Transform.at(x, y, 0)) for x in range(-30, 31, 5) for y in range(-30, 31, 5)]
    plan = OutpostPlan('t', refs=refs, cells=4)
    (x, y), d = landing_spot(plan, clearance=40.0)
    assert d >= 40.0 and math.hypot(x, y) < 80.0


def test_biome_map_projection_round_trip_and_parse():
    from pyfield.games.starfield.biomes import BiomeMap, angular_distance
    for lat, lon in ((0.3, 1.0), (-0.6, -2.0), (0.05, 3.0), (-1.0, 0.4)):
        g, x, y = BiomeMap.to_cell(lat, lon)
        assert g == (0 if lat >= 0 else 1)
        back = BiomeMap.to_latlon(g, x, y)
        assert angular_distance((lat, lon), back) < 0.02
    # a two-biome synthetic map: north grid all biome 7, south all biome 9
    import struct as st
    cells = 4 * 4
    data = st.pack('<HI2I', 0x105, 2, 7, 9) + st.pack('<I', 2)
    for fid in (7, 9):
        data += st.pack('<3I', 4, 4, cells) + st.pack(f'<{cells}I', *([fid] * cells)) + st.pack('<I', cells) + bytes(cells)
    bm = BiomeMap.parse('Test', data, {7: 'SavannaLife01', 9: 'OceanLife02'})
    assert bm.biome_at(0.4, 1.0) == 'SavannaLife01' and bm.biome_at(-0.4, 1.0) == 'OceanLife02'
    assert bm.is_water(9) and not bm.is_water(7)


def test_biome_junctions_find_shared_corners():
    import struct as st
    from pyfield.games.starfield.biomes import BiomeMap, find_junctions
    w = h = 8
    north = [1 if x < 4 else (2 if y < 4 else 3) for y in range(h) for x in range(w)]   # 3 biomes meet at (4, 4)
    south = [3] * (w * h)
    data = st.pack('<HI3I', 0x105, 3, 1, 2, 3) + st.pack('<I', 2)
    for grid in (north, south):
        data += st.pack('<3I', w, h, len(grid)) + st.pack(f'<{len(grid)}I', *grid) + st.pack('<I', len(grid)) + bytes(len(grid))
    bm = BiomeMap.parse('T', data, {1: 'SavannaLife01', 2: 'MountainsLife02', 3: 'OceanLife03'})
    mixed = find_junctions(bm, min_land_biomes=2, max_lat_deg=90)
    assert mixed and set(mixed[0].biomes) >= {'SavannaLife01', 'MountainsLife02'}
    coast = find_junctions(bm, min_land_biomes=1, coast=True, need=['Savanna'], max_lat_deg=90)
    assert coast and all(j.water and 'SavannaLife01' in j.biomes for j in coast)
