# Examples

All scripts live in [`examples/`](https://github.com/iromeroh/pyfield/tree/main/examples). They read the
Starfield `Data` folder from the `PYFIELD_STARFIELD_DATA` environment variable (default: the Steam install path) and
write only under `build/`: nothing is ever written into the game folder. Copy a built plugin (and its
`- Main.ba2`, if any) into `Data` yourself to try it in game.

```
set PYFIELD_STARFIELD_DATA=D:\Games\Starfield\Data      (PowerShell: $env:PYFIELD_STARFIELD_DATA = '...')
python examples/demo_record_inspector.py Starfield.esm
```

## Records and patches

**`demo_record_inspector.py`**: load a plugin with its masters, list records, show typed members, follow links
and placement paths.

**`demo_safe_patch.py`**: build a small plugin in a transaction, validate it against the installed load order,
write it through a temporary file, and print a semantic diff against the masters.

## Scenes, terrain, assets

**`demo_scene.py`**: describe a structure in Python (nodes, transforms, links) and compile it into a new interior
cell with stable FormIDs: recompiling an unchanged scene leaves the plugin byte-identical.

**`demo_terrain.py`**: raise a hill in New Atlantis by editing its `.btd` terrain, validate the LODs, place objects
at the edited heights, and pack the terrain into the plugin's archive (needs the Creation Kit's `Archive2.exe`).

**`demo_transplant.py`**: copy entities with their assets (meshes, materials, sounds) from one plugin into a new,
self-contained plugin. It is written against a specific source plugin; change `SOURCE` and the keys to your own.

## Locations and outposts

**`demo_overlay_site.py`**: a new fixed location on Luna: worldspace, location, surface block, its own terrain
(a raised pad) and a map marker, pinned to the planet with an additive `EOVR` entry.

**`find_outpost_sites.py`**: candidate coordinates from a planet's biome map:

```
python examples/find_outpost_sites.py --planet NesoiPlanetData --biome Savanna
python examples/find_outpost_sites.py --planet NesoiPlanetData --coast           # where land meets water
python examples/find_outpost_sites.py --planet NesoiPlanetData --mix 3           # three land biomes meet
```

It writes a preview PNG of both hemispheres with the candidates marked. A map cell spans tens of kilometres:
biome and coast are regional, the exact ground is generated when you land.

**`demo_outpost_transplant.py`**: a captured outpost rebuilt as a fixed location on another planet: terrain fitted
to the objects (rocks as height targets, structures as height intervals, pillar columns extended to the ground),
object policies (terrain / snap / keep), links and pack-in groups restored, and with `--home` a player-home workshop
(builder menu, power) claimed on arrival.

```
python examples/demo_outpost_transplant.py --capture Selene.json --planet NesoiPlanetData \
    --lat -0.0338 --lon -2.5665 --world-biome SavannaLife10 --home
```

Captures come from PyFieldCapture, an SFSE plugin maintained as a separate project.

## Ships

**`demo_ship_rebuild.py`**: a captured ship rebuilt as a new ship form from its modules; stat variants are chosen
by player level. Use a new `--form-id` per ship.

## Adapters

**`pyfield-csvgame/`**: a complete third-party adapter package for a toy format. Install it next to PyField and
it is discovered through entry points; use it as the template for supporting another game.
