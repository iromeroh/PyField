"""Lazy, preserving node tree.

Physical containment (which group holds which record) is modelled here and only here;
references between records are a separate, schema-level concern.

Preservation contract:
- A group that was never expanded serializes as its original bytes.
- A record whose header and decoded fields are unchanged serializes as its original
  bytes, including the original compressed stream.
- Only modified records are re-encoded; enclosing group sizes are recomputed.
"""
from __future__ import annotations

import struct
from typing import Iterator

from ..errors import FormatError
from . import compression, subrecords as sr
from .format import FormatSpec
from .subrecords import Subrecord


def _sig(raw: bytes) -> str:
    return raw.decode('latin-1')


class RecordNode:
    __slots__ = ('spec', 'header', '_orig_header', '_stored', '_fields', '_plain_len',
                 '_cache', 'parent', 'offset', '__weakref__')

    def __init__(self, spec: FormatSpec, header, stored, parent=None, offset=None):
        if len(header) != spec.record_header_size:
            raise FormatError('bad record header length', offset)
        self.spec = spec
        self.header = bytearray(header)
        self._orig_header = bytes(header) if offset is not None else None
        self._stored = stored            # body exactly as on disk (maybe compressed)
        self._fields = None              # decoded list[Subrecord] once accessed
        self._cache = None               # encoded bytes for the current save pass
        self.parent = parent
        self.offset = offset             # source offset; None for created records

    # -- construction ---------------------------------------------------------------------------
    @classmethod
    def new(cls, spec: FormatSpec, signature: str, form_id: int, fields=(), flags=0, header_tail=b''):
        header = bytearray(spec.record_header_size)
        struct.pack_into('<4sIII', header, 0, signature.encode('latin-1'), 0, flags, form_id)
        header[16:16 + len(header_tail)] = header_tail
        node = cls(spec, header, b'')
        node._fields = list(fields)
        return node

    def copy(self) -> 'RecordNode':
        """Detached, unmodified-looking copy (as a new record: it always re-encodes)."""
        node = RecordNode(self.spec, bytes(self.header), b'')
        node._fields = [Subrecord(f.signature, f.data) for f in self.fields]
        return node

    # -- header ---------------------------------------------------------------------------------
    @property
    def signature(self) -> str:
        return _sig(bytes(self.header[:4]))

    @property
    def form_id(self) -> int:
        return struct.unpack_from('<I', self.header, 12)[0]

    @form_id.setter
    def form_id(self, value: int):
        struct.pack_into('<I', self.header, 12, value)

    @property
    def flags(self) -> int:
        return struct.unpack_from('<I', self.header, 8)[0]

    @flags.setter
    def flags(self, value: int):
        struct.pack_into('<I', self.header, 8, value)

    @property
    def header_tail(self) -> bytes:
        """Version-control and form-version bytes after the common 16; opaque to the core."""
        return bytes(self.header[16:])

    @property
    def is_compressed(self) -> bool:
        return bool(self.flags & self.spec.compressed_flag)

    # -- body -----------------------------------------------------------------------------------
    def plain_body(self) -> bytes:
        """Original body, decompressed. Does not reflect unsaved field edits."""
        if self._orig_header is None:
            return sr.encode(self._fields or [], self.spec)
        if struct.unpack_from('<I', self._orig_header, 8)[0] & self.spec.compressed_flag:
            return compression.decompress(self._stored, self.offset)
        return bytes(self._stored)

    @property
    def fields(self) -> list[Subrecord]:
        """Ordered subrecords. Mutate freely; changes are detected at save time."""
        if self._fields is None:
            self._fields = sr.parse(self.plain_body(), self.spec, self.offset)
        return self._fields

    @fields.setter
    def fields(self, value):
        self._fields = list(value)

    @property
    def is_loaded(self) -> bool:
        return self._fields is not None

    def get(self, signature: str, default=None) -> Subrecord | None:
        return next((f for f in self.fields if f.signature == signature), default)

    def get_all(self, signature: str) -> list[Subrecord]:
        return [f for f in self.fields if f.signature == signature]

    @property
    def editor_id(self) -> str | None:
        sig = self.spec.editor_id_signature
        field = self.get(sig) if sig else None
        return field.data.rstrip(b'\0').decode('utf-8', 'replace') if field else None

    # -- change detection -------------------------------------------------------------------------
    @property
    def is_new(self) -> bool:
        return self._orig_header is None

    def is_modified(self) -> bool:
        if self.is_new:
            return True
        if bytes(self.header) != self._orig_header:
            return True
        return self.body_modified()

    def body_modified(self) -> bool:
        """True if the decoded fields no longer encode to the original body."""
        if self.is_new:
            return True
        if self._fields is None:
            return False
        return sr.encode(self._fields, self.spec) != self.plain_body()

    def _compression_changed(self) -> bool:
        flag = self.spec.compressed_flag
        return bool(struct.unpack_from('<I', self._orig_header, 8)[0] & flag) != self.is_compressed

    def _encode_body(self) -> bytes:
        body = sr.encode(self.fields, self.spec)
        if self.is_compressed:
            level = None
            orig_compressed = self._orig_header is not None and \
                struct.unpack_from('<I', self._orig_header, 8)[0] & self.spec.compressed_flag
            if orig_compressed:
                level = compression.detect_level(self._stored, self.plain_body())
            body = compression.compress(body, self.spec.zlib_level if level is None else level)
        return body

    # -- serialization ---------------------------------------------------------------------------
    def to_bytes(self) -> bytes:
        if self._cache is not None:
            return self._cache
        if not self.is_modified():
            return bytes(self.header) + bytes(self._stored)
        if not self.body_modified() and not self._compression_changed():
            # header-only edit (flags, FormID, version bytes): keep the stored body verbatim
            header = bytearray(self.header)
            struct.pack_into('<I', header, 4, len(self._stored))
            return bytes(header) + bytes(self._stored)
        body = self._encode_body()
        header = bytearray(self.header)
        struct.pack_into('<I', header, 4, len(body))
        return bytes(header) + body

    def nbytes(self) -> int:
        self._cache = self.to_bytes()   # cached for the rest of this save pass (see end_save)
        return len(self._cache)

    def iter_chunks(self) -> Iterator[bytes]:
        yield self.to_bytes()

    def end_save(self):
        self._cache = None

    def __repr__(self):
        edid = f' {self.editor_id!r}' if self._fields is not None and self.editor_id else ''
        return f'<{self.signature} {self.form_id:08X}{edid}>'


class GroupNode:
    __slots__ = ('spec', 'header', '_raw', '_children', '_size', 'parent', 'offset', '__weakref__')

    def __init__(self, spec: FormatSpec, header, raw=None, parent=None, offset=None):
        self.spec = spec
        self.header = bytearray(header)
        self._raw = raw          # full original bytes including header, or None for new groups
        self._children = None if raw is not None else []
        self._size = None        # cached during a save pass
        self.parent = parent
        self.offset = offset

    @classmethod
    def new(cls, spec: FormatSpec, label: bytes, kind: int, header_tail=b''):
        header = bytearray(spec.group_header_size)
        struct.pack_into('<4sI4si', header, 0, spec.group_signature, 0, label, kind)
        header[16:16 + len(header_tail)] = header_tail
        return cls(spec, header)

    @property
    def label_bytes(self) -> bytes:
        return bytes(self.header[8:12])

    @property
    def label_int(self) -> int:
        return struct.unpack_from('<I', self.header, 8)[0]

    @property
    def label_signature(self) -> str:
        return _sig(self.label_bytes)

    @property
    def kind(self) -> int:
        return struct.unpack_from('<i', self.header, 12)[0]

    @property
    def is_expanded(self) -> bool:
        return self._children is not None

    @property
    def children(self) -> list:
        """Direct children (records and groups). Expanding is lazy and one level deep."""
        if self._children is None:
            start = self.offset + self.spec.group_header_size
            self._children = list(parse_nodes(self.spec, self._raw, self.spec.group_header_size,
                                              len(self._raw), self, start))
        return self._children

    def records(self) -> Iterator[RecordNode]:
        """Direct record children only."""
        return (c for c in self.children if isinstance(c, RecordNode))

    def groups(self) -> Iterator['GroupNode']:
        return (c for c in self.children if isinstance(c, GroupNode))

    def walk(self) -> Iterator:
        """Depth-first, document order; expands everything it visits."""
        for child in self.children:
            yield child
            if isinstance(child, GroupNode):
                yield from child.walk()

    def append(self, node):
        node.parent = self
        self.children.append(node)
        return node

    def insert(self, index, node):
        node.parent = self
        self.children.insert(index, node)
        return node

    def remove(self, node):
        self.children.remove(node)
        node.parent = None

    def nbytes(self) -> int:
        if self._size is None:
            if self._children is None:
                self._size = len(self._raw)
            else:
                self._size = self.spec.group_header_size + sum(c.nbytes() for c in self._children)
        return self._size

    def iter_chunks(self) -> Iterator[bytes]:
        if self._children is None:
            header = bytearray(self.header)   # keeps label/kind edits; size is unchanged
            struct.pack_into('<I', header, 4, len(self._raw))
            yield bytes(header)
            yield bytes(self._raw[self.spec.group_header_size:])
            return
        header = bytearray(self.header)
        struct.pack_into('<I', header, 4, self.nbytes())
        yield bytes(header)
        for child in self._children:
            yield from child.iter_chunks()

    def end_save(self):
        self._size = None
        if self._children is not None:
            for child in self._children:
                child.end_save()

    def __repr__(self):
        return f'<GRUP kind={self.kind} label={self.label_bytes.hex()}>'


def parse_nodes(spec: FormatSpec, data, start: int, end: int, parent=None, base=0) -> Iterator:
    """Yield sibling nodes in data[start:end]; `base` is data's offset in the source file."""
    rh, gh = spec.record_header_size, spec.group_header_size
    gsig = spec.group_signature
    pos = start
    while pos < end:
        if pos + 16 > end:
            raise FormatError('truncated header', base + pos - start)
        sig = bytes(data[pos:pos + 4])
        size, = struct.unpack_from('<I', data, pos + 4)
        if sig == gsig:
            if size < gh or pos + size > end:
                raise FormatError(f'invalid group size {size}', base + pos - start)
            yield GroupNode(spec, data[pos:pos + gh], data[pos:pos + size], parent, base + pos - start)
            pos += size
        else:
            if pos + rh + size > end:
                raise FormatError(f'record {sig!r} exceeds its container', base + pos - start)
            yield RecordNode(spec, data[pos:pos + rh], data[pos + rh:pos + rh + size], parent, base + pos - start)
            pos += rh + size
