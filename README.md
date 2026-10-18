# PyField

Structured, validated read/write access to Bethesda plugin files: Starfield first, Oblivion as the second adapter.
PyField treats game worlds as programmable content: typed records, safe edits, placed scenes, terrain, and whole
outposts or POIs rebuilt as new locations.

```
pip install pyfield-esm
```

The package installs as `pyfield-esm` and imports as `pyfield`. Python 3.11+, no runtime dependencies.
Documentation: <https://iromeroh.github.io/pyfield/>

## What it does

- **Read and write plugins** (`.esm`/`.esp`, light and medium masters) losslessly: unmodified data is written back
  byte for byte (all installed Starfield and Oblivion plugins, 10.2 M records, round-trip identically).
- **Typed records** with descriptive attributes (`stat.model`, `refr.placement.position`), queries across a load
  order, overrides, and FormIDs that stay correct across masters (`FormKey`).
- **Transactions**: every commit writes a temporary file, reparses and validates it, and only then replaces the
  target. Unsupported operations raise `UnsupportedOperation` instead of guessing.
- **Scenes and terrain** (Starfield): place object groups with stable IDs, read and edit `.btd` terrain, fit terrain
  to placed objects.
- **Outposts and POIs as new locations** (Starfield): turn a runtime capture into a fixed location on any planet,
  with its own fitted terrain, a player-home workshop, and pack-in groups and links restored; pick sites from the
  planet's biome map.
- **Ships** (Starfield): rebuild a captured ship as a new ship form.

## Quick start

```python
from pyfield import Plugin
from pyfield.core.loadorder import LoadOrder

DATA = r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data'
with LoadOrder.open(DATA, ['Starfield.esm']) as lo:
    marker = lo.resolve('000034:Starfield.esm')            # typed view of the winning record
    print(marker.editor_id, marker.bounds, marker.model)

    patch = Plugin.create('MyPatch.esm', 'starfield', ['Starfield.esm'], flags=0x1)
    patch.set_master_kinds({'Starfield.esm': 'full'})
    with patch.transaction() as tx:
        g = tx.new_record('GLOB', 'My_Global', value=1.0)
        g.value = 2.0
        tx.commit('build/MyPatch.esm', load_order=LoadOrder(lo.plugins + [patch]))   # validated before writing
```

Command line:

```text
pyfield info PLUGIN | records PLUGIN [-s SIG] [--edid GLOB] | show PLUGIN KEY [--raw]
pyfield roundtrip PLUGIN | validate PLUGIN | diff A B | schema SIG | capabilities | runtime CAPTURE
```

## Examples

Scripts in [`examples/`](examples/) read the game folder from `PYFIELD_STARFIELD_DATA` (default: the Steam path)
and write only under `build/`; nothing is written into the game folder.

| Script | Shows |
|---|---|
| `demo_record_inspector.py` | records, typed views, links, placement paths |
| `demo_safe_patch.py` | a validated patch plugin |
| `demo_scene.py` | placing a scene with stable FormIDs |
| `demo_terrain.py` | editing terrain (`.btd`) and packing it into an archive |
| `demo_transplant.py` | copying entities with their assets into a new plugin |
| `demo_overlay_site.py` | a new fixed location on Luna with its own terrain |
| `find_outpost_sites.py` | candidate sites from a planet's biome map (biome, coast, biome junctions) |
| `demo_outpost_transplant.py` | a captured outpost rebuilt as a player home on another planet |
| `demo_ship_rebuild.py` | a captured ship rebuilt as a new ship form |
| `pyfield-csvgame/` | a third-party adapter package (template for new games) |

Runtime captures (outposts, ships) come from PyFieldCapture, an SFSE plugin maintained as a separate project;
`pyfield.scene.runtime` reads its JSON.

## Development

```
pip install -e ".[test]"
python -m pytest              # tests needing the game skip when PYFIELD_STARFIELD_DATA is not installed
```

See [`docs/RELEASING.md`](docs/RELEASING.md) for the release process and [`CHANGELOG.md`](CHANGELOG.md).

## License

MIT for PyField's code; one bundled data file derived from xEdit is MPL-2.0. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyField contains no game data and is not affiliated with or
endorsed by Bethesda Softworks or ZeniMax.
