"""Adapter registry."""
from __future__ import annotations

from pathlib import Path

from ..errors import PyFieldError
from .base import ADAPTER_API_VERSION, GameAdapter

_REGISTRY: dict[str, GameAdapter] = {}


def register(adapter: GameAdapter, replace: bool = False) -> GameAdapter:
    """Make an adapter available by name. Refuses silent replacement of another adapter."""
    if adapter.api_version != ADAPTER_API_VERSION:
        raise PyFieldError(f'adapter {adapter.name!r} targets adapter API {adapter.api_version}, '
                           f'this PyField provides {ADAPTER_API_VERSION}')
    existing = _REGISTRY.get(adapter.name)
    if existing is not None and existing is not adapter and not replace:
        raise PyFieldError(f'adapter {adapter.name!r} already registered')
    _REGISTRY[adapter.name] = adapter
    return adapter


def get(name: str) -> GameAdapter:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise PyFieldError(f'no adapter {name!r}; registered: {sorted(_REGISTRY)}') from None


def adapters() -> list[GameAdapter]:
    _load_builtin()
    return list(_REGISTRY.values())


def detect(head: bytes) -> GameAdapter:
    """Pick the registered adapter whose header sniffing matches these leading bytes."""
    matches = [a for a in adapters() if a.sniff(head)]
    if len(matches) != 1:
        names = [a.name for a in matches]
        raise PyFieldError(f'cannot detect game from plugin header (matches: {names}); pass game=')
    return matches[0]


def detect_file(path) -> GameAdapter:
    with open(Path(path), 'rb') as handle:
        return detect(handle.read(64))


_loaded = False


ENTRY_POINT_GROUP = 'pyfield.adapters'


def _load_builtin():
    """Built-in adapters, then third-party ones from the `pyfield.adapters` entry points.

    An entry point may name a GameAdapter or a zero-argument callable returning one.
    Broken third-party adapters are skipped with a warning instead of breaking import.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    from .starfield import ADAPTER as _sf  # noqa: F401  (registers itself)
    from .oblivion import ADAPTER as _ob  # noqa: F401
    from importlib.metadata import entry_points
    import warnings
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
            adapter = obj() if callable(obj) and not isinstance(obj, GameAdapter) else obj
            if adapter.name not in _REGISTRY:
                register(adapter)
        except Exception as exc:   # one bad plugin must not disable PyField
            warnings.warn(f'pyfield adapter entry point {ep.name!r} failed: {exc}')
