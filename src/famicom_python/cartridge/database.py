"""Who made this cartridge, and how: nes20db first, MAME's software list second.

**nes20db** (NewRisingSun, release 2026-09-26) describes 21,339 dumps in NES 2.0
terms, keyed by SHA-1 of the whole ROM and of PRG and CHR, and covers every
licensed No-Intro dump (docs/cartridge.md "Identifying the board"). It carries
no licence, so it is fetched (``scripts/fetch_references.py``) and read at run
time from the pinned 7z through the ``7z`` program, never committed.

**MAME's ``nes.xml``** (CC0, installed with MAME) is keyed by PRG SHA-1 and adds
what nes20db lacks: the PCB name and the ``mmc1_type``/``mmc3_type``/
``bus_conflict`` features. It is only as good as its sources (Bootgod where he
documented the cartridge), so it informs and logs; it overrides nothing.

Both lookups are optional: without the files the loader falls back on the
header, and says so.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .ines import BoardInfo, RomImage

ROOT = Path(__file__).resolve().parents[3]
NES20DB = ROOT / "reference" / "docs" / "nes20db-2026-09-26.7z"
MAME_NES_XML = Path("/usr/share/games/mame/hash/nes.xml")


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest().upper()


def _size(game: ET.Element, tag: str) -> int:
    element = game.find(tag)
    return 0 if element is None else int(element.get("size", "0"))


def _board(game: ET.Element) -> BoardInfo:
    pcb = game.find("pcb")
    console = game.find("console")
    assert pcb is not None and console is not None
    return BoardInfo(
        mapper=int(pcb.get("mapper", "0")),
        submapper=int(pcb.get("submapper", "0")),
        mirroring=pcb.get("mirroring", "H"),
        battery=pcb.get("battery") == "1",
        prg_ram=_size(game, "prgram"),
        prg_nvram=_size(game, "prgnvram"),
        chr_ram=_size(game, "chrram"),
        chr_nvram=_size(game, "chrnvram"),
        timing=int(console.get("region", "0")),
        console=int(console.get("type", "0")),
    )


@dataclass(frozen=True)
class Nes20Db:
    by_rom: dict[str, BoardInfo]  # SHA-1 of PRG + CHR (+ misc ROM)
    by_parts: dict[tuple[str, str], BoardInfo]  # (PRG SHA-1, CHR SHA-1 or "")


@cache
def load_nes20db(path: Path = NES20DB) -> Nes20Db | None:
    """Parse the pinned nes20db, or None without the file or a ``7z`` program."""
    seven_zip = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
    if not path.exists() or seven_zip is None:
        return None
    xml = subprocess.run(
        [seven_zip, "x", "-so", str(path), "nes20db.xml"], capture_output=True, check=True
    ).stdout
    by_rom: dict[str, BoardInfo] = {}
    by_parts: dict[tuple[str, str], BoardInfo] = {}
    for game in ET.fromstring(xml).iter("game"):
        board = _board(game)
        rom = game.find("rom")
        prg = game.find("prgrom")
        chr_ = game.find("chrrom")
        if rom is not None:
            by_rom.setdefault(rom.get("sha1", ""), board)
        if prg is not None:
            key = (prg.get("sha1", ""), "" if chr_ is None else chr_.get("sha1", ""))
            by_parts.setdefault(key, board)
    return Nes20Db(by_rom, by_parts)


def lookup_nes20db(image: RomImage, db: Nes20Db | None) -> BoardInfo | None:
    """nes20db's description of ``image``: by whole ROM, then by PRG and CHR."""
    if db is None:
        return None
    board = db.by_rom.get(sha1(image.prg + image.chr + image.misc))
    if board is None:
        board = db.by_rom.get(sha1(image.prg + image.chr))
    if board is None:
        board = db.by_parts.get((sha1(image.prg), sha1(image.chr) if image.chr else ""))
    return board


@cache
def load_mame_features(path: Path = MAME_NES_XML) -> dict[str, dict[str, str]] | None:
    """MAME's cartridge features (slot, pcb, mmc1_type, ...) keyed by PRG SHA-1."""
    if not path.exists():
        return None
    features: dict[str, dict[str, str]] = {}
    for software in ET.parse(path).getroot().iter("software"):
        for part in software.iter("part"):
            values = {f.get("name", ""): f.get("value", "") for f in part.iter("feature")}
            values["software"] = software.get("name", "")
            for area in part.iter("dataarea"):
                if area.get("name") == "prg":
                    roms = [rom.get("sha1") for rom in area.iter("rom") if rom.get("sha1")]
                    if len(roms) == 1:
                        features.setdefault(roms[0].upper(), values)
    return features


def lookup_mame(image: RomImage, features: dict[str, dict[str, str]] | None) -> dict[str, str]:
    if features is None:
        return {}
    return features.get(sha1(image.prg), {})
