"""Typed Starfield record schemas (first verified subset).

Each layout is taken from xEdit's wbDefinitionsSF1.pas (dev-4.1.6, sha256 9f01921a…)
and checked by `tools/validate_schemas.py`, which decodes and re-encodes every typed
member of every record of these types in the installed masters and requires
byte-identical output. Members not listed here are preserved untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...schema.codecs import (Array, Bytes, Empty, F32, FormLink, I32, LString, Struct, U8, U16, U32,
                              ZString, rgba, vec3)
from ...schema.records import Member, Region, RecordSchema, SchemaSet

EVIDENCE = 'xEdit SF1 layout; byte-exact decode/encode over installed masters (tools/validate_schemas.py)'

COMPONENTS = Region('BFCB', 'BFCE', 'component')
DESTRUCTION_STAGE = Region('DSTD', 'DSTF', 'destruction_stage')
OBJECT_TEMPLATES = Region('OBTE', 'STOP', 'object_templates')


def components_after(sig):
    return Region(COMPONENTS.start, COMPONENTS.end, COMPONENTS.name, after=sig)


# -- shared members ----------------------------------------------------------------------------
def EDID():
    return Member('EDID', 'editor_id', ZString(), doc='Editor ID')


def FULL(attr='name'):
    return Member('FULL', attr, LString(), doc='display name (string id in localized plugins)')


def OBND():
    return Member('OBND', 'bounds', Struct([('min', vec3()), ('max', vec3())]), doc='object bounds (floats in Starfield)')


def ODTY():
    return Member('ODTY', 'dirtiness', F32)


def MODL():
    return Member('MODL', 'model', ZString(), doc='model file name')


def FLLD():
    return Member('FLLD', 'light_layer', U32)


def KEYWORDS():
    return [Member('KSIZ', 'keyword_count', U32, doc='maintained automatically from keywords'),
            Member('KWDA', 'keywords', Array(FormLink('KYWD')), doc='keyword list')]


POSROT = Struct([('position', vec3()), ('rotation', vec3())])   # rotation in radians
OWNER = Struct([('owner', FormLink('FACT', 'NPC_')), ('unused', Bytes(4)), ('no_crime', U8), ('unused2', Bytes(3))])
LINKED_REF = Struct([('keyword', FormLink('KYWD', 'REFR', 'ACHR')), ('reference', FormLink('REFR', 'ACHR'))],
                    optional_from=1)
ENABLE_PARENT = Struct([('reference', FormLink('REFR', 'ACHR')), ('flags', U8), ('unused', Bytes(3))])
CONTAINER_ITEM = Struct([('item', FormLink()), ('count', I32)])


def placed_common(base_targets):
    """Members shared by REFR and ACHR, in native order."""
    return [
        EDID(),
        Member('NAME', 'base', FormLink(*base_targets), required=True, doc='base object'),
        Member('XRFG', 'reference_group', FormLink('RFGP')),
        Member('XPCS', 'source_pack_in', FormLink('PKIN')),
        Member('XLCN', 'persist_location', FormLink('LCTN')),
        Member('XLRL', 'location_reference', FormLink('LCTN')),
        Member('XLKR', 'linked_refs', LINKED_REF, repeat=True),
        Member('XLKT', 'linked_refs_transient', Empty()),
        Member('XOWN', 'ownership', OWNER),
        Member('XRNK', 'faction_rank', I32, follows='XOWN',
               doc='ownership rank (vanilla lights also carry an unrelated XRNK right after NAME)'),
        Member('XLYR', 'layer', FormLink('LAYR')),
        Member('XESP', 'enable_parent', ENABLE_PARENT),
        Member('XSCL', 'scale', F32),
        Member('DATA', 'placement', POSROT, required=True, doc='position (m) and rotation (radians)'),
    ]


SCHEMAS = [
    RecordSchema('KYWD', 'Keyword', [
        EDID(),
        Member('CNAM', 'color', rgba(), required=True),
        Member('DNAM', 'notes', ZString()),
        Member('TNAM', 'keyword_type', U32, required=True),
        Member('FNAM', 'unknown_fnam', Bytes(4), required=True, doc='always zero'),
        Member('DATA', 'attraction_rule', FormLink('AORU')),
        Member('ENAM', 'flash_linkage', ZString()),
        FULL(),
    ], header_flags={15: 'Restricted'}, regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('GLOB', 'Global', [
        EDID(),
        Member('FLTV', 'value', F32, required=True, doc='globals are stored as float'),
    ], header_flags={6: 'Constant'}, regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('FLST', 'FormID List', class_name='FormIdList', members=[
        EDID(),
        FULL(),
        Member('LNAM', 'forms', FormLink(), repeat=True),
    ], regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('STAT', 'Static', [
        EDID(), OBND(), ODTY(),
        Member('SNTP', 'snap_template', FormLink('STMP')),
        Member('SNBH', 'snap_behavior', FormLink('STBH')),
        Member('DEFL', 'default_layer', FormLink('LAYR')),
        MODL(), FLLD(),
        Member('MODC', 'color_remapping', F32),
        Member('XFLG', 'model_flags', U8),
        FULL(),
        Member('DNAM', 'direction_material', Struct([('max_angle', F32), ('unknown', F32),
                                                     ('leaf_amplitude', F32), ('leaf_frequency', F32)],
                                                    optional_from=2)),
    ], header_flags={2: 'Heading Marker', 9: 'Hidden From Local Map', 10: 'Headtrack Marker',
                     11: 'Used as Platform', 23: 'Is Marker'},
        regions=[components_after('ODTY')], evidence=EVIDENCE),

    RecordSchema('MISC', 'Misc. Item', [
        EDID(), OBND(), ODTY(),
        FULL(), MODL(), FLLD(),
        *KEYWORDS(),
        Member('DATA', 'data', Struct([('value', I32), ('weight', F32)])),
        Member('FLAG', 'flags', U32),
        Member('NNAM', 'short_name', LString()),
    ], regions=[components_after('ODTY'), DESTRUCTION_STAGE], evidence=EVIDENCE),

    RecordSchema('CONT', 'Container', [
        EDID(), OBND(), ODTY(),
        FULL(), MODL(), FLLD(),
        Member('COCT', 'item_count', U32, doc='maintained automatically from items'),
        Member('CNTO', 'items', CONTAINER_ITEM, repeat=True),
        Member('DATA', 'flags', U8),
        *KEYWORDS(),
        Member('NTRM', 'native_terminal', FormLink('TMLM')),
        Member('ONAM', 'contains_only_filter', FormLink('FLST')),
    ], regions=[components_after('ODTY'), DESTRUCTION_STAGE, OBJECT_TEMPLATES], evidence=EVIDENCE),

    RecordSchema('REFR', 'Placed Object', placed_common(()),
                 header_flags={10: 'Persistent', 11: 'Initially Disabled'},
                 regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('ACHR', 'Placed NPC', class_name='PlacedNPC', members=[
        *placed_common(('NPC_',))[:2],
        Member('XLCM', 'level_modifier', I32),
        *placed_common(('NPC_',))[2:],
    ], header_flags={10: 'Persistent', 11: 'Initially Disabled'},
        regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('CELL', 'Cell', [
        EDID(), FULL(),
        Member('DATA', 'cell_flags', U32, doc='bit 0 interior'),
        Member('LTMP', 'lighting_template', FormLink('LGTM')),
        Member('XCLW', 'water_height', F32),
        Member('XCCM', 'sky_region', FormLink('REGN')),
        Member('XOWN', 'ownership', OWNER),
        Member('XRNK', 'faction_rank', I32, follows='XOWN',
               doc='ownership rank (vanilla lights also carry an unrelated XRNK right after NAME)'),
        Member('XLCN', 'location', FormLink('LCTN')),
        Member('XCAS', 'acoustic_space', FormLink('ASPC')),
        Member('XCIM', 'image_space', FormLink('IMGS')),
        Member('XCMO', 'music', FormLink('MUSC')),
        Member('XEMP', 'environment_map', ZString()),
    ], header_flags={2: 'Is Unique', 10: 'Persistent', 17: 'Off Limits', 19: "Can't Wait"},
        regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('WRLD', 'Worldspace', [
        EDID(), FULL(),
        Member('XLCN', 'location', FormLink('LCTN')),
        Member('BNAM', 'biome', FormLink('BIOM')),
        Member('CNAM', 'climate', FormLink('CLMT')),
        Member('NAM2', 'water', FormLink('WATR')),
        Member('NAMA', 'distant_lod_multiplier', F32),
        Member('DATA', 'world_flags', U8),
        Member('FNAM', 'flags2', U8),
        Member('ZNAM', 'music', FormLink('MUSC')),
        Member('WAMB', 'ambient_set', FormLink('AMBS')),
        Member('GNAM', 'gravity_scale', F32),
    ], regions=[components_after('EDID')], evidence=EVIDENCE),

    RecordSchema('NPC_', 'Non-Player Character', class_name='NPC', members=[
        EDID(), OBND(), ODTY(),
        Member('VTCK', 'voice', FormLink('VTYP')),
        Member('TPLT', 'default_template', FormLink('NPC_', 'LVLN')),
        Member('RNAM', 'race', FormLink('RACE'), required=True),
        *KEYWORDS(),
        Member('CNAM', 'class_', FormLink('CLAS')),
        FULL(),
    ], regions=[components_after('ODTY'), DESTRUCTION_STAGE, OBJECT_TEMPLATES], evidence=EVIDENCE),

    RecordSchema('DIAL', 'Dialog Topic', [
        EDID(), FULL(),
        Member('PNAM', 'priority', F32),
        Member('BNAM', 'branch', FormLink('DLBR')),
        Member('QNAM', 'quest', FormLink('QUST')),
        Member('KNAM', 'keyword', FormLink('KYWD')),
        Member('TIFC', 'info_count', U32),
    ], evidence=EVIDENCE),

    RecordSchema('COBJ', 'Constructible Object', [
        EDID(),
        Member('DESC', 'description', LString()),
        Member('BNAM', 'workbench_keyword', FormLink('KYWD')),
        Member('CNAM', 'created_object', FormLink()),
        Member('NNAM', 'amount_produced', U16),
        Member('SNAM', 'menu_priority', F32),
        Member('TNAM', 'tier', U8),
        Member('LRNM', 'learn_method', U8),
        Member('DATA', 'value', U32),
        Member('ANAM', 'menu_art_object', FormLink('ARTO')),
        Member('JNAM', 'max_build_count', FormLink('GLOB')),
        Member('FNAM', 'recipe_filters', Array(FormLink('KYWD'))),
    ], header_flags={26: 'Outpost list recipe'}, evidence=EVIDENCE),
]

COUNTERS = {('MISC', 'KSIZ'): 'KWDA', ('CONT', 'KSIZ'): 'KWDA', ('NPC_', 'KSIZ'): 'KWDA', ('CONT', 'COCT'): 'CNTO'}

_INVENTORY_PATH = Path(__file__).with_name('data') / 'xedit_sf1_inventory.json'


def load_inventory() -> dict | None:
    return json.loads(_INVENTORY_PATH.read_text(encoding='utf-8')) if _INVENTORY_PATH.exists() else None


_ORDER_PATH = Path(__file__).with_name('data') / 'subrecord_order.json'


def load_subrecord_order() -> dict:
    """signature -> observed majority order of top-level subrecords (tools/derive_subrecord_order.py)."""
    if not _ORDER_PATH.exists():
        return {}
    return {sig: t['order'] for sig, t in json.loads(_ORDER_PATH.read_text(encoding='utf-8'))['types'].items()}


def schema_set() -> SchemaSet:
    orders = load_subrecord_order()
    for schema in SCHEMAS:
        schema.field_order = orders.get(schema.signature)
    for (sig, counter), target in COUNTERS.items():
        schema = next(s for s in SCHEMAS if s.signature == sig)
        schema.by_sig(target).counter = counter
    from . import SCHEMA_VERSION
    return SchemaSet(SCHEMAS, load_inventory(), module='pyfield.games.starfield.records', version=SCHEMA_VERSION)
