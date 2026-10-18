# Binary format capability matrix

Status as of 2026-10-14 (v0.1.0.dev0). Legend: ✅ supported with corpus evidence ·
🟡 experimental / partial · ⛔ not implemented (raises `UnsupportedOperation` or is opaque).
The authoritative, machine-readable version is `pyfield capabilities`.

| Capability | Starfield | Oblivion | Previous workspace tools | Evidence |
|---|---|---|---|---|
| Header-only index of any plugin | ✅ | ✅ | ✅ (eager, in memory) | 67 files / 10.2 M records |
| Lazy group expansion, mmap for large files | ✅ | ✅ | ⛔ | Starfield.esm index 1.9–3.6 s |
| Unmodified roundtrip, byte-identical | ✅ | ✅ | partial (`plugin_file`) | all 67 files |
| Subrecord parse/encode incl. `XXXX` | ✅ | ✅ | read ✅ / write in `esm_writer` only | all records of all 67 files |
| Compressed records: read | ✅ | ✅ | ✅ | |
| Compressed records: write | ✅ (level 9) | ✅ (level 6) | ⛔ (`esm_writer`) / ✅ (`plugin_records`) | level reproduces 100% of sampled master streams |
| Group tree edits with size recompute | ✅ any depth | ✅ | one level (`plugin_file`) | unit tests |
| HEDR count/next-ID maintenance | ✅ both conventions | ✅ | CK convention only | unit tests + corpus conventions |
| Native top-level group order on insert | ✅ (190 sigs) | ✅ (UESP list) | per-project subsets | validation `groups.order` |
| FormKey identity, full masters | ✅ | ✅ | file-relative only | |
| Medium (`FD`) / small (`FE`) namespaces | ✅ | n/a | small only, medium rejected | 54 plugins, 0 unresolved header IDs |
| References into CK-saved medium/small plugins | 🟡 | n/a | ⛔ | not yet observed |
| Load order, override chains | ✅ | ✅ (same core) | ⛔ | unit tests + real shuttle overrides |
| Containment vs references | ✅ | ✅ | ⛔ | unit tests |
| Editor-ID index without decoding records | ✅ | ✅ | ⛔ | Starfield.esm ~9 s |
| Typed records | ✅ 13 types | ⛔ | ad-hoc per script | 25.1 M values byte-exact |
| Localized strings (`.strings`) | ⛔ ids only | n/a | ⛔ | |
| VMAD decode/encode | ⛔ opaque | n/a | minimal encoder | backlog |
| Copy/override across plugins | ✅ when namespaces match; ⛔ remap | ✅ | manual | unit tests |
| Transactions, rollback, validated commit | ✅ | ✅ | ⛔ (backup bundles by hand) | unit tests |
| Validation report | ✅ | ✅ (structural) | per-script asserts | unit tests |
| Semantic diff | ✅ | ✅ | per-script | unit tests |
| In-game load of a PyField-written plugin | 🟡 pending manual test | 🟡 | ✅ (many mods) | Phase 3 exit criterion |
| xEdit check of a PyField-written plugin | 🟡 pending manual test | 🟡 | — | Phase 3 exit criterion |
| Scene graph / blueprints / landscape / capture | ⛔ Phases 5–7 | ⛔ | — | |
