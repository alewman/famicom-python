"""Save states (state.py): a run saved and loaded continues exactly as the one that wasn't.

The quick tests use small test ROMs; scripts/state_roundtrip.py runs the same check
on a dump of every mapper class.
"""

from __future__ import annotations

import zlib

import pytest
from conftest import ROMS, rom

from famicom_python.machine import MACHINES
from famicom_python.state import StateError, load_state, save_state
from famicom_python.system import System


def _trace(system: System, frames: int) -> list[tuple]:
    out = []
    for _ in range(frames):
        system.run_frames(1)
        cpu, ppu = system.cpu, system.board.ppu
        out.append(
            (
                bytes(ppu.picture),
                tuple(system.take_samples()),
                (cpu.a, cpu.x, cpu.y, cpu.s, cpu.pc, cpu.p),
                (ppu.v, ppu.t, ppu.status, ppu.line, ppu.dot),
                system.board.t,
                bytes(system.board.ram),
            )
        )
    return out


@pytest.mark.parametrize(
    ("path", "machine"),
    [
        ("sprite_hit_tests_2005.10.05/01.basics.nes", "nes"),  # NROM
        ("instr_test-v5/rom_singles/01-basics.nes", "nes"),  # MMC1, PRG-RAM
        ("mmc3_test_2/rom_singles/4-scanline_timing.nes", "nes"),  # MMC3's IRQ
        ("pal_apu_tests/01.len_ctr.nes", "pal"),
        ("apu_mixer/dmc.nes", "famicom"),
    ],
)
def test_a_loaded_state_continues_as_the_run(path: str, machine: str) -> None:
    rom(path)
    data = (ROMS / path).read_bytes()
    first = System.from_rom(data, MACHINES[machine])
    first.run_frames(40)
    first.run_cycles(12_345)  # mid-frame
    state = save_state(first)
    expected = _trace(first, 30)

    second = System.from_rom(data, MACHINES[machine])
    second.run_frames(7)  # loading overwrites, it does not rely on power-on values
    load_state(second, state)
    assert _trace(second, 30) == expected


def test_a_state_is_refused_by_another_cartridge_or_machine() -> None:
    rom("instr_test-v5/rom_singles/01-basics.nes")
    rom("sprite_hit_tests_2005.10.05/01.basics.nes")
    one = System.from_rom((ROMS / "instr_test-v5/rom_singles/01-basics.nes").read_bytes())
    state = save_state(one)
    other = System.from_rom((ROMS / "sprite_hit_tests_2005.10.05/01.basics.nes").read_bytes())
    with pytest.raises(StateError, match="another cartridge"):
        load_state(other, state)
    pal = System.from_rom(
        (ROMS / "instr_test-v5/rom_singles/01-basics.nes").read_bytes(), MACHINES["pal"]
    )
    with pytest.raises(StateError, match="not the"):
        load_state(pal, state)
    with pytest.raises(StateError, match="not a save state"):
        load_state(one, b"not a state")


def test_a_state_holds_no_code() -> None:
    """Loading creates only this package's classes: a state naming another is refused."""
    rom("instr_test-v5/rom_singles/01-basics.nes")
    system = System.from_rom((ROMS / "instr_test-v5/rom_singles/01-basics.nes").read_bytes())
    state = zlib.decompress(save_state(system)).decode()
    forged = state.replace(
        '"apu":{"object":"famicom_python.apu.APU"', '"apu":{"object":"os.system"', 1
    )
    assert forged != state
    with pytest.raises(StateError):
        load_state(system, zlib.compress(forged.encode()))
