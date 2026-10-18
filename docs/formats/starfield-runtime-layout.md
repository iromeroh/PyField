# Starfield runtime layout (1.16.244) — confirmed by PyFieldCapture calibration

Measured 2026-10-16 by `sfse/PyFieldCapture` against Papyrus values (FormID, position, angles, base, cell, scale) on
three anchors: an outpost beacon, the player, and a landed player ship.

| Object | Offset | Field | Status |
|---|---|---|---|
| TESForm | 0x20 | form flags (u32) | header layout (FormID confirmed next to it) |
| TESForm | 0x28 | FormID (u32) | confirmed (3/3) |
| TESObjectREFR | 0x80 | angle, 3 × f32 radians | confirmed against Papyrus GetAngleX/Y/Z (degrees) |
| TESObjectREFR | 0x8C | location, 3 × f32 | confirmed (3/3) |
| TESObjectREFR | 0x98 | base object pointer | confirmed for beacon and player; for a ship Papyrus `GetBaseObject()` returns a different form (template vs. save-created ship base) |
| TESObjectREFR | 0xB0 | parent cell pointer | confirmed (3/3) |
| TESObjectREFR | 0xD0 | scale, u16 percent | confirmed (scale 1.0) |
| TESObjectCELL | 0x80 | reference count (u32) | **differs from CommonLibSF**: found by locating the anchor in the array |
| TESObjectCELL | 0x88 | reference array (TESObjectREFR* per entry) | **differs from CommonLibSF** (its `ForEachReference` read data at 0x90, count at 0x88 and crashed) |

Capture facts: Papyrus native calls that are not tasklet-callable take about one frame each (1,261 calls took 32 s);
`BSScript::Array` ctor/dtor have no Address Library ID in CommonLibSF, so no arrays cross the native boundary.
Outpost "Selene": `GetRefsLinkedToMe(WorkshopItemKeyword)` = 1,260 built objects (+1 created-base), cell = 613 refs
(mostly save-created procedural content).
