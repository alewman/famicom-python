#!/usr/bin/env python3
"""Assemble NES 2.0 images of the PlayChoice-10 games from MAME's ROM sets.

nes20db (the pinned release) describes 65 PlayChoice-10 images (console type
2) by the SHA-1 of their PRG, CHR and miscellaneous-ROM data; the dumps
circulate as MAME's sets, one zip of EPROM files per game. As
``scripts/vs_images.py`` does for the Vs. System, this finds for every nes20db
entry the MAME set whose files hash to the entry's, and writes the image with
the header nes20db describes, into a directory **outside the repository**:
nothing it reads or writes is ever committed.

    python scripts/pc10_images.py --out /somewhere/pc10-images [--roms DIR] [--list]

Where each file lies comes from ``mame -listxml <set>`` (MAME 0.285,
playch10.cpp, BSD-3): region ``prg`` is the game's program, ``gfx2`` its CHR
ROM, the 8 KiB at ``maincpu`` offset $C000 the INST ROM (the Z80's
instruction-screen code and data), ``rp5h01`` the security PROM.

**The miscellaneous-ROM area** (NES_2.0.wiki "Miscellaneous ROM Area";
PC10_ROM-Images.wiki): "an 8 KiB INST ROM, 16 bytes of PROM Data, 16 bytes of
PROM Counter Out data". MAME's ``security.prm`` holds the 16 data bytes only,
and "all bits in the PROM file are inverted, and the bit ordering is reversed:
bit0 (the first bit of the PROM's serial bitstream) is stored in bit7 of the
1st byte of the file": :func:`prom_data` undoes both. The Counter Out bytes
are "usually constant: 00,00,00,00,FF,FF,FF,FF,00,00,00,00,FF,FF,FF,FF", the
chip's counter bit 5 over 128 clocks, and MAME has no file for them:
:data:`COUNTER_OUT` is written. The proof of all three is nes20db's SHA-1 of
the whole area; an entry whose area does not hash is reported, not written.

``manifest.json`` beside the images records each one's set, and MAME's default
DIP switches for the driver (SW1 and SW2; the same for every set).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vs_images import DEFAULT_ROMS, ROOT, header, read_set, sha1, vs_entries, vs_sets

SOURCE = "nintendo/playch10.cpp"
INST_OFFSET = 0xC000
COUNTER_OUT = bytes.fromhex("00000000ffffffff00000000ffffffff")


def prom_data(security: bytes) -> bytes:
    """MAME's ``security.prm`` as the image's PROM Data: each byte inverted
    and its bits reversed (PC10_ROM-Images.wiki "MAME Format")."""
    return bytes(int(f"{byte ^ 0xFF:08b}"[::-1], 2) for byte in security)


def misc_area(regions: dict[str, list[tuple[int, bytes]]]) -> bytes | None:
    """INST ROM + PROM Data + PROM Counter Out of a set, or None without them."""
    inst = [data for offset, data in regions.get("maincpu", []) if offset == INST_OFFSET]
    prom = regions.get("rp5h01", [])
    if len(inst) != 1 or len(prom) != 1:
        return None
    return inst[0] + prom_data(prom[0][1]) + COUNTER_OUT


def prg_candidates(prg: bytes, size: int) -> dict[str, bytes]:
    """A set's program as nes20db may hold it: as it is, or behind zeros up to
    nes20db's size (*Pro Wrestling*: 96 KiB of EPROM in a 128 KiB image)."""
    found = {"prg": prg}
    if len(prg) < size:
        found[f"{(size - len(prg)) // 1024} KiB of $00, then prg"] = bytes(size - len(prg)) + prg
    return found


def chr_candidates(chr_: bytes, size: int) -> dict[str, bytes]:
    """A set's CHR ROM, or the first ``size`` bytes of it (*Bases Loaded*:
    MAME's EPROM file is 128 KiB, nes20db's CHR its first 64)."""
    found = {"gfx2" if chr_ else "none": chr_}
    if len(chr_) > size > 0:
        found[f"the first {size // 1024} KiB of gfx2"] = chr_[:size]
    return found


def assemble(roms: Path) -> tuple[list[dict], list[dict], list[str]]:
    """(assembled images, nes20db entries left unmatched, sets read).

    An image is *exact* when its whole content hashes to nes20db's; where a
    set's PRG and CHR are the entry's and only the miscellaneous-ROM area is
    not (another dump of the INST ROM or the PROM), the image is written with
    MAME's area and its record says so (``"misc": "MAME's"``): the game is the
    one nes20db describes, and the PROM is the one MAME's BIOS run accepts.
    """
    sets = {}
    for name in vs_sets(SOURCE):
        data = read_set(name, roms)
        if data is None or "prg" not in data["regions"]:
            continue  # playch10 itself: the BIOS alone
        data["prg"] = b"".join(part for _, part in data["regions"]["prg"])
        data["chr"] = b"".join(part for _, part in data["regions"].get("gfx2", []))
        data["misc"] = misc_area(data["regions"])
        sets[name] = data
    images, missing = [], []
    for entry in vs_entries(console="2"):
        best = None
        for name, data in sets.items():
            if data["misc"] is None:
                continue
            for prg_label, prg in prg_candidates(data["prg"], entry["prg_size"]).items():
                if len(prg) != entry["prg_size"] or sha1(prg) != entry["prg_sha1"]:
                    continue
                for chr_label, chr_ in chr_candidates(data["chr"], entry["chr_size"]).items():
                    if len(chr_) != entry["chr_size"]:
                        continue
                    if chr_ and sha1(chr_) != entry["chr_sha1"]:
                        continue
                    exact = sha1(data["misc"]) == entry["misc_sha1"]
                    if best is None or (exact and not best[0]):
                        best = (exact, name, prg_label, chr_label, prg, chr_)
        if best is None or (not best[0] and entry["misc_size"] != len(sets[best[1]]["misc"])):
            missing.append(entry)  # no set, or a dump nes20db files as lacking its PROM
            continue
        exact, name, prg_label, chr_label, prg, chr_ = best
        data = sets[name]
        image = header(entry) + prg + chr_ + data["misc"]
        assert not exact or sha1(image[16:]) == entry["rom_sha1"], entry["name"]
        images.append(
            {
                "entry": entry,
                "set": name,
                "description": data["description"],
                "dips": data["dips"],
                "prg": prg_label,
                "chr": chr_label,
                "misc": "nes20db's" if exact else "MAME's",
                "image": image,
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
        if name in names:
            name = f"{name} [{entry['folder'].rsplit('/', 1)[-1]}]"
        names.add(name)
        record = {
            "file": f"{name}.nes",
            "set": image["set"],
            "description": image["description"],
            "dips": image["dips"],
            "prg": image["prg"],
            "chr": image["chr"],
            "misc": image["misc"],
            **{key: entry[key] for key in ("mapper", "submapper", "mirroring", "expansion")},
        }
        manifest.append(record)
        print(
            f"{record['file']:58} {image['set']:10} mapper {entry['mapper']:3}.{entry['submapper']}"
            f" {entry['mirroring']} device {entry['expansion']:2}"
            f" [{image['prg']}; {image['chr']}; misc {image['misc']}]"
        )
        if not args.list:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / record["file"]).write_bytes(image["image"])
    for entry in missing:
        print(
            f"no set for: {entry['folder']}/{entry['name']} "
            f"(PRG {entry['prg_sha1']}, misc {entry['misc_size']} bytes)"
        )
    used = {record["set"] for record in manifest}
    exact = sum(record["misc"] == "nes20db's" for record in manifest)
    print(
        f"{len(images)} of {len(images) + len(missing)} nes20db PlayChoice-10 images assembled "
        f"({exact} whole to nes20db's hash, {len(images) - exact} with MAME's INST ROM and PROM) "
        f"from {len(used)} of {len(sets)} MAME sets; sets matching nothing: "
        + (", ".join(sorted(set(sets) - used)) or "none")
    )
    if not args.list:
        (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
