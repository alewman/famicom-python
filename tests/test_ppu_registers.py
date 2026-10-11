"""The PPU as the CPU sees it in milestone 1: registers, buffer, palette, frame timing.

PPU_registers.wiki, PPU_scrolling.wiki, PPU_palettes.wiki, PPU_power_up_state.wiki;
the frame events of docs/timing.md "Frame events". The rendering, races and
latch decay are milestone 2's.
"""

from __future__ import annotations

from itertools import pairwise

from conftest import nrom_system

from famicom_python.ppu import VBL


def _ppu_after_warmup():
    system = nrom_system(b"")
    board, ppu = system.board, system.board.ppu
    while ppu.resetting:  # writes are ignored until the first pre-render line
        board.read_byte(0x0000)
    return board, ppu


def test_vbl_sets_on_line_241_dot_1_and_clears_on_the_prerender_line() -> None:
    board, ppu = _ppu_after_warmup()
    while not ppu.status & VBL:
        board.read_byte(0x0000)
    assert ppu.line == 241 and 1 <= ppu.dot <= 3
    while ppu.status & VBL:
        board.read_byte(0x0000)
    assert ppu.line == 261 and 1 <= ppu.dot <= 3


def test_a_frame_is_89342_dots_with_rendering_off() -> None:
    board, ppu = _ppu_after_warmup()
    frame = ppu.frame
    while ppu.frame == frame:
        board.read_byte(0x0000)
    start = ppu.time
    while ppu.frame == frame + 1:
        board.read_byte(0x0000)
    assert abs((ppu.time - start) // ppu.dot_ticks - 341 * 262) <= 3


def test_odd_frames_skip_a_dot_with_rendering_on() -> None:
    # PPU_frame_timing.wiki: (339, 261) -> (0, 0) on odd frames, so frames
    # alternate 89342 and 89341 dots; with rendering off every frame is 89342.
    for mask, expected in ((0x08, {89341, 89342}), (0x00, {89342})):
        _, ppu = _ppu_after_warmup()
        ppu.mask = mask
        starts = []
        frame = ppu.frame
        while len(starts) < 5:
            ppu.run_to(ppu.time + 1)
            if ppu.frame != frame:
                frame = ppu.frame
                starts.append(ppu.time)
        lengths = [(b - a) // ppu.dot_ticks for a, b in pairwise(starts)]
        assert set(lengths) == expected
        if mask:
            assert lengths[0] != lengths[1]  # they alternate


def test_writes_are_ignored_until_the_first_prerender_line() -> None:
    system = nrom_system(b"")
    board, ppu = system.board, system.board.ppu
    assert ppu.resetting
    board.write_byte(0x2000, 0x80)
    board.write_byte(0x2006, 0x21)
    assert ppu.ctrl == 0 and ppu.w == 0
    board.write_byte(0x2003, 0x10)  # $2003 works at once
    assert ppu.oam_addr == 0x10


def test_2007_reads_are_buffered_except_palette() -> None:
    board, _ = _ppu_after_warmup()
    for address, value in ((0x2105, 0x11), (0x2106, 0x22)):
        board.write_byte(0x2006, address >> 8)
        board.write_byte(0x2006, address & 0xFF)
        board.write_byte(0x2007, value)
    board.write_byte(0x2006, 0x21)
    board.write_byte(0x2006, 0x05)
    assert board.read_byte(0x2007) != 0x11  # the stale buffer
    assert board.read_byte(0x2007) == 0x11
    assert board.read_byte(0x2007) == 0x22


def test_palette_mirrors_and_reads_at_once_with_open_bus_above() -> None:
    board, ppu = _ppu_after_warmup()
    board.write_byte(0x2006, 0x3F)
    board.write_byte(0x2006, 0x10)
    board.write_byte(0x2007, 0xED)  # $3F10 is $3F00's cell; 6 bits stored
    assert ppu.palette[0] == 0x2D
    board.write_byte(0x2006, 0x3F)
    board.write_byte(0x2006, 0x00)
    ppu.latch = 0xC0
    assert board.read_byte(0x2007) == 0xED  # bits 7-6 from the I/O latch


def test_2002_read_clears_vbl_and_the_write_toggle() -> None:
    board, ppu = _ppu_after_warmup()
    while not ppu.status & VBL:
        board.read_byte(0x0000)
    board.write_byte(0x2005, 0x00)
    assert ppu.w == 1
    assert board.read_byte(0x2002) & 0x80
    assert ppu.w == 0
    assert not board.read_byte(0x2002) & 0x80


def test_nmi_is_taken_at_vblank_when_enabled() -> None:
    # LDA #$80; STA $2000 (repeated until accepted); loop. NMI handler at $8100.
    program = bytes((0xA9, 0x80, 0x8D, 0x00, 0x20, 0x4C, 0x02, 0x80))
    system = nrom_system(program)
    ppu = system.board.ppu
    while system.cpu.pc != 0x8100 and system.cycles < 200_000:
        system.step()
    assert system.cpu.pc == 0x8100
    assert ppu.line == 241
