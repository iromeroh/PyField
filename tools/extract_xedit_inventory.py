"""Extract a schema *inventory* from xEdit's wbDefinitions*.pas.

For every record definition: its signature, name, and the ordered list of subrecord
members (signature, name, leaf kind, and whether it sits inside a repeating/structured
record-level group). Helper variables (wbEDID, wbFULL, ...) and simple helper functions
are expanded where their definitions contain subrecord calls.

This is an inventory for coverage and cross-checks, not a compiler of xEdit's DSL:
conditional/decider layouts, element-level structure and version gates are not modelled.
The input is MPL-2.0 (xEdit); the generated JSON is a derived work under the same terms.

    python tools/extract_xedit_inventory.py wbDefinitionsSF1.pas -o src/pyfield/games/starfield/data/xedit_sf1_inventory.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SIG = r'[A-Z0-9_]{3}[A-Z0-9_]'
CALL_WITH_SIG = re.compile(r'\b(wb\w+)\(\s*(' + SIG + r')\s*(?:\)|,\s*(?:\'((?:[^\']|\'\')*)\')?)')
IDENT = re.compile(r'\b(wb\w+)\b(?!\s*\()')
FUNC_CALL = re.compile(r'\b(wb\w+)\s*\(')
RECORD_START = re.compile(r'\bwb(?:Ref)?Record\(\s*(' + SIG + r')\s*,\s*\'((?:[^\']|\'\')*)\'')

LEAF_KIND = {
    'wbString': 'zstring', 'wbStringKC': 'zstring', 'wbStringLC': 'zstring', 'wbStringScript': 'zstring',
    'wbLString': 'lstring', 'wbLStringKC': 'lstring', 'wbFormID': 'formid', 'wbFormIDCk': 'formid',
    'wbFormIDCkNoReach': 'formid', 'wbFloat': 'float', 'wbInteger': 'int', 'wbStruct': 'struct',
    'wbArray': 'array', 'wbArrayS': 'array', 'wbByteArray': 'bytes', 'wbUnknown': 'bytes',
    'wbEmpty': 'empty', 'wbUnion': 'union', 'wbRStruct': 'rstruct', 'wbRArray': 'rarray',
    'wbRArrayS': 'rarray', 'wbRUnion': 'runion',
}


def matching_paren(text: str, open_pos: int) -> int:
    """Index of the bracket closing text[open_pos] (comments stripped, strings neutralized)."""
    depth = 0
    for i in range(open_pos, len(text)):
        c = text[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
            if depth == 0:
                return i
    raise ValueError('unbalanced')


def strip_comments(text: str) -> str:
    """Remove comments; neutralize bracket/semicolon characters inside string literals."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            lit = text[i:j + 1]
            out.append(lit.translate(str.maketrans('()[];{}', '<><>,<>')))
            i = j + 1
        elif text.startswith('//', i):
            i = text.find(chr(10), i)
            i = n if i < 0 else i
        elif c == '{':
            i = text.find('}', i) + 1 or n
        elif text.startswith('(*', i):
            i = text.find('*)', i) + 2 if text.find('*)', i) >= 0 else n
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def collect_definitions(text: str) -> dict[str, str]:
    """Variable assignments `wbX := ...;` and function bodies `function wbX(...)...end;`."""
    defs = {}
    for m in re.finditer(r'\b(wb\w+)\s*:=\s*', text):
        start = m.end()
        # assignment ends at the first ';' at paren depth 0
        depth, i = 0, start
        while i < len(text):
            c = text[i]
            if c in '([':
                depth += 1
            elif c in ')]':
                depth -= 1
            elif c == "'":
                i = text.find("'", i + 1)
                if i < 0:
                    break
            elif c == ';' and depth <= 0:
                break
            i += 1
        defs.setdefault(m.group(1), text[start:i])
    for m in re.finditer(r'\bfunction\s+(wb\w+)\s*(\([^)]*\))?\s*:\s*\w+\s*;(.*?)\bend\s*;', text, flags=re.S):
        defs.setdefault(m.group(1), m.group(3))
    return defs


def members(body: str, defs: dict, seen=frozenset(), depth=0) -> list[dict]:
    out = []
    events = []
    for m in CALL_WITH_SIG.finditer(body):
        events.append((m.start(), 'sub', m))
    for m in IDENT.finditer(body):
        events.append((m.start(), 'var', m))
    for m in FUNC_CALL.finditer(body):
        if m.group(1) in defs and m.group(1) not in LEAF_KIND:
            events.append((m.start(), 'fn', m))
    events.sort(key=lambda e: e[0])
    for _, kind, m in events:
        if kind == 'sub':
            fn = m.group(1)
            out.append({'sig': m.group(2), 'name': (m.group(3) or '').replace("''", "'"),
                        'kind': LEAF_KIND.get(fn, fn), 'depth': depth})
        else:
            name = m.group(1)
            if name in seen or name not in defs or depth > 6:
                continue
            sub = members(defs[name], defs, seen | {name}, depth)
            for s in sub:
                s['via'] = [name] + s.get('via', [])
            out.extend(sub)
    # de-duplicate events found both as call and via variable at the same text position
    return out


def extract(path: Path, common: list[Path] = ()) -> dict:
    text = strip_comments(path.read_text(encoding='utf-8', errors='replace'))
    defs = collect_definitions(text)
    for extra in common:   # helper definitions shared by all games (wbDefinitionsCommon.pas)
        for name, body in collect_definitions(strip_comments(extra.read_text(encoding='utf-8', errors='replace'))).items():
            defs.setdefault(name, body)
    records = {}
    for m in RECORD_START.finditer(text):
        open_pos = text.index('(', m.start())
        end = matching_paren(text, open_pos)
        body = text[m.end():end]
        sig, name = m.group(1), m.group(2).replace("''", "'")
        mem = members(body, defs)
        # drop nested element-level SIG-looking calls that are not record members: keep first occurrence order
        records[sig] = {'name': name, 'members': mem}
    return {'source': [path.name] + [c.name for c in common],
            'license': 'MPL-2.0 (derived from xEdit definitions)', 'records': records}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pas')
    ap.add_argument('--common', nargs='*', default=[], help='wbDefinitionsCommon.pas for shared helpers')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    inv = extract(Path(a.pas), [Path(c) for c in a.common])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=1))
    print(f"{len(inv['records'])} records -> {out}")


if __name__ == '__main__':
    main()
