# Writing a game adapter

An adapter tells the generic core everything game-specific. The core itself contains no
record signatures or game names (enforced by `tests/test_adapter_protocol.py`).
Protocol version: `pyfield.games.base.ADAPTER_API_VERSION` (currently 1); `register`
refuses adapters built for another version.

## Pieces

| Piece | Type | Decides |
|---|---|---|
| `format` | `pyfield.core.format.FormatSpec` | header sizes, header/group/extended-size signatures, compression flag and level, subrecord size width, editor-ID signature |
| `header` | `pyfield.core.header.HeaderScheme` | reading/writing masters, record count, next object ID, author; file sniffing |
| `groups` | `pyfield.core.groups.GroupLayout` | top-level kind, owner kinds (label = owning record), FormID/grid label kinds, nested top groups |
| `namespaces`, `small_flag`, `medium_flag`, `localized_flag`, `master_flag` | | FormID namespaces and the header flags selecting them |
| `native_group_order` | tuple of signatures | where new top-level groups go (validation `groups.order`) |
| `record_header_tail` | bytes | defaults for header bytes after the common 16 (e.g. form version) |
| `capabilities` | `CapabilitySet` | declared status of every operation |
| `schema_loader`, `schema_version` | callable → `SchemaSet` | typed record classes, versioned |

Fixed core assumptions: headers start with 4-byte signature + u32 size; record headers
then have u32 flags + u32 FormID; group headers a 4-byte label + i32 kind; record sizes
exclude the header, group sizes include it; subrecords are signature + size (+ optional
extended-size field). Formats outside this (e.g. Morrowind's TES3) need a new core reader.

## Built-in adapters

- `starfield` — `games/starfield`: modern TES4-family container, full/medium/small
  namespaces, 13 typed schemas (version `2026.10.1`), xEdit inventory for cross-checks.
- `oblivion` — `games/oblivion`: 20-byte headers, MAST+DATA, single namespace, no schemas yet.
- Shared TES4-family parts: `games/tes4family.py` (`MODERN_FORMAT`, `TES4_FORMAT`,
  `Tes4HeaderScheme`, `MODERN_GROUPS`, `TES4_GROUPS`). A Skyrim or Fallout 4 adapter is
  mostly a new flag set, group order and schemas on top of these.

## Distribution

Adapters can live in their own package and are discovered through the
`pyfield.adapters` entry-point group (an adapter object or a zero-argument factory):

```toml
[project.entry-points."pyfield.adapters"]
csvgame = "pyfield_csvgame:make_adapter"
```

`examples/pyfield-csvgame` is a complete reference package; `tools/release_check.py`
installs it next to PyField in a clean venv and exercises discovery. A failing
third-party adapter produces a warning, never an import error.

## Schemas

Write `RecordSchema`s (see `games/starfield/schema.py`): top-level members in native
order, `Region`s for opaque repeated blocks, `required`/`repeat`/`counter` where the data
demands, an explicit `class_name` when the derived one reads badly, and an `evidence`
string. Pass an inventory (like the xEdit-derived one) to `SchemaSet` to have every member
cross-checked for existence and ambiguity. Validate against real files with
`tools/validate_schemas.py` (byte-identical decode→encode) before declaring
`schema.typed` supported. Bump `schema_version` whenever a layout changes.

## Checklist for a new adapter

1. FormatSpec + HeaderScheme + GroupLayout; `sniff` must reject other games' files.
2. Roundtrip every available file at `fields` level (`tools/phase0_baseline.py` pattern).
3. FormID namespaces verified on real cross-file references.
4. Capabilities declared honestly; unvalidated paths `experimental`.
5. Toy-style end-to-end test: create, edit, override, commit, reopen, validate.
