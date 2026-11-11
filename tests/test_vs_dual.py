"""The Vs. DualSystem: two sides of one mainboard on one clock (dual.py).

Vs._System.wiki for the shared RAM, the cross interrupt and the watchdog;
NES_2.0.wiki for how an image is split between the sides. The game-level case
needs the images ``scripts/vs_images.py`` assembles (``VS_IMAGES_DIR``).
"""

from __future__ import annotations

import pytest
from test_vs_system import VS_IMAGES, settle, vs_image

from famicom_python.cartridge import load
from famicom_python.dual import VsDualSystem, is_dual, split


def dual_image(first: bytes, second: bytes, chr_size: int = 0x8000) -> bytes:
    """A DualSystem image: two 32 KiB programs (hardware type 5)."""
    one = vs_image(first, hardware=5, chr_size=chr_size)
    two = vs_image(second, hardware=5, chr_size=chr_size)
    header = bytearray(one[:16])
    header[4] = 4  # 64 KiB of PRG
    return bytes(header) + one[16 : 16 + 0x8000] + two[16 : 16 + 0x8000] + one[16 + 0x8000 :]


SPIN = bytes.fromhex("4c 00 f0")  # JMP $F000
FEED = bytes.fromhex("ad 17 40 4c 00 f0")  # LDA $4017; JMP $F000


def dual(first: bytes = FEED, second: bytes = FEED, **kwargs):  # type: ignore[no-untyped-def]
    system = VsDualSystem.from_rom(dual_image(first, second, **kwargs))
    for side in system.sides:
        side.step()  # the reset sequence
    return system


def test_a_dual_image_is_split_between_the_sides() -> None:
    image = load(dual_image(SPIN, FEED), use_database=False).image
    first, second = split(image)
    assert len(first.prg) == len(second.prg) == 0x8000
    assert first.prg[0x7000:0x7003] == SPIN and second.prg[0x7000:0x7003] == FEED[:3]
    assert first.chr == bytes([0xC0]) * 0x2000 + bytes([0xC1]) * 0x2000
    assert second.chr == bytes([0xC2]) * 0x2000 + bytes([0xC3]) * 0x2000
    shared = split(load(dual_image(SPIN, FEED, chr_size=0x4000), use_database=False).image)
    assert shared[0].chr == shared[1].chr and len(shared[0].chr) == 0x4000
    assert is_dual(dual_image(SPIN, FEED)) and not is_dual(vs_image())
    # Raid on Bungeling Bay: 32 KiB for the game, the secondary side; 8 KiB at $E000.
    raid = load(vs_image(prg_size=0xA000, hardware=6), use_database=False).image
    primary, secondary = split(raid)
    assert (len(primary.prg), len(secondary.prg)) == (0x2000, 0x8000)


def test_each_side_answers_its_own_d7() -> None:
    system = dual()
    assert system.primary.board.read_byte(0x4016) & 0x80 == 0x00
    assert system.secondary.board.read_byte(0x4016) & 0x80 == 0x80


def test_the_primary_sides_out1_hands_the_ram_over() -> None:
    system = dual()
    first, second = system.primary.board, system.secondary.board
    second.write_byte(0x6000, 0x22)  # out of reset the secondary side has it
    first.write_byte(0x6000, 0x11)  # ... and the primary side writes nowhere
    assert second.read_byte(0x6000) == 0x22
    first.data_bus = 0x60
    assert first.read_byte(0x6000) == 0x60  # open bus
    first.write_byte(0x4016, 0x02)
    settle(system.primary)
    assert first.read_byte(0x6000) == 0x22
    second.data_bus = 0x60
    assert second.read_byte(0x6000) == 0x60
    second.write_byte(0x4016, 0x02)  # "the secondary CPU has no direct control"
    settle(system.secondary)
    assert system.ram.owner == "primary"
    first.write_byte(0x4016, 0x00)
    settle(system.primary)
    assert system.ram.owner == "secondary"


def test_each_sides_out1_is_the_other_sides_irq() -> None:
    system = dual()
    first, second = system.primary.board, system.secondary.board
    assert first.external_irq and second.external_irq  # both OUT1s are 0 out of reset
    first.write_byte(0x4016, 0x02)
    settle(system.primary)
    assert first.external_irq and not second.external_irq
    second.write_byte(0x4016, 0x02)
    settle(system.secondary)
    assert not first.external_irq
    first.write_byte(0x4016, 0x00)  # "when 0: asserts an IRQ request"
    settle(system.primary)
    assert second.external_irq


def test_the_two_sides_run_on_one_clock() -> None:
    system = dual()
    system.run_frames(3)
    first, second = system.primary.board, system.secondary.board
    assert first.ppu.frame == second.ppu.frame
    assert abs(first.t - second.t) <= 7 * 12  # within an instruction
    assert system.watchdog_resets == 0


def test_the_watchdog_resets_both_sides_when_the_secondary_stops_reading_4017() -> None:
    system = dual(FEED, SPIN)
    system.run_frames(90)  # 1.5 s
    assert system.watchdog_resets == 1
    assert dual(SPIN, FEED).watchdog_resets == 0


@pytest.mark.slow
def test_balloon_fight_runs_on_both_screens() -> None:
    path = VS_IMAGES / "Vs. Balloon Fight.nes"
    if not path.exists():
        pytest.skip("Vs. images not assembled: scripts/vs_images.py (VS_IMAGES_DIR)")
    system = VsDualSystem.from_rom(path)
    system.run_frames(300)
    assert system.watchdog_resets == 0
    assert all(len(set(picture)) > 3 for picture in system.pictures)


def test_a_dualsystem_game_opens_both_screens(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import os

    pygame = pytest.importorskip("pygame")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from famicom_python.frontend import Frontend

    rom = tmp_path / "dual.nes"
    rom.write_bytes(dual_image(FEED, FEED))
    pygame.display.init()
    try:
        frontend = Frontend(pygame, rom, "auto", None, 1, False, False, dip=0x04)
        assert frontend.dual is not None and frontend.system is frontend.dual.primary
        assert frontend.window.get_size() == (512, 240)
        assert [side.board.vs.dip for side in frontend.dual.sides] == [0x04, 0x04]
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_7))
        frontend.run(max_frames=2)
        assert frontend.dual.secondary.board.vs.coins[0]
        assert frontend.dual.secondary.board.ppu.frame == frontend.system.board.ppu.frame
    finally:
        pygame.quit()
