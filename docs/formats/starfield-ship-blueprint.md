# Starfield ships: blueprint records and runtime parts

## In plugins (verified on Starfield.esm, 2026-10-16)
Ships are GBFM records (generic base forms) assembled from `BFCB <name>` … `BFCE` component sections. Modules are
GBFM too (`SMS_*` structural, `SMA_*`/`SMC_*`/`SMM_*` systems with level variants), each pointing at the pack-in
it spawns through `FLFM` (u32 FormID, first subrecord of the module's form).

`Blueprint_Component` (may come from another form: `BGSExternalComponentDataSource_Component`, `EXDC` = source
FormID, `EXCN`/`EXCI` = component name / source per component):

| Subrecord | Content |
|---|---|
| `BUO4` | parts, 36 bytes each: u32 module GBFM FormID, u32 (0), f32 x,y,z (metres), f32 rx,ry,rz (radians), u32 part id |
| `BODM` | u32 part count (= `len(BUO4) / 36`) |
| `BODC` / `BODS` / `BODV` | per-part colour slots: u32 slot count, then per slot a zstring palette name ("DEFAULT", "FREESTAR CITIZEN", …) and 40 bytes (3 × RGB f32 + u32 mask) |
| `BLUF` | u8 flags (4 seen) |
| `BOID` | u32 next part id |

Example `EncShip_Generic_A_Rambler02` (042374): 22 parts, positions on the builder grid (x ±8.11, y steps of 4, z
0.40/3.90/-3.10), weapons rotated (0, π/4, 0) and (−π, π/4, −π).

## At runtime (PyFieldCapture, landed player ship "PyField Probe")
- The ship reference's stored base is a save-created form (FF……); Papyrus `GetBaseObject()` returns the leveled
  template (`LvlShip_Ecliptic_Combat`, 0AE4EE).
- Each part is spawned as pack-in references in the ship's cell. Every spawned reference carries
  `ExtraBlueprintPartOriginData` (0xDD; first u32 = part index) and `ExtraSourcePackIn` (0xD4; form pointer to the
  part's `PKIN ShipPI_*`). 67 parts, 38 distinct pack-ins, 1,874 references. Another ship in the same cell had
  0xDD without 0xD4.
- Pack-in -> module GBFM is the reverse of `FLFM`: unique for 57/67 parts; 10 parts share a model across stat
  variants (cockpit C3/C3X/C4, reactor DC401-403, shield SG-1000…4000, missiles, grav drive, cargo, engines). The
  exact variant lives in the save-created ship base; `ProbeAnchorBase` dumps it for offline mapping.

## Variant ground truth (ship builder, 2026-10-16, player level 114)
Pack-in names carry the family's *base* model, not the installed variant. Installed vs. pack-in name:
missiles CE-59 (pack-in CE-77; candidates CE-49/CE-59), reactor Fusor DC403 (pack-in DC401), shield Assurance SG-3000
(pack-in SG-1000; SG-4000 lvl 84 was available), grav drive Apollo GV300 (GV100), engines Poseidon DT230 (DT210),
cockpit Cabot C4 (C4), cargo "10ST Hauler Shielded Cargo Hold" (at least 2; pack-in 10T-Hauler).
Name matching got 1/7 right and "highest level <= player level" fails on the shield: the variant is a player choice
and must be read from runtime data (runtime blueprint part structure) or supplied by the user.

## Rebuilt ship in game (2026-10-16, PyFieldShipTest.esm, GiveShip via the liner landing recipe)
Spawned, landed, owned, correct shape; reactor 38, hull 1357, cargo 2970, crew 6, jump 30 LY. Open issues:
template door inaccessible (also for the vanilla Constellation_Frontier_Template: quest template; GiveShip now calls
SetExteriorLoadDoorInaccessible(False)); no navmesh (template NVNM dropped) so followers are stuck; ship builder
reports "unattached modules", "missing shield", unassigned weapons (weapon bindings `SHWB` still the template's;
attachment needs the builder frame/snap data). Default colours (paint not captured).

## Template ships link pre-built cells (2026-10-18)

Quest/template ships (e.g. `Constellation_Frontier_Template`) carry `BGSFormLinkData_Component`:
`FLKW SpaceshipLinkedInterior` -> `FLFM` CELL `BlueprintInteriorConstellationFrontierTemplate`, and
`FLKW SpaceshipLinkedExterior` -> CELL `BlueprintExteriorConstellationFrontierTemplate` (BlueprintShips-Starfield.esm).
The game shows those cells in the world; the ship editor rebuilds from the blueprint. A ship rebuilt on the
Frontier template therefore looked exactly like the Frontier in the world while the editor showed its own modules.
`ships.build_ship` drops the component (`DROP_COMPONENTS`); player-built ships have none.
