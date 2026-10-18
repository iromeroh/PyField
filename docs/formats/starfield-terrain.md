# Starfield terrain (.btd) and how planets are assembled

Decoded 2026-10-15 from the installed game (`pyfield.games.starfield.btd`). Evidence scripts
are summarized below; every statement was checked against real files.

## Where terrain lives

- Plugins contain **no LAND records** (Starfield.esm, ShatteredSpace.esm, SFBGS00D.esm: 0).
- Heights are `.btd` files in `Starfield - Terrain01..04.ba2` and `Starfield - TerrainPatch.ba2`
  (1,999 files, 15.45 GB).
- Records arrange them: **SFBK** Surface Block (→ `.btd` via ANAM, size in cells, height range,
  edge connection codes, water height), **SFPT** Surface Pattern (grid of blocks + rotations),
  **SFTR** Surface Tree (one per planet: 256 × 256 pattern FormIDs + rotation bytes, two layers),
  **PCMT/PCBN/PCCN** planet content managers (which POI content goes where).
- Hand-built areas freeze a finite patch: fixed worldspaces (New Atlantis 14 × 14 cells, Akila
  City 9 × 9) have `terrain/<worldspace>.btd`; overlay blocks (`OverlayBlock…`, 3–5 cells) stamp
  hand-made terrain into a procedural surface.

## File layout (versions 4, 5, 6 — identical)

```
0   'BTDB'  u32 version  f32 height_min  f32 height_max  u32 width  u32 height   (samples)
24  4 × u32 (zero)
40  u32 n_ltex,  n_ltex × u32 LTEX FormIDs
..  cells × (f32 min, f32 max)       per-cell height range, row-major
..  cells × 288 bytes                opaque (small per-cell index lists; texture palettes) — preserved
..  chunks × (u32 offset, u32 size)  offsets relative to the chunk chain
..  chunks × zlib → 65,536 bytes     128×128 u16 heights, then 128×128 u16 auxiliary
```

- width = height = cells × 128 (all files). Height = height_min + u16/65535 · (max − min).
- Chunks: 4 LOD levels, coarsest first; level k has ⌈cells / 2^k⌉² chunks covering 2^k cells each,
  **exact decimation** of LOD0 (100% of samples), zero-padded beyond the edge. The auxiliary
  channel is decimated the same way; its meaning is not decoded (probably texture blending).
- All 1,999 files: 4 levels, 288 bytes/cell; parse + serialize byte-identical.

## World mapping

- 128 samples per 100 m cell, sample i at the cell corner + i · 0.78125 m; rows toward +y.
- The file's first cell is (−⌊cells/2⌋, −⌊cells/2⌋) in the worldspace grid: (−7, −7) for New
  Atlantis, (−4, −4) for Akila City. Calibrated with ground objects (rocks, boulders, flora):
  New Atlantis 56.4% of 1,705 within 0.75 m vs ≤ 8.7% for any other origin/orientation;
  Akila City 22.6% of 3,872 vs ≤ 7.7%.

## Writing

Edits re-quantize only touched cells (expanding the file range and re-quantizing everything if
an edit exceeds it), rebuild the coarse LOD chunks by decimation, update per-cell ranges, keep
the auxiliary channel and all untouched chunks' compressed bytes. Demo:
`examples/demo_terrain.py` (10 m hill, 4 of 265 chunks re-encoded, all checks pass).
