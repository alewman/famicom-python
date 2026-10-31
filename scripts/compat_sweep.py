#!/usr/bin/env python3
"""Milestone 7's compatibility sweep: every licensed dump, frames against Mesen2's (a detector).

For each licensed No-Intro dump whose mapper the board implements, read in
place from its zip (never extracted), Mesen2 and the board both run from power
with no input, and the board's frames are compared with Mesen2's, pixel value
for pixel value (``mesen_run.configure_for_comparison`` gives Mesen2 an
identity palette). The board runs on Mesen2's power-on
(``mesen_lockstep.MACHINE``), which keeps the two in lockstep instruction for
instruction; Mesen2 counts frames ended and the board frames begun, so
Mesen2's frame N is the board's N - 1 (measured on SMB1 and Zelda). The
board's frame either side is tried as well and reported if it is closer.

    nice pypy3 scripts/compat_sweep.py --jobs 12 [--only REGEX] [--frames 60,300,600]
    nice pypy3 scripts/compat_sweep.py --aftermarket --mappers 30 --every 20

``--aftermarket`` sweeps the Aftermarket set (homebrew, every dump) instead of
the licensed ones, ``--private`` the Private set (homebrew betas and demos,
every dump), ``--unlicensed`` adds the "(Unl)" dumps to the licensed ones,
``--all`` takes every dump of the sets, pirates included,
``--programs`` the test carts and programs (No-Intro's
"(Program)" and "(Test Program)" dumps, of either set); ``--every N`` keeps one
dump in N, in name order.

    nice pypy3 scripts/compat_sweep.py --fds --frames 1200,2400 --slack 12 --jobs 12
    nice pypy3 scripts/compat_sweep.py --machine pal --only Europe --out PAL.jsonl

``--machine pal`` runs both on PAL (Mesen2's region, the board's PAL row on
Mesen2's power-on, ``mesen_lockstep.lockstep_machine``), PAL's border left out
of the comparison (the board's is PPUSim's, docs/validation.md milestone 10).

``--fds`` sweeps the licensed Famicom Disk System dumps (milestone 9): both
sides get the BIOS (FAMICOM_FDS_BIOS or No-Intro's) and neither changes disks
(Mesen2's automatic insertion is off by default), so each runs its first side.
A disk load's timing is not judged (C39): ``--slack N`` searches N of the
board's frames either side. Every run lists its dumps that differ in
``failures.txt`` beside ``--out``; ``--list FILE`` runs only the dumps named
there, the quick sweep while fixing.

One line of JSON per dump in ``--out`` (appended; dumps already there are
skipped, so an interrupted sweep resumes), and Mesen2's first differing frame
as a PNG, differing pixels magenta, beside it. Nothing it writes is committed.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from count_mappers import BASE, classify
from mesen_lockstep import lockstep_machine, mesen_path
from mesen_run import FRAMES_LUA, REGIONS, ROOT, decode_frames, run_mesen

from famicom_python.cartridge import MAPPERS, fds_bios
from famicom_python.ppu import HEIGHT
from famicom_python.system import System
from famicom_python.video import load_palette, write_png

SETS = [
    "Nintendo - Nintendo Entertainment System (Headered)",
    "2024 - Nintendo - Nintendo Entertainment System (Headered)",
]
AFTERMARKET = "Nintendo - Nintendo Entertainment System (Headered) (Aftermarket)"
PRIVATE = "Nintendo - Nintendo Entertainment System (Headered) (Private)"
FDS_SET = "Nintendo - Family Computer Disk System (FDS)"
OUT = ROOT / "tests" / "mame_traces" / "sweep"
WIDTH, PIXELS = 256, 256 * HEIGHT


def disk_dumps(only: str | None) -> list[Path]:
    """Every licensed dump of the FDS set (the BIOS left out)."""
    return [
        path
        for path in sorted((BASE / FDS_SET).glob("*.zip"))
        if not path.stem.startswith("[BIOS]")
        and classify(path.stem) == "licensed"
        and not (only and not re.search(only, path.stem))
    ]


def licensed_dumps(
    only: str | None,
    mappers: set[int] | None = None,
    every_dump_of: str | None = None,
    programs: bool = False,
    unlicensed: bool = False,
    every_kind: bool = False,
) -> list[Path]:
    """Every licensed dump of ``SETS`` (or every dump of the set
    ``every_dump_of``) whose header names an implemented mapper (of ``mappers``);
    ``unlicensed`` adds the sets' "(Unl)" dumps (not the pirates), ``every_kind``
    every dump: pirates, prototypes, betas and demos too.

    The 2024 set renames many of the other's dumps; a dump whose .nes CRC (from
    the zip's directory) an earlier set already gave is skipped.
    """
    found, seen = [], set()
    for name in [every_dump_of] if every_dump_of else SETS:
        for path in sorted((BASE / name).glob("*.zip")):
            if programs:
                wanted = "(Program)" in path.stem or "(Test Program)" in path.stem
            else:
                kind = classify(path.stem)
                wanted = every_dump_of is not None or every_kind or kind == "licensed"
                wanted = wanted or (unlicensed and kind == "Unl")
            if not wanted or (only and not re.search(only, path.stem)):
                continue
            with zipfile.ZipFile(path) as archive:
                members = [n for n in archive.namelist() if n.lower().endswith(".nes")]
                if len(members) != 1:
                    continue
                crc = archive.getinfo(members[0]).CRC
                header = archive.open(members[0]).read(16)
            if crc in seen:
                continue
            seen.add(crc)
            mapper = (header[6] >> 4) | (header[7] & 0xF0) | ((header[8] & 0x0F) << 8)
            if mapper in MAPPERS and (mappers is None or mapper in mappers):
                found.append(path)
    return found


def mesen_frames(rom: Path, frames: list[int], home: Path, region: int = 1) -> dict[int, list[int]]:
    if rom.name.lower().endswith((".fds", ".fds.zip")) or rom.parent.name == FDS_SET:
        (home / "Firmware").mkdir(exist_ok=True)
        (home / "Firmware" / "disksys.rom").write_bytes(fds_bios())
    lua = FRAMES_LUA % (", ".join(f"[{f}]=true" for f in frames), max(frames))
    lines: dict[str, str] = {}
    run_mesen(
        mesen_path(rom),
        lua=lua.encode(),
        lua_name="frames.lua",
        seconds=600,
        home=home,
        until="DONE",
        for_comparison=True,
        region=region,
        collect=lines,
    )
    return decode_frames(lines)


def unswap_emphasis(value: int) -> int:
    """Mesen2 reports PAL emphasis by channel (bits 6 and 7 exchanged); the board's
    picture keeps $2001's bits as written (machine.Timing.swapped_emphasis)."""
    return (value & ~0xC0) | (value & 0x40) << 1 | (value & 0x80) >> 1


def finished_picture(system: System) -> list[int]:
    """The frame just begun, once its 240 rows are drawn (as scripts/mesen_frames.py)."""
    ppu = system.board.ppu
    while not HEIGHT <= ppu.line < ppu.prerender_line:
        system.step()
    return list(ppu.picture)


def check(rom: Path, frames: list[int], slack: int = 1, machine_name: str = "nes") -> dict:
    result: dict = {"rom": rom.name, "set": rom.parent.name}
    machine = lockstep_machine(machine_name, None)
    border = machine.timing.border
    # PAL's border (line 0, x 0-1 and 254-255) is not compared.
    keep = [i for i in range(PIXELS) if not (border and (i < 256 or i % 256 in (0, 1, 254, 255)))]
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mesen-home-") as home:
        # A fresh home each run: Mesen2 keeps battery saves there. Its own log
        # (every uninitialized RAM read) goes to the process's output: drop it.
        saved = os.dup(1), os.dup(2)
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 1), os.dup2(null, 2)
        try:
            theirs = mesen_frames(rom, frames, Path(home), REGIONS[machine.timing.name])
            if machine.timing.swapped_emphasis:
                theirs = {f: [unswap_emphasis(v) for v in p] for f, p in theirs.items()}
        finally:
            os.dup2(saved[0], 1), os.dup2(saved[1], 2)
    result["mesen_seconds"] = round(time.monotonic() - began, 1)
    try:
        system = System.from_rom(rom, machine)
    except NotImplementedError as error:
        return result | {"status": "unsupported", "error": str(error)}
    board = system.loaded.image.board
    result["mapper"] = f"{board.mapper}.{board.submapper}"
    began = time.monotonic()
    ours: dict[int, list[int]] = {}
    report = []
    try:
        for frame in frames:
            same = frame - 1  # the board's number for Mesen2's frame
            candidates = tuple(range(same - slack, same + slack + 1))
            for candidate in candidates:
                if candidate not in ours:
                    system.run_frames(candidate - system.board.ppu.frame)
                    ours[candidate] = finished_picture(system)
            if frame not in theirs or len(theirs[frame]) != PIXELS:
                report.append({"frame": frame, "error": "Mesen2 gave no 256x240 frame"})
                continue
            want = theirs[frame]
            counts = {c: sum(ours[c][i] != want[i] for i in keep) for c in candidates}
            best = min(counts, key=lambda c: (counts[c], c != same))
            entry = {"frame": frame, "diff": counts[same]}
            if counts[best] < counts[same]:
                entry |= {"closest": best - same, "closest_diff": counts[best]}
            report.append(entry)
    except Exception as error:  # a board crash is a finding, not a sweep failure
        result |= {"status": "crash", "error": f"{type(error).__name__}: {error}"}
    result["board_seconds"] = round(time.monotonic() - began, 1)
    result["frames"] = report
    result["instructions"] = system.instructions
    if "status" not in result:
        # A frame matches if any board frame within the slack does.
        differing = [e for e in report if e.get("closest_diff", e.get("diff", 1))]
        result["status"] = "differs" if differing else "identical"
        if differing and "diff" in differing[0]:
            first = differing[0]
            frame = first["frame"]
            best = frame - 1 + first.get("closest", 0)
            save_diff(OUT / f"{rom.stem}.f{frame}.png", ours[best], theirs[frame])
    return result


def save_diff(path: Path, ours: list[int], theirs: list[int]) -> None:
    colours = load_palette()
    write_png(
        path,
        b"".join(
            b"\xff\x00\xff" if a != b else colours[b & 0x1FF]
            for a, b in zip(ours, theirs, strict=True)
        ),
    )


def worker(job: tuple[str, list[int], int, str]) -> str:
    rom, frames, slack, machine = job
    try:
        return json.dumps(check(Path(rom), frames, slack, machine))
    except BaseException as error:  # recorded; the sweep goes on
        return json.dumps({"rom": Path(rom).name, "status": "error", "error": repr(error)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", default="60,300,600", help="Mesen2's frame counts")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--only", help="regular expression on the dump's name")
    parser.add_argument("--mappers", help="comma-separated iNES mapper numbers")
    parser.add_argument("--out", type=Path, default=OUT / "results.jsonl")
    parser.add_argument("--aftermarket", action="store_true", help="the Aftermarket set instead")
    parser.add_argument("--private", action="store_true", help="the Private set instead")
    parser.add_argument("--unlicensed", action="store_true", help="add the (Unl) dumps")
    parser.add_argument("--all", action="store_true", help="every dump of the sets, pirates too")
    parser.add_argument("--every", type=int, default=1, help="keep one dump in N")
    parser.add_argument("--fds", action="store_true", help="the licensed FDS set instead")
    parser.add_argument("--slack", type=int, default=1, help="board frames tried either side")
    parser.add_argument("--list", type=Path, help="only the dumps named in this file")
    parser.add_argument("--machine", choices=("nes", "pal"), default="nes")
    parser.add_argument(
        "--programs", action="store_true", help="the test carts and programs instead"
    )
    args = parser.parse_args()
    frames = sorted(int(f) for f in args.frames.split(","))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        done = {json.loads(line)["rom"] for line in args.out.read_text().splitlines() if line}
    mappers = {int(m) for m in args.mappers.split(",")} if args.mappers else None
    if args.fds:
        roms = disk_dumps(args.only)[:: args.every]
    else:
        every_dump_of = AFTERMARKET if args.aftermarket else PRIVATE if args.private else None
        roms = licensed_dumps(
            args.only, mappers, every_dump_of, args.programs, args.unlicensed, args.all
        )
        roms = roms[:: args.every]
    if args.list:
        wanted = {line.strip() for line in args.list.read_text().splitlines() if line.strip()}
        roms = [r for r in roms if r.name in wanted]
    roms = [r for r in roms if r.name not in done]
    print(f"{len(roms)} dumps to run ({len(done)} already in {args.out})", flush=True)
    # One process per dump: MesenCore keeps global state between loads.
    context = multiprocessing.get_context("spawn")
    with context.Pool(args.jobs, maxtasksperchild=1) as pool, args.out.open("a") as out:
        jobs = [(str(r), frames, args.slack, args.machine) for r in roms]
        for count, line in enumerate(pool.imap_unordered(worker, jobs), 1):
            out.write(line + "\n")
            out.flush()
            entry = json.loads(line)
            print(f"[{count}/{len(roms)}] {entry['status']:10} {entry['rom']}", flush=True)
    results = [json.loads(line) for line in args.out.read_text().splitlines() if line]
    failing = sorted(r["rom"] for r in results if r["status"] != "identical")
    (args.out.parent / "failures.txt").write_text("".join(f"{name}\n" for name in failing))
    print(f"{len(failing)} of {len(results)} not identical: {args.out.parent / 'failures.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
