# Phase 0 — Code inventory and reuse decisions

Surveyed 2026-10-14 in `C:\shared\Starfield` (605 Python files in project `tools/`
folders, plus `Backup/`). Only plugin-format code is listed; asset tooling (Havok, NIF,
audio, Blender, Papyrus build) is out of PyField's scope for now.

## Plugin read/write modules

| Module | Lines | Copies | Does | Limits found | Decision |
|---|---:|---|---|---|---|
| `esm_reader.py` | 98 | bolero, dogs_n_cats, live_off_the_land, ScreenSFSEPlugin (identical) | strict header walk, decompression with size check, `XXXX` reading, record description/hashes | read-only; no FormID semantics | **Replaced** by `core.index`, `core.nodes`, `core.subrecords`. Its strictness (size checks, nested-`XXXX` rejection) is kept. |
| `esm_writer.py` | 146 | live_off_the_land, ScreenSFSEPlugin (A), bolero (B: larger `GROUP_ORDER`) | new-plugin writer, `XXXX` writing, `set_part`/`drop_component_blocks`, minimal VMAD v6 encoder | rejects compressed records; group order is a per-project subset that diverged; HEDR count written as records+groups only | **Replaced** by `Plugin.create`, `core.subrecords.encode`, `RecordNode` (compression supported). Native group order moved to the adapter (full 190-entry list). VMAD encoder: **to adapt** in Phase 2b (`schema.vmad`). |
| `plugin_file.py` | 164 | bolero | in-place upsert preserving everything else; recomputes group sizes, HEDR count, next ID | one level deep (child groups opaque); HEDR count assumes CK convention; next-ID rule ignores the own-prefix encoding | **Adapted**: same contract generalized — any depth, lazy, both count conventions, delta-based header update. |
| `plugin_records.py` | 131 | ship_mechanic | `Node` tree, compressed-record re-encode, `group()` cloning, VMAD helper | asserts instead of errors; whole-file parse into memory | **Replaced** by `core.nodes` (same idea, lazy and error-reporting). |
| `esm_find.py` | 79 | RadioSFSEPlugin | search records by type + model substring, dump/save templates | CLI-only, latin-1 | **Replaced** by `pyfield records/show` and `Query`. |
| `audit_plugin_world.py` | 186 | interstellar_liners | world audit; `full_masters()` small-master handling | rejects medium masters | **Superseded** by the namespaced `FormIdCodec` (handles full/medium/small; verified on 54 plugins). |
| `prepare_key_nova.py` helpers (`Node`, `ensure_group`, `path`, `replace`, `count`) | — | interstellar_liners | CELL hierarchy insertion with size recompute | module writes on import (guide warns) | **Adapted** as `Transaction.override` + `_ensure_path` (owner record before its child group). |
| `Backup/.../clean_vmad.py` | — | interstellar_liners (implicit dependency) | legacy VMAD reader | `value()` skips, returns None | **Not reused**; VMAD gets an explicit decoder later. |

Dependents: 97 project scripts import `esm_reader`/`esm_writer`/`plugin_file`/`plugin_records`
(dogs_n_cats 63, live_off_the_land 21, bolero 10, ScreenSFSEPlugin 3). Another ~70 one-off
`prepare_*`/`build_*` scripts embed their own GRUP walkers. They are left untouched; new
work should use PyField, and old scripts migrate only when they are next changed.

## Knowledge sources

| Source | Use in PyField |
|---|---|
| `interstellar_liners/docs/ESM_RECORD_EDITING_GUIDE.md` (592 lines) | Preservation rules → ADR decisions 3–6, 10; validation checks `groups.order`, `formid.*`, `header.*`. Per-record recipes (XOWN 12 bytes, XLKR, CTDA 32 bytes, VMAD v6/2, GBFM Unique flags, ACUR triplets) → schema backlog. |
| `dogs_n_cats/docs/esm-editing-notes.md`, `RadioSFSEPlugin/docs/OUTPOST_BUILDER_MENUS.md` | Outpost list COBJ flag `0x04000000` (named in the COBJ schema). |
| xEdit `wbDefinitionsSF1.pas` + `wbDefinitionsCommon.pas` (MPL-2.0, `Backup/local_shuttle_*`, sha256 `9f01921a…`) | Mined into `games/starfield/data/xedit_sf1_inventory.json` (196 record types). |
| Installed xEdit 4.1.5f (`C:\shared\xEdit`, SF1/TES4) | External validator for Phase 3 exit criteria (manual). |

## External dependencies and licenses

Runtime: none (Python ≥ 3.11 stdlib). Tests: pytest. Derived data: xEdit inventory (MPL-2.0).
Game data is read in place and never redistributed.
