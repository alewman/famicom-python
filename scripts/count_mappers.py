#!/usr/bin/env python3
"""Count iNES / NES 2.0 mapper usage across the local No-Intro NES sets.

Read-only: opens each zip, streams the first 16 bytes of each .nes member,
never extracts to disk. Usage: nice python3 scripts/count_mappers.py > coverage.txt
(also writes coverage.json in the current directory). Results: docs/cartridge.md.
"""

from __future__ import annotations

import collections
import json
import re
import sys
import zipfile
from pathlib import Path

BASE = Path("/data/emu/source/myrient.erista.me/files/No-Intro")
SETS = [
    "Nintendo - Nintendo Entertainment System (Headered)",
    "Nintendo - Nintendo Entertainment System (Headered) (Aftermarket)",
    "Nintendo - Nintendo Entertainment System (Headered) (Private)",
    "2024 - Nintendo - Nintendo Entertainment System (Headered)",
]
NONLICENSED = re.compile(
    r"\((Unl|Aftermarket|Pirate|Proto( \d+)?|Beta( \d+)?|Sample|Demo|Program|Hack)\)"
)
CLASS_TAGS = ["Unl", "Pirate", "Aftermarket", "Proto", "Beta", "Sample", "Demo", "Program"]


def classify(name: str) -> str:
    tags = re.findall(r"\(([^)]*)\)", name)
    for wanted in ["Pirate", "Unl", "Aftermarket", "Proto", "Beta", "Sample", "Demo", "Program"]:
        if any(t == wanted or t.startswith(wanted + " ") for t in tags):
            return wanted
    return "licensed"


def parse(h: bytes) -> dict:
    if h[:4] != b"NES\x1a":
        return {"format": "bad-magic"}
    nes2 = (h[7] & 0x0C) == 0x08
    mapper = (h[6] >> 4) | (h[7] & 0xF0)
    d = {
        "format": "NES2.0" if nes2 else ("iNES-dirty" if any(h[12:16]) else "iNES"),
        "mapper": mapper,
        "sub": None,
        "prg16": h[4],
        "chr8": h[5],
        "vmirror": bool(h[6] & 1),
        "battery": bool(h[6] & 2),
        "trainer": bool(h[6] & 4),
        "fourscreen": bool(h[6] & 8),
        "console": h[7] & 3,
    }
    if nes2:
        d["mapper"] = mapper | ((h[8] & 0x0F) << 8)
        d["sub"] = h[8] >> 4
        d["prgram"] = h[10] & 0x0F
        d["prgnvram"] = h[10] >> 4
        d["chrram"] = h[11] & 0x0F
        d["chrnvram"] = h[11] >> 4
        d["timing"] = h[12] & 3
        d["exp"] = h[15] & 0x3F
        d["misc"] = h[14] & 3
    return d


def walk(folder: Path):
    for zpath in sorted(folder.glob("*.zip")):
        try:
            with zipfile.ZipFile(zpath) as z:
                members = [
                    i
                    for i in z.infolist()
                    if i.filename.lower().endswith((".nes", ".fds", ".unf", ".unif"))
                ]
                if not members:
                    yield zpath.stem, None, [i.filename for i in z.infolist()]
                for info in members:
                    with z.open(info) as f:
                        head = f.read(16)
                    yield zpath.stem, info.filename, head
        except zipfile.BadZipFile:
            yield zpath.stem, None, "badzip"


def base_title(name: str) -> str:
    return name.split(" (")[0].strip().lower()


def curve(counter: collections.Counter, total: int, label: str, out):
    cum = 0
    print(f"\n### {label}: {total} entries, {len(counter)} distinct", file=out)
    print("| rank | mapper | count | % | cum % |", file=out)
    print("|---|---|---|---|---|", file=out)
    marks = {}
    for rank, (m, n) in enumerate(counter.most_common(), 1):
        cum += n
        pct = 100 * cum / total
        for t in (80, 90, 95, 98, 99, 100):
            if pct >= t - 1e-9 and t not in marks:
                marks[t] = rank
        if rank <= 40:
            print(f"| {rank} | {m} | {n} | {100 * n / total:.2f} | {pct:.2f} |", file=out)
    print(
        "mappers needed to reach: " + ", ".join(f"{t}% -> {r}" for t, r in sorted(marks.items())),
        file=out,
    )
    return marks


def main():
    out = sys.stdout
    summary = {}
    for setname in SETS:
        folder = BASE / setname
        if not folder.is_dir():
            continue
        rows = []
        oddities = collections.Counter()
        for zname, member, head in walk(folder):
            if member is None:
                oddities[
                    f"no-rom-member:{head if isinstance(head, str) else ','.join(head)[:60]}"
                ] += 1
                continue
            if not member.lower().endswith(".nes"):
                oddities[f"ext:{Path(member).suffix}"] += 1
                continue
            d = parse(head)
            d["name"] = zname
            d["cls"] = classify(zname)
            rows.append(d)
        print(f"\n## {setname}", file=out)
        print(f"zips/members parsed: {len(rows)}; oddities: {dict(oddities)}", file=out)
        fmt = collections.Counter(r["format"] for r in rows)
        print(f"header formats: {dict(fmt)}", file=out)
        cls = collections.Counter(r["cls"] for r in rows)
        print(f"classes: {dict(cls)}", file=out)
        good = [r for r in rows if r["format"] != "bad-magic"]
        cons = collections.Counter(r["console"] for r in good)
        print(f"console type (0 NES/FC,1 VS,2 PC10,3 ext): {dict(cons)}", file=out)
        timing = collections.Counter(r.get("timing") for r in good)
        print(f"NES2.0 timing (0 NTSC,1 PAL,2 multi,3 Dendy): {dict(timing)}", file=out)
        print(
            f"battery: {sum(r['battery'] for r in good)}; trainer: {sum(r['trainer'] for r in good)}; four-screen bit: {sum(r['fourscreen'] for r in good)}; CHR-RAM (chr8==0): {sum(r['chr8'] == 0 for r in good)}",
            file=out,
        )
        exp = collections.Counter(r.get("exp") for r in good)
        print(
            f"default expansion device: {dict(sorted(exp.items(), key=lambda x: -x[1]))}", file=out
        )

        groups = {
            "all": good,
            "licensed": [r for r in good if r["cls"] == "licensed"],
            "non-licensed": [r for r in good if r["cls"] != "licensed"],
        }
        for c in CLASS_TAGS:
            g = [r for r in good if r["cls"] == c]
            if g:
                groups[c] = g
        summary[setname] = {}
        for gname, g in groups.items():
            if not g:
                continue
            ctr = collections.Counter(r["mapper"] for r in g)
            marks = curve(ctr, len(g), f"{setname} / {gname} / dumps by mapper", out)
            summary[setname][gname] = {
                "n": len(g),
                "mappers": dict(ctr.most_common()),
                "marks": marks,
            }
            if gname == "licensed":
                # dedupe by base title: a title counts under its most common mapper
                titles = collections.defaultdict(collections.Counter)
                for r in g:
                    titles[base_title(r["name"])][r["mapper"]] += 1
                tctr = collections.Counter(c.most_common(1)[0][0] for c in titles.values())
                tm = curve(
                    tctr, len(titles), f"{setname} / licensed / unique base titles by mapper", out
                )
                summary[setname]["licensed-titles"] = {
                    "n": len(titles),
                    "mappers": dict(tctr.most_common()),
                    "marks": tm,
                }
                sctr = collections.Counter(
                    f"{r['mapper']}.{r['sub']}" for r in g if r["format"] == "NES2.0"
                )
                print("\n#### licensed mapper.submapper (NES 2.0 headers), top 40", file=out)
                for k, v in sctr.most_common(40):
                    print(f"  {k}: {v}", file=out)
                summary[setname]["licensed-sub"] = dict(sctr.most_common())
                six = sum(1 for r in g if r["mapper"] in (0, 1, 2, 3, 4, 7))
                print(
                    f"\nmappers 0,1,2,3,4,7 cover {six}/{len(g)} = {100 * six / len(g):.2f}% of licensed dumps",
                    file=out,
                )
                sixt = sum(v for k, v in tctr.items() if k in (0, 1, 2, 3, 4, 7))
                print(
                    f"mappers 0,1,2,3,4,7 cover {sixt}/{len(titles)} = {100 * sixt / len(titles):.2f}% of licensed base titles",
                    file=out,
                )
                # PRG-RAM / CHR-RAM / battery by mapper for top mappers
                print("\n#### licensed: per-mapper header features (top 30 mappers)", file=out)
                for m, n in ctr.most_common(30):
                    rs = [r for r in g if r["mapper"] == m]
                    subs = collections.Counter(r["sub"] for r in rs)
                    print(
                        f"  mapper {m}: n={n} battery={sum(r['battery'] for r in rs)} chrram={sum(r['chr8'] == 0 for r in rs)} "
                        f"4scr={sum(r['fourscreen'] for r in rs)} vmirror={sum(r['vmirror'] for r in rs)} subs={dict(subs)} "
                        f"prg16={sorted(collections.Counter(r['prg16'] for r in rs).items())[:8]}",
                        file=out,
                    )
                    if m in (1, 4, 5):
                        ex = [r["name"] for r in rs if r["sub"]][:6]
                        if ex:
                            print(f"      nonzero-sub examples: {ex}", file=out)
    Path("coverage.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
