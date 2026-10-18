"""Asset index: which file (loose or in which archive) provides an asset path.

Precedence follows the game: archives in load order (base archives first, then each
plugin's `<plugin> - *.ba2`), later ones overriding earlier; loose files override archives.
Resolution of a referenced string is *verified*: a candidate path counts only if a provider
exists for it. Game knowledge (asset roots, default roots per extension, implicit
extensions, official plugin names) comes from an `AssetRules` object supplied by the adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path

from .ba2 import Archive, normalize


@dataclass(frozen=True)
class AssetRules:
    roots: tuple[str, ...]                          # top-level asset folders, lower case
    extension_roots: dict = field(default_factory=dict)   # '.nif' -> 'meshes/'
    implicit: tuple = ()                            # (root, extension) tried for extension-less names
    base_archives: tuple[str, ...] = ()             # glob patterns of base-game archives
    official_plugins: tuple[str, ...] = ()          # glob patterns (lower case) of first-party plugins
    texture_extensions: tuple[str, ...] = ('.dds',)
    unverifiable: tuple = ()                        # (root, extension): may live in a compiled database
    opaque_prefixes: tuple[str, ...] = ()           # files not scanned generically (handled by hooks)

    def is_unverifiable(self, text: str) -> bool:
        return any(c.startswith(root) and c.endswith(ext) for c in self.candidates(text)
                   for root, ext in self.unverifiable)

    def candidates(self, text: str) -> list[str]:
        path = normalize(text.strip().strip('\0'))
        if not path:
            return []
        out = [path]
        ext = Path(path).suffix.lower()
        first = path.split('/', 1)[0]
        if ext and first not in self.roots and ext in self.extension_roots:
            out.append(self.extension_roots[ext] + path)
        if not ext:
            for root, implicit_ext in self.implicit:
                out.append((path if first == root.rstrip('/') else root + path) + implicit_ext)
        return list(dict.fromkeys(out))

    def is_official(self, plugin_name: str) -> bool:
        name = plugin_name.lower()
        return any(fnmatch.fnmatchcase(name, pat) for pat in self.official_plugins)


@dataclass(frozen=True)
class Provider:
    kind: str                  # 'loose' | 'archive'
    path: Path                 # loose file or archive file
    owner: str | None          # plugin stem owning the archive (None for base archives / loose)

    def __str__(self):
        return f'{self.kind}:{self.path.name}'


class AssetIndex:
    def __init__(self, data_dir, rules: AssetRules, plugins=(), include_loose: bool = True):
        """plugins: plugin file names in load order (their `<stem> - *.ba2` archives are indexed)."""
        self.data_dir = Path(data_dir)
        self.rules = rules
        self.include_loose = include_loose
        self.archives: list[Archive] = []
        self._owner: dict[Path, str | None] = {}
        self._entries: dict[str, Archive] = {}
        files = sorted(p for p in self.data_dir.iterdir() if p.suffix.lower() == '.ba2') \
            if self.data_dir.is_dir() else []
        base = [p for p in files if any(fnmatch.fnmatchcase(p.name.lower(), g.lower()) for g in rules.base_archives)]
        for p in base:
            self._add(p, None)
        for plugin in plugins:
            stem = Path(plugin).stem.lower()
            for p in files:
                if p not in base and p.name.lower().startswith(stem + ' - '):
                    self._add(p, Path(plugin).stem)

    def _add(self, path: Path, owner):
        arc = Archive(path)
        self.archives.append(arc)
        self._owner[arc.path] = owner
        for name in arc.members:
            self._entries[name] = arc

    # -- lookup -----------------------------------------------------------------------------
    def _loose(self, name: str) -> Path | None:
        if not self.include_loose:
            return None
        p = self.data_dir / name
        return p if p.is_file() else None

    def provider(self, name: str) -> Provider | None:
        name = normalize(name)
        loose = self._loose(name)
        if loose is not None:
            return Provider('loose', loose, None)
        arc = self._entries.get(name)
        if arc is not None:
            return Provider('archive', arc.path, self._owner[arc.path])
        return None

    def exists(self, name: str) -> bool:
        return self.provider(name) is not None

    def resolve(self, text: str) -> str | None:
        """The asset path a referenced string denotes, if a provider exists for it."""
        for cand in self.rules.candidates(text):
            if self.exists(cand):
                return cand
        return None

    def read(self, name: str) -> bytes:
        name = normalize(name)
        loose = self._loose(name)
        if loose is not None:
            return loose.read_bytes()
        arc = self._entries.get(name)
        if arc is None:
            raise FileNotFoundError(name)
        return arc.read(name)

    def names(self, prefix: str = '') -> list[str]:
        prefix = normalize(prefix)
        return sorted(n for n in self._entries if n.startswith(prefix))

    def classify(self, provider: Provider, source_plugin: str | None = None) -> str:
        """owned (by source_plugin) | vanilla | foreign | loose."""
        if provider.kind == 'loose':
            return 'loose'
        if provider.owner is None:
            return 'vanilla'
        if source_plugin and provider.owner.lower() == Path(source_plugin).stem.lower():
            return 'owned'
        if self.rules.is_official(provider.owner + '.esm'):
            return 'vanilla'
        return 'foreign'
