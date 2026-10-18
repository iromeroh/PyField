# Entity transplant and asset round-trips — design

Status: implemented 2026-10-15 (`pyfield.transplant`, `pyfield.assets`); copy mode experimental
until the demo plugin is checked in game. Known limits: a copied Wwise bank brings all of its
events (only the needed media are copied), bank IDs collide if source and target load together;
NIF/material files are copied verbatim (asset paths are not renamed).

## Goal

Pick entities from one mod (with their asset files) and put them into another plugin:

- **reference mode** — the target lists the source (and its masters) as masters and uses the
  entities by FormKey; nothing is copied; the source mod must be installed.
- **copy mode** — records are copied into the target with new FormIDs, references among the
  copied records are rewritten, and the asset files they own are copied into the target's
  own archives: a self-contained distribution.

And support full asset round-trips: extract files (with provenance) to a work folder, let
external tools edit them (Blender/PyNifly, Wwise, lip generation — not part of PyField),
then put them back as loose files or into the plugin's BA2 archives.

## Scope (owner decision, 2026-10-15)

Transplant only entities with **clear asset ownership and self-contained definitions**:
statics, movable statics, activators, furniture, lights, doors, misc items, containers,
NPCs with their own appearance records, armor/addons, keywords, globals, form lists,
Wwise events (audio items), recipes. Records whose meaning lives in relationships —
quests, dialogue, scenes, cells/worldspaces, navmesh, locations, packages, ship
blueprints (GBFM) — are reported as **requires rebuild** and never copied.

The policy is per record type and lives in the game adapter
(`transplant_policy`: `copy` | `rebuild`); unknown types default to `rebuild`.

## FormID safety (the core rule)

Raw FormIDs are rewritten only where their position is known: typed FormLinks, and
whole-subrecord FormID members from the xEdit inventory. The planner also scans every
copied subrecord for 4-byte values equal to a source-own FormID:

- at a known position -> remapped;
- at any other position (VMAD properties, structs, components) -> reported as
  `unverified_reference` with signature and offset. Copy is refused unless the plan
  explicitly accepts those positions (`accept_unverified={'VMAD', ...}`), after review.

References to master records keep their raw values; therefore the target's master layout
must match the source's for every master the copied records can address (checked;
otherwise refused). References to source-own records outside the copy set either pull
those records into the closure (if their type is `copy`) or are reported as
`requires_rebuild` dependencies.

Localized strings: copying from a localized plugin into a non-localized one is refused for
records carrying lstring fields (existing guard).

## Asset discovery

`AssetIndex(data_dir, plugins)`: loose files plus BA2 archives (`Starfield - *.ba2` and
`<plugin> - *.ba2` for each plugin, later overriding earlier; loose overrides archives).

Dependencies are found by string scanning **and verified** against the index — a candidate
that does not resolve to an existing file is reported, never assumed:

- record -> files: path-like strings in any subrecord (models, materials, textures, …),
  resolved with root/extension rules (`Meshes/`, `Materials/`, `Textures/`, …);
- NIF -> files: material paths and geometry references (`DogsNCats\Cat_v01` ->
  `geometries/dogsncats/cat_v01.mesh`);
- .mat (JSON) -> files: texture paths and imported shader models;
- WWED -> soundbank: event identity (`WSED`) matched in the bank JSON of the providing
  archive -> `.bnk`, `.json`, and the event's `.wem` media.

Each file is attributed to its provider: the source plugin's archives (**owned**, copied in
copy mode), the base game (**vanilla**, kept as dependency), another plugin (**foreign**,
dependency unless `include_foreign=True`), or loose (**loose**, ask: `include_loose`).

## Packing

Production packing uses the game's `Tools/Archive2/Archive2.exe` (as all workspace
packagers do): `<Plugin> - Main.ba2` (`-format=General`) and `<Plugin> - Textures.ba2`
(`-format=DDS`), uncompressed, then read back with PyField's own reader and compared
member by member. A pure-Python uncompressed GNRL writer exists for tests and as an
`experimental` fallback.

## Round-trip workflow

```
pyfield assets extract  <plugin> <record|asset...> --out work/   # files + manifest.json (provider, sha256)
   ... edit with external tools ...
pyfield assets status   work/                                     # changed / added / unchanged vs manifest
pyfield assets pack     work/ --plugin MyMod.esm --out build/     # BA2s (or --loose), verified
```

Nothing is written into the game Data folder by PyField commands; deployment stays a
separate, explicit step.
