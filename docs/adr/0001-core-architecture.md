# ADR 0001 — PyField core architecture

Status: accepted (2026-10-14). Phase 0 deliverable.

## Context

Seven Starfield projects in `C:\shared\Starfield` edit plugins with small, copied helper
modules (see [code inventory](../phase0/code-inventory.md)). They work, but each copy has
different limits (no `XXXX` writing, no compression on write, no master-kind awareness,
appended groups in the wrong order) and the hard-won rules live in prose
(`interstellar_liners/docs/ESM_RECORD_EDITING_GUIDE.md`). PyField replaces those helpers
with one tested library while keeping their proven conventions.

## Decisions

1. **Pure Python, no runtime dependencies** (stdlib `struct`, `zlib`, `mmap`, `array`).
   Every machine with the existing tools can run it; performance is adequate
   (Starfield.esm, 1.46 GB / 3.83 M records: header index 1.9–3.6 s, full subrecord decode
   and byte-identical rewrite 67 s).

2. **Three layers, strictly ordered.**
   - `pyfield.core` — game-agnostic container: `FormatSpec`, lazy node tree, compact index,
     `FormKey` + namespaced `FormIdCodec`, `Plugin`, `LoadOrder`. No record semantics.
   - `pyfield.games.<game>` — adapters: header sizes, master-kind flags, native group order,
     capability declarations, schemas. Registered in `pyfield.games`.
   - `pyfield.schema`, `pyfield.edit`, `pyfield.validate`, `pyfield.diff` — typed views,
     transactions, validation reports, semantic diffs (game-agnostic, schema-driven).
   The Oblivion adapter exists from day one (20-byte headers, MAST+DATA, single namespace)
   to keep the core honest; it roundtrips Oblivion.esm and Summerset unchanged.

3. **Preservation by construction, not by re-serialization.** Nodes keep their source
   bytes. Unexpanded groups and unmodified records are written verbatim (including the
   original zlib stream); only modified records are re-encoded, and group sizes are
   recomputed. Typed views replace only the subrecord being set. Unknown data is never
   decoded into a model it could be lost from.

4. **Ordered subrecord lists are canonical**; dict-like access is a view. Repeated tags
   and their order carry meaning (guide rule).

5. **Stable identity = `FormKey(plugin, local_id)`.** Raw FormIDs are file-relative; a
   per-file codec converts with full/medium (`FD`)/small (`FE`) namespaces derived from
   the masters' *own header flags* (empirically established, see
   [starfield-formids.md](../formats/starfield-formids.md)). Unknown master kinds are
   recorded as assumptions and block validated commits.

6. **Never remap raw integers by guess.** Only schema-known FormLinks are converted.
   Copying a record between files is allowed only when every master namespace maps
   identically; otherwise `UnsupportedOperation('override.remap')`.

7. **Physical containment is separate from references.** `LoadOrder.container_of` /
   `placement_path` read the group tree; `TypedRecord.links()` reads FormLinks.

8. **Schemas are hand-verified Python declarations, cross-checked mechanically.**
   xEdit's Pascal DSL (wbDefinitionsSF1.pas) is mined into a JSON *inventory*
   (`tools/extract_xedit_inventory.py`), not compiled. Each typed member must exist at top
   level in the inventory and be unambiguous there (regions like `BFCB…BFCE` component
   blocks, destruction stages and object templates are opaque), and
   `tools/validate_schemas.py` requires byte-identical decode→encode over real masters.
   The schema compiler generates one Python class per record type with typed properties.

9. **Transactions snapshot cheaply** (unexpanded groups are shared, expanded nodes cloned)
   and roll back on exceptions. Commits write a temporary file, reparse and validate it,
   and only then replace the target; validation errors leave the target untouched.

10. **Header conventions are preserved, not normalized.** HEDR record count is kept in
    the file's own convention (CK: records+groups; Bethesda-built masters: records+1) and
    shifted by the edit delta; the next object ID only advances past new own IDs.

11. **Capabilities are declared per adapter** (`validated`, `supported`, `experimental`,
    `unsupported`) and enforced with `CapabilitySet.require`.

## Licensing

- PyField code: owner's choice pending (marked in `pyproject.toml`).
- `games/starfield/data/xedit_sf1_inventory.json` is derived from xEdit definitions
  (MPL-2.0) and stays under MPL-2.0 terms; it is kept as a separate file for that reason.
  Schemas in `games/starfield/schema.py` restate facts (field layouts) verified against
  game data.

## Consequences

- Reading anything is cheap; editing small plugins is cheap; editing a 1.5 GB master
  works but is not optimized (expanded nodes cost memory).
- Typed coverage grows record by record with evidence; untyped data is still safe.
- Localized strings (`.strings`) and VMAD decoding are explicit gaps (capabilities say so).
- Existing project tools can migrate incrementally: `Plugin`/`RecordNode` cover what
  `esm_reader`, `esm_writer`, `plugin_file` and `plugin_records` do.
