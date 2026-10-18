"""Generic heightfield: a regular grid of heights in world space, with analysis and brushes.

Sample (i, j) sits at world (origin_x + i·spacing, origin_y + j·spacing); rows (j) run toward
+y. Heights are float metres held in a flat `array('f')` (row-major, x fastest). Brushes
return the set of modified sample indices so encoders can update only what changed.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import math
from typing import Callable, Iterable


@dataclass
class Heightfield:
    width: int                       # samples along x
    height: int                      # samples along y
    spacing: float                   # metres between samples
    origin: tuple                    # world (x, y) of sample (0, 0)
    values: array = field(default=None)

    def __post_init__(self):
        if self.values is None:
            self.values = array('f', bytes(4 * self.width * self.height))
        if len(self.values) != self.width * self.height:
            raise ValueError('values do not match width × height')

    # -- coordinates ------------------------------------------------------------------------
    def to_sample(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.origin[0]) / self.spacing, (y - self.origin[1]) / self.spacing

    def to_world(self, i: float, j: float) -> tuple[float, float]:
        return self.origin[0] + i * self.spacing, self.origin[1] + j * self.spacing

    @property
    def extent(self) -> tuple[tuple[float, float], tuple[float, float]]:
        return self.to_world(0, 0), self.to_world(self.width - 1, self.height - 1)

    def contains(self, x: float, y: float) -> bool:
        i, j = self.to_sample(x, y)
        return 0 <= i <= self.width - 1 and 0 <= j <= self.height - 1

    # -- access -------------------------------------------------------------------------------
    def get(self, i: int, j: int) -> float:
        i = min(max(i, 0), self.width - 1)
        j = min(max(j, 0), self.height - 1)
        return self.values[j * self.width + i]

    def set(self, i: int, j: int, h: float):
        self.values[j * self.width + i] = h

    def at(self, x: float, y: float) -> float:
        """Bilinear height at a world position (clamped to the grid)."""
        gi, gj = self.to_sample(x, y)
        i0, j0 = math.floor(gi), math.floor(gj)
        fx, fy = gi - i0, gj - j0
        h00, h10 = self.get(i0, j0), self.get(i0 + 1, j0)
        h01, h11 = self.get(i0, j0 + 1), self.get(i0 + 1, j0 + 1)
        return (h00 * (1 - fx) + h10 * fx) * (1 - fy) + (h01 * (1 - fx) + h11 * fx) * fy

    def normal(self, x: float, y: float) -> tuple[float, float, float]:
        d = self.spacing
        dx = (self.at(x + d, y) - self.at(x - d, y)) / (2 * d)
        dy = (self.at(x, y + d) - self.at(x, y - d)) / (2 * d)
        n = math.sqrt(dx * dx + dy * dy + 1)
        return -dx / n, -dy / n, 1 / n

    def slope_deg(self, x: float, y: float) -> float:
        return math.degrees(math.acos(max(-1.0, min(1.0, self.normal(x, y)[2]))))

    # -- analysis -------------------------------------------------------------------------------
    def stats(self, region=None) -> dict:
        idx = self._region_indices(region)
        vals = [self.values[k] for k in idx]
        return {'min': min(vals), 'max': max(vals), 'mean': sum(vals) / len(vals), 'samples': len(vals)}

    def profile(self, a, b, steps: int = 100) -> list[tuple[float, float, float]]:
        """(x, y, height) along a straight line from a to b."""
        out = []
        for k in range(steps + 1):
            t = k / steps
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            out.append((x, y, self.at(x, y)))
        return out

    def _region_indices(self, region):
        if region is None:
            return range(len(self.values))
        (x0, y0), (x1, y1) = region
        i0, j0 = (max(0, int(math.floor(v))) for v in self.to_sample(min(x0, x1), min(y0, y1)))
        i1, j1 = self.to_sample(max(x0, x1), max(y0, y1))
        i1, j1 = min(self.width - 1, int(math.ceil(i1))), min(self.height - 1, int(math.ceil(j1)))
        return [j * self.width + i for j in range(j0, j1 + 1) for i in range(i0, i1 + 1)]

    # -- brushes ------------------------------------------------------------------------------
    def _brush(self, center, radius: float, fn: Callable[[float, float, float], float]) -> set[int]:
        """Apply fn(old_height, weight, distance) to samples within radius; weight = smooth falloff."""
        cx, cy = center
        gi, gj = self.to_sample(cx, cy)
        r = radius / self.spacing
        changed = set()
        for j in range(max(0, int(gj - r) - 1), min(self.height, int(gj + r) + 2)):
            for i in range(max(0, int(gi - r) - 1), min(self.width, int(gi + r) + 2)):
                x, y = self.to_world(i, j)
                d = math.hypot(x - cx, y - cy)
                if d > radius:
                    continue
                t = d / radius
                weight = 1 - t * t * (3 - 2 * t)          # smoothstep falloff: 1 at centre, 0 at rim
                k = j * self.width + i
                new = fn(self.values[k], weight, d)
                if new != self.values[k]:
                    self.values[k] = new
                    changed.add(k)
        return changed

    def raise_(self, center, radius: float, amount: float) -> set[int]:
        """Raise (or lower, with negative amount) with a smooth falloff."""
        return self._brush(center, radius, lambda h, w, d: h + amount * w)

    def flatten(self, center, radius: float, target: float, inner_ratio: float = 0.6) -> set[int]:
        """Flat pad at `target` inside inner_ratio·radius, blended to the original terrain at the rim."""
        def fn(h, w, d):
            t = d / radius
            if t <= inner_ratio:
                return target
            b = (t - inner_ratio) / (1 - inner_ratio)
            b = b * b * (3 - 2 * b)
            return target * (1 - b) + h * b
        return self._brush(center, radius, fn)

    def smooth(self, center, radius: float, strength: float = 0.5) -> set[int]:
        before = array('f', self.values)
        w = self.width

        def avg(k):
            j, i = divmod(k, w)
            vals = [before[(min(max(j + dj, 0), self.height - 1)) * w + min(max(i + di, 0), w - 1)]
                    for dj in (-1, 0, 1) for di in (-1, 0, 1)]
            return sum(vals) / 9

        cx, cy = center
        gi, gj = self.to_sample(cx, cy)
        r = radius / self.spacing
        changed = set()
        for j in range(max(0, int(gj - r)), min(self.height, int(gj + r) + 1)):
            for i in range(max(0, int(gi - r)), min(w, int(gi + r) + 1)):
                x, y = self.to_world(i, j)
                d = math.hypot(x - cx, y - cy)
                if d > radius:
                    continue
                k = j * w + i
                t = d / radius
                weight = strength * (1 - t * t * (3 - 2 * t))
                new = before[k] * (1 - weight) + avg(k) * weight
                if new != before[k]:
                    self.values[k] = new
                    changed.add(k)
        return changed

    def blend_from(self, other: 'Heightfield', mask: Callable[[float, float], float]) -> set[int]:
        """Mix in another heightfield: h = h·(1 - m) + other(x, y)·m, with m = mask(x, y) in [0, 1]."""
        changed = set()
        for j in range(self.height):
            for i in range(self.width):
                x, y = self.to_world(i, j)
                m = mask(x, y)
                if m <= 0 or not other.contains(x, y):
                    continue
                k = j * self.width + i
                new = self.values[k] * (1 - m) + other.at(x, y) * m
                if new != self.values[k]:
                    self.values[k] = new
                    changed.add(k)
        return changed

    def conform(self, points: Iterable[tuple[float, float, float]], radius: float) -> set[int]:
        """Flatten under each (x, y, z): terrain-to-scene alignment for placed foundations."""
        changed = set()
        for x, y, z in points:
            changed |= self.flatten((x, y), radius, z)
        return changed
