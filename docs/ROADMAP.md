# Roadmap and exit-criteria status

## Phase 0 — Audit ✅
| Exit criterion | Status |
|---|---|
| Reviewed design exists | ADR 0001 (review by owner pending) |
| An existing read/write path selected for integration | `plugin_file.py` (bolero) upsert contract generalized into `Plugin`/`Transaction`; reader strictness from `esm_reader.py` |

## Phase 1 — Binary core ✅
| Exit criterion | Status |
|---|---|
| Real plugins can be indexed | all 67 installed plugins |
| Records decode as raw containers | every record of every plugin |
| No-change roundtrip byte-identical | all 67 (Starfield.esm incl. full decode) |
| Unrecognized data preserved | by construction + typed-edit tests |

## Phase 2 — Typed model and queries ✅ (first subset)
| Exit criterion | Status |
|---|---|
| Records as Python objects | 13 typed types; generic views for the rest |
| References resolve across plugins | yes (FD/FE namespaces included) |
| Override chains correct | unit tests + real shuttle overrides |
| Queries consistent | unit tests |
| Containment separate from references | `container_of` / `placement_path` vs `links()` |

## Phase 3 — Safe editing (MVP) ✅ accepted 2026-10-14
| Exit criterion | Status |
|---|---|
| Field changed through a property | yes |
| Plugin written and reparsed | yes (commit reparses the temp file) |
| Change visible in xEdit | **passed 2026-10-14** — SF1Edit 4.1.5p loaded PyFieldDemo.esm (CRC32 8657224F) with no messages; all 629 records with load errors were vanilla Starfield.esm (PERK/WEAP/ARMO/KYWD components newer than that xEdit build) |
| Unmodified fields unchanged | yes (tests compare raw bytes) |
| Real test mod loads in game | **passed 2026-10-14** — PyFieldDemo.esm enabled; console `help PyFieldDemo 4` lists the new records (`show <name>` cannot be used: Starfield does not keep global editor IDs at runtime; value check via `GetGlobalValue <FormID>`) |
| Failed validation does not overwrite source | yes (test) |

## Phase 4 — Public SDK and adapter framework ✅
| Exit criterion | Status |
|---|---|
| Starfield works through a registered adapter | yes (all layers go through `GameAdapter`) |
| Generic core has no Starfield assumptions | enforced by an AST purity test over core/schema/edit/validate/diff |
| A minimal test adapter demonstrates another format | `toy` (in-tree) and `csvgame` (separate package via entry point) |
| Public APIs have compatibility tests | recorded surface + `test_public_api.py`; wheel-installed test run |

Milestone **PyField 1.0** now waits only for an owner
review of the recorded API surface (`docs/api/surface.txt`); the version stays
0.2.0.dev0 until then.

## Phase 5 — Scenes, spatial records, blueprints ✅ accepted 2026-10-15
| Exit criterion | Status |
|---|---|
| A small structure described entirely in Python | `examples/demo_scene.py` (floor, COC marker, light, 3 blueprint instances incl. tilted) |
| Compiles into valid plugin records | 13 records, validation 0 errors |
| Appears at the intended in-game location | **passed 2026-10-15** — `coc PyFieldSceneTest`: all three stacks in place; the tilted stack's upper pieces stay seated on the tilted table (docs/evidence/phase5_scene_test_20261015.jpg) |
| Correct transforms and references | convention from 514 reference-group members; 3,196-ref capture round trip exact; links/enable parents tested |
| Rebuild without changes preserves identities | byte-identical plugin and lock on recompile; a move changes only the moved records |

## Phase 6 — Landscape authoring ✅ accepted 2026-10-15 (heights; texturing not decoded)
| Exit criterion | Status |
|---|---|
| A native landscape fixture can be imported | all 1,999 `.btd` files parse; New Atlantis/Akila City decode to heightfields |
| Geometry reconstructed consistently | world mapping calibrated with placed ground objects (56.4% vs ≤ 8.7% for alternatives); LODs are exact decimations |
| A controlled modification can be exported | 10 m hill, validated (no change outside radius, aux untouched, LODs and ranges consistent), packaged as BA2 |
| The changed landscape is visible in game | **passed 2026-10-15** — owner: "the hill is there and there's a brick tower" (terrain loaded from the plugin's BA2; tower placed at the decoded summit height sits on the ground; docs/evidence/phase6_terrain_tower_*.jpg). Finding: procedural biome flora follows the edited terrain but grows through placed objects (exclusion not yet modelled). Earlier crashes: a void teleport (`coc NewAtlantis` = worldspace) and a WRLD override carrying RNAM/OFST/CLSZ (fixed, now stripped and validated) |
| Surrounding terrain and material transitions inspected/validated | smooth falloff, previews, profile; texture channel untouched (texturing itself not decoded) |

## Phase 7 — Runtime capture of ships and outposts 🚧 (in-game test pending)
Decision 2026-10-16 (owner): capture through an SFSE plugin instead of decoding save change forms.
Save decoding stays read-only and partial (`games/starfield/save.py`: container, header, plugins,
strings, ship registry names); change-form framing is not documented and changes between patches.

| Exit criterion | Status |
|---|---|
| Player-run capture of a named ship and outpost | `sfse/PyFieldCapture`: console `cgf "PyFieldCapture.Outpost"/"Ship"/"Area"` -> `pyfield-capture` JSON; DLL + script build; in-game run pending (`sfse/PyFieldCapture/docs/CAPTURE_TEST.md`) |
| Off-game conversion to PyField structures | `pyfield.scene.runtime`: load-order resolution of runtime FormIDs, anchor-relative blueprints, save-created bases reported (`pyfield runtime`); unit-tested |
| Captured outpost/ship rebuilt as a plugin and seen in game | **ship: spawned, landed, owned, correct shape (2026-10-16)**; open: weapon bindings, module attachment/shield, navmesh, paint, door lock (docs/formats/starfield-ship-blueprint.md). Outpost: blueprint; **overlay location with own terrain seen in game, identical in two characters' saves (2026-10-17)** (`overlay.py`, `examples/demo_overlay_site.py`). **Selene outpost transplanted to Nesoi as a fixed location with fitted terrain, seen in game 2026-10-17** (`outpost.py`, `landscape/fit.py`, site picked with `biomes.py` at a coast/biome junction; extractor columns extended down to the ground). Open: workshop (beacon, power for lamps/machines, builder edits), object LOD for the new worldspace (not generated), islands (shelved) |

## Next cycle (priority order)
1. ✅ Real workflow port: interstellar_liners light-liner cleanup reproduced byte-identically
   on last_mile_shuttle (`ports/README.md`). Next ports when those builders are touched again.
2. Phase 5 (scenes, placed objects, blueprints) on top of the typed REFR/CELL/WRLD layer.
   Groundwork done: entity transplant + asset round trips (docs/design/entity-transplant-and-assets.md);
   copy mode awaits an in-game check of build/transplant_demo/PyFieldTransplantDemo.esm.
3. Schemas: VMAD done (script properties, fragments, quest aliases; games/vmad.py); string tables read (LoadOrder.text). Next: string-table writing (localize a mod: extract texts, per-language tables); typed GBFM/LVLB members; conditions, QUST aliases/stages,
   INFO responses, TMLM, PERK entries, GBFM components; `.strings` reader.
4. Index cache on disk for large masters (editor-ID/FormID tables keyed by file hash).
5. Small research prototypes (spec §29): LAND heightfield reader (Phase 6), Summerset
   worldspace reading via the Oblivion adapter (Phase 10, track A).

## Known limits
- Landed ships in outpost transplants: copied as static pieces (`Rules.include_ships`) they fall apart (havok pieces and clutter come loose, 2026-10-18). Working route ACCEPTED in game 2026-10-18: a ship capture rebuilt as a GBFM (template's BGSFormLinkData_Component dropped) lands on the home's pad via GiveShip, shows its own shape, can be boarded, claimed, edited and renamed. Owner decision 2026-10-18: outpost transplants copy constructions only (no ships, default); the static ship copy stays WIP (`--keep-ships`); ships are copied with the ship pipeline and obtained by command (`PyFieldCapture.GiveShip`). Parking a ship in the home plugin is not planned.
- Partial overrides: newer Bethesda plugins override some records with deltas the engine merges (SFBGS050.esm: LC159WorldLocation with only ACSR/ACID/ACEP; planet EOVR lists). `LoadOrder.resolve()` returns such a delta as the winner; templates must be copied from the defining plugin (`overlay.defining`). A merged view of delta overrides is not implemented.
- `override.remap`: top-level records are remapped across master layouts (remap.py: known positions re-encoded, unknown-position values that would change meaning block unless accepted). Still raw-only: records inside CELL/WRLD/DIAL/QUST containers; `NVNM` navmesh blobs block (layout not decoded; xEdit documents edge links and door refs).
- `strings.localized`: no string tables; lstrings are ids in localized plugins.
- References into CK-saved medium/small plugins not yet observed (experimental).
- Writing a 1.5 GB master works but is memory-heavy once many groups are expanded.
- Morrowind (TES3) does not fit the core's fixed header prefix (ADR 0002).
