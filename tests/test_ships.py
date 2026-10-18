"""Ship blueprint parts (BUO4) and module choice for captured ships."""
import math
import struct

from pyfield.core.formids import FormKey
from pyfield.games.starfield.ships import (PART, BlueprintPart, _clean_angle, blueprint_fields, choose_module,
                                           decode_buo4, encode_buo4)


class Codec:
    def decode(self, raw):
        return FormKey('Starfield.esm', raw & 0xFFFFFF)

    def encode(self, key):
        return key.local_id


def test_buo4_roundtrip_and_layout():
    parts = [BlueprintPart(FormKey('Starfield.esm', 0x27000F), (-0.11, 19.62, 0.40), (0.0, 0.0, 0.0), 0),
             BlueprintPart(FormKey('Starfield.esm', 0x226682), (-4.84, 12.02, -2.27), (0.0, math.pi / 4, 0.0), 20)]
    data = encode_buo4(parts, Codec())
    assert len(data) == 2 * PART.size == 72
    assert struct.unpack_from('<I', data, 0)[0] == 0x27000F and struct.unpack_from('<I', data, 68)[0] == 20
    back = decode_buo4(data, Codec())
    assert [p.module for p in back] == [p.module for p in parts]
    assert all(abs(a - b) < 1e-6 for p, q in zip(back, parts) for a, b in zip(p.position + p.rotation,
                                                                               q.position + q.rotation))
    fields = blueprint_fields(parts, Codec())
    assert [f.signature for f in fields] == ['BUO4', 'BODM', 'BODC', 'BODC', 'BLUF', 'BOID']
    assert struct.unpack('<I', fields[1].data)[0] == 2 and struct.unpack('<I', fields[-1].data)[0] == 21


def test_module_choice_by_player_level():
    a, b, c = (FormKey('Starfield.esm', i) for i in (1, 2, 3))
    shields = [(a, 'SMC_Shields_X_SG-1000_lvl24'), (b, 'SMC_Shields_X_SG-3000_lvl62'),
               (c, 'SMC_Shields_X_SG-4000_lvl84')]
    assert choose_module(shields, 70) == (shields[1], 'level')
    assert choose_module(shields, 10) == (shields[2], 'level')         # nothing usable: highest overall
    assert choose_module([shields[0]], 1) == (shields[0], 'exact')
    retired = [(a, 'xDoNotUse_SMC_Reactor_DC405_lvl98'), (b, 'SMC_Reactor_DC403_lvl62')]
    assert choose_module(retired, 114)[0] == retired[1]
    cargo = [(a, 'SMS_CargoShielded_Sextant_10ST_Hauler_Fore_Experimental'), (b, 'SMS_Cargo_Sextant_10T_Hauler_Fore')]
    assert choose_module(cargo, 114)[0] == cargo[1]
    assert _clean_angle(2 * math.pi + 1e-5) == 0.0 and abs(_clean_angle(7 * math.pi / 4) + math.pi / 4) < 1e-4
