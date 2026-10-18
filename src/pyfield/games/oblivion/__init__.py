"""Oblivion (TES4) adapter: the second format, proving the core is not Starfield-shaped.

20-byte record/group headers, MAST+DATA pairs, a single full-master namespace.
"""
from .. import register
from ...capabilities import Capability, CapabilitySet, Status as S
from ...core.formids import FULL
from ..base import GameAdapter
from ..tes4family import TES4_FORMAT, TES4_GROUPS, Tes4HeaderScheme

# UESP "Oblivion Mod:Mod File Format" top-level group order.
NATIVE_GROUP_ORDER = tuple((
    'GMST GLOB CLAS FACT HAIR EYES RACE SOUN SKIL MGEF SCPT LTEX ENCH SPEL BSGN ACTI APPA '
    'ARMO BOOK CLOT CONT DOOR INGR LIGH MISC STAT GRAS TREE FLOR FURN WEAP AMMO NPC_ CREA '
    'LVLC SLGM KEYM ALCH SBSP SGST LVLI WTHR CLMT REGN CELL WRLD DIAL QUST IDLE PACK CSTY '
    'LSCR LVSP ANIO WATR EFSH').split())

CAPABILITIES = CapabilitySet([
    Capability('binary.read', S.SUPPORTED),
    Capability('binary.roundtrip.unmodified', S.SUPPORTED),
    Capability('binary.write.modified', S.EXPERIMENTAL, 'not yet validated with TES4Edit or the game'),
    Capability('formid.full', S.SUPPORTED),
    Capability('schema.typed', S.UNSUPPORTED, 'Phase 10'),
])

ADAPTER = register(GameAdapter(
    name='oblivion',
    title='The Elder Scrolls IV: Oblivion',
    format=TES4_FORMAT,
    header=Tes4HeaderScheme(master_list_has_data=True),
    groups=TES4_GROUPS,
    header_versions=(1.0, 0.8),
    default_header_version=1.0,
    namespaces=frozenset({FULL}),
    native_group_order=NATIVE_GROUP_ORDER,
    first_object_id=0x800,
    capabilities=CAPABILITIES,
))
