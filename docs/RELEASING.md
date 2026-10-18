# Release process

Package: [`pyfield-esm`](https://pypi.org/project/pyfield-esm/) on PyPI (imports as `pyfield`).

Versioning: `MAJOR.MINOR.PATCH` (PEP 440 pre-releases `.devN`, `aN`, `rcN`).
Before 1.0, minor versions may break the API but must say so in the changelog.
From 1.0: removals or signature changes in `docs/api/surface.txt` require a major version.
Schema packages carry their own version (`adapter.schema_version`).

## Every release

1. `python -m pytest`: all green (corpus tests run when the games are installed; set `PYFIELD_STARFIELD_DATA`).
2. For format or schema changes, corpus evidence:
   `python tools/phase0_baseline.py --starfield <Data> --oblivion <Data>` and
   `python tools/validate_schemas.py <Data>/*.esm`: zero failures.
3. API surface: `python tools/api_surface.py` must match `docs/api/surface.txt` (the test enforces this). For
   intended changes run `--write` and describe them in `CHANGELOG.md` under Added / Changed / Removed.
4. Set the new version in `pyproject.toml` and `pyfield.__version__` (kept equal).
5. Move the `Unreleased` changelog entries under the new version heading; update `docs/ROADMAP.md`.
6. Optional local check: `python tools/release_check.py` (builds the wheel, installs it in a clean venv, runs the
   suite against it).
7. Commit, then tag and push:

   ```
   git tag v0.3.1
   git push origin main --tags
   ```

The `release` workflow checks that the tag matches the package version, builds the sdist and wheel, runs the tests
against the built wheel, and publishes to PyPI through trusted publishing (no API token in the repository). The
`docs` workflow rebuilds the documentation site on every push to `main`; `tests` runs on every push and pull
request (Linux and Windows, Python 3.11 to 3.13).

## One-time setup (done once per project)

1. GitHub: create the public repository and push `main`. In Settings > Pages, set the source to "GitHub Actions".
2. PyPI: create an account (with 2FA), then under "Your projects > Publishing" add a pending trusted publisher:
   project `pyfield-esm`, owner and repository from GitHub, workflow `release.yml`, environment `pypi`.
3. GitHub: Settings > Environments > create `pypi` (optionally require a manual approval before publishing).

## Never publish

`re/` (local executable-analysis workspace), `build/`, captures, plugins or archives built
from game data. `.gitignore` excludes them; the wheel contains only `src/pyfield` and the license files.
