"""Asset dependency discovery: records -> files -> files, every candidate verified.

Strings are found by scanning (records: path-like text in any subrecord; NIF and other
binaries: length-prefixed strings; JSON: every string value). A candidate becomes a
dependency only if the AssetIndex resolves it to an existing file; everything else is
reported as unresolved, never assumed. Adapter hooks add structured dependencies that are
not plain paths (Starfield: Wwise events -> soundbank files).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import re
import struct

from .index import AssetIndex

PRINTABLE = re.compile(rb'[\x20-\x7e]{4,260}')
PATHY = re.compile(r'[\\/]|\.[A-Za-z0-9]{2,7}$')
SCANNED_EXTENSIONS = ('.nif', '.mat', '.json', '.txt', '.agx', '.rig', '.bgsm', '.bgem')


@dataclass
class AssetRef:
    path: str                  # resolved, normalized asset path
    source: str                # what referenced it ('STAT 01000800:MODL', 'meshes/x.nif', ...)
    provider: str = ''         # 'archive:<file>' / 'loose:<file>'
    category: str = ''         # owned | vanilla | foreign | loose


@dataclass
class AssetClosure:
    files: dict = field(default_factory=dict)       # path -> AssetRef (first reference)
    unresolved: list = field(default_factory=list)  # (source, text) that looked like paths but resolve nowhere
    external: list = field(default_factory=list)    # (source, text) living in a compiled database (unverifiable)

    def by_category(self) -> dict:
        out = {}
        for ref in self.files.values():
            out.setdefault(ref.category, []).append(ref.path)
        return {k: sorted(v) for k, v in out.items()}

    def to_dict(self):
        return {'files': {p: {'source': r.source, 'provider': r.provider, 'category': r.category}
                          for p, r in sorted(self.files.items())},
                'unresolved': self.unresolved, 'external_unverified': self.external,
                'by_category': self.by_category()}


def record_strings(fields) -> list[tuple[str, str]]:
    """(subrecord signature, text) for path-like printable runs in a record's subrecords."""
    out = []
    for f in fields:
        for m in PRINTABLE.finditer(f.data):
            text = m.group(0).decode('latin-1').strip()
            if PATHY.search(text):
                out.append((f.signature, text))
    return out


def binary_strings(data: bytes) -> list[str]:
    """Length-prefixed (u32 or u16) printable strings, as NIF and similar formats store them."""
    out, n = set(), len(data)
    for i in range(n - 6):
        for width, fmt in ((4, '<I'), (2, '<H')):
            length = struct.unpack_from(fmt, data, i)[0]
            if 4 <= length <= 260 and i + width + length <= n:
                chunk = data[i + width:i + width + length]
                if chunk.isascii() and all(32 <= b < 127 for b in chunk.rstrip(b'\0')):
                    text = chunk.rstrip(b'\0').decode('ascii')
                    if PATHY.search(text) or '\\' in text:
                        out.add(text)
                    break
    return sorted(out)


def json_strings(data: bytes) -> list[str]:
    try:
        obj = json.loads(data)
    except ValueError:
        return [m.group(0).decode('latin-1') for m in PRINTABLE.finditer(data)]
    out = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return out


def file_strings(path: str, data: bytes) -> list[str]:
    if path.endswith(('.mat', '.json')):
        return json_strings(data)
    if path.endswith('.txt'):
        return [line.strip() for line in data.decode('utf-8', 'replace').splitlines() if line.strip()]
    return binary_strings(data)


class DependencyFinder:
    def __init__(self, assets: AssetIndex, record_hooks: dict | None = None, source_plugin: str | None = None):
        """record_hooks: {signature: fn(view, assets, cache) -> [paths]} for structured references."""
        self.assets = assets
        self.hooks = record_hooks or {}
        self.source_plugin = source_plugin
        self._cache = {}

    def _ref(self, path, source):
        prov = self.assets.provider(path)
        return AssetRef(path, source, str(prov), self.assets.classify(prov, self.source_plugin))

    def _unresolved(self, closure, source, text):
        if not re.search(r'\.(nif|mat|dds|wem|bnk|mesh|af|afx|rig|pex|swf)$', text, re.I):
            return
        if self.assets.rules.is_unverifiable(text):
            closure.external.append((source, text))
        else:
            closure.unresolved.append((source, text))

    def for_records(self, views, follow: bool = True) -> AssetClosure:
        closure = AssetClosure()
        queue = deque()
        for view in views:
            label = f'{view.signature} {view.form_key}'
            found = set()
            for sig, text in record_strings(view.node.fields):
                resolved = self.assets.resolve(text)
                if resolved:
                    found.add((resolved, f'{label}:{sig}'))
                else:
                    self._unresolved(closure, f'{label}:{sig}', text)
            hook = self.hooks.get(view.signature)
            if hook:
                for path in hook(view, self.assets, self._cache):
                    found.add((path, f'{label}:{view.signature}-hook'))
            for path, source in sorted(found):
                if path not in closure.files:
                    closure.files[path] = self._ref(path, source)
                    queue.append(path)
        if follow:
            self._follow(closure, queue)
        return closure

    def for_files(self, paths) -> AssetClosure:
        closure = AssetClosure()
        queue = deque()
        for p in paths:
            resolved = self.assets.resolve(p)
            if resolved is None:
                closure.unresolved.append(('request', p))
                continue
            closure.files[resolved] = self._ref(resolved, 'request')
            queue.append(resolved)
        self._follow(closure, queue)
        return closure

    def _follow(self, closure: AssetClosure, queue: deque):
        while queue:
            path = queue.popleft()
            if not path.endswith(SCANNED_EXTENSIONS) or path.startswith(self.assets.rules.opaque_prefixes):
                continue
            try:
                data = self.assets.read(path)
            except FileNotFoundError:
                continue
            for text in file_strings(path, data):
                resolved = self.assets.resolve(text)
                if resolved is None:
                    self._unresolved(closure, path, text)
                    continue
                if resolved != path and resolved not in closure.files:
                    closure.files[resolved] = self._ref(resolved, path)
                    queue.append(resolved)
