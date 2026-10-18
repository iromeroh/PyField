"""Starfield save games (.sfs) — reading, verified layers only (2026-10-15/16).

Container `BCPS` v1: header (u64 chunk table offset 72, u64 data offset, u64 uncompressed size,
u64 flags 0x40000000, u64 chunk size 262144, u64 alignment 16), one u32 compressed size per
chunk, then zlib streams (each inflating to `chunk size`), each start aligned to 16.

Payload `SFS_SAVEGAME`: u32 header size, header (u32 engine version, u8 save version, u32 save
number, player name, u32 level, location, play time, race, u16 sex, f32 xp, f32 xp needed,
u64 FILETIME, 8 bytes, u32), u8 form version, current and created game version strings,
u16 plugin-info size, plugin info, then a u16 + 12 × u32 pointer block (+52 bytes), and
`(u32, u32 strings array offset, u32)`. Plugin info layout follows Nexus-Mods
StarfieldSaveTool's SFS-decompressed.bt (version gates 122 and 140); everything else here was
checked against real saves. Pointers: [0] FormID array (u32 count + runtime FormIDs),
[1]/[11] unknown tables, [2..5] data regions, [6..9] counts (change forms = [9]).

RefID: 3 bytes, value v (24 bits): kind = v >> 22 (0 = index into the FormID array,
1 = FormID 0x00xxxxxx of the first master, 2 = created form 0xFF000000 | value).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
import zlib

from ...errors import FormatError


def read_container(data: bytes) -> bytes:
    """Decompress a BCPS save container to its SFS_SAVEGAME payload."""
    if data[:4] != b'BCPS':
        raise FormatError('not a Starfield save (missing BCPS)')
    _, version, table, _, data_off, total, _, chunk, align = struct.unpack_from('<4sIQQQQQQQ', data, 0)
    if version != 1:
        raise FormatError(f'unsupported BCPS version {version}')
    count = -(-total // chunk)
    sizes = struct.unpack_from(f'<{count}I', data, table)
    out, pos = bytearray(), data_off
    for size in sizes:
        out += zlib.decompress(data[pos:pos + size])
        pos += size
        pos = (pos + align - 1) // align * align
    if len(out) != total:
        raise FormatError(f'payload {len(out)} bytes, header says {total}')
    return bytes(out)


def _qstr(buf, pos):
    n, = struct.unpack_from('<H', buf, pos)
    return buf[pos + 2:pos + 2 + n].decode('utf-8', 'replace'), pos + 2 + n


@dataclass
class SaveHeader:
    engine_version: int
    save_version: int
    save_number: int
    player_name: str
    player_level: int
    location: str
    play_time: str
    race: str
    form_version: int
    game_version: str
    created_version: str


@dataclass
class SaveGame:
    path: Path | None
    payload: bytes
    header: SaveHeader
    plugins: list = field(default_factory=list)          # full plugins in runtime order
    light_plugins: list = field(default_factory=list)
    medium_plugins: list = field(default_factory=list)
    pointers: tuple = ()
    strings: list = field(default_factory=list)
    _form_ids: tuple | None = field(default=None, repr=False)

    @classmethod
    def open(cls, path) -> 'SaveGame':
        path = Path(path)
        save = cls.parse(read_container(path.read_bytes()))
        save.path = path
        return save

    @classmethod
    def parse(cls, raw: bytes) -> 'SaveGame':
        if raw[:12] != b'SFS_SAVEGAME':
            raise FormatError('not an SFS_SAVEGAME payload')
        hsize, = struct.unpack_from('<I', raw, 12)
        h = raw[16:16 + hsize]
        engine, = struct.unpack_from('<I', h, 0)
        save_version = h[4]
        save_number, = struct.unpack_from('<I', h, 5)
        p = 9
        name, p = _qstr(h, p)
        level, = struct.unpack_from('<I', h, p)
        p += 4
        location, p = _qstr(h, p)
        play_time, p = _qstr(h, p)
        race, p = _qstr(h, p)
        q = 16 + hsize
        form_version = raw[q]
        game_version, q = _qstr(raw, q + 1)
        created, q = _qstr(raw, q)
        info_size, = struct.unpack_from('<H', raw, q)
        q += 2
        plugins, lights, mediums = cls._plugin_info(raw, q, form_version)
        t = q + info_size
        pointers = struct.unpack_from('<12I', raw, t + 2)
        _, strings_off, _ = struct.unpack_from('<III', raw, t + 2 + 48 + 52)
        save = cls(None, raw, SaveHeader(engine, save_version, save_number, name, level, location, play_time,
                                         race, form_version, game_version, created),
                   plugins, lights, mediums, pointers)
        save.strings = cls._strings(raw, strings_off)
        return save

    @staticmethod
    def _plugin_info(raw, q, version):
        q += 2                                     # unknown0, count0 (StarfieldSaveTool)
        count = raw[q]
        q += 1

        def plugin(q):
            name, q = _qstr(raw, q)
            if version >= 140:
                extra = raw[q]
                q += 1
                if extra == 1:
                    q = _skip_creation(raw, q)
            return name, q
        full = []
        for _ in range(count):
            name, q = plugin(q)
            full.append(name)
        n_light, = struct.unpack_from('<H', raw, q)
        q += 2
        light = []
        for _ in range(n_light):
            name, q = plugin(q)
            light.append(name)
        medium = []
        if version >= 122:
            n_medium, = struct.unpack_from('<I', raw, q)
            q += 4
            for _ in range(n_medium):
                name, q = plugin(q)
                medium.append(name)
        return full, light, medium

    @staticmethod
    def _strings(raw, off):
        n, = struct.unpack_from('<H', raw, off)
        pos, out = off + 2, []
        for _ in range(n):
            s, pos = _qstr(raw, pos)
            out.append(s)
        return out

    # -- FormIDs ---------------------------------------------------------------------------------
    @property
    def form_ids(self) -> tuple:
        if self._form_ids is None:
            off = self.pointers[0]
            n, = struct.unpack_from('<I', self.payload, off)
            self._form_ids = struct.unpack_from(f'<{n}I', self.payload, off + 4)
        return self._form_ids

    def resolve_refid(self, value: int) -> int:
        """Runtime FormID for a 24-bit RefID value."""
        kind, v = value >> 22, value & 0x3FFFFF
        if kind == 0:
            return self.form_ids[v] if v < len(self.form_ids) else 0
        if kind == 1:
            return v
        if kind == 2:
            return 0xFF000000 | v
        raise FormatError(f'RefID kind {kind}')

    def plugin_of(self, runtime_form_id: int) -> str | None:
        hi = runtime_form_id >> 24
        if hi == 0xFF:
            return '(created in save)'
        if hi == 0xFE:
            i = (runtime_form_id >> 12) & 0xFFF
            return self.light_plugins[i] if i < len(self.light_plugins) else None
        if hi == 0xFD:
            i = (runtime_form_id >> 16) & 0xFF
            return self.medium_plugins[i] if i < len(self.medium_plugins) else None
        return self.plugins[hi] if hi < len(self.plugins) else None


def _skip_creation(raw, q):
    _, q = _qstr(raw, q)       # creation name
    _, q = _qstr(raw, q)       # creation id
    n, = struct.unpack_from('<H', raw, q)
    q += 2 + n                 # flags
    return q + 1               # achievement friendly
