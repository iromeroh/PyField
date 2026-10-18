"""Group layout contract: what group kinds and labels mean, supplied by the game adapter."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GroupLayout:
    top_kind: int                                   # top-level groups: label = record signature
    kind_names: dict = field(default_factory=dict)  # kind -> readable name
    owner_kinds: frozenset = frozenset()            # label = FormID of the record owning the contents;
                                                    # that record precedes the group among its siblings
    formid_label_kinds: frozenset = frozenset()     # any kind whose label is a FormID (incl. owner kinds)
    grid_kinds: frozenset = frozenset()             # label = two int16 grid coordinates (y, x)
    nested_top_groups: frozenset = frozenset()      # top-level groups whose records sit in child groups
    world_kind: int | None = None                   # children of a worldspace (holds its persistent cell)

    def name(self, kind: int) -> str:
        return self.kind_names.get(kind, f'kind{kind}')
