"""Public API compatibility.

The recorded surface (docs/api/surface.txt) must match the code. An intentional change:
run `python tools/api_surface.py --write`, and note it in CHANGELOG.md (removals and
signature changes are breaking; additions are not).
"""
import difflib
import importlib.util
from pathlib import Path

import pyfield

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location('api_surface', ROOT / 'tools' / 'api_surface.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_surface_matches_record():
    tool = _tool()
    recorded = tool.SURFACE_FILE.read_text().splitlines()
    current = tool.surface().splitlines()
    removed = [line for line in recorded if line not in current]
    diff = '\n'.join(difflib.unified_diff(recorded, current, 'recorded', 'current', lineterm=''))
    assert recorded == current, f'public API changed ({len(removed)} removed/changed lines):\n{diff}'


def test_all_exports_resolve():
    for name in pyfield.__all__:
        assert hasattr(pyfield, name), name


def test_facade_functions_work(tmp_path):
    p = pyfield.create_plugin('Facade.esm', 'starfield', ['Starfield.esm'], flags=1,
                              master_kinds={'Starfield.esm': 'full'})
    with p.transaction() as tx:
        tx.new_record('GLOB', 'Facade_G', value=1.0)
        tx.commit(tmp_path / 'Facade.esm', validate=False)
    q = pyfield.open_plugin(tmp_path / 'Facade.esm')
    assert q.adapter is pyfield.games.get('starfield') and len(q.index) == 1
