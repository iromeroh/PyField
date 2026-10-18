"""Rigid transforms with uniform scale, in a game's placement convention.

Placed references store position (metres in Starfield), three Euler angles (radians) and a
uniform scale. The convention mapping angles to a rotation matrix comes from the adapter
(`rotation_convention`, e.g. Starfield `('xyz', -1)`: R = Rx(-rx)·Ry(-ry)·Rz(-rz), learned from
reference groups in Starfield.esm, docs/formats/starfield-placement.md).
Composition: world = parent ∘ local  <=>  p = P.p + P.s·P.R·l.p,  R = P.R·l.R,  s = P.s·l.s.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

Matrix = tuple

DEFAULT_CONVENTION = ('xyz', -1)
TWO_PI = 2 * math.pi


def _rot(axis: str, a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    if axis == 'x':
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    if axis == 'y':
        return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def mat_mul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mat_vec(m: Matrix, v) -> tuple:
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def transpose(m: Matrix) -> Matrix:
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def euler_to_matrix(angles, convention=DEFAULT_CONVENTION) -> Matrix:
    order, sign = convention
    by_axis = dict(zip('xyz', angles))
    m = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    for axis in order:
        m = mat_mul(m, _rot(axis, sign * by_axis[axis]))
    return m


def matrix_to_euler(m: Matrix, convention=DEFAULT_CONVENTION) -> tuple:
    """Inverse of euler_to_matrix (angles normalized to [0, 2π))."""
    order, sign = convention
    if order != 'xyz':
        raise NotImplementedError(f'decomposition for order {order!r}')
    # m = Rx(a)·Ry(b)·Rz(c):  m[0][2] = sin b,  m[1][2] = -sin a cos b,  m[2][2] = cos a cos b,
    #                          m[0][1] = -cos b sin c,  m[0][0] = cos b cos c
    cb = math.hypot(m[0][0], m[0][1])
    b = math.atan2(m[0][2], cb)
    if cb > 1e-9:
        a = math.atan2(-m[1][2], m[2][2])
        c = math.atan2(-m[0][1], m[0][0])
    else:                                   # gimbal lock: fold everything into a
        a = math.atan2(m[2][1], m[1][1])
        c = 0.0
    return tuple(normalize_angle(sign * v) for v in (a, b, c))


def normalize_angle(a: float) -> float:
    a = math.fmod(a, TWO_PI)
    if a < 0:
        a += TWO_PI
    return 0.0 if abs(a) < 1e-12 or abs(a - TWO_PI) < 1e-12 else a


@dataclass(frozen=True)
class Transform:
    position: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (0.0, 0.0, 0.0)          # Euler angles, radians, adapter convention
    scale: float = 1.0
    convention: tuple = DEFAULT_CONVENTION

    @classmethod
    def at(cls, x=0.0, y=0.0, z=0.0, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0, scale=1.0,
           convention=DEFAULT_CONVENTION) -> 'Transform':
        """Convenience constructor; yaw is rotation about Z, pitch about X, roll about Y (degrees)."""
        return cls((float(x), float(y), float(z)),
                   tuple(math.radians(v) for v in (pitch_deg, roll_deg, yaw_deg)), float(scale), convention)

    @property
    def matrix(self) -> Matrix:
        return euler_to_matrix(self.rotation, self.convention)

    def compose(self, local: 'Transform') -> 'Transform':
        """self ∘ local: the local transform expressed in self's parent space."""
        m = self.matrix
        offset = mat_vec(m, tuple(self.scale * v for v in local.position))
        position = tuple(a + b for a, b in zip(self.position, offset))
        rotation = matrix_to_euler(mat_mul(m, local.matrix), self.convention)
        return Transform(position, rotation, self.scale * local.scale, self.convention)

    def inverse(self) -> 'Transform':
        mt = transpose(self.matrix)
        inv_s = 1.0 / self.scale
        position = tuple(-inv_s * v for v in mat_vec(mt, self.position))
        return Transform(position, matrix_to_euler(mt, self.convention), inv_s, self.convention)

    def relative_to(self, parent: 'Transform') -> 'Transform':
        """The local transform L with parent ∘ L == self."""
        return parent.inverse().compose(self)

    def apply(self, point) -> tuple:
        offset = mat_vec(self.matrix, tuple(self.scale * v for v in point))
        return tuple(a + b for a, b in zip(self.position, offset))

    def close_to(self, other: 'Transform', pos_tol=1e-4, rot_tol=1e-5) -> bool:
        if any(abs(a - b) > pos_tol for a, b in zip(self.position, other.position)):
            return False
        if abs(self.scale - other.scale) > 1e-6:
            return False
        a, b = self.matrix, other.matrix
        return all(abs(a[i][j] - b[i][j]) <= rot_tol for i in range(3) for j in range(3))

    def to_dict(self) -> dict:
        return {'position': [round(v, 6) for v in self.position],
                'rotation_deg': [round(math.degrees(v), 6) for v in self.rotation],
                'scale': self.scale}

    @classmethod
    def from_dict(cls, d: dict, convention=DEFAULT_CONVENTION) -> 'Transform':
        rot = d.get('rotation_deg')
        rotation = tuple(math.radians(v) for v in rot) if rot is not None else tuple(d.get('rotation', (0, 0, 0)))
        return cls(tuple(float(v) for v in d.get('position', (0, 0, 0))), rotation,
                   float(d.get('scale', 1.0)), convention)
