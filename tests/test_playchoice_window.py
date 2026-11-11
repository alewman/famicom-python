"""The PlayChoice-10 in the window: the menu screen above the game's, one
monitor, no BIOS, and sixteen DIP switches (frontend.py). The BIOS here is a
few bytes of Z80 code (test_playchoice.py's)."""

from __future__ import annotations

import os

import pytest
from test_playchoice import COUNTING, RELEASE, bios, pc10_image

from famicom_python.supervisor import Bios

# -- the window --------------------------------------------------------------


def window(tmp_path, monkeypatch, found: Bios | None, name: str = "dual"):  # type: ignore[no-untyped-def]
    pygame = pytest.importorskip("pygame")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from famicom_python import frontend

    def load(wanted: str) -> Bios:
        if found is None:
            raise FileNotFoundError("PlayChoice-10 BIOS not found")
        return Bios(wanted, found.program, found.characters, found.proms)

    monkeypatch.setattr(frontend, "load_bios", load)
    rom = tmp_path / "game.nes"
    rom.write_bytes(pc10_image(COUNTING))
    pygame.display.init()
    return pygame, frontend.Frontend(
        pygame, rom, "auto", None, 1, False, False, dip=0x3F40, bios=name
    )


def test_the_window_has_the_menu_above_the_game(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pygame, frontend = window(tmp_path, monkeypatch, bios(RELEASE))
    try:
        cabinet = frontend.cabinet
        assert cabinet is not None and frontend.system is cabinet.game
        assert cabinet.supervisor.dip == [0x40, 0x3F]
        assert frontend.window.get_size() == (256, 480)
        for _ in range(3):
            frontend.run_frame()
            frontend.draw()
        assert not cabinet.in_reset
    finally:
        pygame.display.quit()


def test_one_monitor_and_no_bios(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pygame, frontend = window(tmp_path, monkeypatch, bios(RELEASE), "single")
    try:
        cabinet = frontend.cabinet
        assert cabinet is not None and frontend.window.get_size() == (256, 240)
        frontend.run_frame()
        frontend.draw()
        # The monitor goes over to the game when /DISP MASK falls (MAME's rule).
        assert not cabinet.monitor_on_game
        cabinet.supervisor.write_port(0, 1)
        cabinet.supervisor.write_port(2, 1)
        cabinet.supervisor.write_port(2, 0)
        assert cabinet.monitor_on_game
        frontend.draw()
    finally:
        pygame.display.quit()
    pygame, frontend = window(tmp_path, monkeypatch, None)
    try:
        # Without the BIOS the game board runs alone, as a console.
        assert frontend.cabinet is None and frontend.system.machine.playchoice
        assert frontend.window.get_size() == (256, 240)
        frontend.run_frame()
        frontend.draw()
    finally:
        pygame.display.quit()


def test_dip_takes_sixteen_switches() -> None:
    from famicom_python.frontend import dip_switches

    assert dip_switches("0000001011111100") == 0x3F40
    assert dip_switches("10000000") == 0x01
