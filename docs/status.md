<!-- SPDX-License-Identifier: MIT -->
# Status

The specification tier of the NES line (famicom-python → famicom-rust →
famicom-rust-fast). The full certification record, with every suite, pin and
seeded fault, is [validation.md](validation.md#certification-record); this page
is the gate a change must pass and the counts it was last measured at.

## The gate

| Step | Command | Count | Measured at |
| --- | --- | --- | --- |
| Lint | `ruff check .` and `ruff format --check .` | clean, 152 files (153 until `gpl_tools.py` left) | the Mesen2 move, 2026-11-24 |
| Quick suite (PyPy, CI's) | `PYPY_GC_NURSERY=1M nice .venv-pypy/bin/python -m pytest -q` | 347 passed, 205 deselected (with `MAME_ROMPATH` set and `PC10_IMAGES_DIR` naming `scripts/pc10_images.py`'s output; without the BIOS, 346 and 1 skipped) | `fa30248`, and again at the Mesen2 move, 2026-11-24 |
| The PlayChoice-10's slow cases | `pytest -m slow tests/test_playchoice.py` | 2 of 2 | `c52a6d3`, 2026-11-23 |
| The slow suites (CPU, PPU, APU, mappers) | `pytest -m slow`, `scripts/run_test_roms.py --suite ...` | not rerun on 2026-11-23 (no behaviour changed; see validation.md for the last full run) | |

## What changed on 2026-11-24

- Mesen2 only as a program: `mesen_accuracycoin.py`, `vs_judge.py`,
  `provenance_probes.py` and `compat_sweep.py` no longer import the old driver
  (`$EMU_TOOLS_GPL/tools/famicom-python/mesen_run.py`); they run mesen2-runner 0.2.0
  (`$EMU_TOOLS_GPL/tools/mesen2/run.py --machine nes`: `--lua` and its complete script
  log, `--frames-at`, `--fds-bios`) through `scripts/mesen2_tool.py`, as the frames and
  lockstep scripts already did. `scripts/gpl_tools.py` left the tree (no users). No
  behaviour changed; the gate, old driver against the new runs on the same library
  (`reference/build-mesen2`, sha1 `c48cfc76`): AccuracyCoin 131 of 147 both ways, the
  same 16 failures and codes (MesenCE: 143 of 147 both ways); the seven provenance
  probes' 1,024 bytes each and `--fds-ready` (50,043 cycles) identical; `vs_judge.py
  --probe` on three games identical; compat_sweep samples identical row for row
  (timings left out): Vs. 11 (`--every 6`), PlayChoice-10 7 (`--every 8`), FDS 5
  (`--every 60`), licensed 89 (`--every 30`: 18 mappers, 14 on PAL; 87 identical, 2
  differ, their diff pictures byte-identical). HEAD's `compat_sweep.py` and
  `provenance_probes.py --fds-ready` had not run since `1d64fd9` (a `mesen_path` import
  that commit removed); the baseline restored it outside the repository. Values OBSERVED
  (Mesen2 b9fa69d via mesen2-runner 0.2.0).
- `fa30248`: `tests/pc10_watchdog.hex`, a supervisor program of our own (no
  firmware) in the BIOS program's place, lets the PlayChoice-10's watchdog run
  out every boot, which the real BIOS never does; one quick test, and famicom-rust's
  lockstep case `pc10-watchdog-Super_Mario_Bros` (validation.md, "The watchdog run
  out"). No behaviour changed. `1d64fd9` and `fb3a045` before it changed tooling
  and documents only.

## What changed on 2026-11-23

- `c52a6d3`: the PlayChoice-10's BIOS is found through `MAME_ROMPATH` (the
  family's variable for MAME's sets; `MAME_ROM_DIR` is gone, nothing documented
  depended on it), and MAME's BSD-3 notice is kept in [NOTICE.md](../NOTICE.md)
  for the tables and values taken from MAME's BSD-3 files (the Vs. protection
  bytes, the RC2C05-01's identifier, the PlayChoice-10 BIOS hashes and screen
  weights, `SUBOR_MATRIX`, `WAIXING_GAL`), the five files holding them marked
  `MIT AND BSD-3-Clause`. No behaviour changed.

## Downstream

famicom-rust transcribes this tree at `fa30248` (whose `src/` is `c52a6d3`'s), the PlayChoice-10 included;
famicom-rust-fast merges famicom-rust. Their README and docs/status.md hold
their gates.
