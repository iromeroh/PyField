# ADR 0002 — Adapter protocol and API stability

Status: accepted (2026-10-14). Phase 4.

## Decisions

1. **Game knowledge moves behind three adapter-supplied objects.** `HeaderScheme`
   (header record: masters, counts, author, sniffing), `GroupLayout` (meaning of group
   kinds/labels) and an explicit `FormatSpec` (no Bethesda defaults). The TES4 family's
   implementations live in `games/tes4family.py`, shared by Starfield and Oblivion.
2. **Purity is tested, not promised.** `test_generic_layers_have_no_game_literals`
   parses the generic modules and fails on any record signature or game name in code
   (docstrings exempt).
3. **A deliberately alien format proves genericity.** The `toy` adapter (16-byte headers,
   `BOX_` groups with top kind 7, u32 subrecord sizes, no extended size, compression bit
   0x1, non-TES4 header record) runs the whole stack: create, transactions, overrides
   with owner chains, containment, editor IDs, validation, detection, roundtrip.
4. **Adapters are distributable separately** through the `pyfield.adapters` entry point;
   registration checks `ADAPTER_API_VERSION` and refuses silent replacement.
5. **The public API is a recorded surface.** `pyfield.__all__` plus the adapter protocol
   are snapshotted in `docs/api/surface.txt`; a test fails on any difference. Changes
   are deliberate (`tools/api_surface.py --write` + changelog).
6. **Schemas are versioned** (`adapter.schema_version`, `SchemaSet.version`), and typed
   classes get stable explicit names where the derived ones read badly
   (`FormIdList`, `PlacedNPC`, `NPC`), exposed by signature and name in
   `pyfield.games.starfield.records`.
7. **Releases are verified from wheels**, in a clean venv, together with the reference
   third-party adapter (`tools/release_check.py`).

## Consequences

- Adding Skyrim/Fallout 4 is configuration plus schemas on `tes4family`.
- Morrowind (TES3) does not fit the fixed 16-byte header prefix and would need its own
  core reader; this is documented rather than hidden.
- `Plugin.hedr` remains as an alias of the generic `Plugin.header_counts`.
