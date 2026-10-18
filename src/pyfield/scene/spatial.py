"""Spatial queries over a scene's placed objects: world bounds, radius/box queries, overlaps.

Bounds come from each base object's OBND (min/max in the object's local space), transformed
to world space and enclosed in an axis-aligned box. Objects without OBND are points.
"""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math

from .transform import Transform


@dataclass(frozen=True)
class Box:
    min: tuple
    max: tuple

    def intersects(self, other: 'Box', margin: float = 0.0) -> bool:
        return all(self.min[i] - margin < other.max[i] and other.min[i] - margin < self.max[i] for i in range(3))

    def overlap_volume(self, other: 'Box') -> float:
        dims = [min(self.max[i], other.max[i]) - max(self.min[i], other.min[i]) for i in range(3)]
        return math.prod(max(0.0, d) for d in dims)

    def contains(self, point) -> bool:
        return all(self.min[i] <= point[i] <= self.max[i] for i in range(3))

    @property
    def center(self) -> tuple:
        return tuple((a + b) / 2 for a, b in zip(self.min, self.max))


def local_bounds(view) -> Box | None:
    """OBND of a base object view (typed `bounds` or raw 6 floats)."""
    b = getattr(view, 'bounds', None)
    if b is not None:
        return Box((b.min.x, b.min.y, b.min.z), (b.max.x, b.max.y, b.max.z))
    raw = view.node.get('OBND')
    if raw is not None and len(raw.data) == 24:
        import struct
        v = struct.unpack('<6f', raw.data)
        return Box(v[:3], v[3:])
    return None


def world_box(local: Box | None, t: Transform) -> Box:
    if local is None:
        return Box(t.position, t.position)
    corners = [t.apply((x, y, z)) for x in (local.min[0], local.max[0]) for y in (local.min[1], local.max[1])
               for z in (local.min[2], local.max[2])]
    return Box(tuple(min(c[i] for c in corners) for i in range(3)), tuple(max(c[i] for c in corners) for i in range(3)))


class SpatialIndex:
    def __init__(self, scene, load_order):
        self.items = []                      # (node id, base view signature, world Transform, Box)
        for node, world in scene.placed():
            base = load_order.resolve(node.base)
            self.items.append((node.id, base.signature if base else '?', world,
                               world_box(local_bounds(base) if base else None, world)))

    def within(self, point, radius: float) -> list[str]:
        return [i for i, _, t, _ in self.items if math.dist(t.position, point) <= radius]

    def in_box(self, box: Box) -> list[str]:
        return [i for i, _, _, b in self.items if b.intersects(box)]

    def nearest(self, point, k: int = 1) -> list[tuple[str, float]]:
        return sorted(((i, math.dist(t.position, point)) for i, _, t, _ in self.items), key=lambda x: x[1])[:k]

    def overlaps(self, min_volume: float = 0.001, ignore=()) -> list[tuple[str, str, float]]:
        """Pairs whose world boxes overlap by more than min_volume (m³); a coarse collision report."""
        out = []
        items = [x for x in self.items if x[0] not in ignore]
        for (a, _, _, ba), (b, _, _, bb) in itertools.combinations(items, 2):
            v = ba.overlap_volume(bb)
            if v > min_volume:
                out.append((a, b, round(v, 4)))
        return out

    def bounds(self) -> Box:
        boxes = [b for *_, b in self.items]
        return Box(tuple(min(b.min[i] for b in boxes) for i in range(3)),
                   tuple(max(b.max[i] for b in boxes) for i in range(3)))
