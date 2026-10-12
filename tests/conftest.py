"""Shared fixtures: the fetched test ROMs, and a skip when they are absent."""

from __future__ import annotations

from pathlib import Path

import pytest

ROMS = Path(__file__).resolve().parent / "test_roms" / "nes-test-roms"
FETCH_HINT = "test ROMs not fetched: python scripts/fetch_references.py"


def rom(relative: str) -> Path:
    path = ROMS / relative
    if not path.exists():
        pytest.skip(FETCH_HINT)
    return path


def nrom_image(
    program: bytes,
    *,
    vectors: tuple[int, int, int] = (0x8100, 0x8000, 0x8200),
    chr_rom: bytes = b"",
) -> bytes:
    """A 16 KiB NROM file: ``program`` at $8000 (and $C000), NMI/RESET/IRQ vectors, 8 KiB CHR."""
    prg = bytearray(0x4000)
    prg[: len(program)] = program
    nmi, reset, irq = vectors
    prg[0x3FFA:0x4000] = bytes(
        (nmi & 0xFF, nmi >> 8, reset & 0xFF, reset >> 8, irq & 0xFF, irq >> 8)
    )
    chr_data = bytes(chr_rom) + bytes(0x2000 - len(chr_rom))
    return b"NES\x1a" + bytes((1, 1, 0, 0)) + bytes(8) + bytes(prg) + chr_data


def nrom_system(program: bytes, machine=None, **kwargs):
    """A powered-on console running ``program`` from $8000, its reset sequence done."""
    from famicom_python.cartridge import load
    from famicom_python.machine import NES_001
    from famicom_python.system import System

    machine = machine or NES_001
    loaded = load(nrom_image(program, **kwargs), use_database=False)
    system = System(loaded.cartridge, machine)
    system.step()  # the reset sequence
    return system
