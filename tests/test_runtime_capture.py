"""Runtime captures written by sfse/PyFieldCapture -> FormKeys and blueprints."""
import json
import math

from pyfield.core.formids import FormKey
from pyfield.scene import ConversionReport, RuntimeCapture


def ref(form_id, base, base_type, pos, rot=(0, 0, 0), sections=('workshop_items',), created=True, edid=''):
    return {'form_id': f'{form_id:08X}', 'type': 74, 'created': created, 'disabled': False, 'deleted': False,
            'base': {'form_id': f'{base:08X}', 'type': 0, 'type_name': base_type, 'editor_id': edid},
            'cell': None, 'pos': list(pos), 'rot': list(rot), 'scale': 1.0,
            'sections': list(sections), 'extra_types': []}


CAPTURE = {
    'format': 'pyfield-capture', 'format_version': 1, 'name': 'Selene', 'kind': 'outpost',
    'captured_utc': '2026-10-16T10:00:00Z',
    'load_order': {'full': ['Starfield.esm', 'Constellation.esm'], 'small': ['Light.esm'], 'medium': ['Mid.esm']},
    'anchor': ref(0x0012AB, 0x054321, 'ACTI', (100.0, 200.0, 10.0), (0, 0, math.pi / 2), ('anchor',), False),
    'refs': [
        ref(0xFF000A01, 0x0002F00D, 'STAT', (101.0, 200.0, 10.0), edid='OutpostWall'),
        ref(0xFF000A02, 0xFE000123, 'STAT', (100.0, 202.0, 10.0)),
        ref(0xFF000A03, 0xFD000456, 'ACTI', (100.0, 200.0, 11.0)),
        ref(0xFF000A04, 0xFF0099AA, 'STAT', (90.0, 200.0, 10.0)),           # base created in the save
        ref(0x00000014, 0x00000007, 'NPC_', (100.0, 200.0, 10.0)),           # the player: never captured
        ref(0x01000B00, 0x01000C00, 'STAT', (0, 0, 0), sections=('workshop_cell',), created=False),
    ],
}


def test_runtime_formids_resolve_through_the_captured_load_order():
    cap = RuntimeCapture.from_dict(CAPTURE)
    assert cap.form_key(0x0002F00D) == FormKey('Starfield.esm', 0x02F00D)
    assert cap.form_key(0x01000C00) == FormKey('Constellation.esm', 0x000C00)
    assert cap.form_key(0xFE000123) == FormKey('Light.esm', 0x123)
    assert cap.form_key(0xFD000456) == FormKey('Mid.esm', 0x0456)
    assert cap.form_key(0xFF0099AA) is None
    assert cap.form_key(0x05000001) is None


def test_capture_to_blueprint_is_anchor_relative_and_reports_skips(tmp_path):
    path = tmp_path / 'Selene.json'
    path.write_text(json.dumps(CAPTURE), encoding='utf-8')
    cap = RuntimeCapture.load(path)
    report = ConversionReport()
    bp = cap.to_blueprint(sections={'workshop_items'}, report=report)
    assert [n.base for n in bp.nodes] == [FormKey('Starfield.esm', 0x02F00D), FormKey('Light.esm', 0x123),
                                          FormKey('Mid.esm', 0x456)]
    assert report.placed == 3 and report.skipped == [(0xFF000A04, 'base created in save')]
    wall = bp.nodes[0]
    assert wall.id == 'OutpostWall_FF000A01'
    # 1 m east of an anchor turned 90 degrees: the local offset lies on one horizontal axis, length 1
    x, y, z = wall.transform.position
    assert abs(math.hypot(x, y) - 1.0) < 1e-6 and abs(z) < 1e-6 and min(abs(x), abs(y)) < 1e-6
    assert cap.summary()['sections']['workshop_items'] == 5
    everything = cap.to_blueprint()
    assert len(everything.nodes) == 4                    # player skipped, created base skipped


def test_linked_refs_and_source_packin_from_extras():
    from pyfield.scene.runtime import RuntimeRef
    d = {'form_id': 'FF000010', 'base': {'form_id': '00000034'}, 'pos': [0, 0, 0], 'rot': [0, 0, 0],
         'extras': [[76, '00' * 16, {'direct': [None, None], 'array_count_at': 32,
                                     'array': ['00054BA6', 'FF000001', None, 'FF000020']}],
                    [212, '00' * 16, '0009D6E2', {'direct': ['0009D6E2', None]}]]}
    r = RuntimeRef.from_dict(d)
    assert r.linked_refs == [(0x54BA6, 0xFF000001), (None, 0xFF000020)]
    assert r.source_packin == 0x9D6E2 and r.extra_types == (76, 212)
