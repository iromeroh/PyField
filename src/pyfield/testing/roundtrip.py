"""Roundtrip harness: proves preservation at increasing depths of decoding.

Levels
  raw     open + write, nothing expanded                -> bytes identical
  tree    every group expanded, no record decoded        -> bytes identical
  fields  every record's subrecords decoded              -> bytes identical
  encode  every record body re-encoded from its fields   -> uncompressed bodies identical,
          compressed bodies identical after decompression; reports how many compressed
          bodies are also reproduced byte for byte by zlib level detection.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..core import compression, subrecords as sr
from ..core.nodes import GroupNode, RecordNode
from ..core.plugin import Plugin

LEVELS = ('raw', 'tree', 'fields', 'encode')


def _digest(chunks) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    for c in chunks:
        h.update(c)
        n += len(c)
    return h.hexdigest(), n


def roundtrip(path, level: str = 'fields', game=None, sample_compressed: int = 200) -> dict:
    path = Path(path)
    if level not in LEVELS:
        raise ValueError(f'level must be one of {LEVELS}')
    t0 = time.perf_counter()
    source_digest, source_size = _digest([path.read_bytes()]) if path.stat().st_size < (1 << 30) \
        else _file_digest(path)
    plugin = Plugin.open(path, game)
    report = {'file': path.name, 'game': plugin.adapter.name, 'level': level, 'bytes': source_size}
    try:
        t_index = time.perf_counter()
        idx = plugin.index
        report['records'] = len(idx)
        report['groups'] = len(idx.groups)
        report['index_seconds'] = round(time.perf_counter() - t_index, 3)
        problems = []
        if level in ('tree', 'fields', 'encode'):
            n_rec = n_grp = 0
            for node in plugin.walk():
                if isinstance(node, GroupNode):
                    n_grp += 1
                else:
                    n_rec += 1
                    if level in ('fields', 'encode'):
                        node.fields  # decode
            if (n_rec, n_grp) != (len(idx), len(idx.groups)):
                problems.append(f'tree walk saw {n_rec} records/{n_grp} groups, index {len(idx)}/{len(idx.groups)}')
        if level == 'encode':
            report.update(_check_encode(plugin, problems, sample_compressed))
        else:
            digest, size = _digest(plugin.iter_chunks(update_header=True))
            report['identical'] = digest == source_digest and size == source_size
            if not report['identical']:
                problems.append(f'output differs (size {size} vs {source_size})')
        report['problems'] = problems
        report['ok'] = not problems
    finally:
        plugin.close()
    report['seconds'] = round(time.perf_counter() - t0, 3)
    return report


def _check_encode(plugin, problems, sample_compressed):
    spec = plugin.spec
    stats = {'reencoded': 0, 'compressed': 0, 'compressed_sampled': 0, 'compressed_byte_identical': 0,
             'zlib_levels': {}}
    for node in plugin.walk():
        if not isinstance(node, RecordNode):
            continue
        plain = node.plain_body()
        body = sr.encode(node.fields, spec)
        stats['reencoded'] += 1
        if body != plain:
            problems.append(f'{node!r}: re-encoded body differs')
            if len(problems) > 20:
                break
            continue
        if node.is_compressed:
            stats['compressed'] += 1
            if stats['compressed_sampled'] < sample_compressed:
                stats['compressed_sampled'] += 1
                level = compression.detect_level(node._stored, plain)
                stats['zlib_levels'][str(level)] = stats['zlib_levels'].get(str(level), 0) + 1
                if level is not None:
                    stats['compressed_byte_identical'] += 1
    return stats


def _file_digest(path):
    h, n = hashlib.sha256(), 0
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n
