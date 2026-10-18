"""Release check: build wheels, install them into a clean virtual environment, test there.

    python tools/release_check.py [--work DIR] [--skip-tests]

Steps
  1. `pip wheel` PyField and the reference adapter (examples/pyfield-csvgame) into dist/.
  2. Create a fresh venv in --work (default: a temp folder), install both wheels + pytest.
  3. Smoke checks inside the venv: version, packaged xEdit inventory, adapter discovery
     through the entry point, CLI entry script, a csvgame plugin written and re-read.
  4. Run the test suite against the *installed* wheel (not the source tree).
Exit status is non-zero on any failure. Never touches game files.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SMOKE = textwrap.dedent('''
    import pyfield, tempfile, pathlib
    from pyfield import games
    print('pyfield', pyfield.__version__, pyfield.__file__)
    assert 'site-packages' in pyfield.__file__, 'not testing the installed wheel'
    sf = games.get('starfield')
    assert sf.schemas is not None and len(sf.schemas.classes) >= 13, 'schemas missing'
    from pyfield.games.starfield.schema import load_inventory
    assert load_inventory() is not None, 'xEdit inventory not packaged'
    csv = games.get('csvgame')
    print('discovered', csv, csv.schema_version)
    d = pathlib.Path(tempfile.mkdtemp())
    p = pyfield.create_plugin('Sheet.csvg', 'csvgame')
    with p.transaction() as tx:
        tx.new_record('ROW_', 'Row_One', value=1.25)
        tx.commit(d / 'Sheet.csvg')
    q = pyfield.open_plugin(d / 'Sheet.csvg')
    assert q.adapter.name == 'csvgame' and next(q.typed_records('ROW_')).value == 1.25
    print('csvgame plugin roundtrip ok')
''')


def run(cmd, **kw):
    print('$', ' '.join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', help='folder for the venv (default: temporary)')
    ap.add_argument('--skip-tests', action='store_true')
    a = ap.parse_args()
    dist = ROOT / 'dist'
    shutil.rmtree(dist, ignore_errors=True)
    run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '-w', dist, ROOT, ROOT / 'examples' / 'pyfield-csvgame'])
    wheels = sorted(dist.glob('*.whl'))
    print('built:', *[w.name for w in wheels])
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix='pyfield-release-'))
    venv = work / 'venv'
    shutil.rmtree(venv, ignore_errors=True)
    run([sys.executable, '-m', 'venv', venv])
    py = venv / ('Scripts' if os.name == 'nt' else 'bin') / 'python'
    run([py, '-m', 'pip', 'install', '-q', *wheels, 'pytest'])
    run([py, '-c', SMOKE], cwd=work)
    cli = venv / ('Scripts' if os.name == 'nt' else 'bin') / 'pyfield'
    run([cli, 'capabilities', 'csvgame'], cwd=work)
    if not a.skip_tests:
        # copy the tests so the source tree is not importable from the test run
        tests = work / 'tests'
        shutil.rmtree(tests, ignore_errors=True)
        shutil.copytree(ROOT / 'tests', tests, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'tools', work / 'tools', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'docs' / 'api', work / 'docs' / 'api', dirs_exist_ok=True)
        run([py, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'], cwd=work)
    print('release check passed; wheels in', dist)


if __name__ == '__main__':
    main()
