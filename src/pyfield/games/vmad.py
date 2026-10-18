"""VMAD (attached Papyrus scripts and their properties), versions 5-6, object format 2 (FO4 / Starfield).

    vm = Vmad.decode(record.get('VMAD').data)
    prop = vm.script('ShipVendorListScript').property('ShipList')
    prop.value                     # [Struct([...Property('leveledShip', OBJECT, ...)]), ...]
    record_bytes = vm.encode()     # byte-identical when nothing changed

Layout: i16 version, i16 object format, u16 script count; per script: wstring name, u8 status (version >= 4),
u16 property count; per property: wstring name, u8 type, u8 status, value. Values: 1 object = u16 unused,
i16 alias, u32 FormID; 2 string = wstring; 3 int = i32; 4 float = f32; 5 bool = u8; 6 variable = a nested
(u8 type, value); 7 struct = u32 member count + properties; 11-17 = u32 count + elements of type - 10.
Bytes after the scripts (quest/scene/info/perk fragments, aliases) are kept verbatim in `suffix`.
FormIDs stay raw (file-relative); use the plugin codec to turn them into FormKeys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

NONE, OBJECT, STRING, INT, FLOAT, BOOL, VARIABLE, STRUCT = range(8)
ARRAY = 10                                   # array type = element type + ARRAY (11..17)
TYPE_NAMES = {NONE: 'none', OBJECT: 'object', STRING: 'string', INT: 'int', FLOAT: 'float', BOOL: 'bool',
              VARIABLE: 'variable', STRUCT: 'struct'}


class VmadError(ValueError):
    pass


@dataclass
class ObjectRef:
    form_id: int                 # raw, file-relative
    alias: int = -1
    unused: int = 0


@dataclass
class Variable:
    type: int
    value: object


@dataclass
class Property:
    name: str
    type: int
    value: object
    status: int = 1

    @property
    def type_name(self) -> str:
        if self.type > ARRAY:
            return TYPE_NAMES.get(self.type - ARRAY, str(self.type - ARRAY)) + '[]'
        return TYPE_NAMES.get(self.type, str(self.type))


@dataclass
class Struct:
    members: list = field(default_factory=list)      # [Property]

    def member(self, name: str) -> Property | None:
        return next((m for m in self.members if m.name.lower() == name.lower()), None)


@dataclass
class Script:
    name: str
    status: int = 0
    properties: list = field(default_factory=list)   # [Property]

    def property(self, name: str) -> Property | None:
        return next((p for p in self.properties if p.name.lower() == name.lower()), None)


@dataclass
class Vmad:
    version: int = 6
    object_format: int = 2
    scripts: list = field(default_factory=list)
    suffix: bytes = b''
    fragments: object = None      # Fragments when the suffix was decoded (decode(..., signature=...))

    def script(self, name: str) -> Script | None:
        return next((s for s in self.scripts if s.name.lower() == name.lower()), None)

    # -- decode -----------------------------------------------------------------------------------
    @classmethod
    def decode(cls, data: bytes, signature: str | None = None) -> 'Vmad':
        """signature (record type) enables structured fragments/aliases; else the suffix stays raw."""
        r = _Reader(data)
        version, fmt, count = r.unpack('<hhH')
        if fmt != 2:
            raise VmadError(f'object format {fmt} not supported')
        vm = cls(version, fmt)
        for _ in range(count):
            name = r.wstring()
            status = r.u8() if version >= 4 else 0
            n, = r.unpack('<H')
            vm.scripts.append(Script(name, status, [r.property() for _ in range(n)]))
        vm.suffix = bytes(data[r.pos:])
        if signature is not None and vm.suffix:
            vm.fragments = decode_fragments(signature, vm.suffix)
        return vm

    # -- encode -----------------------------------------------------------------------------------
    def encode(self) -> bytes:
        w = bytearray(struct.pack('<hhH', self.version, self.object_format, len(self.scripts)))
        for s in self.scripts:
            _wstring(w, s.name)
            if self.version >= 4:
                w.append(s.status)
            w += struct.pack('<H', len(s.properties))
            for p in s.properties:
                _property(w, p)
        return bytes(w) + (encode_fragments(self.fragments) if self.fragments is not None else self.suffix)

    # -- FormIDs ----------------------------------------------------------------------------------
    def object_refs(self):
        """Every ObjectRef in script properties (structs and arrays included), in file order."""
        def walk(value, kind):
            base = kind - ARRAY if kind > ARRAY else kind
            items = value if kind > ARRAY else [value]
            for item in items:
                if base == OBJECT:
                    yield item
                elif base == STRUCT:
                    for m in item.members:
                        yield from walk(m.value, m.type)
                elif base == VARIABLE:
                    yield from walk(item.value, item.type)
        scripts = list(self.scripts)
        if self.fragments is not None:
            if self.fragments.script is not None:
                scripts.append(self.fragments.script)
            for qa in self.fragments.aliases:
                yield qa.alias
                scripts.extend(qa.scripts)
        for s in scripts:
            for p in s.properties:
                yield from walk(p.value, p.type)


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0
        self.object_offsets = []                    # offsets of raw FormIDs, in file order

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise VmadError(f'truncated at {self.pos}')
        values = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return values

    def u8(self) -> int:
        return self.unpack('<B')[0]

    def wstring(self) -> str:
        n, = self.unpack('<H')
        if self.pos + n > len(self.data):
            raise VmadError(f'string overruns at {self.pos}')
        text = self.data[self.pos:self.pos + n].decode('utf-8', 'surrogateescape')
        self.pos += n
        return text

    def property(self) -> Property:
        name = self.wstring()
        kind, status = self.unpack('<BB')
        return Property(name, kind, self.value(kind), status)

    def value(self, kind: int):
        if kind > ARRAY:
            n, = self.unpack('<I')
            if n > len(self.data):
                raise VmadError(f'array count {n} at {self.pos}')
            return [self.value(kind - ARRAY) for _ in range(n)]
        if kind == NONE:
            return None
        if kind == OBJECT:
            self.object_offsets.append(self.pos + 4)
            unused, alias, form_id = self.unpack('<HhI')
            return ObjectRef(form_id, alias, unused)
        if kind == STRING:
            return self.wstring()
        if kind == INT:
            return self.unpack('<i')[0]
        if kind == FLOAT:
            return self.unpack('<f')[0]
        if kind == BOOL:
            return self.u8()
        if kind == VARIABLE:
            inner = self.u8()
            return Variable(inner, self.value(inner))
        if kind == STRUCT:
            n, = self.unpack('<I')
            return Struct([self.property() for _ in range(n)])
        raise VmadError(f'property type {kind} at {self.pos}')


def _wstring(w: bytearray, text: str):
    data = text.encode('utf-8', 'surrogateescape')
    w += struct.pack('<H', len(data)) + data


def _value(w: bytearray, kind: int, value):
    if kind > ARRAY:
        w += struct.pack('<I', len(value))
        for item in value:
            _value(w, kind - ARRAY, item)
    elif kind == NONE:
        pass
    elif kind == OBJECT:
        w += struct.pack('<HhI', value.unused, value.alias, value.form_id)
    elif kind == STRING:
        _wstring(w, value)
    elif kind == INT:
        w += struct.pack('<i', value)
    elif kind == FLOAT:
        w += struct.pack('<f', value)
    elif kind == BOOL:
        w.append(int(value))
    elif kind == VARIABLE:
        w.append(value.type)
        _value(w, value.type, value.value)
    elif kind == STRUCT:
        w += struct.pack('<I', len(value.members))
        for m in value.members:
            _property(w, m)
    else:
        raise VmadError(f'property type {kind}')


def _property(w: bytearray, p: Property):
    _wstring(w, p.name)
    w += struct.pack('<BB', p.type, p.status)
    _value(w, p.type, p.value)


def formid_offsets(data: bytes, record_signature: str | None = None):
    """Offsets of every object FormID in a VMAD, or None if it does not parse. With the record signature,
    FormIDs in fragment scripts and quest aliases (alias owner + alias script properties) are included;
    without it, or if the suffix does not decode, only the scripts part is covered."""
    try:
        r = _Reader(data)
        version, fmt, count = r.unpack('<hhH')
        if fmt != 2:
            return None
        for _ in range(count):
            r.wstring()
            if version >= 4:
                r.u8()
            n, = r.unpack('<H')
            for _ in range(n):
                r.property()
        offsets = set(r.object_offsets)
        if record_signature is not None and r.pos < len(data):
            offsets |= _suffix_offsets(record_signature, data, r.pos)
        return offsets
    except (VmadError, UnicodeDecodeError):
        return None


def _suffix_offsets(signature: str, data: bytes, start: int) -> set:
    layout = FRAGMENT_LAYOUTS.get(signature)
    if layout is None or decode_fragments(signature, data[start:]) is None:
        return set()
    r = _Reader(data)
    r.pos = start
    header = r.unpack(layout[0])
    name = r.wstring()
    if name:
        r.u8()
        n, = r.unpack('<H')
        for _ in range(n):
            r.property()
    count = header[1] if signature == 'QUST' else bin(header[1]).count('1') if len(header) > 1 else r.unpack('<H')[0]
    for _ in range(count):
        r.unpack(layout[1]); r.wstring(); r.wstring()
    if signature == 'SCEN':
        n, = r.unpack('<H')
        for _ in range(n):
            r.unpack(PHASE_LAYOUT); r.wstring(); r.wstring()
    if signature == 'QUST':
        n, = r.unpack('<H')
        for _ in range(n):
            r.object_offsets.append(r.pos + 4)
            r.unpack('<HhI')
            version, _, scripts = r.unpack('<hhH')
            for _ in range(scripts):
                r.wstring()
                if version >= 4:
                    r.u8()
                k, = r.unpack('<H')
                for _ in range(k):
                    r.property()
    return set(r.object_offsets)


# -- fragments and quest aliases (the bytes after the scripts) ------------------------------------
# Layouts read from Starfield.esm (2026-10-16), validated by exact consumption + byte round trip over
# every VMAD (tests/test_vmad.py, scratchpad corpus run):
#   QUST       u8 version, u16 fragment count, fragment script, fragments '<HhiB' (stage, ?, stage index, ?),
#              u16 alias count, aliases (object value, i16 version, i16 object format, scripts)
#   INFO PACK  u8 version, u8 flags, fragment script, one fragment '<B' per set flag bit
#   SCEN       as INFO, then u16 phase count, phase fragments '<BBhbB'
#   PERK TERM TMLM  u8 version, fragment script, u16 count, fragments '<HhB' (index, ?, ?)
# Fragment script: wstring name; if non-empty, u8 status, u16 property count, properties.
# Every fragment ends with two wstrings: script name, fragment (function) name.

FRAGMENT_LAYOUTS = {
    'QUST': ('<BH', '<HhiB'), 'INFO': ('<BB', '<B'), 'PACK': ('<BB', '<B'), 'SCEN': ('<BB', '<B'),
    'PERK': ('<B', '<HhB'), 'TERM': ('<B', '<HhB'), 'TMLM': ('<B', '<HhB'),
}
PHASE_LAYOUT = '<BBhbB'


@dataclass
class Fragment:
    header: tuple                 # layout-specific numbers (QUST: stage, ?, stage index, ?)
    script: str
    name: str


@dataclass
class QuestAlias:
    alias: ObjectRef              # alias id in .alias, owning quest in .form_id
    version: int = 6
    object_format: int = 2
    scripts: list = field(default_factory=list)

    def script(self, name: str) -> Script | None:
        return next((s for s in self.scripts if s.name.lower() == name.lower()), None)


@dataclass
class Fragments:
    signature: str
    header: tuple                 # QUST: (version, count) / INFO PACK SCEN: (version, flags) / others: (version,)
    script: Script | None         # None: empty fragment script name
    fragments: list = field(default_factory=list)
    phases: list = field(default_factory=list)       # SCEN only
    aliases: list = field(default_factory=list)      # QUST only

    @property
    def version(self) -> int:
        return self.header[0]


def _fragment_script(r: _Reader) -> Script | None:
    name = r.wstring()
    if not name:
        return None
    status = r.u8()
    n, = r.unpack('<H')
    return Script(name, status, [r.property() for _ in range(n)])


def _fragment(r: _Reader, layout: str) -> Fragment:
    return Fragment(r.unpack(layout), r.wstring(), r.wstring())


def decode_fragments(signature: str, data: bytes) -> Fragments | None:
    """Structured fragments/aliases of a VMAD suffix, or None if the layout is unknown or does not fit."""
    layout = FRAGMENT_LAYOUTS.get(signature)
    if layout is None or not data:
        return None
    r = _Reader(data)
    try:
        header = r.unpack(layout[0])
        out = Fragments(signature, header, _fragment_script(r))
        count = header[1] if signature == 'QUST' else bin(header[1]).count('1') if len(header) > 1 else r.unpack('<H')[0]
        out.fragments = [_fragment(r, layout[1]) for _ in range(count)]
        if signature == 'SCEN':
            n, = r.unpack('<H')
            out.phases = [_fragment(r, PHASE_LAYOUT) for _ in range(n)]
        if signature == 'QUST':
            n, = r.unpack('<H')
            for _ in range(n):
                unused, alias, form_id = r.unpack('<HhI')
                version, fmt, scripts = r.unpack('<hhH')
                qa = QuestAlias(ObjectRef(form_id, alias, unused), version, fmt)
                for _ in range(scripts):
                    name = r.wstring()
                    status = r.u8() if version >= 4 else 0
                    k, = r.unpack('<H')
                    qa.scripts.append(Script(name, status, [r.property() for _ in range(k)]))
                out.aliases.append(qa)
        if r.pos != len(data):
            return None
        return out
    except (VmadError, UnicodeDecodeError):
        return None


def encode_fragments(fr: Fragments) -> bytes:
    layout = FRAGMENT_LAYOUTS[fr.signature]
    header = (fr.header[0], len(fr.fragments)) if fr.signature == 'QUST' else fr.header
    w = bytearray(struct.pack(layout[0], *header))
    if fr.script is None:
        _wstring(w, '')
    else:
        _wstring(w, fr.script.name)
        w.append(fr.script.status)
        w += struct.pack('<H', len(fr.script.properties))
        for p in fr.script.properties:
            _property(w, p)
    if len(fr.header) == 1:
        w += struct.pack('<H', len(fr.fragments))
    for f in fr.fragments:
        w += struct.pack(layout[1], *f.header)
        _wstring(w, f.script)
        _wstring(w, f.name)
    if fr.signature == 'SCEN':
        w += struct.pack('<H', len(fr.phases))
        for f in fr.phases:
            w += struct.pack(PHASE_LAYOUT, *f.header)
            _wstring(w, f.script)
            _wstring(w, f.name)
    if fr.signature == 'QUST':
        w += struct.pack('<H', len(fr.aliases))
        for qa in fr.aliases:
            w += struct.pack('<HhI', qa.alias.unused, qa.alias.alias, qa.alias.form_id)
            w += struct.pack('<hhH', qa.version, qa.object_format, len(qa.scripts))
            for s in qa.scripts:
                _wstring(w, s.name)
                if qa.version >= 4:
                    w.append(s.status)
                w += struct.pack('<H', len(s.properties))
                for p in s.properties:
                    _property(w, p)
    return bytes(w)
