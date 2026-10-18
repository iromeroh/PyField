# Starfield placement: rotations, cells and placed types

Established 2026-10-15 from Starfield.esm (`pyfield.scene`, adapter fields
`rotation_convention`, `exterior_cell_size`, `placeable_types`).

## Rotation convention

A placed reference's `DATA` holds position (metres) and three angles (radians). The rotation
matrix is

    R = Rx(−rx) · Ry(−ry) · Rz(−rz)        (right-handed basic rotations, column vectors)

and a child placed relative to a parent is `p = P.p + P.s · P.R · l.p`, `R = P.R · l.R`.

Evidence: reference groups (RFGP). A group's root reference (`RNAM`) is the instantiated copy
of one reference in the pack-in's content cell (`PKIN.CNAM`), and every member satisfies
`world(member) = world(root) ∘ local(root)⁻¹ ∘ local(member)`. Over 514 members, the
negated-angle variants match 425 times vs ≤ 254 for positive angles, and among the 48 members
whose instance is tilted, order XYZ matches 33 vs ≤ 22 for any other order. Consequence: a
positive yaw turns objects clockwise seen from above (+90° maps local +X to world −Y).

## Cells

- Exterior cells are 100 × 100 m (46,431 / 46,431 references in 300 cells away from the origin
  fit `floor(x / 100), floor(y / 100) == XCLC grid`).
- Interior cells are grouped by local FormID: block = id mod 10, sub-block = (id / 10) mod 10
  (11,985 / 11,985 interior cells).
- A cell's references live in its children group (kind 6, label = cell FormID), split into
  persistent (8) and temporary (9) groups.

## Placed types

REFR places 31 base types in Starfield.esm (STAT, PDCL, MSTT, LIGH, MISC, PKIN, FURN, BMMO,
ACTI, SOUN, ALCH, LVLI, BNDS, DOOR, CONT, ASPC, IDLM, FLOR, LVLP, BOOK, SECH, TERM, AOPF, GBFM,
ARMO, WEAP, KEYM, AMMO, TXST, SCOL, GRAS); ACHR places only NPC_.

## Round trip

`capture_cell` + `compile_scene` reproduce all 3,196 references of cell AACTEST (0E6E45)
with identical positions and rotation matrices within 3e-7.
