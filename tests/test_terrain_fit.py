"""Terrain fitted to placed objects (landscape/fit.py)."""
import math
import random

from pyfield.landscape.fit import NATURAL, STRUCTURE, SUPPORT, GroundSample, fit_terrain, ground_samples
from pyfield.scene.spatial import Box
from pyfield.scene.transform import Transform


def ground(x, y):
    return 3 + 0.04 * x - 0.02 * y + 2.5 * math.sin(x / 25) * math.cos(y / 30)


def test_recovers_smooth_ground_and_ignores_a_single_outlier():
    rng = random.Random(7)
    samples = [GroundSample(x, y, ground(x, y), ref=k)
               for k, (x, y) in enumerate((rng.uniform(10, 90), rng.uniform(10, 90)) for _ in range(400))]
    samples.append(GroundSample(50.0, 50.0, ground(50, 50) + 6.0, ref='outlier'))     # a rock hanging in the air
    fit = fit_terrain(samples, (0.0, 0.0, 100.0, 100.0), border=10.0)
    hf = fit.surface
    errs = sorted(abs(hf.at(x, y) - ground(x, y)) for x in range(20, 81, 5) for y in range(20, 81, 5))
    assert errs[len(errs) // 2] < 0.15 and errs[-1] < 0.6
    # the outlier is reported, and the ground under it stays close to the true ground (no spike)
    rep = fit.report()
    assert [fit.samples[i].ref for i in fit.outliers] == ['outlier']
    assert abs(hf.at(50, 50) - ground(50, 50)) < 0.3
    assert rep['within_interval'] >= 0.9 * rep['samples']


def test_isolated_object_gets_ground_and_borders_relax_to_the_plane():
    samples = [GroundSample(x, y, 0.0) for x in range(10, 91, 4) for y in range(10, 91, 4)
               if math.hypot(x - 50, y - 50) > 20]
    samples.append(GroundSample(50.0, 50.0, 2.0, 0.2, STRUCTURE, 'hut', lo=1.9, hi=3.0))   # a hut 2 m up
    fit = fit_terrain(samples, (0.0, 0.0, 100.0, 100.0), border=10.0)
    assert 1.89 <= fit.surface.at(50, 50) <= 3.01                                      # neither floats nor buried
    assert abs(fit.surface.at(50, 30)) < 0.3                                           # a local bump, no plateau
    assert abs(fit.surface.at(0, 50)) < 0.05 and abs(fit.surface.at(100, 0)) < 0.05    # borders on the plane
    assert max(fit.surface.slope_deg(x, 50) for x in range(30, 71, 2)) < 40.5


def test_stacked_objects_are_not_ground():
    floor = Box((-4, -4, 0), (4, 4, 3))
    chair = Box((-0.4, -0.4, 0), (0.4, 0.4, 1))
    items = [(Transform.at(0, 0, 1.0), floor, STRUCTURE, 'hab'),
             (Transform.at(0.5, 0.5, 1.2), chair, STRUCTURE, 'chair'),                 # on the hab floor
             (Transform.at(10, 0, 0.3), None, NATURAL, 'rock')]
    s = ground_samples(items)
    refs = {x.ref for x in s}
    assert 'chair' not in refs and {'hab', 'rock'} <= refs
    assert all(abs(x.z - 1.0) < 1e-6 for x in s if x.ref == 'hab')                  # bottom of the bounds
    assert len([x for x in s if x.ref == 'hab']) == 5                                  # centre + 4 corners


def test_supports_need_ground_between_bottom_and_deck():
    deck = Box((-5, -5, -6), (5, 5, 0.5))                                               # legs 6 m below the deck
    items = [(Transform.at(50, 50, 4.0), deck, STRUCTURE, 'pad')]
    s = ground_samples(items)
    assert {x.kind for x in s} == {SUPPORT} and all(abs(x.lo - -2.1) < 1e-6 and abs(x.hi - 3.9) < 1e-6 for x in s)
    ring = [GroundSample(x, y, 0.0) for x in range(10, 91, 4) for y in range(10, 91, 4) if math.hypot(x - 50, y - 50) > 15]
    fit = fit_terrain(ring + s, (0.0, 0.0, 100.0, 100.0), border=10.0)
    assert all(-2.11 <= fit.surface.at(x.x, x.y) <= 3.91 for x in s)
    assert fit.report()['by_kind']['support']['ok'] == 5


def test_floating_structure_is_attached_not_spiked():
    ring = [GroundSample(x, y, 0.0) for x in range(10, 91, 3) for y in range(10, 91, 3)]
    crate = GroundSample(50.0, 50.0, 5.0, 0.2, STRUCTURE, 'crate', lo=4.9, hi=6.0)       # crate floating 5 m up
    fit = fit_terrain(ring + [crate], (0.0, 0.0, 100.0, 100.0), border=10.0, max_slope_deg=35.0)
    rep = fit.report()
    assert rep['attached_objects'] == 1                                               # floats: treated as mounted
    assert abs(fit.surface.at(50, 50)) < 0.3                                          # no spike under it


def test_snap_policy_rests_loose_objects_on_the_fitted_ground():
    from pyfield.landscape import Heightfield
    from pyfield.landscape.fit import snap_to_ground
    hf = Heightfield(101, 101, 1.0, (0.0, 0.0))
    for k in range(len(hf.values)):
        hf.values[k] = 0.2 * (k % 101)                                                 # 0.2 rise per metre in x
    crate = Box((-0.5, -0.5, 0.0), (0.5, 0.5, 1.0))
    t = snap_to_ground(Transform.at(50, 50, 30.0), crate, hf)                          # dropped from 30 m
    assert abs(t.position[2] - (0.2 * 49.5 - 0.05)) < 1e-3                            # lowest corner touches
    rock = snap_to_ground(Transform.at(20, 20, -5.0), None, hf, align=True)
    assert abs(rock.position[2] - (4.0 - 0.05)) < 1e-3
    up = rock.apply((0, 0, 1))
    tilt = math.degrees(math.acos(up[2] - rock.position[2]))
    assert abs(tilt - math.degrees(math.atan(0.2))) < 0.5                             # follows the slope
