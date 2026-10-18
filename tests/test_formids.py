import pytest

from pyfield import FormKey, ResolutionError
from pyfield.core.formids import FormIdCodec, MasterRef, Unresolved

SF_MASTERS = [MasterRef('Starfield.esm', 'full'), MasterRef('sfbgs00d.esm', 'full'),
              MasterRef('SFBGS004.esm', 'small'), MasterRef('SFBGS047.esm', 'small'),
              MasterRef('sfbgs003.esm', 'medium'), MasterRef('SFBGS006.esm', 'medium')]


def test_formkey_text():
    k = FormKey.parse('00ABCD:Starfield.esm')
    assert k == FormKey('STARFIELD.ESM', 0xABCD) and str(k) == '00ABCD:starfield.esm'
    with pytest.raises(ValueError):
        FormKey.parse('nope')


def test_full_medium_small_namespaces():
    # mirrors kinggathcreations_spaceship.esm (observed 2026-10-14)
    c = FormIdCodec('Mod.esm', SF_MASTERS)
    assert c.decode(0x0000003B) == FormKey('starfield.esm', 0x3B)
    assert c.decode(0x0104DE0B) == FormKey('sfbgs00d.esm', 0x04DE0B)
    assert c.decode(0x0202B1CC) == FormKey('mod.esm', 0x02B1CC)          # ordinal own ID
    assert c.decode(0xFD000050) == FormKey('sfbgs003.esm', 0x50)
    assert c.decode(0xFD01ABCD) == FormKey('sfbgs006.esm', 0xABCD)
    assert c.decode(0xFE001123) == FormKey('sfbgs047.esm', 0x123)
    assert c.decode(0) is None
    for raw in (0x0000003B, 0x0104DE0B, 0x0202B1CC, 0xFD000050, 0xFD01ABCD, 0xFE001123):
        assert c.encode(c.decode(raw)) == raw


def test_out_of_range():
    c = FormIdCodec('Mod.esm', SF_MASTERS)
    with pytest.raises(ResolutionError):
        c.decode(0x03000001)
    with pytest.raises(ResolutionError):
        c.decode(0xFD020001)          # Mod.esm is full, so FD:02 is not itself
    assert c.try_decode(0x03000001) == Unresolved(0x03000001)
    with pytest.raises(ResolutionError):
        c.encode(FormKey('Other.esm', 1))
    with pytest.raises(ResolutionError):
        c.encode(FormKey('sfbgs004.esm', 0x1000))   # does not fit 12 bits


def test_compact_own_style_for_bethesda_medium_master():
    # sfta01.esm: masters starfield (full), sfbgs003 (medium); its own records are FD:01
    c = FormIdCodec('sfta01.esm', [MasterRef('starfield.esm', 'full'), MasterRef('sfbgs003.esm', 'medium')],
                    self_kind='medium', own_style='compact')
    assert c.decode(0xFD014607) == FormKey('sfta01.esm', 0x4607)
    assert c.decode(0x01004607) == FormKey('sfta01.esm', 0x4607)   # ordinal form also accepted
    assert c.encode(FormKey('sfta01.esm', 0x4607)) == 0xFD014607


def test_unknown_master_kind_is_an_assumption():
    c = FormIdCodec('Mod.esp', [MasterRef('Missing.esm')])
    assert not c.certain and c.decode(0x00000801).plugin == 'missing.esm'


def test_single_namespace_game_rejects_medium():
    with pytest.raises(ResolutionError):
        FormIdCodec('Mod.esp', [MasterRef('X.esm', 'medium')], namespaces=frozenset({'full'}))
