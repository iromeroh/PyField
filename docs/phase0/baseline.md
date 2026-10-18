# Phase 0 — Test corpus and baseline measurements

Generated from `baseline.json` (run `tools/phase0_baseline.py`, 2026-10-14, Python 3.12,
Windows 11, local SSD). Read-only on all inputs.

**Corpus:** every plugin installed in the Starfield `Data` folder (54 files: Bethesda
masters, DLC, Creations, and this workspace's own mods) plus the Oblivion `Data` masters
and the Summerset/Abecean sources in `C:\shared\Oblivion` (13 files).
Total 67 files, 3.26 GB, 10,204,119 records. **Failures: 0.**

Columns: *index* = header-only scan (s); *raw* = open+write unchanged, byte-identical;
*fields* = every record's subrecords decoded and the file rewritten byte-identically
(s in the last column). \* Starfield.esm fields pass run separately
(`starfield_esm_fields.json`: 3,829,246 records, 67.405 s).

Synthetic fixtures (`pyfield.testing.fixtures`) cover the cases the corpus may not:
`XXXX` extended sizes, nested CELL hierarchies, compressed records, both header sizes.

| File | Game | MB | Records | Groups | Kind | HEDR count | Own IDs | Index s | Raw | Fields | Fields s |
|---|---|---:|---:|---:|---|---|---|---:|---|---|---:|
| Starfield.esm | starfield | 1,457.1 | 3,829,246 | 101,341 | full | records+1 | ordinal | 3.572 | yes | yes* | 67.405 |
| ShatteredSpace.esm | starfield | 501.4 | 1,029,528 | 17,747 | full | records+1 | ordinal | 1.12 | yes | yes | 18.147 |
| BlueprintShips-Starfield.esm | starfield | 303.7 | 1,503,332 | 2,404 | full | records+groups | ordinal | 0.971 | yes | yes | 96.199 |
| Oblivion.esm | oblivion | 277.5 | 1,167,016 | 85,079 | full | records+groups | ordinal | 1.004 | yes | yes | 12.49 |
| SFBGS050.esm | starfield | 106.0 | 485,319 | 6,039 | full | records+1 | ordinal | 0.242 | yes | yes | 5.401 |
| SFBGS00D.esm | starfield | 102.1 | 434,990 | 7,005 | full | records+1 | ordinal | 0.244 | yes | yes | 4.838 |
| kinggathcreations_spaceship.esm | starfield | 94.7 | 371,811 | 3,832 | full | records+groups | ordinal | 0.197 | yes | yes | 8.87 |
| Morrowind_ob.esm | oblivion | 83.9 | 431,403 | 28,987 | full | records+groups | ordinal | 0.257 | yes | yes | 4.341 |
| du_takeover.esm | starfield | 55.5 | 56,929 | 2,124 | full | records+groups | ordinal | 0.055 | yes | yes | 1.01 |
| SummersetIsle.esp | oblivion | 42.0 | 192,511 | 20,570 | full | records+groups | ordinal | 0.119 | yes | yes | 2.01 |
| SFBGS003.esm | starfield | 33.3 | 65,475 | 1,437 | medium | records+1 | compact | 0.042 | yes | yes | 0.954 |
| last_mile_shuttle.esm | starfield | 20.2 | 21,315 | 334 | medium | records+groups | ordinal | 0.015 | yes | yes | 0.434 |
| last_mile_shuttle.esp | starfield | 20.2 | 21,315 | 334 | full | records+groups | ordinal | 0.021 | yes | yes | 1.217 |
| sfta01.esm | starfield | 18.6 | 21,850 | 439 | medium | records+1 | compact | 0.021 | yes | yes | 0.355 |
| positivelynewatlantis.esm | starfield | 18.3 | 5,308 | 418 | medium | records+groups | ordinal | 0.012 | yes | yes | 0.271 |
| Better Cities Resources.esm | oblivion | 16.8 | 145,422 | 4,802 | full | records+groups | ordinal | 0.078 | yes | yes | 2.668 |
| BlueprintShips-SFBGS050.esm | starfield | 16.1 | 80,007 | 283 | full | records+groups | ordinal | 0.04 | yes | yes | 1.168 |
| SFBGS008.esm | starfield | 11.3 | 181 | 45 | small | records+1 | compact | 0.007 | yes | yes | 0.157 |
| sfta03.esm | starfield | 11.1 | 45,310 | 938 | medium | records+1 | compact | 0.026 | yes | yes | 1.171 |
| sfta06.esm | starfield | 10.4 | 56,399 | 663 | medium | records+1 | compact | 0.03 | yes | yes | 0.706 |
| sfta04.esm | starfield | 8.9 | 21,375 | 376 | medium | records+1 | compact | 0.016 | yes | yes | 0.295 |
| sfta05.esm | starfield | 7.7 | 20,046 | 508 | medium | records+1 | compact | 0.013 | yes | yes | 0.242 |
| SFBGS006.esm | starfield | 7.3 | 60,921 | 1,177 | medium | records+1 | compact | 0.028 | yes | yes | 0.609 |
| Oscuro's_Oblivion_Overhaul.esm | oblivion | 7.1 | 20,365 | 218 | full | records+groups | ordinal | 0.035 | yes | yes | 0.233 |
| sfta02.esm | starfield | 6.8 | 15,034 | 575 | medium | records+1 | compact | 0.012 | yes | yes | 0.178 |
| bmxoutpost.esm | starfield | 4.8 | 30,322 | 1,778 | full | records+groups | ordinal | 0.02 | yes | yes | 0.222 |
| Cobl Main.esm | oblivion | 4.0 | 4,372 | 48 | full | records+groups | ordinal | 0.011 | yes | yes | 0.048 |
| blueprintships-sfta06.esm | starfield | 3.3 | 17,298 | 34 | full | records+groups | ordinal | 0.009 | yes | yes | 0.4 |
| functionaldecor.esm | starfield | 1.7 | 9,577 | 1,847 | medium | records+groups | ordinal | 0.006 | yes | yes | 0.08 |
| du_overtime.esm | starfield | 1.5 | 793 | 16 | small | records+groups | ordinal | 0.003 | yes | yes | 0.037 |
| aurie_thegangsallhere.esm | starfield | 1.4 | 695 | 74 | full | records+groups | ordinal | 0.014 | yes | yes | 0.027 |
| sfbgs00c.esm | starfield | 1.4 | 2,438 | 692 | small | records+1 | compact | 0.003 | yes | yes | 0.043 |
| blueprintships-sfta03.esm | starfield | 1.0 | 4,986 | 25 | full | records+groups | ordinal | 0.006 | yes | yes | 0.057 |
| TamRes.esm | oblivion | 1.0 | 5,201 | 40 | full | records+groups | ordinal | 0.032 | yes | yes | 1.601 |
| s-47 speeder bike.esm | starfield | 0.8 | 89 | 32 | full | records+groups | ordinal | 0.002 | yes | yes | 0.086 |
| LenasCompanions.esm | oblivion | 0.8 | 5,110 | 154 | full | records+groups | ordinal | 0.008 | yes | yes | 0.032 |
| MergedLOD.esm | oblivion | 0.6 | 6,412 | 1 | full | records+groups | ordinal | 0.015 | yes | yes | 0.031 |
| zakila.esm | starfield | 0.5 | 1,457 | 127 | small | records+groups | ordinal | 0.002 | yes | yes | 0.012 |
| roleplayersalternatestart.esm | starfield | 0.5 | 1,575 | 373 | medium | records+groups | compact | 0.003 | yes | yes | 0.024 |
| SFBGS047.esm | starfield | 0.5 | 42 | 29 | small | records+1 | compact | 0.002 | yes | yes | 0.006 |
| eaa_spacetruckinplus.esm | starfield | 0.4 | 3,113 | 264 | medium | records+groups | ordinal | 0.005 | yes | yes | 0.021 |
| blep_gore_framework.esm | starfield | 0.3 | 412 | 35 | small | records+groups | ordinal | 0.001 | yes | yes | 0.006 |
| Toaster Says Share v3.esm | oblivion | 0.3 | 678 | 121 | full | records+groups | ordinal | 0.009 | yes | yes | 0.007 |
| Abecean.esp | oblivion | 0.3 | 1,813 | 43 | full | records+groups | ordinal | 0.004 | yes | yes | 0.012 |
| SFBGS004.esm | starfield | 0.3 | 891 | 58 | small | records+1 | compact | 0.001 | yes | yes | 0.009 |
| UndergroundExtractors.esm | starfield | 0.2 | 495 | 4 | small | records+groups | ordinal | 0.001 | yes | yes | 0.007 |
| proximacentri.esm | starfield | 0.2 | 18 | 3 | full | records+groups | ordinal | 0.003 | yes | yes | 0.003 |
| dogsncatsmeshprobe.esm | starfield | 0.2 | 508 | 68 | full | records+groups | ordinal | 0.002 | yes | yes | 0.009 |
| useful brigs - free.esm | starfield | 0.1 | 584 | 165 | small | records+groups | ordinal | 0.001 | yes | yes | 0.007 |
| TamRes_LandscapeResource.esm | oblivion | 0.1 | 1,216 | 4 | full | records+groups | ordinal | 0.014 | yes | yes | 0.006 |
| star_radio.esm | starfield | 0.1 | 233 | 29 | small | records+groups | ordinal | 0.001 | yes | yes | 0.003 |
| sfbgs021.esm | starfield | 0.1 | 508 | 43 | small | records+1 | compact | 0.004 | yes | yes | 0.004 |
| non-lethal framework - free.esm | starfield | 0.1 | 55 | 17 | small | records+groups | ordinal | 0.002 | yes | yes | 0.004 |
| Lovers with PK.esm | oblivion | 0.1 | 239 | 14 | full | records+groups | ordinal | 0.006 | yes | yes | 0.002 |
| live_off_the_land.esm | starfield | 0.1 | 176 | 16 | medium | records+groups | ordinal | 0.0 | yes | yes | 0.003 |
| Constellation.esm | starfield | 0.0 | 56 | 7 | small | records+1 | compact | 0.002 | yes | yes | 0.001 |
| bolero.esm | starfield | 0.0 | 36 | 8 | medium | records+groups | ordinal | 0.0 | yes | yes | 0.001 |
| bolero.esp | starfield | 0.0 | 36 | 8 | medium | records+groups | ordinal | 0.002 | yes | yes | 0.001 |
| SFBGS007.esm | starfield | 0.0 | 62 | 12 | small | records+1 | compact | 0.004 | yes | yes | 0.001 |
| sfbgs023.esm | starfield | 0.0 | 18 | 13 | small | records+1 | compact | 0.002 | yes | yes | 0.001 |
| starship_mechanic.esm | starfield | 0.0 | 69 | 38 | medium | records+groups | ordinal | 0.002 | yes | yes | 0.011 |
| starship_mechanic.esp | starfield | 0.0 | 69 | 38 | full | records+groups | ordinal | 0.001 | yes | yes | 0.001 |
| rbt_skeletonkey.esm | starfield | 0.0 | 27 | 9 | small | records+groups | ordinal | 0.002 | yes | yes | 0.001 |
| ScreenSFSE.esm | starfield | 0.0 | 14 | 5 | medium | records+groups | ordinal | 0.001 | yes | yes | 0.0 |
| even_richer_vendors_sp0ckrates.esm | starfield | 0.0 | 16 | 2 | small | records+groups | ordinal | 0.002 | yes | yes | 0.001 |
| mordrid-register-ship-cheap-lesscheaty.esm | starfield | 0.0 | 1 | 1 | small | records+groups | ordinal | 0.0 | yes | yes | 0.0 |
| scientificgorillatimescaleground6.esm | starfield | 0.0 | 1 | 1 | small | records+groups | ordinal | 0.0 | yes | yes | 0.0 |

## Other measurements

- Typed schema validation over all 54 Starfield plugins (13 record types): 7,586,505
  records, 25,129,047 typed values decoded+re-encoded byte-identically, 14,568,051
  FormLinks, 0 unresolved (`docs/phase2/schema_validation.json`; Starfield.esm 135 s).
- Editor-ID index of Starfield.esm (direct byte reads, no node objects): ~9 s.
- Oblivion.esm has 10 record-header FormIDs whose prefix maps to no master (it has
  none); reported as unresolved, preserved as-is.
