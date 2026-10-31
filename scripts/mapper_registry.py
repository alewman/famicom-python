#!/usr/bin/env python3
"""Generate docs/mappers.md's registry: one row for every mapper, implemented or not.

    NO_INTRO_DIR=... python scripts/mapper_registry.py --results tests/mame_traces/sweep-final

For each mapper number found in the No-Intro sets or in ``MAPPERS``: the class and
module, how many dumps use it, what the last sweep said, where its description
came from (read from its docstrings, so it is what the code itself claims) and
its evidence. Writes between the markers in docs/mappers.md, and
tests/sweep_failures.tsv, the sweep's non-identical dumps, which are also the next
quick-sweep list (`compat_sweep.py --list`, first column). ``--results`` is gitignored;
these two files are the record of it that is kept.
"""

from __future__ import annotations

import argparse
import collections
import inspect
import json
import os
import re
import zipfile
from pathlib import Path

from count_mappers import SETS

from famicom_python.cartridge import MAPPERS

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "mappers.md"
FAILURES = ROOT / "tests" / "sweep_failures.tsv"
BEGIN, END = "<!-- registry begin -->", "<!-- registry end -->"
BASE = Path(os.environ.get("NO_INTRO_DIR", "No-Intro"))
MAIN, AFTERMARKET, PRIVATE = SETS[:3]

#: Mappers with a test ROM that can fail them (docs/claims.md, "Judges passed").
JUDGED = {0, 1, 2, 3, 4, 7, 9, 10, 21, 22, 23, 25, 28, 31, 34, 66, 69, 118, 155}

SOURCES = (
    ("wiki", re.compile(r"\.wiki|the page|wiki", re.I)),
    ("forum", re.compile(r"forum|t=\d+", re.I)),
    ("MAME", re.compile(r"MAME")),
    ("data sheet", re.compile(r"data sheet", re.I)),
    ("the game", re.compile(r"game(s)? decide|its code|the game's|its ROM holds|theirs:", re.I)),
)


def dump_mappers() -> dict[str, tuple[int, str]]:
    """Every dump in the three sets: name to (mapper, set)."""
    dumps = {}
    for name in (MAIN, AFTERMARKET, PRIVATE):
        for path in sorted((BASE / name).glob("*.zip")):
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    with archive.open(member) as file:
                        head = file.read(16)
                    if head[:4] == b"NES\x1a":
                        mapper = head[6] >> 4 | head[7] & 0xF0
                        if head[7] & 0x0C == 8:
                            mapper |= (head[8] & 0x0F) << 8
                        dumps[path.name] = (mapper, name)
    return dumps


def sweep(directory: Path | None) -> list[dict]:
    """The sweep's rows, the last for each dump; two sets can hold different dumps of one name."""
    if not directory:
        return []
    rows = {}
    with (directory / "results.jsonl").open() as file:
        for line in file:
            row = json.loads(line)
            rows[row["rom"], row.get("set")] = row
    return list(rows.values())


def describe(factory) -> tuple[str, str, str]:
    """(class, module, sources) from the class's and module's docstrings."""
    module = inspect.getmodule(factory)
    text = (inspect.getdoc(factory) or "") + " " + (inspect.getdoc(module) or "")
    own = inspect.getdoc(factory) or ""
    found = [name for name, pattern in SOURCES if pattern.search(text)]
    notes = sorted(set(re.findall(r"\bC\d\d\b", own)))
    label = ", ".join(found) or "?"
    return (
        factory.__name__,
        module.__name__.rsplit(".", 1)[-1],
        label + (" (" + ", ".join(notes) + ")" if notes else ""),
    )


def evidence(mapper: int, tally: collections.Counter) -> str:
    if mapper in JUDGED:
        return "judge ROM"
    if tally["identical"]:
        return "matches Mesen2"
    if tally["differs"] or tally["crash"]:
        return "differs, by eye"
    if tally["error"]:
        return "by eye (Mesen2 refuses)"
    return "unit tests only"


def row_mapper(row: dict, dumps: dict) -> int | None:
    """The mapper a row was run as: refused dumps carry none, so the header's."""
    if row.get("mapper") is not None:
        return int(str(row["mapper"]).split(".")[0])
    return dumps.get(row["rom"], (None, ""))[0]


def registry(dumps: dict, rows: list[dict]) -> str:
    sets: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    tallies: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for mapper, name in dumps.values():
        sets[mapper][name] += 1
    for row in rows:
        tallies[row_mapper(row, dumps)][row["status"]] += 1
    lines = [
        "| Mapper | Class | Module | Main | Aftermarket | Private | Identical / differs / "
        "refused | Described by | Evidence |",
        "| ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for mapper in sorted(set(MAPPERS) | set(sets)):
        count, tally = sets[mapper], tallies[mapper]
        swept = f"{tally['identical']} / {tally['differs'] + tally['crash']} / {tally['error']}"
        if mapper in MAPPERS:
            name, module, sources = describe(MAPPERS[mapper])
            proof = evidence(mapper, tally)
        else:
            name, module, sources, proof = "**not implemented**", "", "", ""
            swept = ""
        lines.append(
            f"| {mapper} | {name} | {module} | {count[MAIN]} | {count[AFTERMARKET]} "
            f"| {count[PRIVATE]} | {swept} | {sources} | {proof} |"
        )
    return "\n".join(lines)


def write_failures(dumps: dict, rows: list[dict]) -> int:
    lines = ["# rom\tmapper\tstatus\tdiff at frames 60, 300, 600"]
    for row in sorted(rows, key=lambda r: (r["rom"], str(r.get("set")))):
        if row["status"] != "identical":
            frames = ",".join(str(f.get("diff", "?")) for f in row.get("frames", []))
            lines.append(f"{row['rom']}\t{row_mapper(row, dumps)}\t{row['status']}\t{frames}")
    FAILURES.write_text("\n".join(lines) + "\n")
    return len(lines) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    dumps = dump_mappers()
    rows = sweep(args.results)
    text = DOC.read_text()
    start, end = text.index(BEGIN) + len(BEGIN), text.index(END)
    DOC.write_text(text[:start] + "\n\n" + registry(dumps, rows) + "\n\n" + text[end:])
    if rows:
        print(write_failures(dumps, rows), "non-identical of", len(rows))


if __name__ == "__main__":
    main()
