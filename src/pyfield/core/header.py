"""Plugin header record contract.

The core needs a few facts from the file's header record (masters, record count, next
object ID, author/description) but not their encoding; a `HeaderScheme` supplied by the
game adapter reads and writes them.
"""
from __future__ import annotations

from typing import Iterable


class HeaderScheme:
    """Interface. See pyfield.games.tes4family.Tes4HeaderScheme for the Bethesda implementation."""

    def new_fields(self, masters: Iterable[str], author: str, description: str,
                   version: float, next_object_id: int) -> list:
        raise NotImplementedError

    def masters(self, fields) -> list[str]:
        raise NotImplementedError

    def add_master(self, fields, name: str) -> None:
        raise NotImplementedError

    def author(self, fields) -> str | None:
        return None

    def description(self, fields) -> str | None:
        return None

    def counts(self, fields) -> tuple[float, int, int]:
        """(version, stored record count, next object ID)."""
        raise NotImplementedError

    def set_counts(self, fields, count: int, next_object_id: int) -> None:
        raise NotImplementedError

    def sniff(self, head: bytes, record_header_size: int) -> float | None:
        """Header version if `head` (first bytes of a file) starts with this header, else None."""
        raise NotImplementedError
