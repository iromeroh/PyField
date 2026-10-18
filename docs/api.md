# PyField SDK guide

The stable API is what `import pyfield` exports (`pyfield.__all__`), recorded in
[`api/surface.txt`](api/surface.txt) and checked by `tests/test_public_api.py`.
Game-specific typed classes come from the adapter, e.g. `pyfield.games.starfield.records`.

## Opening data

```python
import pyfield

p = pyfield.open_plugin(r'...\Data\last_mile_shuttle.esm')     # one file; game detected from header
lo = pyfield.open_load_order(r'...\Data', ['last_mile_shuttle.esm'])   # + masters, in order
```

`Plugin` is lazy: opening reads the header and the top-level group list. `plugin.index`
is a header-only scan (Starfield.esm ≈ 2–4 s); groups expand when visited. Use plugins
as context managers (or `close()`) so large memory-mapped masters are released.

| Need | Call |
|---|---|
| header facts | `p.masters`, `p.kind` (full/medium/small), `p.is_localized`, `p.header_counts`, `p.author` |
| every record of some types | `p.records('REFR', 'ACHR')` → `RecordNode`; `p.typed_records(...)` → typed views |
| by raw (file-relative) FormID | `p.find(0x0200ABCD)` |
| by identity | `p.get(FormKey('Starfield.esm', 0x34))` |
| counts per type | `p.index.signature_counts()` |

## Identity

`FormKey(plugin, local_id)` names a record independently of load order; text form
`000034:starfield.esm` (`FormKey.parse`). Each plugin's `codec` converts raw FormIDs
(`p.form_key(raw)`, `p.raw_form_id(key)`), including Starfield's medium (`FD`) and
small (`FE`) namespaces. Undecodable values become `Unresolved(raw)` and are preserved.

## Typed records

```python
from pyfield.games.starfield import records
stat = lo.resolve('000034:Starfield.esm')        # winning version, typed
isinstance(stat, records.STAT)                   # also records.Static
stat.model, stat.bounds.max.z, stat.editor_id
stat.model = r'Meshes\Markers\Other.nif'         # replaces only the MODL subrecord
b = stat.bounds; b.max.z = 2.0; stat.bounds = b  # struct values are copies: assign back
```

Rules:

- Attribute names are descriptive (`placement`, not `DATA`); `pyfield schema SIG` lists
  each attribute with its binary signature and layout.
- Assigning `None` removes an optional subrecord; required ones raise `SchemaError`.
- Count fields (`KSIZ`, `COCT`) follow their lists automatically.
- `view.node.fields` is the ordered raw subrecord list; anything without a schema is
  available (and preserved) there. `view.unknown_signatures()` lists it.
- `view.links()` yields every FormLink (path, target); `view.to_dict()` is a plain dump.
- Localized plugins return `StringRef(id)` for names; string tables are not read yet.

## Load orders and queries

```python
lo.overrides(key)          # [(plugin, node)] in load order; first = defining plugin
lo.resolve(key)            # typed winner
lo.find_editor_id('XMarkerHeading')
lo.query('REFR').references(key).in_plugins('MyMod.esm').where(lambda r: r.scale).list(20)
lo.container_of(view)      # physical owner, e.g. ('cell_children', FormKey of the CELL)
lo.placement_path(view)    # group chain with readable labels
lo.build_reverse_index(); lo.referenced_by(key)
```

## Editing

```python
plugin = pyfield.create_plugin('MyMod.esm', 'starfield', ['Starfield.esm'], flags=0x1,
                               master_kinds={'Starfield.esm': 'full'})
with plugin.transaction() as tx:                  # an exception inside rolls everything back
    kw = tx.new_record('KYWD', 'My_Keyword', color={'r': 0, 'g': 0, 'b': 0, 'a': 0},
                       keyword_type=0, unknown_fnam=bytes(4))
    marker = tx.override(lo.resolve('000034:Starfield.esm'))   # copies container chain if needed
    marker.model = r'Meshes\x.nif'
    tx.remove(some_view)
    report = tx.commit('build/MyMod.esm', load_order=pyfield.LoadOrder(lo.plugins + [plugin]))
```

- New FormIDs are above both the header's next ID and the highest existing own ID.
- `commit` writes a temporary file, reparses and validates it, then replaces the target;
  on errors it raises `ValidationError(report)` and the target is untouched.
  `backup_dir=` keeps a timestamped copy of the replaced file.
- Refused with `UnsupportedOperation`: copying when master layouts differ
  (`override.remap`) or when localized strings would cross a localization boundary
  (`strings.localized`). Check `adapter.capabilities` up front.

## Validation and diffs

`pyfield.validate_plugin(p, load_order=lo)` → `Report` (`errors`, `warnings`, `stats`,
`to_dict()`); codes are stable (`groups.order`, `formid.duplicate`, `link.missing`, …).
`pyfield.diff_plugins(before, after)` → `Diff` with added/removed/changed records and
member-level before/after values.

## Command line

`pyfield info | records | show | schema | roundtrip | validate | diff | capabilities`
(`python -m pyfield.cli --help`).
