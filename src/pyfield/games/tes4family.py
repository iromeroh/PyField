"""Shared definitions for the TES4 plugin family (Oblivion, Fallout 3/NV, Skyrim, Fallout 4, Starfield).

Container format, the `TES4` header record (HEDR / MAST / CNAM / SNAM) and the group
kind meanings are common to these games; adapters pick the variant they need.
"""
from __future__ import annotations

import struct

from ..core.format import FormatSpec
from ..core.groups import GroupLayout
from ..core.header import HeaderScheme
from ..core.subrecords import Subrecord

_COMMON = dict(plugin_header_signature=b'TES4', group_signature=b'GRUP', compressed_flag=0x00040000,
               extended_size_signature=b'XXXX', subrecord_size_format='<H', editor_id_signature='EDID')

TES4_FORMAT = FormatSpec('tes4', record_header_size=20, group_header_size=20, zlib_level=6, **_COMMON)
MODERN_FORMAT = FormatSpec('tes5+', record_header_size=24, group_header_size=24, zlib_level=9, **_COMMON)

_KIND_NAMES = {0: 'top', 1: 'world_children', 2: 'interior_block', 3: 'interior_subblock',
               4: 'exterior_block', 5: 'exterior_subblock', 6: 'cell_children', 7: 'topic_children',
               8: 'cell_persistent', 9: 'cell_temporary'}

TES4_GROUPS = GroupLayout(
    top_kind=0, kind_names=_KIND_NAMES,
    owner_kinds=frozenset({1, 6, 7}), formid_label_kinds=frozenset({1, 6, 7, 8, 9}),
    grid_kinds=frozenset({4, 5}), nested_top_groups=frozenset({'CELL', 'WRLD', 'DIAL'}), world_kind=1)

# Fallout 4 / Starfield add kind 10 (quest children: DIAL/SCEN inside a QUST).
MODERN_GROUPS = GroupLayout(
    top_kind=0, kind_names={**_KIND_NAMES, 10: 'quest_children'},
    owner_kinds=frozenset({1, 6, 7, 10}), formid_label_kinds=frozenset({1, 6, 7, 8, 9, 10}),
    grid_kinds=frozenset({4, 5}), nested_top_groups=frozenset({'CELL', 'WRLD', 'DIAL', 'QUST'}), world_kind=1)


def _z(text: str) -> bytes:
    return text.encode('utf-8') + b'\0'


def _unz(data: bytes) -> str:
    return data.split(b'\0', 1)[0].decode('utf-8', 'replace')


class Tes4HeaderScheme(HeaderScheme):
    """HEDR <f version, u32 count, u32 next object>, CNAM author, SNAM description, MAST [DATA]."""

    def __init__(self, master_list_has_data: bool):
        self.master_list_has_data = master_list_has_data

    def new_fields(self, masters, author, description, version, next_object_id):
        fields = [Subrecord('HEDR', struct.pack('<fII', version, 0, next_object_id))]
        if author:
            fields.append(Subrecord('CNAM', _z(author)))
        if description:
            fields.append(Subrecord('SNAM', _z(description)))
        for m in masters:
            fields += self._master_fields(m)
        return fields

    def _master_fields(self, name):
        out = [Subrecord('MAST', _z(name))]
        if self.master_list_has_data:
            out.append(Subrecord('DATA', bytes(8)))
        return out

    def masters(self, fields):
        return [_unz(f.data) for f in fields if f.signature == 'MAST']

    def add_master(self, fields, name):
        last = max((i for i, f in enumerate(fields) if f.signature in ('MAST', 'DATA')), default=None)
        if last is None:
            last = max(i for i, f in enumerate(fields) if f.signature in ('HEDR', 'CNAM', 'SNAM', 'OFST', 'DELE'))
        fields[last + 1:last + 1] = self._master_fields(name)

    def author(self, fields):
        return next((_unz(f.data) for f in fields if f.signature == 'CNAM'), None)

    def description(self, fields):
        return next((_unz(f.data) for f in fields if f.signature == 'SNAM'), None)

    def _hedr(self, fields):
        for f in fields:
            if f.signature == 'HEDR':
                return f
        raise ValueError('plugin header has no HEDR')

    def counts(self, fields):
        return struct.unpack('<fII', self._hedr(fields).data[:12])

    def set_counts(self, fields, count, next_object_id):
        hedr = self._hedr(fields)
        version = struct.unpack_from('<f', hedr.data)[0]
        data = struct.pack('<fII', version, count, next_object_id) + hedr.data[12:]
        if data != hedr.data:
            hedr.data = data

    def sniff(self, head, record_header_size):
        rh = record_header_size
        if len(head) < rh + 10 or head[:4] != b'TES4' or head[rh:rh + 4] != b'HEDR':
            return None
        return struct.unpack_from('<f', head, rh + 6)[0]


def vmad_formid_offsets(data: bytes):
    """Offsets of object-property FormIDs in a VMAD (version 6, object format 2), or None.

    Superseded by pyfield.games.vmad.formid_offsets (structs, variables, all versions >= 5); kept for
    callers of the old name. Flat properties only: struct properties make it return None.

    Layout per interstellar_liners/docs/ESM_RECORD_EDITING_GUIDE.md: u16 version, u16 object
    format, u16 script count; per script: u16-length name, u8 status, u16 property count; per
    property: u16-length name, u8 type, u8 status, value. Object values are <HhI> (unused, alias,
    FormID); arrays (types 11-15) have a u32 count. Data after the scripts (quest fragments,
    aliases) is not interpreted; it never contains offsets reported here.
    """
    try:
        version, fmt, count = struct.unpack_from('<hhH', data, 0)
        if version != 6 or fmt != 2:
            return None
        pos, offsets = 6, set()
        sizes = {3: 4, 4: 4, 5: 1}
        for _ in range(count):
            n, = struct.unpack_from('<H', data, pos)
            pos += 2 + n + 1
            props, = struct.unpack_from('<H', data, pos)
            pos += 2
            for _ in range(props):
                n, = struct.unpack_from('<H', data, pos)
                pos += 2 + n
                kind = data[pos]
                pos += 2
                items, base = 1, kind
                if kind >= 11:
                    items, = struct.unpack_from('<I', data, pos)
                    pos += 4
                    base = kind - 10
                for _ in range(items):
                    if base == 1:
                        offsets.add(pos + 4)
                        pos += 8
                    elif base == 2:
                        n, = struct.unpack_from('<H', data, pos)
                        pos += 2 + n
                    elif base in sizes:
                        pos += sizes[base]
                    elif base != 0:
                        return None
            if pos > len(data):
                return None
        return offsets
    except (struct.error, IndexError):
        return None


class StringTables:
    """Localized string tables (`strings/<plugin>_<language>.STRINGS/.DLSTRINGS/.ILSTRINGS`).

    Directory: u32 count, u32 data size, count × (u32 id, u32 offset); `.STRINGS` entries are
    null-terminated, the other two are u32 length-prefixed. Texts are returned as the raw bytes
    stored in the table (no re-encoding), without terminator.
    """

    EXTENSIONS = ('strings', 'dlstrings', 'ilstrings')

    def __init__(self, assets, language: str = 'en'):
        self.assets = assets
        self.language = language
        self._tables = {}

    def _load(self, plugin_name: str) -> dict:
        stem = plugin_name.rsplit('.', 1)[0].lower()
        if stem not in self._tables:
            table = {}
            for ext in self.EXTENSIONS:
                name = f'strings/{stem}_{self.language}.{ext}'
                if not self.assets.exists(name):
                    continue
                data = self.assets.read(name)
                count, _ = struct.unpack_from('<II', data, 0)
                base = 8 + 8 * count
                for i in range(count):
                    sid, off = struct.unpack_from('<II', data, 8 + 8 * i)
                    pos = base + off
                    if ext == 'strings':
                        text = data[pos:data.index(b'\0', pos)]
                    else:
                        n, = struct.unpack_from('<I', data, pos)
                        text = data[pos + 4:pos + 4 + n].rstrip(b'\0')
                    table.setdefault(sid, text)
            self._tables[stem] = table
        return self._tables[stem]

    def lookup(self, plugin_name: str, string_id: int) -> bytes | None:
        return self._load(plugin_name).get(string_id)
