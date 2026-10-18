"""Starfield adapter."""
from .. import register
from ...capabilities import Capability, CapabilitySet, Status as S
import struct

from ...core.formids import FULL, MEDIUM, SMALL
from ..base import GameAdapter
from ..tes4family import MODERN_FORMAT, MODERN_GROUPS, Tes4HeaderScheme
from ..vmad import formid_offsets as vmad_formid_offsets

# Native top-level group order: Starfield.esm's 176 groups merged with the extra groups of the
# other Bethesda masters (checked 2026-10-15 over 20 masters, no conflicting pairs): SCCO after
# KSSM (ShatteredSpace), RELA after MESG (sfta04), GPOF GPOG GWED last (SFBGS00D/007/050; every
# installed mod with Gameplay Options also writes GPOF before GPOG).
NATIVE_GROUP_ORDER = tuple((
    'GMST KYWD FFKW LCRT AACT TRNS TXST GLOB DMGT CLAS FACT AFFE HDPT RACE SOUN SECH '
    'ASPC AOPF MGEF LTEX PDCL ENCH SPEL ACTI CURV CUR3 ARMO BOOK CONT DOOR LIGH MISC '
    'STAT SCOL PKIN MSTT GRAS FLOR FURN WEAP AMMO NPC_ LVLN LVLP KEYM ALCH IDLM BMMO '
    'PROJ HAZD BNDS TERM LVLI GBFT GBFM LVLB WTHR WTHS CLMT SPGD REGN NAVI CELL WRLD '
    'NAVM DIAL INFO QUST IDLE PACK CSTY LSCR ANIO WATR EFSH EXPL DEBR IMGS IMAD FLST '
    'PERK BPTD ADDN AVIF CAMS CPTH VTYP MATT IPCT IPDS ARMA LCTN MESG RELA DOBJ DFOB LGTM '
    'MUSC FSTP FSTS SMBN SMQN SMEN DLBR MUST EQUP SCEN OTFT ARTO MOVT COLL CLFM REVB '
    'RFGP AMDL AAMD MAAM LAYR COBJ OMOD ZOOM INNR KSSM SCCO AORU STAG IRES BIOM NOCM LENS '
    'OVIS STND STMP GCVR MRPH TRAV RSGD OSWP ATMO LVSC SPCH AAPD VOLI SFBK SFPC SFPT '
    'SFTR PCMT BMOD STBH PNDT CNDF PCBN PCCN STDT WWED RSPJ AOPS AMBS WBAR PTST LMSW '
    'FORC TMLM EFSQ SDLT MTPT CLDF FOGV WKMF LGDI PSDC SUNP PMFT TODD AVMD CHAL FXPD '
    'GPOF GPOG GWED').split())

from . import assets as _assets   # noqa: E402

# Self-contained definitions that may be copied between plugins (owner decision 2026-10-15);
# everything else, including all relationship-heavy types, is rebuild-only.
TRANSPLANT_POLICY = {sig: 'copy' for sig in (
    'STAT MSTT ACTI FURN LIGH DOOR FLOR MISC CONT BOOK ALCH AMMO WEAP ARMO ARMA NPC_ RACE HDPT '
    'TXST KYWD GLOB FLST WWED COBJ LVLI LVLN VTYP CLAS SCOL').split()}

# Base object types that can be placed, and the record that places them: exactly the types
# vanilla references place in Starfield.esm (2026-10-15: REFR 31 types, ACHR only NPC_).
PLACEABLE = {sig: 'REFR' for sig in (
    'STAT PDCL MSTT LIGH MISC PKIN FURN BMMO ACTI SOUN ALCH LVLI BNDS DOOR CONT ASPC IDLM FLOR LVLP BOOK '
    'SECH TERM AOPF GBFM ARMO WEAP KEYM AMMO TXST SCOL GRAS').split()}
PLACEABLE['NPC_'] = 'ACHR'

SCHEMA_VERSION = '2026.10.1'   # bump when typed layouts change (see CHANGELOG)

CAPABILITIES = CapabilitySet([
    Capability('binary.read', S.SUPPORTED, 'all installed masters index; see docs/phase0/baseline.md'),
    Capability('binary.roundtrip.unmodified', S.SUPPORTED, 'byte-identical for every corpus file'),
    Capability('binary.write.modified', S.SUPPORTED, 'modified records re-encoded; zlib level reproduced when detectable'),
    Capability('formid.full', S.SUPPORTED),
    Capability('formid.medium', S.SUPPORTED, 'FD namespace observed in Bethesda masters; own compact IDs decoded'),
    Capability('formid.small', S.SUPPORTED, 'FE namespace observed in Bethesda masters'),
    Capability('formid.user_medium_as_master', S.EXPERIMENTAL,
               'references INTO a CK-saved medium plugin (ordinal own IDs) not yet observed'),
    Capability('strings.localized', S.SUPPORTED, 'string tables read (tes4family.StringTables); copies into '
               'non-localized plugins are de-localized like the CK (New Atlantis WRLD override identical to CK output)'),
    Capability('schema.typed', S.SUPPORTED, '13 record types; 25.1M member values byte-exact over 54 plugins '
               '(docs/phase2/schema_validation.json); other types: generic view'),
    Capability('schema.vmad', S.UNSUPPORTED, 'VMAD kept as opaque bytes'),
    Capability('override.remap', S.UNSUPPORTED, 'copies need identical master namespaces'),
    Capability('edit.transactions', S.VALIDATED, 'PyFieldDemo.esm: SF1Edit loads clean, game loads it (2026-10-14)'),
    Capability('assets.read', S.SUPPORTED, 'BA2 GNRL/DX10 (LZ4/zlib) + loose; game precedence'),
    Capability('assets.dependencies', S.SUPPORTED, 'records/NIF/.mat/Wwise banks; every reference verified; '
               'vanilla materials (materialsbeta.cdb) reported as external-unverified'),
    Capability('assets.pack', S.SUPPORTED, 'Archive2.exe General/DDS, read-back verified'),
    Capability('transplant.reference', S.SUPPORTED),
    Capability('transplant.copy', S.EXPERIMENTAL, 'self-contained types only; structurally validated, '
               'not yet loaded in game'),
    Capability('scene.compile', S.VALIDATED, 'new interior cells and existing cells; stable identities via lock; '
               'PyFieldSceneTest.esm checked in game 2026-10-15'),
    Capability('scene.rotation', S.VALIDATED, 'Rx(-x)Ry(-y)Rz(-z), learned from reference groups; tilted '
               'composition confirmed in game 2026-10-15'),
    Capability('scene.capture', S.SUPPORTED, 'cell -> blueprint; 3,196-reference round trip exact'),
    Capability('scene.existing_localized_cell', S.UNSUPPORTED,
               'overriding a cell with a localized name needs string tables (strings.localized)'),
    Capability('landscape.read', S.SUPPORTED, '.btd v4-6: all 1,999 vanilla files roundtrip; heights decoded and '
               'calibrated against placed ground objects'),
    Capability('landscape.write', S.VALIDATED, 'height edits with LOD rebuild; aux channel preserved; New Atlantis hill '
               'seen in game 2026-10-15 (loaded from the plugin BA2)'),
    Capability('landscape.texturing', S.UNSUPPORTED, 'auxiliary channel and per-cell 288-byte data not decoded'),
    Capability('landscape.surface_records', S.UNSUPPORTED, 'SFBK/SFPT/SFTR authoring not implemented'),
])

class StarfieldAdapter(GameAdapter):
    def lstring_signatures(self, record_signature: str) -> frozenset:
        cache = self.__dict__.setdefault('_lstrings', {})
        if record_signature not in cache:
            from .schema import load_inventory
            inv = (load_inventory() or {}).get('records', {}).get(record_signature, {})
            cache[record_signature] = frozenset(m['sig'] for m in inv.get('members', []) if m['kind'] == 'lstring')
        return cache[record_signature]


ADAPTER = register(StarfieldAdapter(
    name='starfield',
    title='Starfield',
    format=MODERN_FORMAT,
    header=Tes4HeaderScheme(master_list_has_data=False),
    groups=MODERN_GROUPS,
    header_versions=(0.96,),
    default_header_version=0.96,
    namespaces=frozenset({FULL, MEDIUM, SMALL}),
    localized_flag=0x80,
    small_flag=0x100,
    medium_flag=0x400,
    native_group_order=NATIVE_GROUP_ORDER,
    record_header_tail=struct.pack('<IHH', 0, 582, 0),   # version control, form version 582, unknown
    next_id_has_own_prefix=True,
    capabilities=CAPABILITIES,
    schema_loader=lambda: __import__('pyfield.games.starfield.schema', fromlist=['schema_set']).schema_set(),
    schema_version=SCHEMA_VERSION,
    inventory_loader=lambda: __import__('pyfield.games.starfield.schema', fromlist=['load_inventory']).load_inventory(),
    formid_array_signatures=frozenset({'KWDA'}),
    formid_locators={'VMAD': vmad_formid_offsets},
    transplant_policy=TRANSPLANT_POLICY,
    asset_rules=_assets.RULES,
    asset_hooks={'WWED': _assets.wwed_assets},
    rotation_convention=('xyz', -1),       # R = Rx(-rx)·Ry(-ry)·Rz(-rz); docs/formats/starfield-placement.md
    exterior_cell_size=100.0,              # metres; 46,431/46,431 refs in 300 cells
    placeable_types=PLACEABLE,
    # Worldspace overrides drop the large-reference lists and the cell offset tables, which index
    # the defining file (all 21 CK-saved WRLD overrides installed; copying them crashed the game).
    override_strip={'WRLD': frozenset({'RNAM', 'OFST', 'CLSZ'})},
))
