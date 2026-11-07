"""Controllers besides the standard pad (peripherals.py), each against its wiki page."""

from __future__ import annotations

from types import SimpleNamespace

from conftest import nrom_image, nrom_system

from famicom_python import peripherals as p
from famicom_python.cartridge import load
from famicom_python.joypad import START, A, B
from famicom_python.machine import FAMICOM, NES_001, NTSC
from famicom_python.system import System
from famicom_python.video import load_palette, palette_for


def _strobe(board, value: int) -> None:
    """Write $4016, then two cycles: OUT0-2 reach the devices at the next put."""
    board.write_byte(0x4016, value)
    board.read_byte(0x0000)
    board.read_byte(0x0000)


def _read(board, address: int) -> int:
    """A port read, then another cycle: on the NES-001 /OE ends only when the next
    cycle is not a read of the same port (the board's joypad_oe_per_cycle)."""
    value = board.read_byte(address)
    board.read_byte(0x0000)
    return value


def _reads(board, address: int, count: int, bit: int) -> list[int]:
    return [_read(board, address) >> bit & 1 for _ in range(count)]


def test_four_score_sends_two_pads_then_its_signature() -> None:
    # Four_player_adapters.wiki "Four Score": $4016 D0 = pads 1 and 3, then reads
    # 16-23 = 0001 0000; $4017 D0 = pads 2 and 4, then 0010 0000; then 1s.
    board = nrom_system(b"", NES_001).board
    four = p.FourScore()
    board.pads = list(four.ports)
    four.pads[0].buttons = A
    four.pads[2].buttons = B | START
    four.pads[1].buttons = 0
    four.pads[3].buttons = A
    _strobe(board, 1)
    _strobe(board, 0)
    first = _reads(board, 0x4016, 26, 0)
    assert first[:8] == [1, 0, 0, 0, 0, 0, 0, 0]
    assert first[8:16] == [0, 1, 0, 1, 0, 0, 0, 0]
    assert first[16:24] == [0, 0, 0, 1, 0, 0, 0, 0] and first[24:] == [1, 1]
    second = _reads(board, 0x4017, 24, 0)
    assert second[:16] == [0] * 8 + [1] + [0] * 7
    assert second[16:24] == [0, 0, 1, 0, 0, 0, 0, 0]


def test_hori_adapter_swaps_the_signatures_on_d1() -> None:
    board = nrom_system(b"", FAMICOM).board
    board.expansion = p.HoriAdapter()
    _strobe(board, 1)
    _strobe(board, 0)
    assert _reads(board, 0x4016, 24, 1)[16:] == [0, 0, 1, 0, 0, 0, 0, 0]
    assert _reads(board, 0x4017, 24, 1)[16:] == [0, 0, 0, 1, 0, 0, 0, 0]


def _ppu(line: int = 0, dot: int = 0, value: int = 0x0F) -> SimpleNamespace:
    picture = [0x0F] * (256 * 240)
    picture[100 * 256 + 128] = value
    return SimpleNamespace(timing=NTSC, picture=picture, line=line, dot=dot, time=0)


PALETTE = load_palette(palette_for(NTSC))


def test_zapper_lines_fit_zap_ruder() -> None:
    # Zapper.wiki: about 26 lines on white ($20), 24 on light grey ($10), 19 on
    # dark grey ($00); black ($0F) nothing.
    lines = p.zapper_lines(PALETTE)
    assert abs(lines[0x20] - 26) < 1.5 and abs(lines[0x10] - 24) < 1.5
    assert abs(lines[0x00] - 19) < 1.5
    assert lines[0x0F] == 0 and lines[0x30] >= lines[0x10]


def test_zapper_sees_white_after_the_beam_passes_and_for_about_26_lines() -> None:
    ppu = _ppu(value=0x30)
    zapper = p.Zapper(ppu, PALETTE)
    zapper.aim = (128, 100)

    def seen(line: int, dot: int) -> bool:
        ppu.line, ppu.dot = line, dot
        return not zapper.read() & 0x08  # D3 = 0: light

    assert not seen(99, 200)  # the beam has not reached it
    assert seen(100, 140) and seen(120, 0)
    assert not seen(130, 0)  # drained
    zapper.aim = None
    assert not seen(100, 140)
    zapper.aim = (128, 100)
    ppu.picture[100 * 256 + 128] = 0x0F
    assert not seen(100, 140)


def test_zapper_trigger_reads_1_while_pulled_and_100_ms_after() -> None:
    ppu = _ppu()
    zapper = p.Zapper(ppu, PALETTE)
    assert not zapper.read() & 0x10
    zapper.trigger = True
    assert zapper.read() & 0x10
    zapper.trigger = False
    ppu.time += int(NTSC.master_hz * 0.09)
    assert zapper.read() & 0x10
    ppu.time += int(NTSC.master_hz * 0.02)
    assert not zapper.read() & 0x10


def test_zapper_on_the_nes_reads_on_4017_d3_d4_and_the_famicoms_through_expansion() -> None:
    nes = nrom_system(b"", NES_001)
    zapper = p.plug(nes.board, p.ZAPPER, famicom=False)
    assert isinstance(zapper, p.Zapper) and nes.board.pads[1] is zapper
    zapper.trigger = True
    assert nes.board.read_byte(0x4017) & 0x18 == 0x18  # no light, trigger
    famicom = nrom_system(b"", FAMICOM)
    zapper = p.plug(famicom.board, p.ZAPPER, famicom=True)
    zapper.trigger = True
    assert famicom.board.read_byte(0x4017) & 0x18 == 0x18
    famicom.board.data_bus = 0  # $4016 D3-D4 are open bus on the Famicom
    assert famicom.board.read_byte(0x4016) & 0x18 == 0


def _convert(vaus, clock: list[int], position: int) -> None:
    vaus.position = position
    vaus.set_out0(True)
    clock[0] += 100
    vaus.set_out0(False)
    clock[0] += int(0.008 * NTSC.master_hz)  # past the longest conversion
    vaus.data()  # settles


def _vaus_reads(vaus_device, clock: list[int], position: int, read, shift) -> list[int]:
    _convert(vaus_device.vaus, clock, position)
    bits = []
    for _ in range(8):
        bits.append(read())
        shift()
    return bits


def test_vaus_returns_the_knob_inverted_msb_first() -> None:
    # Arkanoid_controller.wiki: 8 latched bits after a conversion, inverted, MSB first.
    clock = [0]
    nes = p.VausNES(lambda: clock[0], int(NTSC.master_hz))
    bits = _vaus_reads(nes, clock, 0xA5, lambda: nes.read() >> 4 & 1, nes.clock)
    assert bits == [(~0xA5 >> (7 - i)) & 1 for i in range(8)]
    nes.vaus.fire = True
    assert nes.read() & 0x08
    famicom = p.VausFamicom(lambda: clock[0], int(NTSC.master_hz))
    bits = _vaus_reads(
        famicom, clock, 0x3C, lambda: famicom.read(1) >> 1 & 1, lambda: famicom.clock(1)
    )
    assert bits == [(~0x3C >> (7 - i)) & 1 for i in range(8)]
    famicom.vaus.fire = True
    assert famicom.read(0) == 0x02


def test_vaus_conversion_is_not_done_straight_after_the_strobe() -> None:
    # "the 8 latched bits can be safely read after strobing ... before the new
    # conversion completes": a strobe leaves the last result in place.
    clock = [0]
    nes = p.VausNES(lambda: clock[0], int(NTSC.master_hz))
    _convert(nes.vaus, clock, 0x10)
    assert nes.vaus.shift == 0x10
    nes.vaus.position = 0xF0
    nes.vaus.set_out0(True)
    clock[0] += 100
    nes.vaus.set_out0(False)
    assert nes.vaus.shift == 0x10


def test_power_pad_order_and_ones_after_eight_reads() -> None:
    # Power_Pad.wiki: D3 = 2, 1, 5, 9, 6, 10, 11, 7; D4 = 4, 3, 12, 8, then 1s.
    board = nrom_system(b"", NES_001).board
    pad = p.plug(board, p.POWER_PAD_B, famicom=False)
    pad.buttons = 1 << 0 | 1 << 8 | 1 << 11  # buttons 1, 9, 12
    _strobe(board, 1)
    _strobe(board, 0)
    values = [_read(board, 0x4017) for _ in range(10)]
    assert [v >> 3 & 1 for v in values] == [0, 1, 0, 1, 0, 0, 0, 0, 1, 1]
    assert [v >> 4 & 1 for v in values] == [0, 0, 1, 0, 1, 1, 1, 1, 1, 1]


def test_family_trainer_scans_rows_and_reads_columns_low() -> None:
    board = nrom_system(b"", FAMICOM).board
    mat = p.plug(board, p.FAMILY_TRAINER_B, famicom=True)
    mat.buttons = 1 << 0 | 1 << 6  # button 1 (top, left), button 7 (middle row)
    _strobe(board, 0b011)  # the top row only
    assert board.read_byte(0x4017) & 0x1E == 0x1E & ~0x10
    _strobe(board, 0b101)  # the middle row only: button 7, third column, D2
    assert board.read_byte(0x4017) & 0x1E == 0x1E & ~0x04
    _strobe(board, 0b110)  # the bottom row only
    assert board.read_byte(0x4017) & 0x1E == 0x1E


def _scan_keyboard(board) -> list[int]:
    """Family BASIC's procedure (Family_BASIC_Keyboard.wiki "Usage"): $05, then
    per row $04 (column 0, next row) and $06 (column 1), reading $4017 after each."""
    _strobe(board, 0x05)
    out = []
    for _ in range(9):
        _strobe(board, 0x04)
        out.append(board.read_byte(0x4017) & 0x1E)
        _strobe(board, 0x06)
        out.append(board.read_byte(0x4017) & 0x1E)
    return out


def test_family_basic_keyboard_scan_finds_the_held_keys() -> None:
    board = nrom_system(b"", FAMICOM).board
    keyboard = p.plug(board, p.FAMILY_BASIC_KEYBOARD, famicom=True)
    keyboard.keys = {"RETURN", "A", "SPACE"}
    scan = _scan_keyboard(board)
    assert scan[0] == 0x1E & ~0x04  # row 0 column 0: RETURN on D2
    assert scan[12] == 0x1E & ~0x10  # row 6 column 0: A on D4
    assert scan[17] == 0x1E & ~0x04  # row 8 column 1: SPACE on D2
    assert all(v == 0x1E for i, v in enumerate(scan) if i not in (0, 12, 17))


def test_family_basic_keyboard_lode_runner_detection() -> None:
    # The wiki: the 10th row reads $1E; disabled, $00.
    board = nrom_system(b"", FAMICOM).board
    p.plug(board, p.FAMILY_BASIC_KEYBOARD, famicom=True)
    _scan_keyboard(board)
    _strobe(board, 0x04)  # column 0 of row 9, the keyless 10th
    assert board.read_byte(0x4017) & 0x1E == 0x1E
    _strobe(board, 0x00)
    assert board.read_byte(0x4017) & 0x1E == 0


def test_konami_hyper_shot_enables_each_player_on_out1_out2() -> None:
    board = nrom_system(b"", FAMICOM).board
    shot = p.plug(board, p.KONAMI_HYPER_SHOT, famicom=True)
    shot.buttons = 0b1011  # P1 Run, P1 Jump, P2 Jump
    _strobe(board, 0)
    assert board.read_byte(0x4017) & 0x1E == 0b10110
    _strobe(board, 2)  # player 1 off
    assert board.read_byte(0x4017) & 0x1E == 0b10000
    _strobe(board, 4)  # player 2 off
    assert board.read_byte(0x4017) & 0x1E == 0b00110


def test_nes2_header_names_the_device_and_routes_nes_only_ones_to_the_nes() -> None:
    image = bytearray(nrom_image(b""))
    image[7] |= 0x08  # NES 2.0
    image[15] = p.FOUR_SCORE
    loaded = load(bytes(image), use_database=False)
    assert loaded.image.board.expansion == p.FOUR_SCORE
    image[15] = p.ZAPPER
    system = System(load(bytes(image), use_database=False).cartridge, FAMICOM)
    system.loaded = load(bytes(image), use_database=False)
    assert isinstance(system.plug(), p.Zapper)
    assert isinstance(system.board.expansion, p.FamicomZapper)
