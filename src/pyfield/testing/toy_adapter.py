"""A deliberately non-Bethesda format, used to prove the core is game-agnostic.

Differences from the TES4 family: 16-byte record/group headers with no tail, group
signature `BOX_` with top-level kind 7, u32 subrecord sizes and no extended-size field,
compression flag 0x1, editor IDs in `IDNT`, and a header record `TOYP` holding
`VERS` (f32), `INFO` (u32 count, u32 next ID), `AUTH` and repeated `DEPS` (masters).
Kind 3 groups are "children of a ROOM" (owner kind); `ROOM` is a nested top-level group.
"""
from __future__ import annotations

import struct

from ..capabilities import Capability, CapabilitySet, Status
from ..core.format import FormatSpec
from ..core.groups import GroupLayout
from ..core.header import HeaderScheme
from ..core.subrecords import Subrecord
from ..games import register
from ..games.base import GameAdapter
from ..schema.codecs import F32, FormLink, U32, ZString
from ..schema.records import Member, RecordSchema, SchemaSet

TOY_FORMAT = FormatSpec('toy', record_header_size=16, group_header_size=16, plugin_header_signature=b'TOYP',
                        group_signature=b'BOX_', compressed_flag=0x1, extended_size_signature=None,
                        subrecord_size_format='<I', zlib_level=1, editor_id_signature='IDNT')

TOY_GROUPS = GroupLayout(top_kind=7, kind_names={7: 'top', 3: 'room_contents'}, owner_kinds=frozenset({3}),
                         formid_label_kinds=frozenset({3}), nested_top_groups=frozenset({'ROOM'}))


def _z(text):
    return text.encode() + b'\0'


class ToyHeader(HeaderScheme):
    def new_fields(self, masters, author, description, version, next_object_id):
        fields = [Subrecord('VERS', struct.pack('<f', version)),
                  Subrecord('INFO', struct.pack('<II', 0, next_object_id))]
        if author:
            fields.append(Subrecord('AUTH', _z(author)))
        fields += [Subrecord('DEPS', _z(m)) for m in masters]
        return fields

    def masters(self, fields):
        return [f.data.rstrip(b'\0').decode() for f in fields if f.signature == 'DEPS']

    def add_master(self, fields, name):
        fields.append(Subrecord('DEPS', _z(name)))

    def author(self, fields):
        return next((f.data.rstrip(b'\0').decode() for f in fields if f.signature == 'AUTH'), None)

    def counts(self, fields):
        version = next(struct.unpack('<f', f.data)[0] for f in fields if f.signature == 'VERS')
        count, next_id = next(struct.unpack('<II', f.data) for f in fields if f.signature == 'INFO')
        return version, count, next_id

    def set_counts(self, fields, count, next_object_id):
        for i, f in enumerate(fields):
            if f.signature == 'INFO':
                fields[i] = Subrecord('INFO', struct.pack('<II', count, next_object_id))

    def sniff(self, head, record_header_size):
        if head[:4] != b'TOYP' or head[16:20] != b'VERS':
            return None
        return struct.unpack_from('<f', head, 24)[0]


TOY_SCHEMAS = [
    RecordSchema('ITEM', 'Toy Item', [
        Member('IDNT', 'editor_id', ZString()),
        Member('WGHT', 'weight', F32),
        Member('PRCE', 'price', U32),
    ]),
    RecordSchema('PLCE', 'Toy Placement', [
        Member('IDNT', 'editor_id', ZString()),
        Member('BASE', 'base', FormLink('ITEM'), required=True),
        Member('XPOS', 'x', F32),
    ]),
]

ADAPTER = register(GameAdapter(
    name='toy',
    title='Toy format (tests only)',
    format=TOY_FORMAT,
    header=ToyHeader(),
    groups=TOY_GROUPS,
    header_versions=(2.5,),
    default_header_version=2.5,
    native_group_order=('ITEM', 'ROOM'),
    first_object_id=0x10,
    capabilities=CapabilitySet([Capability('binary.read', Status.SUPPORTED)]),
    schema_loader=lambda: SchemaSet(TOY_SCHEMAS),
    schema_version='toy-1',
), replace=True)
