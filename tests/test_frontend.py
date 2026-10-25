"""The desktop frontend: its conversions without pygame, and the window itself
through SDL's dummy drivers when pygame-ce is installed (the ``frontend`` extra)."""

from __future__ import annotations

import os
from array import array
from pathlib import Path

import pytest
from conftest import nrom_image

from famicom_python.frontend import (
    SoundBuffer,
    frame_bytes,
    palette_words,
    samples_s16,
    save_path,
)


def test_frame_bytes_are_opaque_bgra() -> None:
    words = palette_words([b"\x12\x34\x56", b"\xff\xff\xff"])
    assert frame_bytes([0, 1], words) == bytes([0x56, 0x34, 0x12, 0xFF]) + b"\xff" * 4


def test_samples_are_clipped_signed_16_bit() -> None:
    assert list(array("h", samples_s16([0.0, 0.1, -5.0, 5.0], gain=1.0))) == [
        0, 3276, -32768, 32767,
    ]  # fmt: skip


def test_sound_buffer_pads_with_silence() -> None:
    buffer = SoundBuffer()
    buffer.push(b"\x01\x02\x03")
    stream = memoryview(bytearray(b"\xaa" * 6))
    buffer.fill(None, stream)
    assert bytes(stream) == b"\x01\x02\x03\x00\x00\x00" and len(buffer) == 0


def test_the_save_sits_beside_the_rom() -> None:
    assert save_path(Path("/x/Zelda (USA).zip")) == Path("/x/Zelda (USA).zip.sav")


def test_the_window_runs_frames_and_keeps_the_save(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from famicom_python.frontend import Frontend

    # INC $6000; JMP $8000 on a battery-backed NROM board with 8 KiB of PRG-RAM.
    image = bytearray(nrom_image(bytes((0xEE, 0x00, 0x60, 0x4C, 0x00, 0x80))))
    image[6] |= 0x02
    rom = tmp_path / "counter.nes"
    rom.write_bytes(bytes(image))
    palette = tmp_path / "grey.pal"
    palette.write_bytes(bytes(v for i in range(64) for v in (i * 4,) * 3))
    pygame.display.init()
    try:
        frontend = Frontend(pygame, rom, "famicom", palette, 2, False, False)
        assert frontend.system.board.expansion_pads[0] is not None
        frontend.run(max_frames=2)
        frontend.save()
        count = save_path(rom).read_bytes()[0]
        assert count > 0
        again = Frontend(pygame, rom, "famicom", palette, 2, False, False)
        assert again.system.cartridge.battery_ram()[0] == count
    finally:
        pygame.quit()
