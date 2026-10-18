"""Starfield asset rules and Wwise soundbank resolution.

WWED.WSED holds the Wwise event GUID as four u32 values (observed 2026-10-15 on every event
of star_radio and Dogs & Cats banks): for GUID {AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEFFFF... } the
values are (BBBBCCCC, AAAAAAAA, last 4 bytes, DDDD + first 2 bytes of the node).
Plugin soundbanks live at sound/soundbanks/<bank id>.bnk with a <bank id>.json description
listing IncludedEvents (Name, Id = FNV-1 hash of the lower-case name, GUID) and the media
each event references (ReferencedStreamedFiles / IncludedMemoryFiles: Id -> <Id>.wem).
"""
from __future__ import annotations

import json
import struct

from ...assets.index import AssetRules

RULES = AssetRules(
    roots=('meshes', 'geometries', 'materials', 'textures', 'sound', 'scripts', 'interface', 'terrain',
           'particles', 'planetdata', 'misc', 'video', 'strings', 'shadersfx'),
    extension_roots={'.nif': 'meshes/', '.af': 'meshes/', '.afx': 'meshes/', '.rig': 'meshes/',
                     '.agx': 'meshes/', '.hkx': 'meshes/', '.txt': 'meshes/', '.mat': 'materials/',
                     '.dds': 'textures/', '.mesh': 'geometries/', '.wem': 'sound/', '.bnk': 'sound/',
                     '.pex': 'scripts/', '.ffxanim': 'sound/', '.swf': 'interface/'},
    implicit=(('geometries/', '.mesh'),),
    base_archives=('starfield - *.ba2',),
    official_plugins=('starfield.esm', 'shatteredspace.esm', 'sfbgs*.esm', 'constellation.esm', 'sfta*.esm',
                      'blueprintships-*.esm', 'oldmars.esm'),
    unverifiable=(('materials/', '.mat'),),          # vanilla materials are compiled into materialsbeta.cdb
    opaque_prefixes=('sound/soundbanks/',),          # bank JSON lists Wwise project paths; see wwed_assets
)

SOUNDBANK_DIR = 'sound/soundbanks/'


def wsed_from_guid(guid: str) -> tuple[int, int, int, int]:
    """The four u32 a WWED.WSED stores for a Wwise GUID string."""
    h = guid.strip('{}').replace('-', '')
    a, b, c, d, e = h[0:8], h[8:12], h[12:16], h[16:20], h[20:32]
    return int(b + c, 16), int(a, 16), int(e[4:], 16), int(d + e[:4], 16)


def wsed_values(data: bytes) -> tuple[int, int, int, int]:
    return struct.unpack('<4I', data[:16])


def bank_index(assets) -> dict:
    """WSED tuple -> {'event', 'bank', 'files'} over every soundbank JSON the index provides."""
    out = {}
    for name in assets.names(SOUNDBANK_DIR):
        if not name.endswith('.json'):
            continue
        try:
            info = json.loads(assets.read(name))['SoundBanksInfo']
        except (ValueError, KeyError):
            continue
        for bank in info.get('SoundBanks', []):
            bank_files = [SOUNDBANK_DIR + bank['Path'].replace('\\', '/').lower(), name]
            for ev in bank.get('IncludedEvents', []):
                media = [SOUNDBANK_DIR + f'{m["Id"]}.wem' for key in ('ReferencedStreamedFiles', 'IncludedMemoryFiles')
                         for m in ev.get(key, [])]
                out[wsed_from_guid(ev['GUID'])] = {'event': ev['Name'], 'bank': bank['ShortName'],
                                                   'files': bank_files + media}
    return out


def wwed_assets(view, assets, cache: dict) -> list[str]:
    """Soundbank files needed by a WWED record (bank, its JSON, the event's media)."""
    wsed = view.node.get('WSED')
    if wsed is None or len(wsed.data) < 16:
        return []
    if 'banks' not in cache:
        cache['banks'] = bank_index(assets)
    hit = cache['banks'].get(wsed_values(wsed.data))
    return [f for f in hit['files'] if assets.exists(f)] if hit else []
