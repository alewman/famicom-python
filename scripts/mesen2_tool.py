# SPDX-License-Identifier: MIT
"""Run the family's Mesen2 tool as a separate program and read its outputs (docs/provenance.md).

mesen2-runner is a GPL tool kept outside this repository, in emu-tools-gpl. By emu-tools'
contract (section 5) it is found at its documented path under ``EMU_TOOLS_GPL``,
``$EMU_TOOLS_GPL/tools/mesen2/run.py``, and run as a program: nothing of it is imported or
copied here, and only what it writes (``manifest.json``, ``frame-NNNNNN.png``,
``insn.jsonl.gz``, ``script-log.txt``) is read, with this repository's own code below.

The library: ``MESEN_CORE`` if set, else this checkout's hand build under
``reference/build-mesen2`` (docs/validation.md) if present, else the tool's own build. The
manifest says which and whether its commit and patches were checked.
"""

from __future__ import annotations

import gzip
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAND_BUILD = ROOT / "reference/build-mesen2/Mesen2/InteropDLL/obj.linux-x64/MesenCore.so"
#: The interpreter for the tool, as its README runs it (``python3 -I run.py``): the system's,
#: not this checkout's venv, since the tool brings its own dependencies (Pillow for frames).
TOOL_PYTHON = "python3"
#: The board's timing names (machine.Timing.name) as the tool's --region spells them.
REGIONS = {"NTSC": "ntsc", "PAL": "pal", "Dendy": "dendy"}


def run_py() -> Path:
    """The tool's run.py; exit status 3 (a missing input) when it cannot be found."""
    root = os.environ.get("EMU_TOOLS_GPL")
    path = Path(root or "$EMU_TOOLS_GPL") / "tools/mesen2/run.py"
    if not root or not path.is_file():
        print(
            f"mesen2-runner not found at {path}: set EMU_TOOLS_GPL to a checkout of "
            "emu-tools-gpl (a GPL tool kept outside this repository)",
            file=sys.stderr,
        )
        sys.exit(3)
    return path


def loose_rom(rom: Path, scratch: Path) -> Path:
    """The tool's loader takes loose files only: a .zip's one NES or FDS image, extracted."""
    if rom.suffix.lower() != ".zip":
        return rom
    with zipfile.ZipFile(rom) as archive:
        (member,) = [n for n in archive.namelist() if n.lower().endswith((".nes", ".fds"))]
        scratch.mkdir(parents=True, exist_ok=True)
        target = scratch / Path(member).name
        target.write_bytes(archive.read(member))
    return target


def run(
    rom: Path,
    out: Path,
    frames: int,
    *,
    region: str = "ntsc",
    frames_at: list[int] | None = None,
    trace: str | None = None,
    lua: Path | None = None,
    ppu_reset_at_power: bool = True,
    oam_row_corruption: bool = True,
    timeout: float = 600,
) -> dict:
    """One run of machine ``nes``; returns the manifest. Stops with the tool's status if not 0."""
    command = [
        TOOL_PYTHON, "-I", str(run_py()), "--machine", "nes",
        "--rom", str(loose_rom(rom, out / "rom")), "--out", str(out),
        "--frames", str(frames), "--region", region, "--timeout", str(timeout),
        "--nes-ppu-reset-at-power", "on" if ppu_reset_at_power else "off",
        "--nes-oam-row-corruption", "on" if oam_row_corruption else "off",
    ]  # fmt: skip
    if frames_at:
        command += ["--frames-at", ",".join(map(str, frames_at))]
    if trace:
        command += ["--trace", trace]
    if lua:
        command += ["--lua", str(lua)]
    if not os.environ.get("MESEN_CORE") and HAND_BUILD.exists():
        command += ["--lib", str(HAND_BUILD)]
    done = subprocess.run(command, check=False)
    if done.returncode != 0:
        raise SystemExit(done.returncode)
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def read_grey16_png(path: Path) -> tuple[int, int, list[int]]:
    """Width, height and pixels of a 16-bit greyscale PNG (the tool's NES frames:
    palette index | emphasis x 64, as the board's own picture holds them)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    at, idat = 8, b""
    width = height = 0
    while at < len(data):
        (size,) = struct.unpack(">I", data[at : at + 4])
        kind, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + size]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, colour, interlace) != (16, 0, 0):
                raise ValueError(f"{path}: not 16-bit grey, non-interlaced")
        elif kind == b"IDAT":
            idat += body
        at += 12 + size
    raw = zlib.decompress(idat)
    stride, bpp = width * 2, 2
    rows: list[bytearray] = []
    prior = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up = prior[i]
            corner = prior[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                line[i] = (line[i] + pred) & 0xFF
        rows.append(line)
        prior = line
    pixels = [row[i] << 8 | row[i + 1] for row in rows for i in range(0, stride, 2)]
    return width, height, pixels


def insn_records(path: Path) -> Iterator[dict]:
    """The tool's trace/insn records (JSON Lines, gzipped)."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for text in stream:
            if text.strip():
                yield json.loads(text)
