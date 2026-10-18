"""Compact record index built by a header-only scan.

Large masters (Starfield.esm: ~1.5 GB) are indexed without materializing node objects:
columns live in `array` buffers, and a record node is created only when requested.
"""
from __future__ import annotations

from array import array
from bisect import bisect_left
import struct
from typing import Iterator, NamedTuple

from ..errors import FormatError
from .format import FormatSpec


def sig_to_int(sig: str | bytes) -> int:
    if isinstance(sig, str):
        sig = sig.encode('latin-1')
    return int.from_bytes(sig, 'little')


def int_to_sig(value: int) -> str:
    return value.to_bytes(4, 'little').decode('latin-1')


class IndexEntry(NamedTuple):
    signature: str
    form_id: int
    flags: int
    offset: int
    size: int           # stored body size
    group: int          # index into RecordIndex.groups of the immediate parent group (-1: top level)


class GroupEntry(NamedTuple):
    offset: int
    size: int
    label: bytes
    kind: int
    parent: int         # index of the enclosing group (-1: top level)


class RecordIndex:
    def __init__(self):
        self.form_ids = array('I')
        self.offsets = array('Q')
        self.sizes = array('I')
        self.flags = array('I')
        self.sigs = array('I')
        self.parents = array('i')
        self.groups: list[GroupEntry] = []
        self._by_form_id = None

    def __len__(self):
        return len(self.form_ids)

    @classmethod
    def scan(cls, spec: FormatSpec, data, start: int, end: int | None = None) -> 'RecordIndex':
        idx = cls()
        end = len(data) if end is None else end
        rh, gh = spec.record_header_size, spec.group_header_size
        gsig = spec.group_signature
        unpack = struct.Struct('<4sIII').unpack_from
        fids, offs, sizes, flags, sigs, parents = (idx.form_ids, idx.offsets, idx.sizes, idx.flags,
                                                   idx.sigs, idx.parents)
        groups = idx.groups
        stack = []            # (end, group index)
        parent = -1
        pos = start
        while pos < end:
            while stack and pos >= stack[-1][0]:
                if pos > stack[-1][0]:
                    raise FormatError('node crosses its group boundary', pos)
                stack.pop()
                parent = stack[-1][1] if stack else -1
            if pos + 16 > end:
                raise FormatError('truncated header', pos)
            sig, size, f, fid = unpack(data, pos)
            if sig == gsig:
                if size < gh or pos + size > end:
                    raise FormatError(f'invalid group size {size}', pos)
                groups.append(GroupEntry(pos, size, bytes(data[pos + 8:pos + 12]),
                                         struct.unpack_from('<i', data, pos + 12)[0], parent))
                parent = len(groups) - 1
                stack.append((pos + size, parent))
                pos += gh
            else:
                if pos + rh + size > end:
                    raise FormatError(f'record {sig!r} exceeds file', pos)
                fids.append(fid); offs.append(pos); sizes.append(size); flags.append(f)
                sigs.append(int.from_bytes(sig, 'little')); parents.append(parent)
                pos += rh + size
        return idx

    def entry(self, i: int) -> IndexEntry:
        return IndexEntry(int_to_sig(self.sigs[i]), self.form_ids[i], self.flags[i],
                          self.offsets[i], self.sizes[i], self.parents[i])

    def __iter__(self) -> Iterator[IndexEntry]:
        return (self.entry(i) for i in range(len(self)))

    def of_signature(self, *signatures) -> Iterator[IndexEntry]:
        wanted = {sig_to_int(s) for s in signatures}
        sigs = self.sigs
        return (self.entry(i) for i in range(len(self)) if sigs[i] in wanted)

    def _sorted(self) -> array:
        # (form_id << 32 | position), sorted: ~8 bytes/record instead of a dict's ~100.
        if self._by_form_id is None:
            self._by_form_id = array('Q', sorted(f << 32 | i for i, f in enumerate(self.form_ids)))
        return self._by_form_id

    def positions(self, form_id: int) -> list[int]:
        """Index positions of records with this raw FormID (normally 0 or 1)."""
        table = self._sorted()
        i = bisect_left(table, form_id << 32)
        out = []
        while i < len(table) and table[i] >> 32 == form_id:
            out.append(table[i] & 0xFFFFFFFF)
            i += 1
        return out

    def duplicates(self) -> dict[int, list[int]]:
        table, out = self._sorted(), {}
        for a, b in zip(table, table[1:]):
            if a >> 32 == b >> 32:
                out.setdefault(a >> 32, [a & 0xFFFFFFFF]).append(b & 0xFFFFFFFF)
        return out

    def group_path(self, group: int) -> list[GroupEntry]:
        path = []
        while group != -1:
            g = self.groups[group]
            path.append(g)
            group = g.parent
        return path[::-1]

    def signature_counts(self) -> dict[str, int]:
        counts = {}
        for s in self.sigs:
            counts[s] = counts.get(s, 0) + 1
        return {int_to_sig(k): v for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}
