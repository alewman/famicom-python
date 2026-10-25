#!/usr/bin/env python3
"""Record PPUSim's answers to the C12 scenes for the quick test to replay.

    python scripts/ppusim_goldens.py           # write tests/ppusim_goldens.json.gz
    python scripts/ppusim_goldens.py --check   # only report where ours differs

Runs every scene of ``tests/ppusim_scenes.py`` on a ``ppusim_compare.Pair``
(our PPU and PPUSim, skew 3, fed the same CPU cycles) and keeps PPUSim's
observations; ours are compared on the way, and each case where they differ
is printed. ``tests/test_ppusim_goldens.py`` then replays the scenes on our
PPU alone and holds it to PPUSim's answers, except the cases it lists as
known. Needs the PPUSim build (scripts/build_ppusim.py).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from ppusim_compare import SIM_PIXEL_H, Pair  # noqa: E402
from ppusim_scenes import SCENES, first_difference, observation, scene_rom  # noqa: E402

GOLDENS = ROOT / "tests" / "ppusim_goldens.json.gz"


class Recorder(Pair):
    """A Pair that answers ``observe`` with PPUSim's view, keeping ours alongside."""

    def __init__(self) -> None:
        super().__init__(scene_rom())  # type: ignore[arg-type]
        ours = self.ours
        self.mark: list[tuple[int, int, int]] = []
        self.cartridge.ppu_address = lambda a, t: self.mark.append(  # type: ignore[method-assign]
            (ours.line, ours.dot, a)
        )
        self.results: dict[str, dict] = {}
        self.ours_results: dict[str, dict] = {}

    def trace(self, on: bool) -> None:
        super().trace(on)
        if on:
            self.mark.clear()

    def status(self) -> tuple[int, int]:
        self.idle(3)
        return self.access(2)

    def observe(self, name, lines, ale_line, status=None) -> None:
        picture = self.ours.picture
        trace = self.sim_trace() if lines else []
        pixels = {(e.v, e.h): e.video for e in trace}
        sim_ale, high = {}, False
        for e in trace:
            ale = bool(e.pins & 1)
            if ale and not high and e.v == ale_line and 1 <= e.h < 340:
                sim_ale[e.h] = e.address
            high = ale
        ours_status, sim_status = status if status is not None else (None, None)
        self.results[name] = observation(
            {line: [pixels.get((line, x + SIM_PIXEL_H), -1) for x in range(256)] for line in lines},
            sim_ale,
            sim_status,
        )
        self.ours_results[name] = observation(
            {line: list(picture[line * 256 : line * 256 + 256]) for line in lines},
            {d: a for ln, d, a in self.mark if ln == ale_line and 1 <= d < 340},
            ours_status,
        )


def main() -> int:
    check = "--check" in sys.argv[1:]
    goldens: dict[str, dict] = {}
    differ = 0
    for scene_name, scene in SCENES.items():
        recorder = Recorder()
        scene(recorder)
        for name, sim in recorder.results.items():
            if recorder.ours_results[name] != sim:
                differ += 1
                print(f"differs: {name}: {first_difference(recorder.ours_results[name], sim)}")
        print(f"{scene_name}: {len(recorder.results)} cases", flush=True)
        goldens.update(recorder.results)
    print(f"{differ} of {len(goldens)} cases differ from PPUSim")
    if not check:
        text = json.dumps(goldens, separators=(",", ":"), sort_keys=True)
        GOLDENS.write_bytes(gzip.compress(text.encode(), mtime=0))
        print(f"wrote {GOLDENS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
