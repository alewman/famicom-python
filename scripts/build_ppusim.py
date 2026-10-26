#!/usr/bin/env python3
"""Build Breaknes's PPUSim with our shim into reference/build-ppusim/libppusim.so.

PPUSim (gate-level RP2C02G, CC0-1.0) comes from the pinned breaknes checkout in
reference/src/breaknes (scripts/pinned_repos.json); the shim,
scripts/ppusim/ppusim_shim.cpp, is ours. The result is a build product under
reference/, never committed. Needs g++ with C++20; about a minute with -j.

    python scripts/build_ppusim.py
    python scripts/build_ppusim.py --source ../breaknes --out reference/build-ppusim-patched

``--source`` builds another breaknes checkout (a candidate upstream patch) into
``--out``; point the adapter at it with ``PPUSIM_LIBRARY=<out>/libppusim.so``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREAKNES = ROOT / "reference" / "src" / "breaknes"
OUT = ROOT / "reference" / "build-ppusim"
LIBRARY = OUT / "libppusim.so"
SHIM = ROOT / "scripts" / "ppusim" / "ppusim_shim.cpp"
FLAGS = ["-std=c++20", "-O2", "-fPIC", "-w"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=BREAKNES, help="a breaknes checkout")
    parser.add_argument("--out", type=Path, default=OUT, help="the build directory")
    args = parser.parse_args()
    breaknes, out = args.source.resolve(), args.out.resolve()
    if not breaknes.exists():
        print("reference/src/breaknes missing: python scripts/fetch_references.py", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    library = out / LIBRARY.name
    ppusim = breaknes / "Chips" / "PPUSim"
    logic = breaknes / "Common" / "BaseLogicLib"
    sources = sorted(ppusim.glob("*.cpp")) + sorted(logic.glob("*.cpp"))
    includes = ["-I", str(ppusim), "-I", str(logic)]

    def compile_one(source: Path) -> Path:
        obj = out / f"{source.parent.name}_{source.stem}.o"
        if not obj.exists() or obj.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["g++", *FLAGS, *includes, "-c", str(source), "-o", str(obj)], check=True
            )
        return obj

    with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as pool:
        objects = list(pool.map(compile_one, sources))
    shim = out / "ppusim_shim.o"
    subprocess.run(["g++", *FLAGS, *includes, "-c", str(SHIM), "-o", str(shim)], check=True)
    subprocess.run(
        ["g++", "-shared", "-o", str(library), *map(str, objects), str(shim)], check=True
    )
    print(f"built {library}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
