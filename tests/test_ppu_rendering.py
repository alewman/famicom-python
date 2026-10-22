"""The PPU's picture and its bus, on a synthetic NROM: the quick-loop checks.

The test ROMs of milestone 2 are the judges (``pytest -m slow``,
docs/validation.md); these pin the parts a reader meets first, each against
the wiki page that states it: pixels from the shifters with fine X
(PPU_rendering.wiki, PPU_scrolling.wiki), the priority multiplexer and sprite-0
hit (PPU_OAM.wiki), overflow (PPU_sprite_evaluation.wiki), the backdrop
override (PPU_palettes.wiki), and the fetches on the connector
(PPU_rendering.wiki "Cycles 257-320": what MMC3 counts once per line).
"""

from __future__ import annotations

from itertools import pairwise

from conftest import nrom_system

from famicom_python.ppu import OVERFLOW, SPRITE0, WIDTH

# Tile 1: each row is low plane $F0, high plane $CC, so pixels 3 3 1 1 2 2 0 0;
# tile 2 is opaque throughout (pixel value 3). Both tables hold the same tiles.
TILES = bytes(16) + bytes([0xF0] * 8 + [0xCC] * 8) + bytes([0xFF] * 16)
BACKDROP = 0x0F


def _system(ctrl: int = 0x00, mask: int = 0x1E):
    """A console looping at $8000 with tile 1 in CHR, its PPU past the write-ignore."""
    table = TILES + bytes(0x1000 - len(TILES))
    system = nrom_system(bytes((0x4C, 0x00, 0x80)), chr_rom=table + table)
    ppu = system.board.ppu
    system.run_frames(2)
    ppu.palette[0] = BACKDROP
    ppu.palette[1:4] = bytes((0x01, 0x02, 0x03))
    ppu.palette[0x11:0x14] = bytes((0x21, 0x22, 0x23))
    for i in range(0, 256, 4):
        ppu.oam[i] = 0xF0  # every sprite below the picture
    ppu.ctrl, ppu.mask = ctrl, mask
    return system, ppu


def _run_to_line(system, line: int) -> None:
    """Run whole instructions until the PPU reaches ``line`` of the next frame."""
    ppu = system.board.ppu
    system.run_frames(1)
    while ppu.line < line:
        system.step()


def _one_frame_of_dots(ppu) -> None:
    """Run the PPU alone from the start of a frame to the start of the next."""
    frame = ppu.frame
    while ppu.frame == frame:
        ppu.run_to(ppu.time + 1)


def _row(ppu, line: int, start: int = 0, count: int = 8) -> list[int]:
    return list(ppu.picture[line * WIDTH + start : line * WIDTH + start + count])


def test_background_pixels_come_from_the_pattern_planes() -> None:
    system, ppu = _system()
    ppu.ciram[0] = 1  # tile (0, 0) of nametable 0
    system.run_frames(2)
    for line in range(8):
        assert _row(ppu, line) == [3, 3, 1, 1, 2, 2, BACKDROP, BACKDROP]
    assert _row(ppu, 8) == [BACKDROP] * 8


def test_fine_x_selects_the_bit_and_the_left_column_can_be_hidden() -> None:
    system, ppu = _system()
    ppu.ciram[0] = 1
    ppu.x = 2
    system.run_frames(1)
    assert _row(ppu, 0) == [1, 1, 2, 2, BACKDROP, BACKDROP, BACKDROP, BACKDROP]
    ppu.x = 0
    ppu.mask = 0x18  # BG on, left 8 pixels hidden
    system.run_frames(1)
    assert _row(ppu, 0) == [BACKDROP] * 8


def test_greyscale_and_emphasis_reach_the_output() -> None:
    system, ppu = _system(mask=0x1E | 0x01 | 0xA0)
    ppu.ciram[0] = 1
    ppu.palette[3] = 0x2C
    system.run_frames(1)
    assert ppu.picture[0] == (0x2C & 0x30) | (0xA0 << 1)


def test_sprite_in_front_behind_and_sprite_zero_hit() -> None:
    for behind in (False, True):
        system, ppu = _system()
        ppu.ciram[32 + 12] = 1  # BG tile at x 96-103, lines 8-15
        ppu.oam[0:4] = bytes((9, 1, 0x20 if behind else 0x00, 100))  # lines 10-17
        _run_to_line(system, 9)
        assert not ppu.status & SPRITE0
        _run_to_line(system, 240)
        assert ppu.status & SPRITE0
        # Line 10, x 100-107: the sprite's 3 3 1 1 2 2 0 0 over the BG's
        # 2 2 0 0 (pixels 4-7 of its tile) and the backdrop beyond.
        row = _row(ppu, 10, 100)
        if behind:
            assert row == [0x02, 0x02, 0x21, 0x21, 0x22, 0x22, BACKDROP, BACKDROP]
        else:
            assert row == [0x23, 0x23, 0x21, 0x21, 0x22, 0x22, BACKDROP, BACKDROP]


def test_sprite_zero_hit_needs_both_opaque_and_never_happens_at_x_255() -> None:
    system, ppu = _system()
    for column in range(32):
        ppu.ciram[32 + column] = 2  # opaque BG on lines 8-15
    ppu.oam[0:4] = bytes((9, 1, 0x40, 255))  # flipped: x 255 shows pixel value 0
    _run_to_line(system, 240)
    assert not ppu.status & SPRITE0
    ppu.oam[2] = 0x00  # unflipped: x 255 shows pixel value 3, still no hit
    _run_to_line(system, 240)
    assert not ppu.status & SPRITE0
    ppu.oam[3] = 254  # x 254: pixel value 3 over opaque BG, a hit
    _run_to_line(system, 240)
    assert ppu.status & SPRITE0


def test_nine_sprites_on_a_line_set_overflow_eight_do_not() -> None:
    for count, expected in ((8, 0), (9, OVERFLOW)):
        system, ppu = _system()
        for n in range(count):
            ppu.oam[4 * n : 4 * n + 4] = bytes((50, 1, 0, 8 * n))
        _run_to_line(system, 240)
        assert ppu.status & OVERFLOW == expected


def test_rendering_off_shows_the_backdrop_or_the_palette_entry_v_points_at() -> None:
    system, ppu = _system(mask=0x00)
    ppu.palette[5] = 0x16
    system.run_frames(1)
    assert set(ppu.picture) == {BACKDROP}
    ppu.v = 0x3F05
    system.run_frames(1)
    assert set(ppu.picture) == {0x16}


def test_every_pattern_fetch_reaches_the_cartridge_and_a12_rises_once_per_line() -> None:
    _, ppu = _system(ctrl=0x08)  # background at $0000, sprites at $1000
    cartridge = ppu.cartridge
    reads = []
    addresses = []
    original_read = cartridge.ppu_read
    cartridge.ppu_read = lambda address, t: reads.append(address) or original_read(address, t)
    cartridge.ppu_address = lambda address, t: addresses.append(address)
    ppu._watch = True
    _one_frame_of_dots(ppu)
    reads.clear()
    addresses.clear()
    _one_frame_of_dots(ppu)
    # 34 tiles x 2 planes + 8 sprite slots x 2 planes on each of 241 lines.
    assert len(reads) == 241 * (34 * 2 + 8 * 2)
    # Four addresses per tile and per sprite slot, plus 337 and 339; and dot
    # 0's after a rendering line (C27): lines 1-239 of the frame (the window
    # starts after line 0's dot 0), not the next line 0, as the frame was odd
    # and its skip took the dot-340 fetch.
    assert (ppu.frame - 1) & 1
    assert len(addresses) == 241 * (34 * 4 + 8 * 4 + 2) + 239
    a12 = [address >> 12 & 1 for address in addresses]
    rises = [i for i, (a, b) in enumerate(pairwise(a12), 1) if b and not a]
    # A12 rises at each sprite slot's pattern fetch (8 per line); only the
    # first follows a long low stretch (the background's), and that is the
    # rise MMC3's M2 filter counts: one per line.
    assert len(rises) == 241 * 8
    assert sum(1 for i in rises if not any(a12[i - 8 : i])) == 241


def test_empty_sprite_slots_fetch_tile_ff() -> None:
    # Secondary OAM is cleared to $FF on dots 1-64, so slots with no sprite
    # fetch tile $FF (PPU_rendering.wiki "Cycles 257-320").
    system, ppu = _system(ctrl=0x08)  # sprites at $1000
    ppu.oam[0:4] = bytes((50, 1, 0, 8))  # one sprite on lines 51-58
    ppu.oam[4:12] = bytes((40, 2, 0, 16, 40, 2, 0, 24))  # two on lines 41-48 fill slots 1-2
    _run_to_line(system, 55)
    cartridge = ppu.cartridge
    reads = []
    original_read = cartridge.ppu_read
    cartridge.ppu_read = lambda address, t: reads.append(address) or original_read(address, t)
    line = ppu.line
    while ppu.line == line:
        system.step()
    sprite_reads = [a for a in reads if a & 0x1000]
    assert sprite_reads[:2] == [0x1010 | (line - 50), 0x1018 | (line - 50)]
    assert {a >> 4 & 0xFF for a in sprite_reads[2:16]} == {0xFF}


def test_register_effects_land_dots_after_the_access() -> None:
    # Measured on PPUSim (ppu.DELAYS, docs/validation.md milestone 2), with
    # rendering off so each dot shows palette[v]: a $2007 write reaches palette
    # RAM 3 dots after the access and v increments a dot later; the second
    # $2006 write's copy lands 2 dots after; greyscale and emphasis reach the
    # pixel already looked up.
    _, ppu = _system(mask=0x00)
    ppu.palette[1:3] = bytes((0x11, 0x12))
    ppu.palette[5] = 0x15

    def access_at(line: int, dot: int) -> int:
        while (ppu.line, ppu.dot) != (line, dot):
            ppu.run_to(ppu.time + 1)
        return dot + 1 - 2  # the pixel of the first dot after the access

    ppu.v = 0x3F01
    x = access_at(100, 100)
    ppu.write_register(7, 0x16)
    x2 = access_at(101, 100)
    ppu.write_register(6, 0x3F)
    ppu.write_register(6, 0x05)
    x3 = access_at(102, 100)
    ppu.write_register(1, 0x21)  # greyscale and red emphasis
    access_at(103, 0)
    ppu.write_register(1, 0x00)
    ppu.v = 0x3F01
    x4 = access_at(104, 100)
    ppu.read_register(7)  # a read increments v just as late
    access_at(105, 0)
    assert _row(ppu, 100, x - 1, 7) == [0x11, 0x11, 0x11, 0x11, 0x16, 0x12, 0x12]
    assert _row(ppu, 101, x2, 4) == [0x12, 0x12, 0x15, 0x15]
    assert _row(ppu, 102, x3 - 2, 3) == [0x15, 0x50, 0x50]  # $15 & $30, emphasis bit 6
    assert _row(ppu, 104, x4, 6) == [0x16, 0x16, 0x16, 0x16, 0x12, 0x12]
