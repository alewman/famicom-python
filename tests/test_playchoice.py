"""The PlayChoice-10: its game board's row and panel, the security PROM, the
supervisor's memory, ports, screen, interrupt and watchdog, and the cabinet's
lines to the game.

Sources as the code cites them: Nintendo's PCH1-CPU schematic, MAME's
playch10.cpp and rp5h01.cpp, PC10_ROM-Images.wiki, NES_2.0.wiki. The quick
cases run a few bytes of Z80 code in place of the BIOS; the cases with the
real BIOS and a game need MAME's ``playch10`` set (``FAMICOM_PC10_BIOS``) and
the images ``scripts/pc10_images.py`` assembles (``PC10_IMAGES_DIR``), and
skip without them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from famicom_python.cartridge import load
from famicom_python.joypad import DOWN, LEFT, RIGHT, SELECT, START, UP, A, B
from famicom_python.machine import MACHINES, NTSC
from famicom_python.playchoice import (
    COUNTER_OUT,
    PlayChoiceGun,
    PlayChoicePad,
    game_roms,
)
from famicom_python.state import load_state, save_state
from famicom_python.supervisor import (
    BUP_KEY,
    CHANNEL,
    COIN_1,
    COIN_2,
    CSEL0,
    DISP_MASK,
    DOG_DI,
    ENTER,
    GAME_RES,
    GAME_STOP,
    INT_DETECT,
    PPU_RES,
    RP5H01,
    SDCS,
    Z80_HZ,
    Bios,
    PlayChoice,
    Supervisor,
    bios_path,
    load_bios,
)
from famicom_python.system import System

PC10_IMAGES = Path(os.environ.get("PC10_IMAGES_DIR", "pc10-images"))
PROM = bytes(range(0x11, 0x21))
INST = bytes([0xC3, 0x00, 0xC0]) + bytes(0x1FFD)


def pc10_image(program: bytes = b"\x4c\x00\xf0", *, misc: bytes | None = None, device: int = 1):
    """An NES 2.0 PlayChoice-10 image (NROM): ``program`` at $F000, the reset
    vector on it, NMI and IRQ on an RTI at $F800."""
    prg = bytearray(0x8000)
    prg[0x7000 : 0x7000 + len(program)] = program
    prg[0x7800] = 0x40  # RTI
    prg[0x7FFA:] = bytes((0x00, 0xF8, 0x00, 0xF0, 0x00, 0xF8))
    if misc is None:
        misc = INST + PROM + COUNTER_OUT
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 2, 1, 0, 0x0A, 0, 0, 0, 0, 0, 0, 3, device])
    return header + bytes(prg) + bytes(0x2000) + misc


def bios(program: bytes = b"\x18\xfe", nmi: bytes = b"\xed\x45") -> Bios:
    """A BIOS of a few bytes: ``program`` at 0, ``nmi`` at $0066; character 1
    has every pixel 7, character 2 every pixel 1; each PROM holds its index's
    low nibble, inverted (so a colour's channel is the index's weights)."""
    rom = bytearray(0x4000)
    rom[: len(program)] = program
    rom[0x66 : 0x66 + len(nmi)] = nmi
    solid = bytes(8) + b"\xff" * 8 + bytes(0x2000 - 16)
    low = bytes(8) + b"\xff" * 16 + bytes(0x2000 - 24)
    proms = tuple(bytes(~i & 0x0F for i in range(256)) for _ in range(3))
    return Bios("dual", bytes(rom), (solid, solid, low), proms)  # type: ignore[arg-type]


def cabinet(z80: bytes = b"\x18\xfe", game: bytes = b"\x4c\x00\xf0", **kwargs) -> PlayChoice:  # type: ignore[no-untyped-def]
    loaded = load(pc10_image(game), use_database=False)
    return PlayChoice(loaded, bios(z80, **kwargs))


# -- the game board ----------------------------------------------------------


def test_console_type_2_is_the_playchoice_row() -> None:
    machine = System.machine_for(pc10_image())
    assert machine is MACHINES["playchoice"] and machine.playchoice
    assert machine.cpu_variant == "RP2A03E" and machine.ppu_variant == "RP2C03B"
    timing = machine.timing
    assert timing.rgb and not timing.odd_frame_skip and timing.palette == "RP2C03"
    assert (timing.master_hz, timing.cpu_divider, timing.lines) == (
        NTSC.master_hz,
        NTSC.cpu_divider,
        NTSC.lines,
    )


def test_the_image_keeps_the_inst_rom_and_the_prom() -> None:
    roms = game_roms(load(pc10_image(), use_database=False).image)
    assert roms is not None
    assert (roms.inst, roms.prom, roms.counter_out) == (INST, PROM, COUNTER_OUT)
    # An older dump: the INST ROM alone.
    old = game_roms(load(pc10_image(misc=INST), use_database=False).image)
    assert old is not None and old.prom is None and old.inst == INST
    assert game_roms(load(pc10_image(misc=b""), use_database=False).image) is None


def report(pad, reads: int = 10) -> list[int]:  # type: ignore[no-untyped-def]
    pad.set_strobe(True)
    pad.set_strobe(False)
    bits = []
    for _ in range(reads):
        bits.append(pad.read() & 1)
        pad.clock()
    return bits


def test_the_panels_registers_report_as_controllers_and_then_ones() -> None:
    pad = PlayChoicePad()
    for bit, button in enumerate((A, B, SELECT, START, UP, DOWN, LEFT, RIGHT)):
        pad.buttons = button
        assert report(pad) == [int(n == bit) for n in range(8)] + [1, 1]


def test_player_2_has_no_select_or_start() -> None:
    pad = PlayChoicePad(select_start=False)
    pad.buttons = 0xFF
    assert report(pad, 8) == [1, 1, 0, 0, 1, 1, 1, 1]


def test_cntrl_mask_holds_start_and_select_released() -> None:
    pad = PlayChoicePad()
    pad.buttons = 0xFF
    pad.masked = True
    assert report(pad, 8) == [1, 1, 0, 0, 1, 1, 1, 1]
    pad.masked = False
    assert report(pad, 8) == [1] * 8


def test_the_ports_drive_d0_to_d4_and_leave_the_rest_to_the_bus() -> None:
    # LDA #1; STA $4016; LSR; STA $4016; LDA $4016; STA $00; LDA $4017; STA $01; JMP
    program = bytes.fromhex("a9 01 8d 16 40 4a 8d 16 40 ad 16 40 85 00 ad 17 40 85 01 4c 13 f0")
    system = System.from_rom(pc10_image(program), MACHINES["playchoice"])
    system.board.pads[0].buttons = A
    system.run_cycles(200)
    assert system.board.ram[0] == 0x41 and system.board.ram[1] == 0x40


def test_the_gun_shares_4017_with_player_2() -> None:
    system = System.from_rom(pc10_image(device=8), MACHINES["playchoice"])
    gun = system.plug()
    assert isinstance(gun, PlayChoiceGun) and system.board.pads[1] is gun
    gun.pad.buttons = A
    gun.set_strobe(True)
    assert gun.read() == 0x08 | 1  # no light, no trigger, A
    gun.trigger = True
    assert gun.read() & 0x10
    gun.masked = True
    assert not gun.read() & 0x10


# -- the security PROM -------------------------------------------------------


def test_the_prom_counts_falling_clocks_and_reads_out_serially() -> None:
    prom = RP5H01(PROM)
    prom.write(True, False, False)
    prom.write(False, False, False)
    bits = []
    for _ in range(64):
        bits.append(prom.data_out)
        prom.write(False, True, False)
        assert prom.data_out == bits[-1]  # nothing moves on the rising edge
        prom.write(False, False, False)
    assert bits == [PROM[i >> 3] >> (i & 7) & 1 for i in range(64)]
    assert prom.counter == 64 and prom.data_out == bits[0]  # six bits: around again
    prom.write(False, False, True)
    assert prom.data_out == PROM[8] & 1  # TEST: the seventh bit counts too


def test_the_proms_counter_output_is_bit_5_and_reset_holds_it() -> None:
    prom = RP5H01(PROM)
    seen = []
    for _ in range(128):
        seen.append(prom.counter_output)
        prom.write(False, True, False)
        prom.write(False, False, False)
    assert seen == [n >> 5 & 1 for n in range(128)]
    prom.write(True, True, False)
    prom.write(True, False, False)
    assert prom.counter == 0


# -- the supervisor ----------------------------------------------------------


def supervisor(program: bytes = b"\x18\xfe", **kwargs) -> Supervisor:  # type: ignore[no-untyped-def]
    roms = game_roms(load(pc10_image(), use_database=False).image)
    sup = Supervisor(bios(program, **kwargs), roms)
    sup.power()
    return sup


def test_the_z80s_memory() -> None:
    sup = supervisor()
    assert sup.read_byte(0x0000) == 0x18 and sup.read_byte(0xC000) == 0xC3
    sup.write_byte(0x8000, 0x12)
    sup.write_byte(0x8801, 0x34)
    assert sup.read_byte(0x8000) == 0x12
    # 8W's upper half mirrors the lower until the key is turned.
    assert sup.read_byte(0x8C01) == 0x34
    sup.write_port(BUP_KEY, 1)
    assert sup.read_byte(0x8C01) == 0x00
    sup.write_byte(0x8C01, 0x56)
    assert (sup.read_byte(0x8801), sup.read_byte(0x8C01)) == (0x34, 0x56)


def test_the_screens_ram_is_the_z80s_only_while_sdcs_is_low() -> None:
    sup = supervisor()
    sup.write_byte(0x9000, 0x01)
    sup.write_port(SDCS, 1)
    sup.write_byte(0x9000, 0x02)
    assert sup.video_ram[0] == 0x01 and not sup.screen_blank


def test_the_prom_through_e000() -> None:
    sup = supervisor()
    assert sup.prom is not None
    sup.write_byte(0xE000, 0x00)  # D0 low: RESET
    sup.write_byte(0xE000, 0x01)
    bits = []
    for _ in range(16):
        value = sup.read_byte(0xFFFF)
        assert value & 0xE7 == 0xE7 and value & 0x10  # counter bit 5 is 0, inverted
        bits.append(value >> 3 & 1)
        sup.write_byte(0xE000, 0x09)
        sup.write_byte(0xE000, 0x01)
    assert bits == [(PROM[i >> 3] >> (i & 7) & 1) ^ 1 for i in range(16)]
    # Another channel: an empty socket.
    sup.write_port(CSEL0, 1)
    assert sup.read_byte(0xE000) == 0xE7 and sup.read_byte(0xC000) == 0xFF


def test_port_0_coins_buttons_and_int_detect() -> None:
    sup = supervisor()
    assert sup.read_port(0) == INT_DETECT  # nothing detected reads 1
    sup.int_detect = True
    assert sup.read_port(0x10) == 0  # reads decode two address lines
    sup.read_port(3)
    assert sup.read_port(0) == INT_DETECT
    sup.buttons = CHANNEL | ENTER
    sup.insert_coin(0)
    sup.insert_coin(1, at=sup.t + Z80_HZ // 10)
    assert sup.read_port(0) == INT_DETECT | CHANNEL | ENTER | COIN_1
    sup.t += Z80_HZ // 10
    assert sup.read_port(0) == INT_DETECT | CHANNEL | ENTER | COIN_2
    sup.t += Z80_HZ // 10
    assert sup.read_port(0) == INT_DETECT | CHANNEL | ENTER
    sup.dip = [0x40, 0x3F]
    assert (sup.read_port(1), sup.read_port(2)) == (0x40, 0x3F)


def test_the_watchdog_resets_on_the_eighth_blank() -> None:
    sup = supervisor()
    while sup.blanks < 7:
        sup.step()
    assert sup.watchdog_resets == 0
    while sup.blanks < 8:
        sup.step()
    assert sup.watchdog_resets == 1
    # DOG DI holds the counter: LD A,1; OUT (9),A; JR $
    sup = supervisor(bytes.fromhex("3e 01 d3 09 18 fe"))
    while sup.blanks < 20:
        sup.step()
    assert sup.watchdog_resets == 0 and sup.latch[DOG_DI]


def test_the_blank_interrupt_fires_once_until_nmi_ei_is_dropped() -> None:
    start = bytes.fromhex("31 00 88 3e 01 d3 08 18 fe")  # LD SP,$8800; LD A,1; OUT (8),A; JR $
    count = bytes.fromhex("21 00 80 34")  # LD HL,$8000; INC (HL)
    sup = supervisor(start, nmi=count + bytes.fromhex("ed 45"))
    while sup.blanks < 5:
        sup.step()
    sup.step()
    assert sup.ram[0] == 1
    # XOR A; OUT (8),A; INC A; OUT (8),A; RETN: armed again each time.
    sup = supervisor(start, nmi=count + bytes.fromhex("af d3 08 3c d3 08 ed 45"))
    while sup.blanks < 5:
        sup.step()
    for _ in range(8):
        sup.step()
    assert sup.ram[0] == 5


def test_the_blank_is_60_21_times_a_second() -> None:
    sup = supervisor(bytes.fromhex("3e 01 d3 09 18 fe"))
    while sup.t < 10 * Z80_HZ:
        sup.step()
    # 5.04 MHz / (327 x 256), the first at line 240.
    assert sup.blanks == 602


def test_the_screen_draws_characters_through_the_proms() -> None:
    sup = supervisor()
    sup.write_byte(0x9000 + 2 * 64 + 2, 0x01)  # row 2, column 1: character 1 ...
    sup.write_byte(0x9000 + 2 * 64 + 3, 0x05 << 3)  # ... in colour 5
    sup.write_byte(0x9000, 0x02)  # row 0: in the vertical blank
    assert sup.picture() == bytes(256 * 240 * 3)  # SDCS low: blank
    sup.write_port(SDCS, 1)
    picture = sup.picture()
    # Index (5 << 3 | 7) & 15 = 15: every weight, 0x0E + 0x1F + 0x43 + 0x8F.
    assert picture[(16 * 256 + 8) * 3 :][:3] == b"\xff\xff\xff"
    assert picture[:3] == bytes(3)  # row 0 is not shown
    # MAME's thirty rows: row 0's character 2, pixel 1, colour 0: weight 0x0E.
    assert sup.picture((0, 240))[:3] == b"\x0e\x0e\x0e"


# -- the cabinet -------------------------------------------------------------

# LD A,1; OUT (n),A for /PPU RES, /GAME RES, /GAME STOP, DOG DI; JR $
RELEASE = bytes.fromhex("3e 01 d3 0a d3 04 d3 05 d3 09 18 fe")
# LDA #$80; STA $2000; INC $10; JMP $F002 (the write repeated: the first
# falls in the PPU's window after its reset)
COUNTING = bytes.fromhex("a9 80 8d 00 20 e6 10 4c 02 f0")


def test_the_game_is_held_in_reset_until_the_z80_lets_go() -> None:
    held = cabinet(bytes.fromhex("3e 01 d3 09 18 fe"), COUNTING)
    held.run_frames(3)
    assert held.in_reset and held.game.instructions == 0 and held.game.board.ram[0x10] == 0
    assert held.game_picture() == [0x0F] * (256 * 240) and not held.sound_on
    running = cabinet(RELEASE, COUNTING)
    running.run_frames(3)
    assert not running.in_reset and running.game.board.ram[0x10] != 0
    running.supervisor.write_port(DISP_MASK, 1)
    assert running.game_picture() is running.game.board.ppu.picture


def test_the_two_clocks_stay_within_an_instruction() -> None:
    machine = cabinet(RELEASE, COUNTING)
    for _ in range(20_000):
        machine.step()
        gap = machine.supervisor.t * 945 - machine.game.board.t * 176
        assert abs(gap) <= 23 * 945  # the longest Z80 instruction; a 2A03's is shorter


def test_game_stop_waits_for_the_games_interrupt() -> None:
    machine = cabinet(RELEASE, COUNTING)
    machine.run_frames(3)
    supervisor = machine.supervisor
    supervisor.read_port(3)
    machine.run_frames(1)
    assert supervisor.int_detect  # the PPU's /INT was seen
    supervisor.write_port(GAME_STOP, 0)
    assert not machine.stopped
    machine.run_frames(2)
    assert machine.stopped
    count = machine.game.board.ram[0x10]
    machine.run_frames(2)
    assert machine.game.board.ram[0x10] == count
    supervisor.write_port(GAME_STOP, 1)
    machine.run_frames(2)
    assert not machine.stopped and machine.game.board.ram[0x10] != count
    # A game that never enables its NMI is never stopped (nor detected).
    quiet = cabinet(RELEASE, bytes.fromhex("e6 10 4c 00 f0"))
    quiet.run_frames(3)
    quiet.supervisor.write_port(GAME_STOP, 0)
    quiet.run_frames(3)
    assert not quiet.stopped and not quiet.supervisor.int_detect


def test_game_res_resets_the_2a03_and_ppu_res_the_ppu() -> None:
    machine = cabinet(RELEASE, COUNTING)
    machine.run_frames(3)
    ppu = machine.game.board.ppu
    assert ppu.ctrl == 0x80
    machine.supervisor.write_port(PPU_RES, 0)
    assert ppu.ctrl == 0
    machine.supervisor.write_port(GAME_RES, 0)
    assert machine.in_reset
    count = machine.game.board.ram[0x10]
    machine.run_frames(2)
    assert machine.game.board.ram[0x10] == count
    machine.supervisor.write_port(PPU_RES, 1)
    machine.supervisor.write_port(GAME_RES, 1)
    machine.run_frames(3)
    assert machine.game.board.ram[0x10] != count and ppu.ctrl == 0x80


def test_cntrl_mask_reaches_the_panel() -> None:
    machine = cabinet()
    pads = machine.game.board.pads
    assert pads[0].masked
    machine.supervisor.write_port(1, 1)
    assert not pads[0].masked


def test_a_save_state_keeps_both_processors() -> None:
    first = cabinet(RELEASE, COUNTING)
    first.run_frames(3)
    first.insert_coin()
    first.supervisor.dip = [0x40, 0x3F]
    second = cabinet(RELEASE, COUNTING)
    load_state(second, save_state(first))
    for machine in (first, second):
        machine.run_frames(3)
    one, two = first.supervisor, second.supervisor
    assert (one.t, one.latch, one.dip, one.blanks) == (two.t, two.latch, two.dip, two.blanks)
    assert one.cpu.capture_state() == two.cpu.capture_state()
    assert first.game.board.t == second.game.board.t
    assert first.game.board.ram == second.game.board.ram
    assert (first.in_reset, first.stopped) == (second.in_reset, second.stopped)


# -- the real BIOS and a game ------------------------------------------------


def real(name: str = "Super Mario Bros..nes") -> PlayChoice:
    if not bios_path().exists():
        pytest.skip("PlayChoice-10 BIOS not found (FAMICOM_PC10_BIOS)")
    path = PC10_IMAGES / name
    if not path.exists():
        pytest.skip("PlayChoice-10 images not assembled: scripts/pc10_images.py (PC10_IMAGES_DIR)")
    machine = PlayChoice.from_rom(path, load_bios())
    machine.supervisor.dip = [0x40, 0x3F]  # MAME's defaults: 300 units a coin, one a second
    return machine


def test_the_real_bios_starts_and_arms_its_interrupt() -> None:
    machine = real()
    machine.run_seconds(2.5)
    supervisor = machine.supervisor
    # "WAIT 10 Sec." is up, the blank interrupt has been re-armed every frame,
    # the watchdog has never fired, and the PROM has been clocked.
    assert supervisor.watchdog_resets == 0 and supervisor.blanks > 140
    assert not supervisor.screen_blank and len(set(supervisor.picture())) > 1
    assert supervisor.prom is not None and supervisor.prom.counter
    assert machine.in_reset and not machine.game_shown


@pytest.mark.slow
def test_the_bios_checks_the_prom_runs_the_game_and_takes_it_away() -> None:
    machine = real()
    supervisor = machine.supervisor
    supervisor.dip[1] = 0x05  # 60 units of time a second
    machine.run_seconds(11.7)
    # The PROM passed: the game is listed, released and showing its attract mode.
    assert not machine.in_reset and machine.game_shown and machine.game.instructions > 1_000_000
    machine.insert_coin()
    machine.run_seconds(1.5)
    assert machine.in_reset and not machine.game_shown  # time bought: waiting for Enter
    machine.press(ENTER)
    machine.run_seconds(2.0)
    pad = machine.game.board.pads[0]
    assert not machine.in_reset and machine.game_shown and machine.sound_on and not pad.masked
    before = machine.game.instructions
    machine.run_seconds(1.0)
    assert machine.game.instructions > before and not machine.stopped
    # 300 units at 60 a second: gone. Start is masked, the game stopped at one
    # of its own interrupts, its sound cut.
    machine.run_seconds(5.0)
    assert machine.stopped and pad.masked and not machine.sound_on
    frozen = machine.game.instructions
    machine.run_seconds(1.0)
    assert machine.game.instructions == frozen and supervisor.watchdog_resets == 0


@pytest.mark.slow
def test_the_bios_refuses_a_wrong_prom() -> None:
    good = real()
    data = bytearray((PC10_IMAGES / "Super Mario Bros..nes").read_bytes())
    data[-32] ^= 0x10  # one bit of the PROM's data
    bad = PlayChoice(load(bytes(data), use_database=False), good.bios)
    bad.supervisor.dip = [0x40, 0x3F]
    bad.run_seconds(11.7)
    assert bad.in_reset and bad.game.instructions == 0 and not bad.game_shown
