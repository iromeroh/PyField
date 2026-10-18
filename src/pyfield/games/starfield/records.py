"""Typed Starfield record classes, by signature and by class name.

    from pyfield.games.starfield import records
    records.STAT is records.Static        # True
    isinstance(view, records.REFR)        # typed view check

Signatures that are not valid identifiers keep their trailing underscore (NPC_).
"""
from __future__ import annotations


def _classes():
    from . import ADAPTER
    return ADAPTER.schemas.classes


def __getattr__(name):
    classes = _classes()
    if name in classes:
        return classes[name]
    for cls in classes.values():
        if cls.__name__ == name:
            return cls
    raise AttributeError(f'no typed Starfield record {name!r}; available: {sorted(classes)}')


def __dir__():
    classes = _classes()
    return sorted(set(classes) | {c.__name__ for c in classes.values()})
