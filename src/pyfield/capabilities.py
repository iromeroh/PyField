"""Capability declarations.

Each adapter declares what it can do and how well it is validated. Callers (and the
CLI `pyfield capabilities`) can inspect this instead of discovering limits by failure,
and `require()` turns an unsupported or unvalidated capability into an explicit error.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import UnsupportedOperation


class Status(str, Enum):
    VALIDATED = 'validated'        # automated tests + external tool or in-game evidence
    SUPPORTED = 'supported'        # automated tests pass; no external evidence yet
    EXPERIMENTAL = 'experimental'  # implemented, known gaps; opt-in
    UNSUPPORTED = 'unsupported'    # raises UnsupportedOperation


@dataclass(frozen=True)
class Capability:
    key: str
    status: Status
    note: str = ''


class CapabilitySet:
    def __init__(self, items=()):
        self._items = {c.key: c for c in items}

    def get(self, key) -> Capability:
        return self._items.get(key, Capability(key, Status.UNSUPPORTED, 'not declared'))

    def require(self, key, allow_experimental=False):
        cap = self.get(key)
        if cap.status == Status.UNSUPPORTED or (cap.status == Status.EXPERIMENTAL and not allow_experimental):
            raise UnsupportedOperation(key, f'{cap.status.value}: {cap.note}' if cap.note else cap.status.value)
        return cap

    def __iter__(self):
        return iter(sorted(self._items.values(), key=lambda c: c.key))

    def report(self) -> list[dict]:
        return [{'capability': c.key, 'status': c.status.value, 'note': c.note} for c in self]
