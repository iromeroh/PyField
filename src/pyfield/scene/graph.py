"""Scene graph: placed objects as a hierarchy of nodes with stable logical identities.

A node's `id` is its stable identity ("camp/crate_2"): the compiler maps ids to FormIDs
through a lock file, so recompiling an unchanged scene reuses every FormID. Group nodes
(base None) only carry a transform for their children. References between placed objects
(linked refs, enable parents) are expressed by node id and resolved at compile time.

Blueprints are reusable node sets (JSON interchange, `BLUEPRINT_VERSION`), instantiated into
a scene under a parent node with an id prefix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Iterator

from ..core.formids import FormKey
from ..errors import PyFieldError
from .transform import DEFAULT_CONVENTION, Transform

BLUEPRINT_VERSION = 1


@dataclass
class Link:
    target: str                      # node id (or FormKey text for an existing reference)
    keyword: FormKey | None = None


@dataclass
class SceneNode:
    id: str
    base: FormKey | None = None      # placed base object; None for a pure transform group
    transform: Transform = field(default_factory=Transform)
    children: list = field(default_factory=list)
    persistent: bool = False
    disabled: bool = False
    links: list = field(default_factory=list)          # [Link]
    enable_parent: str | None = None                   # node id
    properties: dict = field(default_factory=dict)     # typed REFR member values (e.g. {'layer': FormKey})
    tags: tuple = ()

    def __post_init__(self):
        if isinstance(self.base, str):
            self.base = FormKey.parse(self.base)

    def add(self, node: 'SceneNode') -> 'SceneNode':
        self.children.append(node)
        return node

    def walk(self, parent: Transform | None = None) -> Iterator[tuple['SceneNode', Transform]]:
        world = parent.compose(self.transform) if parent is not None else self.transform
        yield self, world
        for child in self.children:
            yield from child.walk(world)

    # -- serialization ----------------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = {'id': self.id}
        if self.base is not None:
            d['base'] = str(self.base)
        d['transform'] = self.transform.to_dict()
        if self.persistent:
            d['persistent'] = True
        if self.disabled:
            d['disabled'] = True
        if self.links:
            d['links'] = [{'target': l.target, **({'keyword': str(l.keyword)} if l.keyword else {})}
                          for l in self.links]
        if self.enable_parent:
            d['enable_parent'] = self.enable_parent
        if self.properties:
            d['properties'] = {k: (str(v) if isinstance(v, FormKey) else v) for k, v in self.properties.items()}
        if self.tags:
            d['tags'] = list(self.tags)
        if self.children:
            d['children'] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict, convention=DEFAULT_CONVENTION) -> 'SceneNode':
        return cls(
            id=d['id'], base=FormKey.parse(d['base']) if d.get('base') else None,
            transform=Transform.from_dict(d.get('transform', {}), convention),
            children=[cls.from_dict(c, convention) for c in d.get('children', [])],
            persistent=d.get('persistent', False), disabled=d.get('disabled', False),
            links=[Link(l['target'], FormKey.parse(l['keyword']) if l.get('keyword') else None)
                   for l in d.get('links', [])],
            enable_parent=d.get('enable_parent'), properties=dict(d.get('properties', {})),
            tags=tuple(d.get('tags', ())))


@dataclass
class Scene:
    name: str
    nodes: list = field(default_factory=list)          # root nodes
    origin: Transform = field(default_factory=Transform)

    def add(self, node: SceneNode) -> SceneNode:
        self.nodes.append(node)
        return node

    def walk(self) -> Iterator[tuple[SceneNode, Transform]]:
        """(node, transform in the target cell's space) for every node, depth first."""
        for node in self.nodes:
            yield from node.walk(self.origin)

    def placed(self) -> list[tuple[SceneNode, Transform]]:
        return [(n, t) for n, t in self.walk() if n.base is not None]

    def find(self, node_id: str) -> SceneNode | None:
        return next((n for n, _ in self.walk() if n.id == node_id), None)

    def check(self) -> list[str]:
        """Structural problems: duplicate ids, links/enable parents to unknown nodes."""
        ids, problems = {}, []
        for n, _ in self.walk():
            if n.id in ids:
                problems.append(f'duplicate node id {n.id!r}')
            ids[n.id] = n
        for n in ids.values():
            for l in n.links:
                if l.target not in ids and ':' not in l.target:
                    problems.append(f'{n.id}: link to unknown node {l.target!r}')
            if n.enable_parent and n.enable_parent not in ids and ':' not in n.enable_parent:
                problems.append(f'{n.id}: enable parent {n.enable_parent!r} unknown')
            if (n.links or n.enable_parent) and n.base is None:
                problems.append(f'{n.id}: group nodes cannot carry links')
        return problems

    # -- blueprints --------------------------------------------------------------------------------
    def instantiate(self, blueprint: 'Blueprint', prefix: str, at: Transform | None = None,
                    parent: SceneNode | None = None) -> SceneNode:
        """Add a copy of a blueprint as a group node `prefix` (child ids become 'prefix/<id>')."""
        group = SceneNode(prefix, None, at or Transform(convention=self.origin.convention))
        id_map = {}

        def copy(node):
            new = SceneNode(f'{prefix}/{node.id}', node.base, node.transform, [], node.persistent,
                            node.disabled, [], node.enable_parent, dict(node.properties), node.tags)
            id_map[node.id] = new.id
            new.children = [copy(c) for c in node.children]
            new.links = [Link(l.target, l.keyword) for l in node.links]
            return new
        group.children = [copy(n) for n in blueprint.nodes]
        for n, _ in group.walk():
            for l in n.links:
                l.target = id_map.get(l.target, l.target)
            if n.enable_parent:
                n.enable_parent = id_map.get(n.enable_parent, n.enable_parent)
        (parent.children if parent else self.nodes).append(group)
        return group

    def to_dict(self) -> dict:
        return {'name': self.name, 'origin': self.origin.to_dict(), 'nodes': [n.to_dict() for n in self.nodes]}

    @classmethod
    def from_dict(cls, d: dict, convention=DEFAULT_CONVENTION) -> 'Scene':
        return cls(d['name'], [SceneNode.from_dict(n, convention) for n in d.get('nodes', [])],
                   Transform.from_dict(d.get('origin', {}), convention))


@dataclass
class Blueprint:
    """A reusable set of nodes in local space (origin = blueprint anchor)."""
    name: str
    nodes: list = field(default_factory=list)
    description: str = ''
    source: str = ''                       # provenance (e.g. 'captured from 00ABCD:Mod.esm cell')

    def to_dict(self) -> dict:
        return {'format': 'pyfield-blueprint', 'version': BLUEPRINT_VERSION, 'units': 'metres, degrees',
                'name': self.name, 'description': self.description, 'source': self.source,
                'nodes': [n.to_dict() for n in self.nodes]}

    @classmethod
    def from_dict(cls, d: dict, convention=DEFAULT_CONVENTION) -> 'Blueprint':
        if d.get('format') != 'pyfield-blueprint':
            raise PyFieldError('not a PyField blueprint')
        if d.get('version', 0) > BLUEPRINT_VERSION:
            raise PyFieldError(f'blueprint version {d["version"]} is newer than supported ({BLUEPRINT_VERSION})')
        return cls(d['name'], [SceneNode.from_dict(n, convention) for n in d.get('nodes', [])],
                   d.get('description', ''), d.get('source', ''))

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=1), encoding='utf-8')

    @classmethod
    def load(cls, path, convention=DEFAULT_CONVENTION) -> 'Blueprint':
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')), convention)
