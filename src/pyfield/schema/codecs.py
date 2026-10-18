"""Value codecs: bytes <-> Python values for subrecord payloads.

Every codec reads from a buffer at a position and returns (value, new_position), and
writes a value back to bytes. Decoding then encoding an unmodified value must reproduce
the original bytes exactly; `Struct` keeps any trailing bytes it does not model, and
FormLinks keep unresolvable raw values, so typed access never loses data.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any, Iterator

from ..core.formids import FormKey, Unresolved
from ..errors import ResolutionError, SchemaError


class Context:
    """What decoding needs from the containing plugin."""

    def __init__(self, codec=None, localized=False):
        self.codec = codec            # FormIdCodec of the file the bytes belong to
        self.localized = localized


class Codec:
    kind = 'codec'
    size: int | None = None           # fixed byte size, if any

    def read(self, buf, pos: int, ctx: Context):
        raise NotImplementedError

    def write(self, value, ctx: Context) -> bytes:
        raise NotImplementedError

    def default(self):
        return None

    def links(self, value) -> Iterator[tuple[str, Any]]:
        """(path, FormKey|Unresolved) for every FormLink inside `value`."""
        return iter(())

    def describe(self) -> str:
        return self.kind

    # whole-payload helpers ------------------------------------------------------------------
    def decode(self, data: bytes, ctx: Context):
        value, pos = self.read(data, 0, ctx)
        if pos != len(data):
            raise SchemaError(f'{self.describe()}: {len(data) - pos} unread trailing bytes')
        return value

    def encode(self, value, ctx: Context) -> bytes:
        return self.write(value, ctx)


class Int(Codec):
    kind = 'int'

    def __init__(self, fmt: str = '<I'):
        self.fmt = fmt
        self.size = struct.calcsize(fmt)

    def read(self, buf, pos, ctx):
        if pos + self.size > len(buf):
            raise SchemaError(f'{self.describe()} needs {self.size} bytes')
        return struct.unpack_from(self.fmt, buf, pos)[0], pos + self.size

    def write(self, value, ctx):
        try:
            return struct.pack(self.fmt, int(value))
        except struct.error as exc:
            raise SchemaError(f'{self.describe()}: {value!r}: {exc}') from None

    def default(self):
        return 0

    def describe(self):
        return {'<B': 'u8', '<H': 'u16', '<I': 'u32', '<Q': 'u64', '<b': 'i8', '<h': 'i16',
                '<i': 'i32', '<q': 'i64'}.get(self.fmt, self.fmt)


U8, U16, U32, I8, I16, I32 = Int('<B'), Int('<H'), Int('<I'), Int('<b'), Int('<h'), Int('<i')


class Float(Codec):
    """f32. Values that do not survive a float round-trip (NaN payloads) are kept as raw bits."""
    kind = 'float'
    size = 4

    def read(self, buf, pos, ctx):
        if pos + 4 > len(buf):
            raise SchemaError('f32 needs 4 bytes')
        value = struct.unpack_from('<f', buf, pos)[0]
        if math.isnan(value) and struct.pack('<f', value) != bytes(buf[pos:pos + 4]):
            return RawFloat(bytes(buf[pos:pos + 4])), pos + 4
        return value, pos + 4

    def write(self, value, ctx):
        if isinstance(value, RawFloat):
            return value.raw
        return struct.pack('<f', float(value))

    def default(self):
        return 0.0

    def describe(self):
        return 'f32'


@dataclass(frozen=True)
class RawFloat:
    raw: bytes

    def __float__(self):
        return struct.unpack('<f', self.raw)[0]


F32 = Float()


class Bool8(Codec):
    kind = 'bool'
    size = 1

    def read(self, buf, pos, ctx):
        v = buf[pos]
        return (v if v > 1 else bool(v)), pos + 1     # odd values are kept, not normalized

    def write(self, value, ctx):
        return bytes([int(value)])

    def default(self):
        return False


class ZString(Codec):
    """Null-terminated UTF-8. A payload without terminator is preserved as such."""
    kind = 'zstring'

    def read(self, buf, pos, ctx):
        end = bytes(buf[pos:]).find(b'\0')
        if end < 0:
            return ZText(bytes(buf[pos:]).decode('utf-8', 'surrogateescape'), terminated=False), len(buf)
        raw = bytes(buf[pos:pos + end])
        return ZText(raw.decode('utf-8', 'surrogateescape')), pos + end + 1

    def write(self, value, ctx):
        data = str(value).encode('utf-8', 'surrogateescape')
        return data if isinstance(value, ZText) and not value.terminated else data + b'\0'

    def default(self):
        return ''


class ZText(str):
    """str that remembers whether its source was null-terminated."""

    def __new__(cls, value, terminated=True):
        obj = super().__new__(cls, value)
        obj.terminated = terminated
        return obj


@dataclass(frozen=True)
class StringRef:
    """Localized string id (resolved through .strings files, which PyField does not read yet)."""
    id: int

    def __str__(self):
        return f'<lstring {self.id:#x}>'


class LString(Codec):
    """Localized string: a u32 id in localized plugins, otherwise a null-terminated string."""
    kind = 'lstring'

    def read(self, buf, pos, ctx):
        if ctx.localized:
            v, pos = U32.read(buf, pos, ctx)
            return StringRef(v), pos
        return ZString().read(buf, pos, ctx)

    def write(self, value, ctx):
        if isinstance(value, StringRef):
            if not ctx.localized:
                raise SchemaError('cannot write a string id into a non-localized plugin')
            return struct.pack('<I', value.id)
        if ctx.localized:
            raise SchemaError('localized plugin: assign a StringRef (string tables are not supported)')
        return ZString().write(value, ctx)


class Bytes(Codec):
    kind = 'bytes'

    def __init__(self, size: int | None = None):
        self.size = size

    def read(self, buf, pos, ctx):
        end = len(buf) if self.size is None else pos + self.size
        if end > len(buf):
            raise SchemaError(f'bytes[{self.size}] past end')
        return bytes(buf[pos:end]), end

    def write(self, value, ctx):
        value = bytes(value)
        if self.size is not None and len(value) != self.size:
            raise SchemaError(f'expected {self.size} bytes, got {len(value)}')
        return value

    def default(self):
        return bytes(self.size or 0)

    def describe(self):
        return f'bytes[{self.size if self.size is not None else "*"}]'


class Empty(Codec):
    """Marker subrecord with no payload."""
    kind = 'empty'
    size = 0

    def read(self, buf, pos, ctx):
        return True, pos

    def write(self, value, ctx):
        return b''

    def default(self):
        return True


class FormLink(Codec):
    """u32 file-relative FormID <-> FormKey (None for null)."""
    kind = 'formlink'
    size = 4

    def __init__(self, *targets: str):
        self.targets = tuple(targets)      # allowed target signatures (documentation + validation)

    def read(self, buf, pos, ctx):
        raw, pos = U32.read(buf, pos, ctx)
        if ctx.codec is None:
            return Unresolved(raw) if raw else None, pos
        return ctx.codec.try_decode(raw), pos

    def write(self, value, ctx):
        if value is None:
            return b'\0\0\0\0'
        if isinstance(value, Unresolved):
            return struct.pack('<I', value.raw)
        if isinstance(value, str):
            try:
                value = FormKey.parse(value)
            except ValueError as exc:
                raise SchemaError(str(exc)) from None
        if not isinstance(value, FormKey):
            raise SchemaError(f'FormLink needs a FormKey, got {value!r}')
        if ctx.codec is None:
            raise ResolutionError('no FormID context for encoding a FormKey')
        return struct.pack('<I', ctx.codec.encode(value))

    def links(self, value):
        if value is not None:
            yield '', value

    def describe(self):
        return f'formlink[{"|".join(self.targets) or "*"}]'


class Flags(Codec):
    kind = 'flags'

    def __init__(self, base: Int, names: dict[int, str]):
        self.base, self.names, self.size = base, names, base.size

    def read(self, buf, pos, ctx):
        return self.base.read(buf, pos, ctx)

    def write(self, value, ctx):
        if isinstance(value, (set, frozenset, list, tuple)):
            lookup = {n: b for b, n in self.names.items()}
            value = sum(1 << lookup[n] for n in value)
        return self.base.write(value, ctx)

    def default(self):
        return 0

    def names_of(self, value: int) -> list[str]:
        return [self.names.get(b, f'bit{b}') for b in range(self.base.size * 8) if value >> b & 1]

    def describe(self):
        return f'flags<{self.base.describe()}>'


class Enum(Codec):
    kind = 'enum'

    def __init__(self, base: Int, names: dict[int, str]):
        self.base, self.names, self.size = base, names, base.size

    def read(self, buf, pos, ctx):
        return self.base.read(buf, pos, ctx)

    def write(self, value, ctx):
        if isinstance(value, str):
            lookup = {n: v for v, n in self.names.items()}
            value = lookup[value]
        return self.base.write(value, ctx)

    def default(self):
        return 0

    def describe(self):
        return f'enum<{self.base.describe()}>'


class StructValue:
    """Ordered named values with attribute access. `_extra` holds unmodelled trailing bytes."""

    __slots__ = ('_names', '_values', '_extra')

    def __init__(self, names, values, extra=b''):
        object.__setattr__(self, '_names', tuple(names))
        object.__setattr__(self, '_values', dict(zip(names, values)))
        object.__setattr__(self, '_extra', extra)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name not in self._values:
            raise AttributeError(f'no field {name!r}; fields: {self._names}')
        self._values[name] = value

    def __getitem__(self, key):
        return self._values[self._names[key]] if isinstance(key, int) else self._values[key]

    def __iter__(self):
        return (self._values[n] for n in self._names)

    def __eq__(self, other):
        return isinstance(other, StructValue) and self._names == other._names and \
            self._values == other._values and self._extra == other._extra

    def to_dict(self):
        return {n: (v.to_dict() if isinstance(v, StructValue) else v) for n, v in self._values.items()}

    def __repr__(self):
        inner = ', '.join(f'{n}={self._values[n]!r}' for n in self._names)
        return f'({inner}{", +" + str(len(self._extra)) + "B" if self._extra else ""})'


class Struct(Codec):
    """Sequence of named codecs.

    optional_from: fields at or after this index may be absent (shorter older layouts);
    absent fields decode as None and are not written. Bytes after the last modelled field
    are preserved in `_extra` when `allow_extra` is set.
    """
    kind = 'struct'

    def __init__(self, fields: list[tuple[str, Codec]], optional_from: int | None = None, allow_extra=False):
        self.fields = fields
        self.optional_from = optional_from
        self.allow_extra = allow_extra
        sizes = [c.size for _, c in fields]
        self.size = None if None in sizes or optional_from is not None or allow_extra else sum(sizes)

    def read(self, buf, pos, ctx):
        values = []
        for i, (name, codec) in enumerate(self.fields):
            if self.optional_from is not None and i >= self.optional_from and pos >= len(buf):
                values.append(None)
                continue
            try:
                value, pos = codec.read(buf, pos, ctx)
            except SchemaError as exc:
                raise SchemaError(f'{name}: {exc}') from None
            values.append(value)
        extra = b''
        if self.allow_extra:
            extra, pos = bytes(buf[pos:]), len(buf)
        return StructValue([n for n, _ in self.fields], values, extra), pos

    def write(self, value, ctx):
        if isinstance(value, dict):
            value = StructValue(list(value), list(value.values()))
        out = bytearray()
        for i, (name, codec) in enumerate(self.fields):
            v = value[name] if name in value._names else None
            if v is None and self.optional_from is not None and i >= self.optional_from:
                break
            out += codec.write(v, ctx)
        return bytes(out) + value._extra

    def default(self):
        return StructValue([n for n, _ in self.fields], [c.default() for _, c in self.fields])

    def make(self, **values) -> StructValue:
        base = self.default()
        for k, v in values.items():
            setattr(base, k, v)
        return base

    def links(self, value):
        for name, codec in self.fields:
            v = value[name] if value is not None else None
            if v is not None:
                for path, link in codec.links(v):
                    yield (f'{name}.{path}' if path else name), link

    def describe(self):
        return '{' + ', '.join(f'{n}: {c.describe()}' for n, c in self.fields) + '}'


class Array(Codec):
    """Homogeneous array: count is 'rest' (fills the payload), an Int prefix, or a fixed number."""
    kind = 'array'

    def __init__(self, element: Codec, count: 'str | Int | int' = 'rest'):
        self.element, self.count = element, count

    def read(self, buf, pos, ctx):
        items = []
        if isinstance(self.count, Int):
            n, pos = self.count.read(buf, pos, ctx)
        elif isinstance(self.count, int):
            n = self.count
        else:
            n = None
        while (n is None and pos < len(buf)) or (n is not None and len(items) < n):
            v, pos = self.element.read(buf, pos, ctx)
            items.append(v)
        return items, pos

    def write(self, value, ctx):
        value = list(value)
        prefix = b''
        if isinstance(self.count, Int):
            prefix = self.count.write(len(value), ctx)
        elif isinstance(self.count, int) and len(value) != self.count:
            raise SchemaError(f'array needs exactly {self.count} items')
        return prefix + b''.join(self.element.write(v, ctx) for v in value)

    def default(self):
        return [self.element.default() for _ in range(self.count)] if isinstance(self.count, int) else []

    def links(self, value):
        for i, v in enumerate(value or ()):
            for path, link in self.element.links(v):
                yield (f'[{i}].{path}' if path else f'[{i}]'), link

    def describe(self):
        return f'array<{self.element.describe()}>'


def vec3(*names) -> Struct:
    names = names or ('x', 'y', 'z')
    return Struct([(n, F32) for n in names])


def rgba() -> Struct:
    return Struct([('r', U8), ('g', U8), ('b', U8), ('a', U8)])
