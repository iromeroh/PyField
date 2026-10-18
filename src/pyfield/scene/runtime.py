"""Runtime captures: ships, outposts and areas exported from a running game (Phase 7).

The SFSE plugin `sfse/PyFieldCapture` writes `pyfield-capture` JSON files (Documents/My Games/
Starfield/PyField/captures/<name>.json) from console commands such as
`cgf "PyFieldCapture.Outpost" "Selene"`. Each reference carries its runtime FormID, base form,
position/rotation (radians)/scale and the discovery sections that found it; the file also carries
the game's load order, so runtime FormIDs resolve to FormKeys here, offline.

    cap = RuntimeCapture.load('Selene.json')
    bp = cap.to_blueprint(sections={'workshop_items'})
    bp.save('selene.blueprint.json')

Forms created in the save (FormID 0xFF......) cannot be referenced from a plugin: references to
them are skipped and listed in `Blueprint` conversion results, to be rebuilt (transplant rules).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core.formids import FormKey
from ..errors import PyFieldError
from .graph import Blueprint, SceneNode
from .transform import Transform

CAPTURE_VERSION = 1
STARFIELD_CONVENTION = ('xyz', -1)
PLAYER_REF = 0x14


@dataclass
class RuntimeForm:
    form_id: int
    type: int = 0
    type_name: str = ''
    editor_id: str = ''

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        return cls(int(d['form_id'], 16), d.get('type', 0), d.get('type_name', ''), d.get('editor_id', ''))


@dataclass
class RuntimeRef:
    form_id: int
    base: RuntimeForm | None
    position: tuple
    rotation: tuple
    scale: float = 1.0
    created: bool = False
    disabled: bool = False
    deleted: bool = False
    cell: RuntimeForm | None = None
    sections: tuple = ()
    extra_types: tuple = ()
    type: int = 0
    extras: tuple = ()                 # raw extra-data entries: [type, payload hex, (pack-in id), (forms)]
    resolved_links: tuple = ()         # (keyword runtime id or None, target runtime id), resolved in game

    @classmethod
    def from_dict(cls, d):
        extras = tuple(tuple(e) for e in d.get('extras', ()) if isinstance(e, list))
        resolved = tuple((int(k, 16) or None, int(t, 16)) for k, t in d.get('links', ()))
        types = tuple(d.get('extra_types', ())) or tuple(e[0] for e in extras)
        return cls(int(d['form_id'], 16), RuntimeForm.from_dict(d.get('base')), tuple(d['pos']), tuple(d['rot']),
                   float(d.get('scale', 1.0)), bool(d.get('created')), bool(d.get('disabled')),
                   bool(d.get('deleted')), RuntimeForm.from_dict(d.get('cell')), tuple(d.get('sections', ())),
                   types, d.get('type', 0), extras, resolved)

    def _forms(self, extra_type: int):
        for e in self.extras:
            if e and e[0] == extra_type:
                yield next((x for x in e[2:] if isinstance(x, dict)), {})

    @property
    def linked_refs(self) -> list:
        """[(keyword runtime FormID or None, target runtime FormID)] from ExtraLinkedRef (0x4C): an array of
        {keyword, reference} pairs in captures since 2026-10-18."""
        if self.resolved_links:
            return list(self.resolved_links)
        out = []
        for forms in self._forms(0x4C):
            arr = (forms.get('small_array') or {}).get('words') or forms.get('array') or []
            for i in range(0, len(arr) - 1, 2):
                if arr[i + 1]:
                    out.append((int(arr[i], 16) if arr[i] else None, int(arr[i + 1], 16)))
        return out

    @property
    def source_packin(self) -> int | None:
        """Runtime FormID of the pack-in that spawned this reference (ExtraSourcePackIn, 0xD4)."""
        for e in self.extras:
            if e and e[0] == 0xD4:
                return next((int(x, 16) for x in e[2:] if isinstance(x, str)), None)
        return None


@dataclass
class ConversionReport:
    placed: int = 0
    skipped: list = field(default_factory=list)      # (runtime FormID, reason)


@dataclass
class RuntimeCapture:
    name: str
    kind: str
    anchor: RuntimeRef | None
    refs: list
    full: list = field(default_factory=list)          # load order, runtime index = position
    light: list = field(default_factory=list)
    medium: list = field(default_factory=list)
    captured_utc: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'RuntimeCapture':
        if d.get('format') != 'pyfield-capture':
            raise PyFieldError('not a PyField runtime capture')
        if d.get('format_version', 0) > CAPTURE_VERSION:
            raise PyFieldError(f'capture version {d["format_version"]} is newer than supported ({CAPTURE_VERSION})')
        lo = d.get('load_order', {})
        anchor = d.get('anchor')
        return cls(d['name'], d['kind'], RuntimeRef.from_dict(anchor) if anchor else None,
                   [RuntimeRef.from_dict(r) for r in d.get('refs', [])],
                   lo.get('full', []), lo.get('small', []), lo.get('medium', []), d.get('captured_utc', ''))

    @classmethod
    def load(cls, path) -> 'RuntimeCapture':
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))

    # -- FormIDs ----------------------------------------------------------------------------------
    def form_key(self, runtime_id: int) -> FormKey | None:
        """FormKey for a runtime FormID; None for save-created forms or unknown plugin slots."""
        hi = runtime_id >> 24
        if hi == 0xFF:
            return None
        if hi == 0xFE:
            files, index, local = self.light, (runtime_id >> 12) & 0xFFF, runtime_id & 0xFFF
        elif hi == 0xFD:
            files, index, local = self.medium, (runtime_id >> 16) & 0xFF, runtime_id & 0xFFFF
        else:
            files, index, local = self.full, hi, runtime_id & 0xFFFFFF
        if index >= len(files) or not files[index]:
            return None
        return FormKey(files[index], local)

    def plugin_files(self, order=None) -> list:
        """Every captured plugin (full, medium and light slots) in load order.

        `order` is a plugin list in load order (e.g. Plugins.txt entries); plugins it does not name (the base
        game masters) come first in their runtime slot order, the rest follow `order`. Without it: full,
        then medium, then light slots.
        """
        names = list(dict.fromkeys(n for n in self.full + self.medium + self.light if n))
        if not order:
            return names
        rank = {n.lower(): i for i, n in enumerate(order)}
        slot = {n: i for i, n in enumerate(names)}
        return sorted(names, key=lambda n: (n.lower() in rank, rank.get(n.lower(), slot[n])))

    # -- queries ----------------------------------------------------------------------------------
    def select(self, sections=None, created_only=False, include_actors=False) -> list:
        out = []
        for r in self.refs:
            if r.form_id == PLAYER_REF or r.deleted:
                continue
            if r.cell is None and self.anchor is not None and self.anchor.cell is not None:
                continue                               # not placed in the world (limbo / storage)
            if sections is not None and not set(r.sections) & set(sections):
                continue
            if created_only and not r.created:
                continue
            if not include_actors and r.base is not None and r.base.type_name == 'NPC_':
                continue
            out.append(r)
        return out

    def summary(self) -> dict:
        by_section, by_type, created_bases = {}, {}, 0
        for r in self.refs:
            for s in r.sections:
                by_section[s] = by_section.get(s, 0) + 1
            t = r.base.type_name if r.base else '?'
            by_type[t] = by_type.get(t, 0) + 1
            created_bases += bool(r.base and r.base.form_id >> 24 == 0xFF)
        return {'name': self.name, 'kind': self.kind, 'refs': len(self.refs), 'sections': by_section,
                'base_types': dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
                'save_created_bases': created_bases}

    # -- conversion -------------------------------------------------------------------------------
    def to_blueprint(self, sections=None, created_only=False, include_actors=False,
                     convention=STARFIELD_CONVENTION, report: ConversionReport | None = None) -> Blueprint:
        """Blueprint of the selected references, transforms relative to the capture anchor."""
        report = report if report is not None else ConversionReport()
        anchor = Transform(convention=convention)
        if self.anchor is not None:
            a = self.anchor
            anchor = Transform(a.position, a.rotation, 1.0, convention)
        nodes = []
        for r in self.select(sections, created_only, include_actors):
            base = self.form_key(r.base.form_id) if r.base else None
            if base is None:
                why = 'base created in save' if r.base and r.base.form_id >> 24 == 0xFF else 'base not resolvable'
                report.skipped.append((r.form_id, why))
                continue
            world = Transform(r.position, r.rotation, r.scale or 1.0, convention)
            label = r.base.editor_id or f'{base.local_id:06X}'
            nodes.append(SceneNode(f'{label}_{r.form_id:08X}', base, world.relative_to(anchor),
                                   disabled=r.disabled, tags=(f'runtime:{r.form_id:08X}', *r.sections)))
        report.placed = len(nodes)
        return Blueprint(self.name, nodes,
                         description=f'{len(nodes)} references from a runtime {self.kind} capture',
                         source=f'PyFieldCapture {self.captured_utc}'.strip())
