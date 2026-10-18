# Phase 0 — Schema inventory

Source: xEdit `wbDefinitionsSF1.pas` + `wbDefinitionsCommon.pas` (MPL-2.0), mined by
`tools/extract_xedit_inventory.py` into `src/pyfield/games/starfield/data/xedit_sf1_inventory.json`
(196 record types; ordered members with signature, name, leaf kind and the helper path
they came from). Component blocks (`wbBaseFormComponents`, `BFCB…BFCE`) are listed but
excluded from the "top-level" count.

The inventory is used to (1) cross-check every typed member (it must exist at top level
and be unambiguous there) and (2) plan coverage. It is not a compiler of xEdit's DSL:
deciders, unions, version gates and element structure are not modelled.

Typed now (13 types, `games/starfield/schema.py`): ACHR, CELL, COBJ, CONT, DIAL, FLST, GLOB, KYWD, MISC, NPC_, REFR, STAT, WRLD.
Record types with no schema are still fully readable/writable through generic views.

Backlog in priority order (current mods' needs): VMAD decoder (v6/format 2, with opaque
alias/fragment suffix), conditions block (CTDA/CIS1/CIS2), QUST aliases/stages/objectives,
INFO responses, TMLM menu items, PERK entries, GBFM component blocks, LCTN ACUR/LCUR,
ARMA/RACE, PKIN/SCOL, LAND (Phase 6).

| Sig | Name | Top-level members (xEdit) | Typed members |
|---|---|---:|---:|
| AACT | Action | 9 |  |
| AAMD | Aim Assist Model Data | 2 |  |
| AAPD | Aim Assist Pose Data | 11 |  |
| ACHR | Placed NPC | 45 | 15 |
| ACTI | Activator | 45 |  |
| ADDN | Addon Node | 13 |  |
| AFFE | Affinity Event | 11 |  |
| ALCH | Ingestible | 44 |  |
| AMBS | Ambience Set | 5 |  |
| AMDL | Aim Model | 2 |  |
| AMMO | Ammunition | 34 |  |
| ANIO | Animated Object | 8 |  |
| AOPF | Audio Occlusion Primitive | 12 |  |
| AOPS | Aim Optical Sight Marker | 2 |  |
| AORU | Attraction Rule | 3 |  |
| ARMA | Armor Addon | 37 |  |
| ARMO | Armor | 45 |  |
| ARTO | Art Object | 16 |  |
| ASPC | Acoustic Space | 17 |  |
| ASTP | Association Type | 7 |  |
| ATMO | Atmosphere | 4 |  |
| AVIF | Actor Value Information | 10 |  |
| AVMD | AVMS Data | 10 |  |
| BIOM | Biome | 48 |  |
| BMMO | Biome Marker | 23 |  |
| BMOD | Bone Modifier | 2 |  |
| BNDS | Bendable Spline | 6 |  |
| BOOK | Book | 34 |  |
| BPTD | Body Part Data | 16 |  |
| CAMS | Camera Shot | 16 |  |
| CELL | Cell | 36 | 13 |
| CHAL | Challenge | 1 |  |
| CLAS | Class | 7 |  |
| CLDF | Clouds | 2 |  |
| CLFM | Color | 8 |  |
| CLMT | Climate | 5 |  |
| CNDF | Condition Form | 6 |  |
| COBJ | Constructible Object | 28 | 12 |
| COLL | Collision Layer | 8 |  |
| CONT | Container | 43 | 13 |
| CPTH | Camera Path | 7 |  |
| CSTY | Combat Style | 18 |  |
| CUR3 | Curve 3D | 2 |  |
| CURV | Curve Table | 2 |  |
| DEBR | Debris | 3 |  |
| DFOB | Default Object | 3 |  |
| DIAL | Dialog Topic | 13 | 7 |
| DLBR | Dialog Branch | 5 |  |
| DLVW | Dialog View | 0 |  |
| DMGT | Damage Type | 4 |  |
| DOBJ | Default Object Manager | 2 |  |
| DOOR | Door | 37 |  |
| DUAL | Dual Cast Data | 11 |  |
| EFSH | Effect Shader | 9 |  |
| EFSQ | Effect Sequence | 2 |  |
| ENCH | Enchantment | 16 |  |
| EQUP | Equip Type | 5 |  |
| EXPL | Explosion | 15 |  |
| EYES | Eyes | 4 |  |
| FACT | Faction | 26 |  |
| FFKW | Form Folder Keyword List | 2 |  |
| FLOR | Flora | 45 |  |
| FLST | FormID List | 9 | 3 |
| FOGV | Fog Volume | 2 |  |
| FORC | Force Data | 2 |  |
| FSTP | Footstep | 4 |  |
| FSTS | Footstep Set | 4 |  |
| FURN | Furniture | 49 |  |
| FXPD | Facial Expression | 4 |  |
| GBFM | Generic Base Form | 15 |  |
| GBFT | Generic Base Form Template | 2 |  |
| GCVR | Ground Cover | 6 |  |
| GLOB | Global | 3 | 2 |
| GMST | Game Setting | 3 |  |
| GPOF | Gameplay Option | 16 |  |
| GPOG | Gameplay Options Group | 5 |  |
| GRAS | Grass | 11 |  |
| GWED | Gravity Wielder Effect Data | 3 |  |
| HAZD | Hazard | 21 |  |
| HDPT | Head Part | 19 |  |
| IDLE | Animation | 10 |  |
| IDLM | Idle Marker | 21 |  |
| IMAD | Image Space Adapter | 2 |  |
| IMGS | Image Space | 4 |  |
| INFO | Dialog response | 57 |  |
| INGR | Ingredient | 33 |  |
| INNR | Instance Naming Rules | 9 |  |
| IPCT | Impact | 17 |  |
| IPDS | Impact Data Set | 3 |  |
| IRES | Resource | 16 |  |
| KEYM | Key | 33 |  |
| KSSM | Sound Keyword Mapping | 6 |  |
| KYWD | Keyword | 9 | 8 |
| LAYR | Layer | 5 |  |
| LCRT | Location Reference Type | 9 |  |
| LCTN | Location | 38 |  |
| LENS | Lens Flare | 11 |  |
| LGDI | Legendary Item | 34 |  |
| LGTM | Lighting Template | 3 |  |
| LIGH | Light | 36 |  |
| LMSW | Layered Material Swap | 3 |  |
| LSCR | Load Screen | 12 |  |
| LTEX | Landscape Texture | 6 |  |
| LVLB | Leveled Base Form | 29 |  |
| LVLI | Leveled Item | 35 |  |
| LVLN | Leveled NPC | 27 |  |
| LVLP | Leveled Pack In | 25 |  |
| LVSC | Leveled Space Cell | 14 |  |
| LVSP | Leveled Spell | 15 |  |
| MAAM | Melee Aim Assist Model | 2 |  |
| MATT | Material Type | 9 |  |
| MESG | Message | 18 |  |
| MGEF | Magic Effect | 13 |  |
| MISC | Misc. Item | 35 | 11 |
| MOVT | Movement Type | 7 |  |
| MRPH | Morphable Object | 6 |  |
| MSTT | Moveable Static | 32 |  |
| MTPT | Material Path | 2 |  |
| MUSC | Music Type | 10 |  |
| MUST | Music Track | 13 |  |
| NAVI | Navmesh Info Map | 4 |  |
| NAVM | Navmesh | 5 |  |
| NOCM | Navmesh Obstacle Manager | 5 |  |
| NOTE | Note | 22 |  |
| NPC_ | Non-Player Character | 115 | 10 |
| OMOD | Object Modification | 18 |  |
| OSWP | Object Swap | 4 |  |
| OTFT | Outfit | 3 |  |
| OVIS | Object Visibility Manager | 3 |  |
| PACK | Package | 54 |  |
| PCBN | Planet Content Manager Branch Node | 15 |  |
| PCCN | Planet Content Manager Content Node | 7 |  |
| PCMT | Planet Content Manager Tree | 11 |  |
| PDCL | Projected Decal | 12 |  |
| PERK | Perk | 41 |  |
| PERS | Unknown - PERS | 2 |  |
| PKIN | Pack-In | 21 |  |
| PLYR | Player Reference | 2 |  |
| PMFT | Photo Mode Feature | 8 |  |
| PNDT | Planet | 23 |  |
| PROJ | Projectile | 34 |  |
| PSDC | Particle System Define Collection | 2 |  |
| PTST | Surface Pattern Style | 1 |  |
| QUST | Quest | 56 |  |
| RACE | Race | 123 |  |
| REFR | Placed Object | 100 | 14 |
| REGN | Region | 7 |  |
| RELA | Relationship | 3 |  |
| REVB | Reverb Parameters | 4 |  |
| RFGP | Reference Group | 7 |  |
| RSGD | Resource Generation Data | 3 |  |
| RSPJ | Research Project | 15 |  |
| SCCO | Scene Collection | 5 |  |
| SCEN | Scene | 174 |  |
| SCOL | Static Collection | 14 |  |
| SCRL | Scroll | 28 |  |
| SDLT | Secondary Damage List | 4 |  |
| SECH | Sound Echo Marker | 26 |  |
| SFBK | Surface Block | 17 |  |
| SFPC | Surface Pattern Config | 5 |  |
| SFPT | Surface Pattern | 8 |  |
| SFTR | Surface Tree | 8 |  |
| SMBN | Story Manager Branch Node | 9 |  |
| SMEN | Story Manager Event Node | 10 |  |
| SMQN | Story Manager Quest Node | 14 |  |
| SOUN | Sound Marker | 9 |  |
| SPCH | Speech Challenge | 11 |  |
| SPEL | Spell | 23 |  |
| SPGD | Shader Particle Geometry | 4 |  |
| STAG | Animation Sound Tag Set | 5 |  |
| STAT | Static | 21 | 12 |
| STBH | Snap Template Behavior | 9 |  |
| STDT | Star | 12 |  |
| STMP | Snap Template | 14 |  |
| STND | Snap Template Node | 25 |  |
| SUNP | Sun Preset | 4 |  |
| TACT | Talking Activator | 43 |  |
| TDED | Track Damage Effect Data | 2 |  |
| TERM | Terminal | 57 |  |
| TES4 | Main File Header | 13 |  |
| TMLM | Terminal Menu | 26 |  |
| TODD | Time Of Day Data | 2 |  |
| TRAV | Traversal | 3 |  |
| TRNS | Transform | 4 |  |
| TXST | Texture Set | 14 |  |
| VOLI | Volumetric Lighting | 2 |  |
| VTYP | Voice Type | 5 |  |
| WATR | Water | 21 |  |
| WBAR | Weapon Barrel Model | 2 |  |
| WEAP | Weapon | 60 |  |
| WKMF | Wwise Keyword Mapping | 6 |  |
| WRLD | Worldspace | 40 | 12 |
| WTHR | Weather | 35 |  |
| WTHS | Weather Settings | 7 |  |
| WWED | Wwise Event Data | 5 |  |
| ZOOM | Zoom | 2 |  |
