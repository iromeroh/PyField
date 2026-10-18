"""Regression checks against installed game data (skipped when absent).

Environment: PYFIELD_STARFIELD_DATA / PYFIELD_OBLIVION_DATA override the default Steam paths.
Run everything including slow masters with `pytest -m "corpus"`; full-corpus measurements
live in tools/phase0_baseline.py and tools/validate_schemas.py.
"""
import os
from pathlib import Path

import pytest

from pyfield import FormKey
from pyfield.core.loadorder import LoadOrder
from pyfield.testing.roundtrip import roundtrip

SF = Path(os.environ.get('PYFIELD_STARFIELD_DATA',
                         r'C:\Program Files (x86)\Steam\steamapps\common\Starfield\Data'))
OB = Path(os.environ.get('PYFIELD_OBLIVION_DATA',
                         r'C:\Program Files (x86)\Steam\steamapps\common\Oblivion\Data'))

pytestmark = pytest.mark.corpus


def need(path: Path):
    if not path.exists():
        pytest.skip(f'{path} not installed')
    return path


@pytest.mark.parametrize('name', ['SFBGS004.esm', 'Constellation.esm', 'SFBGS003.esm', 'sfta01.esm'])
@pytest.mark.parametrize('level', ['raw', 'fields'])
def test_starfield_roundtrip(name, level):
    r = roundtrip(need(SF / name), level)
    assert r['ok'], r['problems']


def test_oblivion_roundtrip():
    r = roundtrip(need(OB / 'Oblivion.esm'), 'raw')
    assert r['ok'] and r['game'] == 'oblivion'


def test_bethesda_medium_master_references():
    need(SF / 'sfta01.esm')
    with LoadOrder.open(SF, ['sfta01.esm']) as lo:
        p = lo.plugin('sfta01.esm')
        assert p.kind == 'medium' and p.codec.own_style == 'compact'
        refs = [v for v in p.typed_records('REFR') if isinstance(v.base, FormKey)][:200]
        assert refs and all(lo.resolve(v.base) is not None for v in refs)


def test_xmarker_heading_is_static():
    need(SF / 'Starfield.esm')
    with LoadOrder.open(SF, ['Starfield.esm']) as lo:
        v = lo.resolve(FormKey('Starfield.esm', 0x34))
        assert v.signature == 'STAT' and v.editor_id == 'XMarkerHeading'
