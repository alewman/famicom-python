"""The Vs. System: its machine rows, RGB PPUs, mainboard I/O, sockets and chips.

Sources as the code cites them: Vs._System.wiki, NES_2.0.wiki "Vs. System
Type", PPU_palettes.wiki, PPU_registers.wiki "2C05 identifier", Zapper.wiki,
INES_Mapper_099.wiki, MAME's vsnes.cpp for the protection chips. The game-level
cases need the images ``scripts/vs_images.py`` assembles (``VS_IMAGES_DIR``)
and skip without them.
"""

from __future__ import annotations

import os
import re
from itertools import pairwise
from pathlib import Path

import pytest

from famicom_python.apu import APU
from famicom_python.cartridge import load
from famicom_python.cartridge.namco import Namco108, VsProtected108
from famicom_python.cartridge.vs import VsSockets
from famicom_python.joypad import LEFT, RIGHT, SELECT, START, UP, A, B
from famicom_python.machine import MACHINES, NES_001, NTSC, VS_MACHINES, VS_PPUS, vs_machine
from famicom_python.system import System
from famicom_python.video import IMAGES, RGB_DAC, rgb_palette
from famicom_python.vs import VS_ZAPPER, VsStick, VsZapper, panel

WIKI = IMAGES.parent / "PPU_palettes.wiki"
VS_IMAGES = Path(os.environ.get("VS_IMAGES_DIR", "vs-images"))


def vs_image(
    program: bytes = b"\x4c\x00\x80",
    *,
    prg_size: int = 0x8000,
    chr_size: int = 0x4000,
    mapper: int = 99,
    ppu: int = 0,
    hardware: int = 0,
    expansion: int = 4,
) -> bytes:
    """An NES 2.0 Vs. System image: ``program`` at the reset vector, each 8 KiB
    of PRG ending in its bank number, each 8 KiB of CHR filled with its own."""
    prg = bytearray(prg_size)
    for bank in range(prg_size // 0x2000):
        prg[bank * 0x2000 + 0x1FF0] = bank
    start = 0x10000 - min(prg_size, 0x8000)
    top = min(prg_size, 0x8000)
    prg[top - 0x1000 : top - 0x1000 + len(program)] = program
    reset = start + top - 0x1000
    prg[top - 6 : top] = bytes((0, 0xF8, reset & 0xFF, reset >> 8, 0, 0xF8))
    chr_rom = b"".join(bytes([0xC0 + bank]) * 0x2000 for bank in range(chr_size // 0x2000))
    if prg_size % 0x4000:
        size_low, size_high = (prg_size.bit_length() - 1) << 2 | 0, 0x0F
        if prg_size == 0xA000:  # 40 KiB = 2^13 * 5
            size_low = 13 << 2 | 2
        elif prg_size == 0x6000:  # 24 KiB = 2^13 * 3
            size_low = 13 << 2 | 1
    else:
        size_low, size_high = prg_size // 0x4000, 0
    header = bytes(
        [
            0x4E, 0x45, 0x53, 0x1A, size_low, chr_size // 0x2000,
            (mapper & 0x0F) << 4 | 0x08, (mapper & 0xF0) | 0x09, mapper >> 8, size_high,
            0x05, 0, 0, hardware << 4 | ppu, 0, expansion,
        ]
    )  # fmt: skip
    return header + bytes(prg) + chr_rom


def vs_system(**kwargs) -> System:  # type: ignore[no-untyped-def]
    image = vs_image(**kwargs)
    loaded = load(image, use_database=False)
    system = System(loaded.cartridge, vs_machine(loaded.image.board.vs_ppu))
    system.loaded = loaded
    system.step()  # the reset sequence
    return system


def settle(system: System) -> None:
    """Two more cycles: a $4016 write's OUT lines move on the next put."""
    system.board.read_byte(0x0000)
    system.board.read_byte(0x0000)


# -- the machine rows --------------------------------------------------------


def test_the_header_names_the_console_and_its_ppu() -> None:
    board = load(vs_image(ppu=5, hardware=4), use_database=False).image.board
    assert (board.console, board.vs_ppu, board.vs_hardware) == (1, 5, 4)
    assert System.machine_for(vs_image(ppu=5)) is VS_MACHINES[5]
    assert System.machine_for(vs_image(ppu=0)) is MACHINES["vs"]
    assert System.machine_for(vs_image(ppu=7)) is MACHINES["vs"]  # a reserved number


def test_every_vs_ppu_has_a_row_and_a_colour_table() -> None:
    assert set(VS_PPUS) == {0, 2, 3, 4, 5, 8, 9, 10, 11}
    for number, (chip, timing) in VS_PPUS.items():
        machine = VS_MACHINES[number]
        assert machine.ppu_variant == chip and machine.timing is timing
        assert machine.cpu_variant == "RP2A03" and machine.vs_side == "secondary"
        assert timing.rgb and not timing.odd_frame_skip and not timing.oam_corruption
        assert timing.palette in RGB_DAC
        assert MACHINES["vs" if not number else "vs-" + chip.lower()] is machine
        assert timing.swapped_control == chip.startswith("RC2C05")


def test_the_home_consoles_are_untouched() -> None:
    assert NTSC.odd_frame_skip and NTSC.oam_corruption and not NTSC.rgb
    assert not NTSC.swapped_control and NTSC.identifier_mask == 0
    assert NES_001.vs_side is None and NES_001.apu_tables == "NTSC"


# -- the RGB PPUs ------------------------------------------------------------


def test_the_colour_tables_are_the_wikis() -> None:
    if not WIKI.exists():
        pytest.skip("PPU_palettes.wiki not fetched")
    text = WIKI.read_text(encoding="utf-8")
    start, end = text.index("=== 2C03 and 2C05 ==="), text.index("=== 2C05-99 ===")
    cells = re.findall(r"\|(\d{3})\n", text[start:end])
    assert tuple(int(cell, 8) for cell in cells) == RGB_DAC["RP2C03"]
    for number in range(1, 5):
        section = text[text.index(f"==== RP2C04-000{number} ====") :]
        rows = re.search(r"((?: \d{3}(?:,\d{3}){15}\n){4})", section)
        assert rows is not None
        values = tuple(int(cell, 8) for cell in re.findall(r"\d{3}", rows.group(1)))
        assert values == RGB_DAC[f"RP2C04-000{number}"]


def test_the_2c03_palette_is_the_pinned_file() -> None:
    path = IMAGES / "2C03_wiki.pal"
    if not path.exists():
        pytest.skip("2C03_wiki.pal not fetched")
    data = path.read_bytes()
    assert [data[i : i + 3] for i in range(0, len(data), 3)] == rgb_palette("RP2C03")


def test_the_four_2c04s_permute_one_master_palette() -> None:
    masters = {frozenset(RGB_DAC[f"RP2C04-000{n}"]) for n in range(1, 5)}
    assert len(masters) == 1
    assert len(next(iter(masters))) == 60  # the "60-color master palette"
    assert len({RGB_DAC[f"RP2C04-000{n}"] for n in range(1, 5)}) == 4


def test_emphasis_drives_its_channel_to_full_brightness() -> None:
    palette = rgb_palette("RP2C03")
    assert palette[0x16] == bytes((255, 0, 0)) and palette[0x00] == bytes((109, 109, 109))
    assert palette[0x40 | 0x00] == bytes((255, 109, 109))  # $2001 bit 5: red
    assert palette[0x80 | 0x00] == bytes((109, 255, 109))  # bit 6: green
    assert palette[0x100 | 0x0F] == bytes((0, 0, 255))  # bit 7: blue, even on black
    assert all(palette[0x1C0 | index] == b"\xff\xff\xff" for index in range(64))


def test_the_rc2c05_swaps_control_and_mask_and_returns_its_identifier() -> None:
    system = vs_system(ppu=10)  # RC2C05-03: $2002 AND $1F = $1C
    board, ppu = system.board, system.board.ppu
    ppu.resetting = False
    board.write_byte(0x2000, 0x1E)
    assert ppu.mask == 0x1E and ppu.ctrl == 0
    board.write_byte(0x2001, 0x04)
    assert ppu.ctrl == 0x04
    board.write_byte(0x2005, 0xFF)  # the I/O latch holds $FF
    assert board.read_byte(0x2002) & 0x1F == 0x1C
    assert board.read_byte(0x2000) & 0x1F == 0x1F  # the latch itself is untouched
    assert vs_system(ppu=11).board.read_byte(0x2002) & 0x1F == 0x1B
    assert vs_system(ppu=9).board.read_byte(0x2002) & 0x3F == 0x3D


def test_the_other_rgb_ppus_keep_their_registers() -> None:
    system = vs_system(ppu=5)
    board, ppu = system.board, system.board.ppu
    ppu.resetting = False
    board.write_byte(0x2000, 0x04)
    board.write_byte(0x2001, 0x1E)
    assert (ppu.ctrl, ppu.mask) == (0x04, 0x1E)
    board.write_byte(0x2005, 0xFF)
    assert board.read_byte(0x2002) & 0x1F == 0x1F


def frame_lengths(machine_name: str) -> set[int]:
    """Master ticks between frame starts with rendering on, over six frames."""
    program = bytes.fromhex("a9 08 8d 01 20 4c 00 f0")  # LDA #$08; STA $2001; JMP $F000
    loaded = load(vs_image(program), use_database=False)
    system = System(loaded.cartridge, MACHINES[machine_name])
    ppu, board = system.board.ppu, system.board
    system.run_frames(3)
    starts = []
    for _ in range(7):
        frame = ppu.frame
        while ppu.frame == frame:
            system.step()
        starts.append(board.t - (ppu.line * 341 + ppu.dot) * 4 - (board.t - ppu.time))
    return {b - a for a, b in pairwise(starts)}


def test_an_rgb_ppu_never_skips_the_odd_frames_dot() -> None:
    whole = 341 * 262 * 4
    assert frame_lengths("vs") == {whole}
    assert frame_lengths("nes") == {whole, whole - 4}


def test_rendering_switched_off_mid_line_corrupts_no_oam_on_an_rgb_ppu() -> None:
    for name, corrupts in (("vs", False), ("nes", True)):
        loaded = load(vs_image(), use_database=False)
        ppu = System(loaded.cartridge, MACHINES[name]).board.ppu
        ppu.resetting = False
        ppu.write_register(1, 0x18)
        ppu.run_to(ppu.time + (341 * 10 + 100) * 4)
        ppu.write_register(1, 0x00)
        assert (ppu._oam_corrupt is not None) == corrupts


# -- the letterless RP2A03 ---------------------------------------------------


def test_the_letterless_2a03_has_no_tonal_noise_and_a_shorter_lowest_period() -> None:
    old, new = APU(tables="RP2A03"), APU()
    for apu in (old, new):
        apu.write(0x400E, 0x8F)
    assert (old.noise.mode_bit, new.noise.mode_bit) == (1, 6)
    assert old.noise.period == 2046 // 2 - 1 and new.noise.period == 4068 // 2 - 1
    old.write(0x400E, 0x0E)
    new.write(0x400E, 0x0E)
    assert old.noise.period == new.noise.period


def test_reset_leaves_the_letterless_frame_counter_alone() -> None:
    old, new = APU(tables="RP2A03"), APU()
    for apu in (old, new):
        apu.power()
        for _ in range(1000):
            apu.clock()
        apu.reset()
    assert new.pending_frame_write is not None  # $4017 rewritten: the counter restarts
    assert old.pending_frame_write is None


# -- the mainboard's ports ---------------------------------------------------


def test_4016_and_4017_carry_the_switches_and_drive_every_line() -> None:
    system = vs_system()
    board, vs = system.board, system.board.vs
    board.data_bus = 0xFF
    # D7: a UniSystem game's CPU is the secondary side's (C75).
    assert board.read_byte(0x4016) == 0x80 and board.read_byte(0x4017) == 0x00
    vs.side = "primary"
    assert board.read_byte(0x4016) == 0x00
    vs.dip = 0b0000_0001  # switch 1: $4016 D3
    assert board.read_byte(0x4016) == 0x08
    vs.dip = 0b0000_0010  # switch 2: $4016 D4
    assert board.read_byte(0x4016) == 0x10
    vs.dip = 0b1111_1100  # switches 3-8: $4017 D2-D7
    assert board.read_byte(0x4016) == 0x00 and board.read_byte(0x4017) == 0xFC
    vs.dip = 0
    vs.service = True
    assert board.read_byte(0x4016) == 0x04
    assert MACHINES["famicom"].vs_side is None


def test_a_coin_is_a_pulse_of_about_fifty_milliseconds() -> None:
    system = vs_system()
    board = system.board
    system.insert_coin()
    assert board.read_byte(0x4016) & 0x60 == 0x20
    system.run_cycles(round(0.040 * 1_789_773))
    assert board.read_byte(0x4016) & 0x60 == 0x20
    system.run_cycles(round(0.011 * 1_789_773))
    assert board.read_byte(0x4016) & 0x60 == 0x00
    system.insert_coin(1)  # the second acceptor is its own bit
    assert board.read_byte(0x4016) & 0x60 == 0x40
    with pytest.raises(ValueError):
        System.from_rom(vs_image(), MACHINES["famicom"]).insert_coin()


def test_the_sticks_report_as_controllers_do() -> None:
    system = vs_system()
    board = system.board
    board.pads[0].buttons = A | SELECT  # the right stick's A, and panel button 1
    board.pads[1].buttons = B
    board.write_byte(0x4016, 1)
    settle(system)
    board.write_byte(0x4016, 0)
    settle(system)

    def bits(address: int) -> list[int]:
        report = []
        for _ in range(8):
            report.append(board.read_byte(address) & 1)
            board.read_byte(0x0000)  # /OE rises: the register shifts
        return report

    right, left = bits(0x4016), bits(0x4017)
    assert right == [1, 0, 1, 0, 0, 0, 0, 0] and left == [0, 1, 0, 0, 0, 0, 0, 0]


def test_the_panel_puts_player_one_where_the_game_reads() -> None:
    pads = [VsStick(), VsStick()]
    panel(pads, [A | START | LEFT, B | SELECT], first_on_4017=False)
    assert pads[0].buttons == A | START | LEFT and pads[1].buttons == B | SELECT
    panel(pads, [A | START | LEFT, B | SELECT], first_on_4017=True)
    # The sticks change sides; buttons 1 and 3 stay on $4016, 2 and 4 on $4017.
    assert pads[1].buttons == A | LEFT | SELECT and pads[0].buttons == B | START


def test_the_protection_jumper_holds_the_fourth_bit() -> None:
    system = System.from_rom(vs_image(hardware=4), vs_machine(0))
    assert [pad.jumper for pad in system.board.pads] == [START, START]
    assert System.from_rom(vs_image(), vs_machine(0)).board.pads[0].jumper == 0
    stick = VsStick(START)
    stick.set_strobe(True)
    stick.set_strobe(False)
    bits = []
    for _ in range(8):
        bits.append(stick.read())
        stick.clock()
    assert bits == [0, 0, 0, 1, 0, 0, 0, 0]


def test_the_vs_zapper_reports_through_the_shift_register() -> None:
    system = System.from_rom(vs_image(expansion=VS_ZAPPER), vs_machine(0))
    gun = system.plug()
    assert isinstance(gun, VsZapper) and system.board.pads[0] is gun

    def report() -> int:
        gun.set_strobe(True)
        gun.set_strobe(False)
        value = 0
        for bit in range(8):
            value |= gun.read() << bit
            gun.clock()
        return value

    assert report() == UP  # 0, 0, 0, 0, 1, 0, light, trigger
    gun.trigger = True
    assert report() == UP | RIGHT
    gun.trigger = False
    ppu = system.board.ppu
    gun.aim = (128, 120)
    ppu.picture[120 * 256 + 128] = 0x20  # white, just drawn
    ppu.line, ppu.dot = 121, 0
    assert report() == UP | LEFT  # light sense is 1 when detecting, unlike the NES gun


def test_the_coin_counter_counts_falling_edges_anywhere_in_4020_5fff() -> None:
    system = vs_system()
    board, vs = system.board, system.board.vs
    board.write_byte(0x4020, 1)
    assert vs.coin_counter == 1 and vs.coins_counted == 0
    board.write_byte(0x5FFF, 0)
    assert vs.coin_counter == 0 and vs.coins_counted == 1
    board.write_byte(0x4020, 1)
    board.data_bus = 0x40  # "reading from the register effectively writes ... open bus"
    assert board.read_byte(0x4020) == 0x40
    assert vs.coins_counted == 2
    board.write_byte(0x4020, 1)
    system.reset()
    assert vs.coin_counter == 0


def test_the_ram_at_6000_is_two_kilobytes_mirrored() -> None:
    system = vs_system()
    board = system.board
    board.write_byte(0x6123, 0x5A)
    assert [board.read_byte(a) for a in (0x6123, 0x6923, 0x7123, 0x7923)] == [0x5A] * 4
    board.write_byte(0x7FFF, 0xA5)
    assert board.read_byte(0x67FF) == 0xA5


def test_the_ram_is_the_mainboards_whatever_the_daughterboard() -> None:
    # Mapper 206 has no RAM of its own and MMC1 can switch its own off.
    for mapper in (206, 1, 2, 67, 75):
        system = vs_system(mapper=mapper, prg_size=0x10000, chr_size=0x8000)
        system.board.write_byte(0x6000, 0x77)
        assert system.board.read_byte(0x6800) == 0x77, mapper


def test_every_vs_mapper_has_four_screens() -> None:
    for mapper in (99, 1, 2, 67, 75, 206):
        image = bytearray(vs_image(mapper=mapper, prg_size=0x10000, chr_size=0x8000))
        image[6] |= 0x08  # four-screen: every Vs. image's header says so
        cartridge = load(bytes(image), use_database=False).cartridge
        for table in range(4):
            assert cartridge.ciram_a10(0x2000 + table * 0x400) is None
            cartridge.ppu_write(0x2000 + table * 0x400, table + 1, 0)
        assert [cartridge.ppu_read(0x2000 + t * 0x400, 0) for t in range(4)] == [1, 2, 3, 4]


def test_a_save_state_keeps_the_mainboard() -> None:
    from famicom_python.state import load_state, save_state

    # LDA $4016; STA $6000; INC $6001; JMP $F000
    image = vs_image(bytes.fromhex("ad 16 40 8d 00 60 ee 01 60 4c 00 f0"), ppu=5)
    first = System.from_rom(image, vs_machine(5))
    first.run_cycles(5000)
    first.insert_coin()
    first.board.vs.dip = 0x41
    first.run_cycles(100)
    second = System.from_rom(image, vs_machine(5))
    load_state(second, save_state(first))
    for system in (first, second):
        system.run_cycles(200_000)  # past the coin's 50 ms
    one, two = first.board.vs, second.board.vs
    assert first.board.t == second.board.t and one.ram.data == two.ram.data
    assert (one.dip, one.coins, one.coin_counter) == (two.dip, two.coins, two.coin_counter)
    assert one.ram.data[1] != 0


# -- mapper 99 ---------------------------------------------------------------


def test_out2_selects_the_chr_socket() -> None:
    system = vs_system()
    board, cartridge = system.board, system.cartridge
    assert isinstance(cartridge, VsSockets)
    assert cartridge.ppu_read(0x0000, 0) == 0xC0
    board.write_byte(0x4016, 0x04)
    settle(system)
    assert cartridge.ppu_read(0x0000, 0) == 0xC1 and cartridge.ppu_read(0x1FFF, 0) == 0xC1
    board.write_byte(0x4016, 0x00)
    settle(system)
    assert cartridge.ppu_read(0x0000, 0) == 0xC0


def test_an_empty_chr_socket_drives_nothing() -> None:
    system = vs_system(chr_size=0x2000)
    system.board.write_byte(0x4016, 0x04)
    settle(system)
    assert system.cartridge.ppu_read(0x0000, 0) is None


def test_a_24k_image_lies_at_a000_and_8000_is_open_bus() -> None:
    cartridge = load(vs_image(prg_size=0x6000), use_database=False).cartridge
    assert cartridge.cpu_read(0x8000, 0) is None and cartridge.cpu_read(0x9FFF, 0) is None
    assert [cartridge.cpu_read(a, 0) for a in (0xBFF0, 0xDFF0, 0xFFF0)] == [0, 1, 2]


def test_gumshoes_fifth_bank_follows_out2() -> None:
    system = vs_system(prg_size=0xA000)
    board, cartridge = system.board, system.cartridge
    assert [cartridge.cpu_read(a, 0) for a in (0x9FF0, 0xBFF0, 0xDFF0, 0xFFF0)] == [0, 1, 2, 3]
    board.write_byte(0x4016, 0x04)
    settle(system)
    assert [cartridge.cpu_read(a, 0) for a in (0x9FF0, 0xBFF0, 0xDFF0, 0xFFF0)] == [4, 1, 2, 3]


# -- the daughterboards' protection chips -----------------------------------


def test_the_namco_108_boards_get_their_chips_by_hardware_type() -> None:
    def board_for(hardware: int) -> Namco108:
        image = vs_image(mapper=206, prg_size=0x10000, chr_size=0x8000, hardware=hardware)
        cartridge = load(image, use_database=False).cartridge
        assert isinstance(cartridge, Namco108)
        return cartridge

    assert type(board_for(0)) is Namco108 and board_for(0).cpu_read(0x5E01, 0) is None
    rbi = board_for(1)
    assert isinstance(rbi, VsProtected108)
    assert rbi.cpu_read(0x5E00, 0) == 0
    assert [rbi.cpu_read(0x5E01, 0) for _ in range(4)] == [0xFF, 0xFD, 0xF5, 0xF4]
    assert rbi.cpu_read(0x5600, 0) == 0 and rbi.cpu_read(0x5601, 0) == 0xFF  # A11 not decoded
    assert rbi.cpu_read(0x5E02, 0) is None
    tko = board_for(2)
    assert tko.cpu_read(0x5E00, 0) == 0
    assert [tko.cpu_read(0x5E01, 0) for _ in range(3)] == [0xFF, 0xBF, 0xB7]
    assert tko.cpu_read(0x5601, 0) is None
    for _ in range(29):
        tko.cpu_read(0x5E01, 0)
    assert tko.cpu_read(0x5E01, 0) == 0xFF  # the 32 bytes come round
    xevious = board_for(3)
    assert [xevious.cpu_read(a, 0) for a in (0x5678, 0x578F, 0x5567)] == [0x00, 0xD1, 0x3E]
    assert xevious.cpu_read(0x54FF, 0) == 0x05
    assert [xevious.cpu_read(a, 0) for a in (0x5678, 0x578F, 0x5567)] == [0x01, 0x89, 0x37]
    assert xevious.cpu_read(0xFFF0, 0) is not None


def test_a_protected_board_still_sees_the_coin_counter() -> None:
    system = vs_system(mapper=206, prg_size=0x10000, chr_size=0x8000, hardware=2)
    board = system.board
    board.write_byte(0x4020, 1)
    board.data_bus = 0x5E  # as LDA $5E00 leaves it: the address's high byte
    assert board.read_byte(0x5E00) == 0  # the chip answers; the read clocked the latch
    assert system.board.vs.coins_counted == 1


# -- the games ---------------------------------------------------------------


def game(name: str) -> System:
    path = VS_IMAGES / name
    if not path.exists():
        pytest.skip("Vs. images not assembled: scripts/vs_images.py (VS_IMAGES_DIR)")
    system = System.from_rom(path, System.machine_for(path))
    system.plug()
    return system


@pytest.mark.slow
def test_super_mario_bros_takes_a_coin_and_starts() -> None:
    system = game("Vs. Super Mario Bros. (SM4-4 E).nes")
    assert system.machine is VS_MACHINES[5] and isinstance(system.cartridge, VsSockets)
    system.run_frames(200)
    attract = bytes(system.board.ppu.picture)
    assert len(set(attract)) > 4  # a title screen, not a blank one
    system.insert_coin()
    system.run_frames(30)
    assert system.board.vs.coins_counted == 1  # the game saw it and pulsed the meter
    waiting = system.board.ram[0x0770]  # the game's mode byte, with a credit
    system.board.pads[0].buttons = SELECT  # panel button 1: one player
    system.run_frames(8)
    system.board.pads[0].buttons = 0
    system.run_frames(240)
    assert system.board.ram[0x0770] != waiting  # it left the title for World 1-1
    assert bytes(system.board.ppu.picture) != attract


@pytest.mark.slow
def test_a_2c05_game_boots_only_with_its_ppu() -> None:
    system = game("Vs. Gumshoe.nes")
    assert system.machine is VS_MACHINES[10]
    system.run_frames(120)
    assert len(set(system.board.ppu.picture)) > 4
