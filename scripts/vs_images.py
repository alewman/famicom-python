#!/usr/bin/env python3
"""Assemble NES 2.0 images of the Vs. System games from MAME's ROM sets.

nes20db (the pinned release, ``famicom_python.cartridge.database``) describes
74 Vs. System images by the SHA-1 of their PRG and CHR data; the dumps
themselves circulate as MAME's sets, one zip of EPROM files per game. This
finds, for every nes20db entry, the MAME set and the arrangement of its EPROMs
whose hashes are the entry's, and writes the image with the header nes20db
describes, into a directory **outside the repository**: nothing it reads or
writes is ever committed.

    python scripts/vs_images.py --out /somewhere/vs-images [--roms DIR] [--list]

Where each EPROM lies comes from ``mame -listxml <set>`` (regions and offsets;
MAME 0.285, vsnes.cpp, BSD-3). The arrangements tried are NES_2.0.wiki's
("PRG-ROM Area", "CHR-ROM Area"):

- a UniSystem's PRG as its sockets 1D/6D..1A/6A stand at $8000-$FFFF, an
  unpopulated low socket left out (a 24 KiB image lies at $A000-$FFFF);
- *Vs. Gumshoe*'s 40 KiB as the 32 KiB seen with $4016 D2 = 0, then the 8 KiB
  that D2 = 1 puts at $8000;
- a daughterboard's EPROMs in either order (MAME loads *Super Xevious*' and
  *Freedom Force*'s halves swapped);
- a DualSystem's main side, then its sub side; *Raid on Bungeling Bay*'s 32 KiB
  and then the 8 KiB of its second CPU;
- CHR: one side's, or the main side's and then the sub side's.

A hash match is the proof; an entry with no match is reported and skipped.
``manifest.json`` beside the images records the set and arrangement of each,
and MAME's default DIP switch setting for the set (SW1 = bit 0).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from itertools import permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from famicom_python.cartridge.database import NES20DB  # noqa: E402

DEFAULT_ROMS = Path("/data/emu/source/myrient.erista.me/files/MAME/ROMs (non-merged)")
SOURCE = "nintendo/vsnes.cpp"
BANK = 0x2000


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest().upper()


# -- nes20db ---------------------------------------------------------------


def vs_entries(path: Path = NES20DB) -> list[dict]:
    """nes20db's Vs. System games (console type 1), with their names."""
    xml = subprocess.run(
        ["7z", "x", "-so", str(path), "nes20db.xml"], capture_output=True, check=True
    ).stdout.decode("utf-8")
    entries = []
    for name, body in re.findall(r"<game><!--\s*(.*?)\s*-->(.*?)</game>", xml, re.DOTALL):
        game = ET.fromstring(f"<game>{body}</game>")
        name = html.unescape(name).replace("\\", "/")
        console = game.find("console")
        if console is None or console.get("type") != "1":
            continue

        def attribute(tag: str, key: str, game: ET.Element = game) -> str:
            element = game.find(tag)
            return "" if element is None else element.get(key, "")

        entries.append(
            {
                "name": name.rsplit("/", 1)[-1].removesuffix(".nes"),
                "folder": name.rsplit("/", 1)[0],
                "prg_sha1": attribute("prgrom", "sha1"),
                "prg_size": int(attribute("prgrom", "size") or 0),
                "chr_sha1": attribute("chrrom", "sha1"),
                "chr_size": int(attribute("chrrom", "size") or 0),
                "prg_ram": int(attribute("prgram", "size") or 0),
                "prg_nvram": int(attribute("prgnvram", "size") or 0),
                "chr_ram": int(attribute("chrram", "size") or 0),
                "chr_nvram": int(attribute("chrnvram", "size") or 0),
                "mapper": int(attribute("pcb", "mapper")),
                "submapper": int(attribute("pcb", "submapper") or 0),
                "mirroring": attribute("pcb", "mirroring"),
                "battery": attribute("pcb", "battery") == "1",
                "region": int(attribute("console", "region") or 0),
                "vs_hardware": int(attribute("vs", "hardware") or 0),
                "vs_ppu": int(attribute("vs", "ppu") or 0),
                "expansion": int(attribute("expansion", "type") or 0),
            }
        )
    return entries


def _ram_shift(size: int) -> int:
    """NES 2.0's RAM size code: 64 << code bytes (0: none)."""
    if not size:
        return 0
    code = (size // 64).bit_length() - 1
    if 64 << code != size:
        raise ValueError(f"RAM size {size} has no NES 2.0 code")
    return code


def _rom_size(size: int, unit: int) -> tuple[int, int]:
    """A ROM area's low byte and high nibble: units, or the exponent-multiplier form."""
    if size % unit == 0 and size // unit < 0xF00:
        return (size // unit) & 0xFF, (size // unit) >> 8
    for multiplier in range(4):
        odd = multiplier * 2 + 1
        if size % odd == 0 and (size // odd) & (size // odd - 1) == 0:
            return ((size // odd).bit_length() - 1) << 2 | multiplier, 0xF
    raise ValueError(f"ROM size {size} cannot be written in a NES 2.0 header")


def header(entry: dict) -> bytes:
    """The NES 2.0 header that says what nes20db says (NES_2.0.wiki)."""
    prg_low, prg_high = _rom_size(entry["prg_size"], 0x4000)
    chr_low, chr_high = _rom_size(entry["chr_size"], 0x2000)
    mapper = entry["mapper"]
    flags6 = (mapper & 0x0F) << 4 | (0x02 if entry["battery"] else 0)
    flags6 |= {"H": 0, "V": 1, "4": 8}.get(entry["mirroring"], 0)
    return bytes(
        [
            0x4E,
            0x45,
            0x53,
            0x1A,
            prg_low,
            chr_low,
            flags6,
            (mapper & 0xF0) | 0x08 | 0x01,  # NES 2.0, console type 1
            entry["submapper"] << 4 | mapper >> 8,
            chr_high << 4 | prg_high,
            _ram_shift(entry["prg_nvram"]) << 4 | _ram_shift(entry["prg_ram"]),
            _ram_shift(entry["chr_nvram"]) << 4 | _ram_shift(entry["chr_ram"]),
            entry["region"],
            entry["vs_hardware"] << 4 | entry["vs_ppu"],
            0,
            entry["expansion"],
        ]
    )


# -- MAME's sets -----------------------------------------------------------


def vs_sets() -> list[str]:
    """The machines of MAME's vsnes driver."""
    listing = subprocess.run(["mame", "-listsource"], capture_output=True, text=True, check=True)
    return [line.split()[0] for line in listing.stdout.splitlines() if line.endswith(SOURCE)]


def read_set(name: str, roms: Path) -> dict | None:
    """A set's regions as (offset, bytes) lists, its DIP default and description."""
    archive = roms / f"{name}.zip"
    if not archive.exists():
        return None
    xml = subprocess.run(["mame", "-listxml", name], capture_output=True, text=True).stdout
    if not xml.strip():
        return None
    machine = next(m for m in ET.fromstring(xml).iter("machine") if m.get("name") == name)
    regions: dict[str, list[tuple[int, bytes]]] = {}
    with zipfile.ZipFile(archive) as files:
        members = set(files.namelist())
        for rom in machine.iter("rom"):
            if rom.get("name") in members and rom.get("region") is not None:
                data = files.read(rom.get("name", ""))
                regions.setdefault(rom.get("region", ""), []).append(
                    (int(rom.get("offset", "0"), 16), data)
                )
    dips: dict[str, int] = {}
    for switch in machine.iter("dipswitch"):
        for value in switch.iter("dipvalue"):
            if value.get("default") == "yes":
                tag = switch.get("tag", "")
                dips[tag] = dips.get(tag, 0) | int(value.get("value", "0"))
    return {
        "description": machine.findtext("description", ""),
        "regions": {key: sorted(parts) for key, parts in regions.items()},
        "dips": dips,
    }


def _joined(parts: list[tuple[int, bytes]]) -> bytes:
    return b"".join(data for _, data in parts)


def prg_candidates(regions: dict[str, list[tuple[int, bytes]]]) -> dict[str, bytes]:
    """Every arrangement of a set's program EPROMs the module notes list, by name."""
    main = regions.get("prg") or regions.get("maincpu") or []
    sub = regions.get("sub", [])
    extra = regions.get("user1", [])
    found: dict[str, bytes] = {}
    if not main:
        return found
    whole = _joined(main)
    found["sockets"] = whole
    if len(main) > 1 and len(main) <= 4:
        for order in permutations(range(len(main))):
            found.setdefault(
                "order " + "".join(map(str, order)), b"".join(main[i][1] for i in order)
            )
    if len(whole) == 5 * BANK:
        # Gumshoe: MAME's region is the 16 KiB EPROM (both $8000 banks), then
        # $A000-$FFFF; the image is the D2 = 0 view, then the D2 = 1 bank.
        banks = [whole[i : i + BANK] for i in range(0, len(whole), BANK)]
        found["gumshoe"] = banks[0] + banks[2] + banks[3] + banks[4] + banks[1]
    if sub:
        found["main + sub"] = whole + _joined(sub)
    if extra:
        found["main + second CPU"] = whole + _joined(extra)
    # nes20db's "[padded]" images: the same data with each side filled out to
    # 32 KiB, for loaders that know only whole 16 KiB units.
    for fill in (b"\xff", b"\x00"):
        tag = f", padded with ${fill[0]:02X}"

        def side(data: bytes, fill: bytes = fill) -> bytes:
            return fill * (4 * BANK - len(data)) + data

        if len(whole) < 4 * BANK:
            found["sockets" + tag] = side(whole)
            if sub:
                found["main + sub" + tag] = side(whole) + side(_joined(sub))
        if extra:
            found["main + second CPU" + tag] = whole + side(_joined(extra))
        if "gumshoe" in found:
            found["gumshoe" + tag] = found["gumshoe"] + fill * BANK
    return found


def chr_candidates(regions: dict[str, list[tuple[int, bytes]]]) -> dict[str, bytes]:
    one = _joined(regions.get("gfx1", []))
    two = _joined(regions.get("gfx2", []))
    found = {"none": b""}
    if one:
        found["gfx1"] = one
    if two:
        found["gfx1 + gfx2"] = one + two
    return found


# -- matching --------------------------------------------------------------


def assemble(roms: Path) -> tuple[list[dict], list[dict], list[str]]:
    """(assembled images, nes20db entries left unmatched, sets read)."""
    by_prg: dict[str, list[tuple[str, str, bytes, dict]]] = {}
    sets = {}
    for name in vs_sets():
        data = read_set(name, roms)
        if data is None:
            continue
        sets[name] = data
        for label, prg in prg_candidates(data["regions"]).items():
            by_prg.setdefault(sha1(prg), []).append((name, label, prg, data))
    images, missing = [], []
    for entry in vs_entries():
        match = None
        for name, label, prg, data in by_prg.get(entry["prg_sha1"], []):
            for chr_label, chr_ in chr_candidates(data["regions"]).items():
                if len(chr_) == entry["chr_size"] and (not chr_ or sha1(chr_) == entry["chr_sha1"]):
                    match = (name, label, chr_label, prg, chr_, data)
                    break
            if match:
                break
        if match is None:
            missing.append(entry)
            continue
        name, label, chr_label, prg, chr_, data = match
        images.append(
            {
                "entry": entry,
                "set": name,
                "description": data["description"],
                "prg": label,
                "chr": chr_label,
                "dips": data["dips"],
                "image": header(entry) + prg + chr_,
            }
        )
    return images, missing, sorted(sets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="where the images go (outside the repository)")
    parser.add_argument("--roms", type=Path, default=DEFAULT_ROMS, help="MAME's set zips")
    parser.add_argument("--list", action="store_true", help="report the matches, write nothing")
    args = parser.parse_args()
    if not args.list and args.out is None:
        parser.error("--out or --list")
    if args.out is not None and ROOT in args.out.resolve().parents:
        parser.error("--out must lie outside the repository: ROMs are never committed")
    images, missing, sets = assemble(args.roms)
    manifest = []
    names: set[str] = set()
    for image in images:
        entry = image["entry"]
        name = entry["name"]
        if name in names:  # nes20db lists a few images twice (a padded copy)
            name = f"{name} [{entry['folder'].rsplit('/', 1)[-1]}]"
        names.add(name)
        record = {
            "file": f"{name}.nes",
            "set": image["set"],
            "description": image["description"],
            "prg": image["prg"],
            "chr": image["chr"],
            "dips": image["dips"],
            **{key: entry[key] for key in ("mapper", "vs_hardware", "vs_ppu", "expansion")},
        }
        manifest.append(record)
        print(
            f"{record['file']:60} {image['set']:14} mapper {entry['mapper']:3} "
            f"hw {entry['vs_hardware']} ppu {entry['vs_ppu']:2} [{image['prg']}; {image['chr']}]"
        )
        if not args.list:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / record["file"]).write_bytes(image["image"])
    for entry in missing:
        print(f"no set for: {entry['folder']}/{entry['name']} (PRG {entry['prg_sha1']})")
    used = {record["set"] for record in manifest}
    print(
        f"{len(images)} of {len(images) + len(missing)} nes20db Vs. images assembled "
        f"from {len(used)} of {len(sets)} MAME sets; sets matching nothing: "
        + (", ".join(sorted(set(sets) - used)) or "none")
    )
    if not args.list:
        (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
