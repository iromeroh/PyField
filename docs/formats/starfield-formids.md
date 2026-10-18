# Starfield file-relative FormIDs and plugin header conventions

Established empirically on 2026-10-14 from the 54 installed Starfield plugins
(`tools/phase0_baseline.py`; probe scripts in the session notes). Implemented in
`pyfield.core.formids.FormIdCodec` and `pyfield.core.plugin`.

## Master namespaces

Each master is classified by **its own** TES4 header flags (not by the referencing file):
`0x100` small, `0x400` medium, otherwise full. A raw FormID in a file decodes as:

| High byte | Layout | Target |
|---|---|---|
| `00`–`FC` | `II LLLLLL` | full master #II (counting full masters only, in MAST order); `II == #full` → this file |
| `FD` | `FD II LLLL` | medium master #II (medium masters only); `II == #medium` and this file is medium → this file |
| `FE` | `FE III LLL` | small master #III; `III == #small` and this file is small → this file |

Evidence:

- `last_mile_shuttle.esm` masters `Starfield, sfbgs00d, SFBGS004(small), SFBGS047(small)`:
  own records `02xxxxxx` (two full masters), not `04`.
- `kinggathcreations_spaceship.esm` (8 masters, 2 full, 4 small, 2 medium): own `02…`,
  base object `FD000050` → `sfbgs003.esm` (medium #0).
- `sfta01.esm` (medium, masters `starfield`, `sfbgs003`(medium)): references `FD00…` to
  sfbgs003 and its own records `FD01…`.
- `SFBGS004.esm` (small): own records `FE000…`.

## Own-record style

- **compact**: Bethesda-built medium/small masters store own records in their namespace
  (`FD01…`, `FE000…`), with HEDR next ID `FF001000`.
- **ordinal**: Creation-Kit-saved user plugins keep `II LLLLLL` own IDs even when flagged
  medium (`live_off_the_land.esm` 0x401 → `01…`) or small (`du_overtime.esm` 0x101 → `01…`).

Both decode; encoding uses the style detected from the file. New plugins use ordinal.
**Open question:** how other plugins reference *into* a CK-saved medium/small plugin
(capability `formid.user_medium_as_master`, experimental).

## HEDR record count

| Convention | Value | Seen in |
|---|---|---|
| records+groups | all records and groups except TES4 | 34 CK-saved Starfield plugins, all 13 Oblivion files |
| records+1 | records including TES4, groups not counted | 20 Bethesda-built Starfield masters (Starfield.esm, ShatteredSpace, SFBGS*, sfta*) |

PyField keeps each file's convention and shifts the stored value by the edit delta.

## Other header facts

- Starfield MAST entries have no DATA companion; Oblivion's do (8 zero bytes).
- Record header bytes 16–23 (Starfield): u32 version control, u16 form version (582 in
  current CK output, 581 in Starfield.esm), u16 unknown. Preserved opaque.
- zlib level: 9 reproduces Bethesda Starfield streams; 6 reproduces Oblivion streams.
  CK-saved user plugins are mixed (61 of 132 compressed records in last_mile_shuttle.esm
  match no standard level); unmodified records are copied verbatim, so this never matters
  for preservation.
