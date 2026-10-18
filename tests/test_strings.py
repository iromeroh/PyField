"""Localized text through LoadOrder.strings / text / display_name (loose string tables)."""
import struct

from pyfield import FormKey
from pyfield.core.loadorder import LoadOrder
from pyfield.testing import fixtures as fx

sub, z, record, group = fx.sub, fx.z, fx.record, fx.group


def strings_table(entries):
    """.STRINGS: u32 count, u32 data size, (u32 id, u32 offset)*, zero-terminated texts."""
    data, directory = b'', b''
    for sid, text in entries.items():
        directory += struct.pack('<II', sid, len(data))
        data += text.encode() + bytes(1)
    return struct.pack('<II', len(entries), len(data)) + directory + data


def test_localized_and_plain_names(tmp_path):
    misc = record('MISC', 0x800, sub('EDID', z('Loc_Thing')) + sub('FULL', struct.pack('<I', 5)) + sub('DATA', bytes(8)))
    tes4 = sub('HEDR', struct.pack('<fII', 0.96, 2, 0x801)) + sub('CNAM', z('test'))
    (tmp_path / 'Loc.esm').write_bytes(record('TES4', 0, tes4, 0x81) + group(b'MISC', 0, misc))   # ESM + localized
    (tmp_path / 'strings').mkdir()
    (tmp_path / 'strings' / 'loc_en.strings').write_bytes(strings_table({5: 'Probe Widget'}))
    (tmp_path / 'strings' / 'loc_es.strings').write_bytes(strings_table({5: 'Artilugio sonda'}))
    plain = record('MISC', 0x800, sub('EDID', z('Plain_Thing')) + sub('FULL', z('Plain Widget')) + sub('DATA', bytes(8)))
    tes4b = sub('HEDR', struct.pack('<fII', 0.96, 2, 0x801)) + sub('CNAM', z('test'))
    (tmp_path / 'Plain.esp').write_bytes(record('TES4', 0, tes4b) + group(b'MISC', 0, plain))
    with LoadOrder.open(tmp_path, ['Loc.esm', 'Plain.esp'], 'starfield') as lo:
        thing = lo.resolve(FormKey('Loc.esm', 0x800))
        assert lo.display_name(thing) == 'Probe Widget'
        assert lo.display_name(thing, 'es') == 'Artilugio sonda'
        assert lo.display_name(lo.resolve(FormKey('Plain.esp', 0x800))) == 'Plain Widget'
        assert lo.text(thing, 'DESC') is None
