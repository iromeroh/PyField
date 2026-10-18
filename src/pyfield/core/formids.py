"""Stable record identity.

On disk a FormID is *file-relative*: its high bits select one of the file's masters (or
the file itself). The same record therefore has different raw FormIDs in different
files. `FormKey(plugin, local_id)` is the load-order-independent identity used by the
rest of PyField; a per-file `FormIdCodec` converts between the two.

The codec is generic over three master namespaces, matching what is observed in modern
Bethesda files (see docs/formats/starfield-formids.md):

- ``full``:   ``II LLLLLL``            ordinal among full masters, 24-bit local ID
- ``medium``: ``FD II LLLL``           ordinal among medium masters, 16-bit local ID
- ``small``:  ``FE III LLL``           ordinal among small masters, 12-bit local ID

A game without medium/small masters (Oblivion) simply never declares those kinds.
The file's own records use either the ordinal after the last full master ("ordinal"
style, written by the Creation Kit for user plugins) or the namespace matching its own
kind ("compact" style, seen in Bethesda-built medium/small masters). Both decode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from ..errors import ResolutionError

FULL, MEDIUM, SMALL, UNKNOWN = 'full', 'medium', 'small', 'unknown'
_LOCAL_BITS = {FULL: 24, MEDIUM: 16, SMALL: 12}


def canonical_name(name: str) -> str:
    return name.lower()


@dataclass(frozen=True, slots=True, order=True)
class FormKey:
    plugin: str          # canonical (lower-case) file name of the defining plugin
    local_id: int

    def __post_init__(self):
        object.__setattr__(self, 'plugin', canonical_name(self.plugin))
        if not 0 <= self.local_id <= 0xFFFFFF:
            raise ValueError(f'local id out of range: {self.local_id:#x}')

    def __str__(self):
        return f'{self.local_id:06X}:{self.plugin}'

    def __repr__(self):
        return f'FormKey({self})'

    @classmethod
    def parse(cls, text: str) -> 'FormKey':
        m = re.fullmatch(r'\s*([0-9A-Fa-f]{1,6})\s*[:@]\s*(.+?)\s*', text)
        if not m:
            raise ValueError(f'not a FormKey: {text!r} (expected "00ABCD:PluginFile")')
        return cls(m.group(2), int(m.group(1), 16))


@dataclass(frozen=True, slots=True)
class MasterRef:
    name: str
    kind: str = UNKNOWN


@dataclass
class FormIdCodec:
    """Converts raw FormIDs of one file to FormKeys and back."""
    self_name: str
    masters: list[MasterRef]
    self_kind: str = FULL
    own_style: str = 'ordinal'           # 'ordinal' or 'compact' (used for encoding own IDs)
    namespaces: frozenset = frozenset({FULL, MEDIUM, SMALL})
    assumptions: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._by_kind = {FULL: [], MEDIUM: [], SMALL: []}
        for m in self.masters:
            kind = m.kind
            if kind == UNKNOWN:
                self.assumptions.append(f'master {m.name} kind unknown; assumed full')
                kind = FULL
            if kind not in self.namespaces:
                raise ResolutionError(f'master {m.name}: {kind} masters do not exist in this format')
            self._by_kind[kind].append(canonical_name(m.name))
        self._lookup = {}
        for kind, names in self._by_kind.items():
            for i, n in enumerate(names):
                self._lookup[n] = (kind, i)
        self._self = canonical_name(self.self_name)

    @property
    def certain(self) -> bool:
        return not self.assumptions

    def master_names(self) -> list[str]:
        return [canonical_name(m.name) for m in self.masters]

    # -- decoding -----------------------------------------------------------------------------
    def decode(self, raw: int) -> FormKey | None:
        """FormKey for a raw FormID; None for the null reference 0. Raises ResolutionError."""
        if raw == 0:
            return None
        hi = raw >> 24
        if hi == 0xFE and SMALL in self.namespaces:
            return self._namespaced(SMALL, (raw >> 12) & 0xFFF, raw & 0xFFF, raw)
        if hi == 0xFD and MEDIUM in self.namespaces:
            return self._namespaced(MEDIUM, (raw >> 16) & 0xFF, raw & 0xFFFF, raw)
        fulls = self._by_kind[FULL]
        if hi < len(fulls):
            return FormKey(fulls[hi], raw & 0xFFFFFF)
        if hi == len(fulls):
            return FormKey(self._self, raw & 0xFFFFFF)
        raise ResolutionError(f'{raw:08X}: master index {hi} out of range in {self.self_name}')

    def _namespaced(self, kind, index, local, raw):
        names = self._by_kind[kind]
        if index < len(names):
            return FormKey(names[index], local)
        if index == len(names) and self.self_kind == kind:
            return FormKey(self._self, local)
        raise ResolutionError(f'{raw:08X}: {kind} master index {index} out of range in {self.self_name}')

    def try_decode(self, raw: int):
        try:
            return self.decode(raw)
        except ResolutionError:
            return Unresolved(raw)

    # -- encoding -----------------------------------------------------------------------------
    def encode(self, key: FormKey | None) -> int:
        if key is None:
            return 0
        if key.plugin == self._self:
            kind = self.self_kind if self.own_style == 'compact' else FULL
            index = len(self._by_kind[kind])
        elif key.plugin in self._lookup:
            kind, index = self._lookup[key.plugin]
        else:
            raise ResolutionError(f'{key}: {key.plugin} is not a master of {self.self_name}')
        if key.local_id >> _LOCAL_BITS[kind]:
            raise ResolutionError(f'{key}: local id does not fit a {kind} FormID')
        if kind == SMALL:
            return 0xFE000000 | index << 12 | key.local_id
        if kind == MEDIUM:
            return 0xFD000000 | index << 16 | key.local_id
        if index >= 0xFD:
            raise ResolutionError(f'too many full masters for {key}')
        return index << 24 | key.local_id

    def is_own(self, raw: int) -> bool:
        key = self.try_decode(raw)
        return isinstance(key, FormKey) and key.plugin == self._self


@dataclass(frozen=True, slots=True)
class Unresolved:
    """A raw FormID that cannot be mapped in its file's context (kept, never guessed)."""
    raw: int

    def __str__(self):
        return f'{self.raw:08X}:<unresolved>'
