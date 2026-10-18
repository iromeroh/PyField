"""Terrain fitted to placed objects: a smooth surface under a captured scene, nothing floating or buried deep.

Captured outposts/POIs carry objects but not the ground they sat on (generated terrain differs per playthrough).
The fit rebuilds that ground from the objects themselves:

1. samples (`ground_samples`):
   - natural objects (rocks, flora: the landing area's own dressing) are height targets at their origin;
   - structures are height *intervals* at their footprint corners and centre: an ordinary structure needs
     ground between 0.1 m below and 1 m above its bottom; a support (bounds reaching more than 1 m below the
     origin: foundations, pillar segments, landing-pad legs) needs ground between its bottom and its top;
   - objects resting on a structure (furniture in a hab, upper pillar segments) give no sample;
2. base surface: least-squares trend plane + smooth residual of the targets by normalized convolution on two
   scales (fine where targets are dense, coarse to bridge gaps), relaxing to the plane away from data and
   towards the borders; natural targets that disagree with their neighbours are dropped as outliers and
   reported, never forced with a spike;
3. slope limit (relaxation caps the steepest gradients);
4. projection: smooth local corrections push the surface into every violated interval; satisfied intervals do
   not pull, so structures do not wrinkle the ground.

    samples = ground_samples(items)     # items: (Transform, local Box | None, NATURAL | STRUCTURE, ref)
    fit = fit_terrain(samples, (x0, y0, x1, y1))
    fit.surface.at(x, y); fit.report()
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import math

from .heightfield import Heightfield

NATURAL, STRUCTURE, SUPPORT, ELEVATED = 'natural', 'structure', 'support', 'elevated'


@dataclass
class GroundSample:
    x: float
    y: float
    z: float                           # target height (natural) or contact height (structure bottom)
    weight: float = 1.0                # weight as a target in the base surface
    kind: str = NATURAL
    ref: object = None                 # caller's id for reporting
    lo: float | None = None            # acceptable ground interval (defaults: z - 0.4 .. z + 0.8)
    hi: float | None = None
    trusted: bool = False              # support known to reach the ground (foundation/pillar column): never an outlier

    def __post_init__(self):
        if self.lo is None:
            self.lo = self.z - 0.4
        if self.hi is None:
            self.hi = self.z + 0.8


@dataclass
class FitResult:
    surface: Heightfield
    samples: list
    plane: tuple                       # (a, b, c): z = a + b x + c y
    gaps: list = field(default_factory=list)     # per sample: surface - interval (+ buries, - leaves floating, 0 ok)
    outliers: list = field(default_factory=list)  # indices into samples (natural targets left out)
    slope_limited: int = 0
    projection_passes: int = 0
    attached: list = field(default_factory=list)  # structure samples floating > max_raise: treated as mounted
    embedded: list = field(default_factory=list)  # structure samples set > max_lower into the ground: kept so

    def report(self, limit: int = 10) -> dict:
        out = set(self.outliers)
        floating = [i for i, g in enumerate(self.gaps) if g < -1e-3 and i not in out]
        sinking = [i for i, g in enumerate(self.gaps) if g > 1e-3 and i not in out]
        by_kind = {}
        for i, s in enumerate(self.samples):
            k = by_kind.setdefault(s.kind, {'samples': 0, 'ok': 0, 'outliers': 0})
            k['samples'] += 1
            k['ok'] += abs(self.gaps[i]) <= 1e-3
            k['outliers'] += i in out

        def item(i):
            s = self.samples[i]
            return {'ref': s.ref, 'kind': s.kind, 'at': [round(s.x, 1), round(s.y, 1)], 'violation_m': round(self.gaps[i], 2)}
        rest = sorted(floating + sinking, key=lambda i: -abs(self.gaps[i]))
        mags = sorted(abs(self.gaps[i]) for i in range(len(self.gaps)) if i not in out)
        refs = {}
        for i in sorted(out, key=lambda i: -abs(self.gaps[i])):
            refs.setdefault(self.samples[i].ref, item(i))
        return {
            'samples': len(self.samples), 'within_interval': sum(abs(g) <= 1e-3 for g in self.gaps),
            'by_kind': by_kind, 'floating': len(floating), 'buried': len(sinking),
            'outlier_samples': len(out), 'outlier_objects': len(refs),
            'attached_objects': len({self.samples[i].ref for i in self.attached}),
            'embedded_objects': len({self.samples[i].ref for i in self.embedded}),
            'p95_violation_m': round(mags[int(len(mags) * 0.95)], 3) if mags else 0.0,
            'max_violation_m': round(mags[-1], 3) if mags else 0.0,
            'slope_limited_samples': self.slope_limited, 'projection_passes': self.projection_passes,
            'worst': [item(i) for i in rest[:limit]],
            'outliers': list(refs.values())[:limit],
        }


# -- samples ----------------------------------------------------------------------------------------

def ground_samples(items, min_footprint: float = 1.0, support_depth: float = 1.0,
                   float_tol: float = 0.1, sink_tol: float = 0.3, bin_size: float = 2.0, deck_clear: float = 0.6,
                   natural_band: tuple = (0.4, 0.8), carriers=()) -> list:
    """Ground samples from placed objects: items are (transform, local_box | None, kind, ref).

    kind NATURAL gives a target at the origin; STRUCTURE gives intervals at the footprint centre and corners,
    turning into SUPPORT when the bounds reach more than `support_depth` below the origin. An object whose
    centre lies inside a structure's footprint (>= `min_footprint` m^2) with its bottom above that structure's
    bottom rests on it and gives no sample. Only the lowest structure contact in each `bin_size` bin needs
    ground under it; higher ones (walkways, wall lights, frames) are ELEVATED: they must just not be buried.
    Supports constrain but are not height targets (their bottoms are below the ground by design); the ground
    stays `deck_clear` m below a support column's top and at most `sink_tol` (more for wide structures) above a
    structure's bottom, so the biome's grass does not grow through floors and pads.
    """
    objects = []                    # (ref, kind, centre xy, bottom, top, world xy box | None, points)
    trusted = set()                 # items given as SUPPORT by the caller (named columns)
    for t, box, kind, ref in items:
        x, y, z = t.position
        if box is None:
            objects.append((ref, kind, (x, y), z, z, None, [(x, y)]))
            continue
        pts = [t.apply((bx, by, bz)) for bx in (box.min[0], box.max[0]) for by in (box.min[1], box.max[1])
               for bz in (box.min[2], box.max[2])]
        bottom, top = min(p[2] for p in pts), max(p[2] for p in pts)
        xy = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        if kind == NATURAL:
            objects.append((ref, kind, (x, y), z, z, xy, [(x, y)]))
            continue
        corners = [t.apply((bx, by, box.min[2])) for bx in (box.min[0], box.max[0]) for by in (box.min[1], box.max[1])]
        cx, cy = sum(c[0] for c in corners) / 4, sum(c[1] for c in corners) / 4
        if kind != SUPPORT:
            kind = SUPPORT if bottom < z - support_depth else STRUCTURE
        else:
            trusted.add(len(objects))
        objects.append((ref, kind, (cx, cy), bottom, top, xy, [(cx, cy)] + [(c[0], c[1]) for c in corners]))
    first_carrier = len(objects)    # carriers: (transform, local box) that hold others but give no samples
    for t, box in carriers:
        pts = [t.apply((bx, by, bz)) for bx in (box.min[0], box.max[0]) for by in (box.min[1], box.max[1])
               for bz in (box.min[2], box.max[2])]
        xy = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        objects.append((None, STRUCTURE, ((xy[0] + xy[2]) / 2, (xy[1] + xy[3]) / 2), min(p[2] for p in pts),
                        max(p[2] for p in pts), xy, []))
    bucket = {}                     # structures able to carry others, by 8 m cell
    for k, (_, kind, _, _, _, xy, _) in enumerate(objects):
        if kind == NATURAL or xy is None or (xy[2] - xy[0]) * (xy[3] - xy[1]) < min_footprint:
            continue
        for bx in range(math.floor(xy[0] / 8), math.floor(xy[2] / 8) + 1):
            for by in range(math.floor(xy[1] / 8), math.floor(xy[3] / 8) + 1):
                bucket.setdefault((bx, by), []).append(k)

    def resting(k):
        _, kind, (cx, cy), bottom, _, _, _ = objects[k]
        if kind == NATURAL:
            return False
        for o in bucket.get((math.floor(cx / 8), math.floor(cy / 8)), ()):
            if o != k:
                xy, ob = objects[o][5], objects[o][3]
                if xy[0] <= cx <= xy[2] and xy[1] <= cy <= xy[3] and bottom > ob + 0.05:
                    return True
        return False
    # support columns (stacked foundation/pillar segments, centres within 1.5 m): the ground must lie between
    # the column's lowest bottom and its highest top; lower segments may be buried, the deck may not
    column_top, column_members = {}, {}
    by_cell = {}
    for k, (_, kind, (cx, cy), _, _, _, _) in enumerate(objects):
        if kind == SUPPORT:
            by_cell.setdefault((math.floor(cx / 1.5), math.floor(cy / 1.5)), []).append(k)
    for k, (_, kind, (cx, cy), _, top, _, _) in enumerate(objects):
        if kind != SUPPORT:
            continue
        ci, cj = math.floor(cx / 1.5), math.floor(cy / 1.5)
        members = [o for di in (-1, 0, 1) for dj in (-1, 0, 1) for o in by_cell.get((ci + di, cj + dj), ())
                   if math.hypot(objects[o][2][0] - cx, objects[o][2][1] - cy) <= 1.5]
        column_members[k] = members
        column_top[k] = max([top] + [objects[o][4] for o in members])
    lowest = {}                     # lowest structure contact per bin: only those may need ground under them
    for k, (_, kind, _, bottom, _, _, points) in enumerate(objects):
        if k < first_carrier and kind in (STRUCTURE, SUPPORT) and not resting(k):
            for x, y in points:
                key = (math.floor(x / bin_size), math.floor(y / bin_size))
                lowest[key] = min(lowest.get(key, math.inf), bottom)
    out = []
    for k, (ref, kind, _, bottom, top, xy, points) in enumerate(objects):
        if k >= first_carrier or resting(k):
            continue
        for x, y in points:
            grounded = bottom <= lowest.get((math.floor(x / bin_size), math.floor(y / bin_size)), math.inf) + 0.05
            if kind == NATURAL:
                out.append(GroundSample(x, y, bottom, 1.0, kind, ref, lo=bottom - natural_band[0],
                                        hi=bottom + natural_band[1]))
            elif kind == SUPPORT and grounded:
                deck = max(bottom + 0.2, column_top[k] - deck_clear)       # grass must not grow through the deck
                out.append(GroundSample(x, y, bottom, 0.0, kind, ref, lo=bottom - float_tol, hi=deck,
                                        trusted=k in trusted or any(o in trusted for o in column_members[k])))
            elif kind == STRUCTURE and grounded:          # wide structures may sit into a slope
                bury = max(sink_tol, 0.04 * math.hypot(xy[2] - xy[0], xy[3] - xy[1])) if xy else sink_tol
                out.append(GroundSample(x, y, bottom, 0.2, kind, ref, lo=bottom - float_tol, hi=bottom + bury))
            else:                   # something lower stands here: this object only must not be buried
                out.append(GroundSample(x, y, bottom, 0.0, ELEVATED, ref, lo=-math.inf, hi=bottom + sink_tol))
    return out


# -- grid helpers -------------------------------------------------------------------------------------

def _gauss_kernel(sigma_cells: float) -> list:
    r = max(1, int(math.ceil(3 * sigma_cells)))
    return [math.exp(-0.5 * (i / sigma_cells) ** 2) for i in range(-r, r + 1)]


def _blur(values, w: int, h: int, sigma_cells: float):
    """Separable Gaussian blur, unnormalized kernel (peak 1), zero outside the grid."""
    k = _gauss_kernel(sigma_cells)
    r = len(k) // 2
    tmp = array('d', bytes(8 * w * h))
    for j in range(h):
        row = j * w
        for i in range(w):
            v = values[row + i]
            if v == 0.0:
                continue
            lo, hi = max(0, i - r), min(w - 1, i + r)
            for ii in range(lo, hi + 1):
                tmp[row + ii] += v * k[ii - i + r]
    out = array('d', bytes(8 * w * h))
    for j in range(h):
        row = j * w
        lo, hi = max(0, j - r), min(h - 1, j + r)
        for jj in range(lo, hi + 1):
            kk = k[jj - j + r]
            dst = jj * w
            for i in range(w):
                v = tmp[row + i]
                if v != 0.0:
                    out[dst + i] += v * kk
    return out


def _splat(points, w: int, h: int, x0: float, y0: float, step: float):
    """Bilinear splat of (weight, weight x value) for points (x, y, value, weight)."""
    num = array('d', bytes(8 * w * h))
    den = array('d', bytes(8 * w * h))
    for x, y, v, wt in points:
        if wt <= 0:
            continue
        gi, gj = (x - x0) / step, (y - y0) / step
        i0, j0 = math.floor(gi), math.floor(gj)
        fx, fy = gi - i0, gj - j0
        for di, dj, f in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            i, j = i0 + di, j0 + dj
            if 0 <= i < w and 0 <= j < h and f > 0:
                num[j * w + i] += wt * f * v
                den[j * w + i] += wt * f
    return num, den


def _plane(samples, weights):
    """Weighted least-squares plane z = a + b x + c y (falls back to the weighted mean)."""
    sw = sx = sy = sz = sxx = syy = sxy = sxz = syz = 0.0
    for s, w in zip(samples, weights):
        sw += w; sx += w * s.x; sy += w * s.y; sz += w * s.z
        sxx += w * s.x * s.x; syy += w * s.y * s.y; sxy += w * s.x * s.y; sxz += w * s.x * s.z; syz += w * s.y * s.z
    if sw == 0:
        return 0.0, 0.0, 0.0
    mx, my, mz = sx / sw, sy / sw, sz / sw
    cxx, cyy, cxy = sxx / sw - mx * mx, syy / sw - my * my, sxy / sw - mx * my
    cxz, cyz = sxz / sw - mx * mz, syz / sw - my * mz
    det = cxx * cyy - cxy * cxy
    if abs(det) < 1e-9 * max(1.0, cxx * cyy):
        return mz, 0.0, 0.0
    b = (cxz * cyy - cyz * cxy) / det
    c = (cyz * cxx - cxz * cxy) / det
    return mz - b * mx - c * my, b, c


def _violation(s, h):
    return h - s.hi if h > s.hi else (h - s.lo if h < s.lo else 0.0)


# -- fit -----------------------------------------------------------------------------------------------

def fit_terrain(samples, extent, spacing: float = 1.5625, fine_sigma: float = 3.0, coarse_sigma: float = 15.0,
                border: float = 25.0, max_slope_deg: float = 40.0, outlier_gap: float = 1.5,
                projection_sigma: float = 2.5, projection_passes: int = 30, neighbour_radius: float = 6.0,
                rounds: int = 4, max_raise: float = 1.5, max_lower: float = 1.5,
                natural_radius: float = 10.0) -> FitResult:
    """Smooth ground under the samples within extent = (x0, y0, x1, y1) metres (see module doc).

    `border` metres along the extent's edges fade to the trend plane (no step where the block meets the
    surrounding surface); `fine_sigma`/`coarse_sigma` are the two smoothing scales and `projection_sigma` the
    width of interval corrections (m).
    """
    x0, y0, x1, y1 = extent
    w = int(round((x1 - x0) / spacing)) + 1
    h = int(round((y1 - y0) / spacing)) + 1
    inside = [s for s in samples if x0 <= s.x <= x1 and y0 <= s.y <= y1]
    near = {}
    for s in inside:
        if s.kind == NATURAL:
            near.setdefault((math.floor(s.x / natural_radius), math.floor(s.y / natural_radius)), []).append(s)

    def rocks_near(s):
        ci, cj = math.floor(s.x / natural_radius), math.floor(s.y / natural_radius)
        return any(math.hypot(n.x - s.x, n.y - s.y) <= natural_radius
                   for di in (-1, 0, 1) for dj in (-1, 0, 1) for n in near.get((ci + di, cj + dj), ()))
    # rocks and plants are the ground's evidence; structures only shape it where none are around
    weights = [0.0 if s.kind != NATURAL and rocks_near(s) else s.weight for s in inside]
    a, b, c = plane = _plane(inside, weights)

    def trend(x, y):
        return a + b * x + c * y

    def fade(x, y):
        e = min(x - x0, x1 - x, y - y0, y1 - y) / border if border > 0 else 1.0
        return 1.0 if e >= 1 else max(0.0, e) ** 2 * (3 - 2 * max(0.0, e))

    fades = array('d', [fade(x0 + (k % w) * spacing, y0 + (k // w) * spacing) for k in range(w * h)])
    cstep = spacing * 4                         # the gap-bridging scale runs on a 4x coarser grid
    cw, ch = int(math.ceil((x1 - x0) / cstep)) + 1, int(math.ceil((y1 - y0) / cstep)) + 1
    surface = Heightfield(w, h, spacing, (x0, y0))
    outliers = set()
    for it in range(4):
        pts = [(s.x, s.y, s.z - trend(s.x, s.y), 0.0 if k in outliers else wt) for k, (s, wt) in enumerate(zip(inside, weights))]
        fn, fd = _splat(pts, w, h, x0, y0, spacing)
        fn, fd = _blur(fn, w, h, fine_sigma / spacing), _blur(fd, w, h, fine_sigma / spacing)
        cn, cd = _splat(pts, cw, ch, x0, y0, cstep)
        cn, cd = _blur(cn, cw, ch, coarse_sigma / cstep), _blur(cd, cw, ch, coarse_sigma / cstep)
        coarse = Heightfield(cw, ch, cstep, (x0, y0), array('f', [n / d if d > 1e-6 else 0.0 for n, d in zip(cn, cd)]))
        conf = Heightfield(cw, ch, cstep, (x0, y0), array('f', [d / (d + 0.05) for d in cd]))
        for j in range(h):
            for i in range(w):
                k = j * w + i
                x, y = x0 + i * spacing, y0 + j * spacing
                d = fd[k]
                alpha = d / (d + 0.5)                         # ~ one full-weight target within a sigma
                r = alpha * (fn[k] / d if d > 1e-9 else 0.0) + (1 - alpha) * coarse.at(x, y) * conf.at(x, y)
                surface.values[k] = trend(x, y) + r * fades[k]
        found = False
        for k, s in enumerate(inside):          # natural targets far from the local surface are outliers
            if s.kind == NATURAL and k not in outliers and abs(s.z - surface.at(s.x, s.y)) > outlier_gap:
                outliers.add(k)
                found = True
        if not found:
            break
    limited = _limit_slope(surface, math.tan(math.radians(max_slope_deg)))
    base = array('f', surface.values)             # natural ground: projection corrections are measured from it
    # projection: local smooth corrections into the violated intervals of structures and supports. A large
    # correction is only made where neighbouring objects need one too (a plateau the targets missed); a
    # lone object needing it is an outlier, reported instead of raising a spike.
    bounded = [k for k, s in enumerate(inside) if s.kind != NATURAL]
    need = {k: _violation(inside[k], surface.at(inside[k].x, inside[k].y)) for k in bounded}
    cells = {}
    for k in bounded:
        cells.setdefault((math.floor(inside[k].x / neighbour_radius), math.floor(inside[k].y / neighbour_radius)), []).append(k)
    attached, embedded = [], []
    for k in bounded:
        v = need[k]
        s = inside[k]
        if s.kind == STRUCTURE and not s.trusted and v < -max_raise:
            # floats more than max_raise above the ground: mounted on something (wall greebles, roof panels);
            # it only must not be buried, it does not raise the ground
            s.lo = -math.inf
            attached.append(k)
            continue
        if s.kind == STRUCTURE and not s.trusted and v > max_lower:
            # set into the ground deeper than max_lower in the original: embedded, the ground is not dug out
            s.hi = math.inf
            embedded.append(k)
            continue
        if abs(v) <= outlier_gap or s.trusted:              # columns are built down to the ground: trusted
            continue
        ci, cj = math.floor(s.x / neighbour_radius), math.floor(s.y / neighbour_radius)
        agree = {inside[o].ref for di in (-1, 0, 1) for dj in (-1, 0, 1) for o in cells.get((ci + di, cj + dj), ())
                 if inside[o].ref != s.ref and math.hypot(inside[o].x - s.x, inside[o].y - s.y) <= neighbour_radius
                 and need[o] * v > 0 and abs(need[o]) > outlier_gap / 2}
        if len(agree) < 2:
            outliers.add(k)
    bounded = [k for k in bounded if k not in outliers]
    bounded += [k for k, s in enumerate(inside) if s.kind == NATURAL and k not in outliers]   # rocks hold the ground
    passes = 0
    for _round in range(rounds):                    # project, then limit slopes; repeat so mounds keep their height
        for _ in range(projection_passes):
            viol = [(inside[k].x, inside[k].y, -_violation(inside[k], surface.at(inside[k].x, inside[k].y)), 1.0)
                    for k in bounded]
            viol = [p for p in viol if abs(p[2]) > 0.005]
            if not viol:
                break
            passes += 1
            num, den = _splat(viol, w, h, x0, y0, spacing)
            sig = projection_sigma / spacing
            num, den = _blur(num, w, h, sig), _blur(den, w, h, sig)
            for k in range(w * h):
                if den[k] > 1e-9:
                    surface.values[k] += num[k] / max(den[k], 1.0) * fades[k]
        changed = _limit_slope(surface, math.tan(math.radians(max_slope_deg)), anchor=base)
        limited += changed
        if not changed:
            break
    gaps = [_violation(s, surface.at(s.x, s.y)) for s in inside]
    result = FitResult(surface, inside, plane, gaps, sorted(outliers), limited, passes)
    result.attached = sorted(attached)
    result.embedded = sorted(embedded)
    return result


def _limit_slope(hf: Heightfield, max_grad: float, passes: int = 20, anchor=None) -> int:
    """Pull samples toward their neighbours where the gradient exceeds max_grad; returns samples changed.

    With `anchor` (the uncorrected surface), only the sample farther from its anchor moves (by the whole
    excess): corrections widen instead of raising rims around pits or lowering the natural ground.
    """
    w, h, step = hf.width, hf.height, hf.spacing
    limit = max_grad * step
    v = hf.values
    changed = set()
    for _ in range(passes):
        moved = False
        for j in range(h):
            for i in range(w):
                k = j * w + i
                for di, dj in ((1, 0), (0, 1)):
                    ii, jj = i + di, j + dj
                    if ii >= w or jj >= h:
                        continue
                    q = jj * w + ii
                    d = v[q] - v[k]
                    if abs(d) > limit:
                        sign = 1 if d > 0 else -1
                        if anchor is None:
                            excess = (abs(d) - limit) / 2 * sign
                            v[k] += excess
                            v[q] -= excess
                        elif abs(v[k] - anchor[k]) >= abs(v[q] - anchor[q]):
                            v[k] += (abs(d) - limit) * sign          # k moves toward q
                        else:
                            v[q] -= (abs(d) - limit) * sign          # q moves toward k
                        changed.add(k)
                        changed.add(q)
                        moved = True
        if not moved:
            break
    return len(changed)


# -- object policies ------------------------------------------------------------------------------------
# Per object, after the fit: TERRAIN = the ground adapted to it (default for structures), SNAP = the object
# moves onto the fitted ground (loose objects: rocks, flora, crates, clutter; also a fix for outliers),
# KEEP = left exactly as captured (attached or elevated pieces).
TERRAIN, SNAP, KEEP = 'terrain', 'snap', 'keep'


def _align_matrix(normal) -> tuple:
    """Rotation taking +z onto `normal` (Rodrigues; identity for a level surface)."""
    nx, ny, nz = normal
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / n, ny / n, nz / n
    ax, ay = -ny, nx                                  # axis = z x n (in the xy plane)
    s = math.hypot(ax, ay)
    if s < 1e-9:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ax, ay, c = ax / s, ay / s, nz
    t = 1 - c
    return ((t * ax * ax + c, t * ax * ay, s * ay),
            (t * ax * ay, t * ay * ay + c, -s * ax),
            (-s * ay, s * ax, c))


def snap_to_ground(t, box, surface: Heightfield, embed: float = 0.05, align: bool = False, max_tilt_deg: float = 25.0):
    """The transform moved (and optionally tilted) so the object's bottom rests on the surface.

    The bottom is placed at the lowest ground point under the footprint (centre and corners) minus `embed`,
    so no corner floats; `align` tilts the object to the ground normal at its centre (capped at
    `max_tilt_deg`), as for rocks and plants on a slope.
    """
    from ..scene.transform import Transform, mat_mul, matrix_to_euler
    if align:
        nx, ny, nz = surface.normal(t.position[0], t.position[1])
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, nz / math.sqrt(nx * nx + ny * ny + nz * nz)))))
        if tilt > max_tilt_deg:
            f = math.tan(math.radians(max_tilt_deg)) / math.tan(math.radians(tilt))
            nx, ny = nx * f, ny * f
        rotation = matrix_to_euler(mat_mul(_align_matrix((nx, ny, nz)), t.matrix), t.convention)
        t = Transform(t.position, rotation, t.scale, t.convention)
    if box is None:
        x, y, _ = t.position
        return Transform((x, y, surface.at(x, y) - embed), t.rotation, t.scale, t.convention)
    pts = [t.apply((bx, by, bz)) for bx in (box.min[0], box.max[0]) for by in (box.min[1], box.max[1])
           for bz in (box.min[2], box.max[2])]
    bottom = min(p[2] for p in pts)
    foot = [t.apply((bx, by, box.min[2])) for bx in (box.min[0], box.max[0]) for by in (box.min[1], box.max[1])]
    ground = min([surface.at(t.position[0], t.position[1])] + [surface.at(p[0], p[1]) for p in foot])
    dz = ground - embed - bottom
    x, y, z = t.position
    return Transform((x, y, z + dz), t.rotation, t.scale, t.convention)
