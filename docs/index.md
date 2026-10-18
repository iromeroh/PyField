# PyField

Structured, validated read/write access to Bethesda plugin files: Starfield first, Oblivion as the second adapter.
PyField treats game worlds as programmable content: typed records, safe edits, placed scenes, terrain, and whole
outposts or POIs rebuilt as new locations.

```
pip install pyfield-esm
```

The package installs as `pyfield-esm` and imports as `pyfield`. Python 3.11+, no runtime dependencies.

## Start here

- [SDK guide](api.md): opening plugins and load orders, typed records, identity (`FormKey`), editing in
  transactions, validation and diffs, the command line.
- [Examples](examples.md): runnable scripts, from a record inspector to a full outpost transplant.
- [Writing adapters](adapters.md): support another game as a separate package.

## Guarantees

- Unmodified data is written back byte for byte.
- Typed members replace only their own subrecord; unknown subrecords are kept in order.
- FormIDs are converted only at schema-known positions, never by pattern matching.
- Commits validate a reparsed temporary file before replacing the target.
- Unsupported operations raise `UnsupportedOperation` naming the capability.

## Starfield format notes

The format pages document what PyField decoded and verified against the installed game, with the evidence: FormID
namespaces, placement conventions, terrain files, fixed planet locations and biome maps, ship blueprints, and the
runtime memory layout used by captures.

PyField contains no game data and is not affiliated with or endorsed by Bethesda Softworks or ZeniMax.
