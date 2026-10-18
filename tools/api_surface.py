"""Snapshot of PyField's public API, used by tests/test_public_api.py.

    python tools/api_surface.py            # print
    python tools/api_surface.py --write    # update docs/api/surface.txt (record the change in CHANGELOG)

The surface covers everything in `pyfield.__all__` (signatures, public methods and
properties of classes) plus the adapter protocol (GameAdapter fields, HeaderScheme
methods, GroupLayout and FormatSpec fields) and the CLI command list.
"""
from __future__ import annotations

import argparse
import dataclasses
import inspect
from pathlib import Path

SURFACE_FILE = Path(__file__).resolve().parents[1] / 'docs' / 'api' / 'surface.txt'


def _sig(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return '(...)'


def _class_lines(name, cls):
    lines = [f'class {name}{"(" + ", ".join(b.__name__ for b in cls.__bases__ if b is not object) + ")" if cls.__bases__ != (object,) else ""}']
    if dataclasses.is_dataclass(cls):
        for f in dataclasses.fields(cls):
            lines.append(f'  field {f.name}')
    for attr in sorted(vars(cls)):
        if attr.startswith('_') and attr not in ('__init__', '__enter__', '__exit__', '__iter__'):
            continue
        value = vars(cls)[attr]
        if isinstance(value, property):
            lines.append(f'  property {attr}' + (' (settable)' if value.fset else ''))
        elif isinstance(value, (classmethod, staticmethod)):
            lines.append(f'  {type(value).__name__} {attr}{_sig(value.__func__)}')
        elif inspect.isfunction(value):
            if dataclasses.is_dataclass(cls) and attr == '__init__':
                continue
            lines.append(f'  def {attr}{_sig(value)}')
    return lines


def surface() -> str:
    import pyfield
    from pyfield import cli
    from pyfield.core.format import FormatSpec
    from pyfield.core.groups import GroupLayout
    from pyfield.core.header import HeaderScheme
    from pyfield.games.base import ADAPTER_API_VERSION, GameAdapter
    lines = [f'# pyfield public surface (adapter API {ADAPTER_API_VERSION})']
    for name in sorted(pyfield.__all__):
        obj = getattr(pyfield, name)
        if name == '__version__':
            continue
        if inspect.isclass(obj):
            lines += _class_lines(name, obj)
        elif inspect.isfunction(obj):
            lines.append(f'def {name}{_sig(obj)}')
        elif inspect.ismodule(obj):
            lines.append(f'module {name}: ' + ', '.join(sorted(n for n in vars(obj)
                                                              if not n.startswith('_') and inspect.isfunction(getattr(obj, n)))))
    lines.append('# adapter protocol')
    for name, cls in [('GameAdapter', GameAdapter), ('HeaderScheme', HeaderScheme),
                      ('GroupLayout', GroupLayout), ('FormatSpec', FormatSpec)]:
        lines += _class_lines(name, cls)
    lines.append('# cli')
    lines.append('commands: ' + ' '.join(sorted(n[4:] for n in vars(cli) if n.startswith('cmd_'))))
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    text = surface()
    if a.write:
        SURFACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SURFACE_FILE.write_text(text)
        print('wrote', SURFACE_FILE)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
