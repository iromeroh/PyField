"""Asset round-trips: extract with provenance, detect edits, pack into verified BA2 archives.

Archives are built with the game's Archive2.exe (`-format=General` / `-format=DDS`,
`-compression=None`, as all workspace packagers do), then read back with PyField's reader
and compared member by member: general files byte for byte, textures by their pixel data
(Archive2 rewrites DDS headers). Nothing here writes into the game Data folder unless the
caller passes it explicitly as an output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from ..errors import PyFieldError
from .ba2 import Archive, normalize

MANIFEST = 'pyfield-assets.json'
TEXTURE_SUFFIX = '.dds'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_archive2(data_dir) -> Path:
    exe = Path(data_dir).parent / 'Tools' / 'Archive2' / 'Archive2.exe'
    if not exe.exists():
        raise PyFieldError(f'Archive2.exe not found at {exe} (install the Creation Kit tools)')
    return exe


# -- extraction with provenance ---------------------------------------------------------------

def extract(index, paths, out_dir, categories: dict | None = None) -> dict:
    """Copy assets to out_dir/<path> and write a manifest (provider, sha256, category)."""
    out_dir = Path(out_dir)
    manifest = {'data_dir': str(index.data_dir), 'files': {}}
    for path in sorted(set(paths)):
        data = index.read(path)
        dest = out_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        manifest['files'][path] = {'provider': str(index.provider(path)), 'sha256': sha256(data),
                                   'category': (categories or {}).get(path, '')}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return manifest


def work_files(work_dir) -> dict[str, Path]:
    work_dir = Path(work_dir)
    return {normalize(p.relative_to(work_dir).as_posix()): p for p in sorted(work_dir.rglob('*'))
            if p.is_file() and p.name != MANIFEST}


def status(work_dir) -> dict:
    """changed / added / removed / unchanged relative to the extraction manifest."""
    work_dir = Path(work_dir)
    manifest = json.loads((work_dir / MANIFEST).read_text(encoding='utf-8'))['files']
    files = work_files(work_dir)
    out = {'changed': [], 'added': [], 'removed': [], 'unchanged': []}
    for path, file in files.items():
        if path not in manifest:
            out['added'].append(path)
        elif sha256(file.read_bytes()) != manifest[path]['sha256']:
            out['changed'].append(path)
        else:
            out['unchanged'].append(path)
    out['removed'] = sorted(set(manifest) - set(files))
    return out


# -- packing -------------------------------------------------------------------------------------

@dataclass
class PackResult:
    archives: dict = field(default_factory=dict)      # archive path -> {'members': n, 'sha256': ...}
    log: list = field(default_factory=list)


def split_members(files: dict[str, bytes]) -> tuple[dict, dict]:
    textures = {k: v for k, v in files.items() if k.endswith(TEXTURE_SUFFIX)}
    general = {k: v for k, v in files.items() if not k.endswith(TEXTURE_SUFFIX)}
    return general, textures


def _dds_payload(data: bytes) -> bytes:
    if data[:4] != b'DDS ':
        return data
    return data[148:] if data[84:88] == b'DX10' else data[128:]


def build_archive(files: dict[str, bytes], out_path, fmt: str, archive2: Path, log: list) -> dict:
    """Pack `files` (normalized path -> bytes) with Archive2, then verify by reading back."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pyfield-pack-') as tmp:
        root = Path(tmp) / 'root'
        for name, data in files.items():
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        if out_path.exists():
            out_path.unlink()
        cmd = [str(archive2), str(root), f'-create={out_path}', f'-root={root}', f'-format={fmt}', '-compression=None']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        log.append({'cmd': cmd, 'returncode': r.returncode, 'stdout': r.stdout[-500:], 'stderr': r.stderr[-500:]})
        if r.returncode != 0 or not out_path.exists():
            raise PyFieldError(f'Archive2 failed for {out_path.name}: {r.stdout[-300:]} {r.stderr[-300:]}')
    archive = Archive(out_path)
    if set(archive.members) != set(files):
        raise PyFieldError(f'{out_path.name}: members differ after packing '
                           f'(missing {sorted(set(files) - set(archive.members))[:5]}, '
                           f'extra {sorted(set(archive.members) - set(files))[:5]})')
    for name, data in files.items():
        got = archive.read(name)
        same = got == data if fmt == 'General' else _dds_payload(got) == _dds_payload(data)
        if not same:
            raise PyFieldError(f'{out_path.name}: {name} differs after packing')
    return {'members': len(files), 'sha256': sha256(out_path.read_bytes()), 'format': fmt}


def pack(files: dict[str, bytes], plugin_name: str, out_dir, archive2: Path) -> PackResult:
    """`<plugin> - Main.ba2` (general files) and `<plugin> - Textures.ba2` (DDS) in out_dir."""
    stem = Path(plugin_name).stem
    general, textures = split_members({normalize(k): v for k, v in files.items()})
    result = PackResult()
    out_dir = Path(out_dir)
    if general:
        path = out_dir / f'{stem} - Main.ba2'
        result.archives[str(path)] = build_archive(general, path, 'General', archive2, result.log)
    if textures:
        path = out_dir / f'{stem} - Textures.ba2'
        result.archives[str(path)] = build_archive(textures, path, 'DDS', archive2, result.log)
    return result


def pack_work_dir(work_dir, plugin_name: str, out_dir, archive2: Path, loose: bool = False) -> PackResult:
    """Pack every file of an extraction work folder (or copy them as loose files with loose=True)."""
    files = {name: path.read_bytes() for name, path in work_files(work_dir).items()}
    if loose:
        result = PackResult()
        for name, data in files.items():
            dest = Path(out_dir) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        result.archives['loose'] = {'members': len(files)}
        return result
    return pack(files, plugin_name, out_dir, archive2)


def rebuild_plugin_archives(index, plugin_name: str, replacements: dict[str, bytes], out_dir, archive2: Path,
                            removals=()) -> PackResult:
    """New `<plugin> - *.ba2` = the plugin's current archive members with replacements/additions applied."""
    stem = Path(plugin_name).stem.lower()
    current = {}
    for arc in index.archives:
        if arc.path.name.lower().startswith(stem + ' - '):
            for name in arc.members:
                current[name] = arc.read(name)
    current.update({normalize(k): v for k, v in replacements.items()})
    for r in removals:
        current.pop(normalize(r), None)
    return pack(current, plugin_name, out_dir, archive2)


def copy_tree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True)
