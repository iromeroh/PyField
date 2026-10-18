# Starfield: fixed locations on planets (verified on Starfield.esm, 2026-10-16)

Planet surfaces are generated at runtime (landing-site worldspaces and cells are save-created). Handcrafted
fixed locations are their own small worldspaces pinned to a planet position:

- `PNDT` (planet data) `CNAM` (top level, after the components): array of 20-byte entries
  `f64 latitude, f64 longitude, u32 worldspace FormID`, angles in **radians**.
  Luna (`LunaPlanetData`): Nova Galactic Research Station `LC126World` at (-0.10435, -1.06998) = -5.98°, -61.31°;
  Apollo Landing Site `LC159World` at (-0.00230, 0.37897) = -0.13°, 21.71°.
  Mars: Cydonia `CydoniaCity` at 41.03°N, 9.80°W (matches the real Cydonia region).
- The worldspace carries `BGSWorldSpaceOverlay_Component` (`SNAM`, `PNAM`, `BNAM`) and its location in `XLCN`;
  bounds `NAM0`/`NAM9` are a few hundred metres.
- The location (`LCTN`) has `PNAM` = the planet's `<...>_Surface` location; `XNAM`/`YNAM` are -1/-3 for every
  fixed surface location (placeholders, not coordinates).
- A quest may force the location into an alias (`Landmark_Apollo` `ALFL`); cells reference the world in `XTV2`.
- Luna's `PCCC` (98 KB, Houdini data component) does not reference these locations.

## Plugins add locations with `EOVR` (verified 2026-10-17)

Form version 582 (current) planet overrides carry `EOVR`: an array of **21-byte** entries
`f64 latitude, f64 longitude (radians), u32 worldspace FormID, u8 flag (1)`. Overrides list only their own
entries, never the vanilla `CNAM` ones, so the list is **additive**: a plugin pins a location without restating
(or breaking) vanilla or other mods. Seen in 9 installed Creations, e.g. `sfta05.esm` GagarinPlanetData
(0.24367, -1.14525, `SFTA05VillaWorld`), `sfta01.esm` SumatiPlanetData (2 entries in one subrecord),
`kinggathcreations_spaceship.esm` EarthPlanetData. Orbital "planet data" records for space stations carry none.

## Overlay terrain

Each overlay worldspace's `BGSWorldSpaceOverlay_Component` `BNAM` names an `SFBK` surface block
(`OverlayBlock<World>`, `NAM1` 'OverlayBlock') whose `ANAM` is `Data\Terrain\<World>.btd`, `DNAM` the size in
cells (Apollo 3x3, Cydonia 10x10, sfta05 villa 6x6), `ENAM` the height range (-500, 1000) and `FNAM` one u16 per
cell (quantized in that range; looks like the per-cell mean height). Calibrated on Cydonia (3,456 ground objects):
the file's first cell is (-floor(n/2), -floor(n/2)) and heights are absolute worldspace Z (77% within 0.75 m,
median offset 0.00 m), the same convention as New Atlantis. The generated surface outside the block varies per
playthrough; the block is fixed data, so a location that ships its own block has the same ground everywhere.

## Pinning a captured outpost/POI

**Verified in game 2026-10-17** (`examples/demo_overlay_site.py`, PyFieldOverlayTest.esm): a new location on
Luna with its own 3x3-cell block (flat ground, a raised 40 m pad) appeared, landable from the planet map, with the
same terrain in saves of two different characters.


An overlay worldspace with its cells and references, a location under the planet's surface location, an `SFBK`
with a `.btd` fitted to the captured objects (archived), and one `EOVR` entry in an override of the planet. The
latitude/longitude choose the spot; terrain alignment does not depend on them.

## Water (open, 2026-10-17)

- SFBK `WHGT` (f32) is the block's water height in its own frame: -FLT_MAX (no water) for 1,640 blocks incl.
  almost every overlay; procedural lakes/pools/river ends use local levels (-7, -20, -35, -40);
  `OverlayBlockNeonCity` (Volii Alpha ocean city) 195; New Atlantis -500, LC116 -1000 (water switched off).
- The generated ocean's level relative to an overlay's frame is not found in PNDT/BIOM yet. A transplant pinned
  at (0.35, -0.80) on Nesoi (ocean) loaded fully submerged. Planet biome maps (`planetdata/biomemaps/*.biom`:
  u16 0x105, u32 n + n biome FormIDs, u32 2 grids, each u32 w, h, n + n u32 biome ids + u32 n + n u8 resources;
  256 x 256 per hemisphere) show ocean biomes (`OceanLife*`). Projection calibrated 2026-10-17 (below).
- Fast travel from the planet's surface to an overlay location works (verified 2026-10-18 at Selene Home on Nesoi:
  terrain, heights and objects load). An earlier void with no air (2026-10-17) came with a location that had lost
  its `PNAM` parent (copied from a partial override); with the planet's surface location as parent it loads.
- Measured 2026-10-17 (Selene Home at (0.35, -0.80) on Nesoi): the game set the location ~197 m below its
  plugin heights (onto the local seabed); sea surface at +20.6 m in the plugin's frame. An island build (outpost
  and ground lifted 34.6 m, shore fading to the seabed, block `WHGT` = 20.6) still loaded underwater; not
  diagnosed (save cache, re-levelling onto the local surface, or a global ocean level). Islands are shelved
  (`outpost.make_island`, demo `--island` kept, unused by default).

## Biome maps: projection (calibrated 2026-10-17)

Grid 0 = northern hemisphere, grid 1 = southern, each a stereographic disc around its pole:
`r = 0.52 * tan(colatitude / 2)` (fraction of the grid width); north `x = 0.5 + r cos(lon)`, `y = 0.5 - r sin(lon)`;
south mirrored `x = 0.5 - r cos(lon)`, `y = 0.5 - r sin(lon)`. Of the 61 vanilla fixed locations whose worldspace
biome is in their planet's map, 56 land on a cell of their own biome (57 of 65 nats of rarity-weighted evidence;
a typical wrong projection scores 14). Independent in-game check on Nesoi: (0.35, -0.80) is `OceanLife06` (the
transplant there loaded underwater), (-0.517, 2.236) is forest (loaded on land). Scripts:
`tools/calibrate_biome_maps.py`, `refine_biome_projection.py`; code: `games/starfield/biomes.py`; site finder:
`examples/find_outpost_sites.py` (biome filter, `--coast`, preview PNG). A map cell spans tens of km: biome and
coast are regional; exact ground and shoreline are generated on landing.
