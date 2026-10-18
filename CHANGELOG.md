# Changelog

## Unreleased

## 0.3.0 (2026-10-18): first public release

### Packaging
- Published on PyPI as `pyfield-esm` (imports as `pyfield`); MIT license, with the bundled xEdit-derived
  `xedit_sf1_inventory.json` under MPL-2.0 (`THIRD_PARTY_NOTICES.md`). Documentation site (MkDocs) and GitHub
  Actions: tests (Linux/Windows, Python 3.11-3.13), docs to GitHub Pages, release to PyPI on version tags
  (trusted publishing). Examples and scripts read the game folder from `PYFIELD_STARFIELD_DATA`.

### Added
- `games/starfield/biomes.py`: planet biome maps (`.biom` parse, calibrated stereographic per-hemisphere
  projection, `biome_at(lat, lon)`), `find_sites` (biome filter, away from water and existing fixed locations,
  `coast` option) and `preview_png`; `examples/find_outpost_sites.py`.
- Terrain fit and transplant refinements after in-game review: trusted foundation/pillar columns (extended with
  copies of their `_Mid` segment down to the natural ground instead of raising mounds), structures move the
  ground at most 1.5 m up or down (beyond: attached / embedded, reported), large objects (landing pads) carry
  others without sampling, structures are height targets only away from rocks, slope limiting anchored to the
  natural ground (no rims), snapping capped at 1.5 m, decks keep ground 0.6 m below (no grass through),
  stricter defaults (rock band -0.25/+0.5 m, 2 m fine scale, 50 degree slopes).
- `games/starfield/outpost.py`: outpost/POI transplant (`plan_outpost` -> classify, recentre, fit terrain,
  policies; `build_outpost` -> overlay location from a template pinned on the target planet, fitted terrain,
  one scene per exterior cell, map marker + landing spot with 40 m clearance). Actors and save-created bases
  are skipped and reported; masters are added up front in load order. `overlay.OverlayTemplate.from_world`,
  `pinned_worlds`, `template_for_planet` (cells from the defining plugin). `RuntimeCapture.plugin_files(order)`
  lists full, medium and light slots in load order. Demo `examples/demo_outpost_transplant.py`: Selene ->
  "Selene Home" on Nesoi (1,857 references, 7 masters, 0 validation errors).
- `landscape/fit.py`: terrain fitted to placed objects. Natural objects are height targets; structures are
  height intervals (supports/pillar columns: between column bottom and deck); resting/elevated objects only
  must not be buried. Trend plane + two-scale normalized convolution, slope limit, then smooth projection
  into violated intervals; lone disagreeing objects are reported outliers, never spiked. Object policies
  `terrain` / `snap` (`snap_to_ground`, optional tilt to the slope) / `keep`. Selene outpost (1,858 refs):
  525 loose objects snap (median 0.31 m), 97 structures shape the ground, 8 large outliers reported.
- `games/starfield/overlay.py`: overlay locations, i.e. a new worldspace pinned to a planet position with its
  own terrain (`build_overlay`: WRLD + persistent/exterior cells, LCTN under the planet surface, SFBK surface
  block, additive `EOVR` entry in a planet override; `place_map_marker`; `blank_terrain`). Templates from
  Apollo Landing Site; SFBK `FNAM` decoded as per-cell corner heights (exact on every border cell of Apollo
  and Cydonia). Demo `examples/demo_overlay_site.py` (Luna test site with a raised pad). Scene compiler
  places persistent references into worldspaces owned by the target plugin.
- VMAD fragments and quest aliases (`Vmad.decode(data, signature)` -> `Fragments`, `QuestAlias`):
  QUST stage fragments + alias scripts, INFO/PACK/SCEN (+ phases), PERK/TERM/TMLM. All 2,455
  suffixes in Starfield.esm decode exactly and round-trip; FormID locators take the record type
  (19,186 more known positions, quest alias references included).
- `LoadOrder.strings(language)`, `text(view, sig)`, `display_name(view)`: localized names from
  string tables in each plugin's archives or loose files (any language); adapter `name_signature`.
- `pyfield.games.vmad`: VMAD decoder/encoder (scripts, properties of every type incl. structs,
  struct arrays and variables; fragments/aliases kept verbatim). All 9,042 VMADs in Starfield.esm
  round-trip byte-identically; the Starfield adapter's FormID locator now covers struct members
  (709 VMADs had FormIDs the flat locator missed).
- `pyfield.remap` and `Transaction.override(..., accept_unverified=)`: overrides across different
  master layouts re-encode FormIDs through FormKeys at known positions and add masters; values at
  unknown positions that would change meaning block (`override.remap`) unless accepted. Text
  subrecords are never scanned. `ships.build_ship` remaps templates from any plugin.
- Phase 7 runtime capture: SFSE plugin `sfse/PyFieldCapture` (read-only; console `cgf`
  commands export outposts, ships and areas to `pyfield-capture` JSON) and
  `pyfield.scene.runtime` / `pyfield runtime` (runtime FormIDs -> FormKeys through the
  captured load order, anchor-relative blueprints, save-created bases reported).
- `games/starfield/save.py`: read-only save reader (BCPS container, header, plugin lists,
  FormID array, strings).
- `RecordNode.body_modified()`; header-only edits (e.g. flag bits) now keep the stored
  (possibly compressed) body verbatim instead of re-encoding it.
- `LoadOrder.around(plugin, data_dir)` for plugins outside the data folder (staging copies).
- `validate_plugin(..., baseline_order=)`, `Plugin.source_group_order`: group-order problems
  already in the source are warnings (`groups.order_preexisting`); new ones stay errors.
- Observed subrecord order per record type (`tools/derive_subrecord_order.py`,
  `games/starfield/data/subrecord_order.json`, `RecordSchema.field_order`) used for inserting
  new subrecords, including next to unmodelled fields; `Member.follows` (XRNK after XOWN).
- Diff reports subrecord reordering (`RecordChange.order`).
- `ports/light_liner_cleanup.py`: byte-identical reproduction of the interstellar_liners
  cleanup (see `ports/README.md`).

- Entity transplant (`pyfield.transplant`): reference and copy modes, closure over
  self-contained record types (adapter `transplant_policy`), FormID remapping at known
  positions only (typed members, xEdit whole-FormID members, KWDA arrays, VMAD locator),
  unknown positions blocking unless accepted, rebuild-only references blocking or nulled
  on request (nulled list entries dropped), master-layout check, localization guard.
- Assets (`pyfield.assets`): BA2 reader (GNRL/DX10, LZ4), experimental GNRL writer, asset
  index with game precedence, verified dependency closure (records, NIF length-prefixed
  strings, .mat JSON, Wwise WWED -> soundbank via WSED/GUID), extract/status/pack round trip,
  Archive2 packing with read-back verification, rebuild of a plugin's archives.
- Adapter fields: `inventory_loader`, `formid_array_signatures`, `formid_locators`,
  `transplant_policy`, `asset_rules`, `asset_hooks`. CLI: `assets`, `transplant`.
- `Transaction.commit` creates the output folder.

- Phase 5 scenes (`pyfield.scene`): transforms in the game's placement convention
  (Starfield `Rx(-x)Ry(-y)Rz(-z)`, learned from reference groups), scene graph with stable node
  ids, blueprints (JSON interchange), spatial index (bounds, radius/box/nearest, overlaps), scene
  diff, scene compiler (new interior cells from a template, existing interior/exterior cells,
  100 m exterior grid check, REFR/ACHR, links, enable parents, lock file for stable FormIDs,
  removal of deleted nodes), cell capture into blueprints. CLI `blueprint capture`.
- Adapter fields `rotation_convention`, `exterior_cell_size`, `placeable_types` (31 REFR types
  observed in Starfield.esm + NPC_ -> ACHR).
- `Plugin.add_master` refuses masters that would shift existing own FormIDs
  (`masters.add_shifts_own_ids`).

- Phase 6 landscape: `pyfield.landscape.Heightfield` (world/sample transforms, bilinear
  sampling, normals/slope, stats, profiles, raise/flatten/smooth/blend/conform brushes);
  Starfield `.btd` codec (`games/starfield/btd.py`, versions 4-6, byte-identical roundtrip of all
  1,999 vanilla terrain files, LOD rebuild by decimation, re-quantization, preserved auxiliary
  channel); format notes `docs/formats/starfield-terrain.md`; demo `examples/demo_terrain.py`.

- String tables (`tes4family.StringTables`) and de-localizing copies (`Transaction.strings`).
- Exterior persistent references go to the worldspace persistent cell (`GroupLayout.world_kind`).
- Adapter `override_strip` (Starfield WRLD: RNAM/OFST/CLSZ) and validation `override.foreign_offsets`.
- Phase 6 accepted in game: terrain loaded from a plugin BA2 (hill + tower near New Atlantis).

### Fixed
- WRLD overrides copied RNAM/OFST/CLSZ from the master (crashed the game on travel to the worldspace).
- Starfield native group order: GPOF before GPOG; SCCO, RELA, GWED added (from 20 Bethesda masters).
- New top-level groups go where they introduce the fewest order violations.
- New subrecords were placed after the last *modelled* predecessor only (e.g. XOWN right
  after NAME when unmodelled fields followed).

## 0.2.0.dev0 — 2026-10-14 (Phase 4: public SDK and adapter framework)

### Added
- Adapter protocol pieces `HeaderScheme`, `GroupLayout`; TES4-family implementations in
  `pyfield.games.tes4family`; `ADAPTER_API_VERSION`; entry-point discovery
  (`pyfield.adapters`); `register(..., replace=)` guard.
- Public facade: `open_plugin`, `create_plugin`, `open_load_order`, `__all__`;
  `Plugin.header_counts`.
- `pyfield.games.starfield.records`: typed classes by signature and name.
- Schema versions (`schema_version` 2026.10.1); `RecordSchema.class_name`.
- CLI `schema` command.
- `toy` test adapter, reference package `examples/pyfield-csvgame`.
- Compatibility tooling: `tools/api_surface.py`, `docs/api/surface.txt`,
  `tests/test_public_api.py`, purity test for generic layers.
- Release tooling: `tools/release_check.py`, package data for the xEdit inventory.
- Docs: `docs/api.md`, `docs/adapters.md`, `docs/RELEASING.md`, ADR 0002.

### Changed (breaking for pre-release users)
- `FormatSpec` has no Bethesda defaults; TES4/MODERN specs moved to `games.tes4family`.
- `GameAdapter`: `hedr_versions` -> `header_versions`, `default_hedr_version` ->
  `default_header_version`, `master_list_has_data` -> `Tes4HeaderScheme(...)`,
  `default_form_version` -> `record_header_tail`; new required `header`, `groups`.
- Typed class names: `FormidList` -> `FormIdList`, `PlacedNpc` -> `PlacedNPC`,
  `NonPlayerCharacter` -> `NPC`.

## 0.1.0.dev0 — 2026-10-14

First development cycle (spec §29: inventory, record core, schemas, identity, queries,
transactional writes, validation).

### Phase 0
- Code inventory with reuse decisions, schema inventory (196 Starfield record types mined
  from xEdit), capability matrix, test corpus + baseline over 67 installed plugins,
  ADR 0001.
- Established Starfield FormID namespaces (full / `FD` medium / `FE` small, by master
  header flags), own-ID styles, and the two HEDR count conventions.

### Phase 1 — binary core
- `FormatSpec` for 24-byte (Starfield) and 20-byte (Oblivion) containers.
- Lazy node tree, compact header index, mmap for large files.
- Preserving writer: verbatim unmodified groups/records, re-encoded modified records,
  zlib level reproduction, header maintenance in the file's own convention.
- Roundtrip harness (`raw`, `tree`, `fields`, `encode`); 0 failures over the corpus.

### Phase 2 — typed model and queries
- Codecs (ints, floats with NaN-bit preservation, z/l-strings, FormLinks, flags, enums,
  structs with optional/extra bytes, arrays), record schemas with regions, schema compiler
  with xEdit cross-checks, typed views with in-place subrecord replacement and counters.
- 13 typed Starfield types; 25.1 M values validated byte-exact.
- `LoadOrder`: master kinds, override chains, winners, editor-ID index, reverse
  references, containment vs references, `Query`.

### Phase 3 — safe editing
- `Transaction`: snapshot/rollback, collision-free FormID allocation, new records,
  overrides with owner-chain creation, removal, master management, validated commits
  through temporary files.
- Guards: override refused when master namespaces differ (`override.remap`) or localized
  strings would cross a localization boundary (`strings.localized`).
- Validation report (header, IDs, group order/placement, decode, required members,
  links resolve/exist/type) and semantic diff.
- CLI and two demos.
