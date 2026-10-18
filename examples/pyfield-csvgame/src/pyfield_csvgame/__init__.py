"""Reference third-party adapter for PyField.

"CSV game" is an invented format: 16-byte headers, signature `CSVG`, groups `CSG_`,
u16 subrecord sizes, no compression, editor IDs in `ENAM`. It shows the minimum an adapter
package needs: a FormatSpec, a HeaderScheme, a GroupLayout, capabilities, optional
schemas, and an entry point (see pyproject.toml).
"""
from __future__ import annotations

import struct

from pyfield import Capability, CapabilitySet, Status
from pyfield.core.format import FormatSpec
from pyfield.core.groups import GroupLayout
from pyfield.core.header import HeaderScheme
from pyfield.core.subrecords import Subrecord
from pyfield.games.base import GameAdapter
from pyfield.schema.codecs import F32, ZString
from pyfield.schema.records import Member, RecordSchema, SchemaSet

__version__ = '0.1.0'
SCHEMA_VERSION = 'csvgame-1'


class CsvHeader(HeaderScheme):
    """Header record CSVG: HEAD <f32 version, u32 count, u32 next id>, then DEP_ per master."""

    def new_fields(self, masters, author, description, version, next_object_id):
        return [Subrecord('HEAD', struct.pack('<fII', version, 0, next_object_id))] + \
            [Subrecord('DEP_', m.encode() + b'\0') for m in masters]

    def masters(self, fields):
        return [f.data.rstrip(b'\0').decode() for f in fields if f.signature == 'DEP_']

    def add_master(self, fields, name):
        fields.append(Subrecord('DEP_', name.encode() + b'\0'))

    def counts(self, fields):
        return struct.unpack('<fII', next(f.data for f in fields if f.signature == 'HEAD'))

    def set_counts(self, fields, count, next_object_id):
        for i, f in enumerate(fields):
            if f.signature == 'HEAD':
                version = struct.unpack_from('<f', f.data)[0]
                fields[i] = Subrecord('HEAD', struct.pack('<fII', version, count, next_object_id))

    def sniff(self, head, record_header_size):
        if head[:4] != b'CSVG' or head[record_header_size:record_header_size + 4] != b'HEAD':
            return None
        return struct.unpack_from('<f', head, record_header_size + 6)[0]


def make_adapter() -> GameAdapter:
    return GameAdapter(
        name='csvgame',
        title='CSV Game (reference adapter)',
        format=FormatSpec('csvgame', record_header_size=16, group_header_size=16,
                          plugin_header_signature=b'CSVG', group_signature=b'CSG_', compressed_flag=0,
                          extended_size_signature=None, editor_id_signature='ENAM'),
        header=CsvHeader(),
        groups=GroupLayout(top_kind=0, kind_names={0: 'top'}),
        header_versions=(1.0,),
        native_group_order=('ROW_',),
        first_object_id=1,
        capabilities=CapabilitySet([Capability('binary.read', Status.SUPPORTED),
                                    Capability('edit.transactions', Status.SUPPORTED)]),
        schema_loader=lambda: SchemaSet([RecordSchema('ROW_', 'Row', [
            Member('ENAM', 'editor_id', ZString()),
            Member('VALU', 'value', F32),
        ])], version=SCHEMA_VERSION),
        schema_version=SCHEMA_VERSION,
    )
