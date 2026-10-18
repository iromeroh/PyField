# Ports of existing workspace builders

Each port re-implements a proven legacy builder with PyField and is checked against that
builder's preserved output. Ports read their inputs (bundles, game Data) read-only and write
only under `PyField/build/`.

## light_liner_cleanup.py — interstellar_liners `prepare_light_liner_cleanup.py`

Input: the Oct 11 bundle `interstellar_liners/build/light_liner_cleanup_20261011_205353`
(`before/Data/last_mile_shuttle.esp`, CK-saved, 21,315 records, 334 groups) plus the masters
in Data. Steps: GBFM/CELL Unique bits, LCTN ACUR triplets, captain-faction ownership in the
ships' linked interiors, ESM derivation (flags 0x401, INCC, 02-prefixed next ID).

Results (2026-10-15):

| Run | ESP vs legacy | ESM vs legacy | Other |
|---|---|---|---|
| `--legacy-placement` | **byte-identical file** | **byte-identical file** | validation 0 errors (43,207 links), idempotent |
| default | 20,768 / 21,315 records identical; the 547 changed REFRs differ only in subrecord position | same | same ownership counts (CONT 3, MISC 372, ALCH 169, LVLI 3), interiors, INCC 43 |

Placement difference: the legacy rule inserts `XOWN XRNK` before the first `XLYR`/`XLCN`/`DATA`;
PyField's default follows the order learned from Bethesda masters, where `XLYR` precedes
`XOWN` in 17,389 of 18,647 vanilla references that have both. Both forms occur in vanilla.

What the port changed in PyField: native group order taken from 20 Bethesda masters
(GPOF before GPOG; SCCO, RELA, GWED added); pre-existing group disorder is a warning, new
disorder an error; header-only edits keep stored bodies; observed subrecord order for
insertion (`tools/derive_subrecord_order.py`) and `Member.follows` anchoring; diff reports
reordering; `LoadOrder.around` for staging copies.
