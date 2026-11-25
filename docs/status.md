<!-- SPDX-License-Identifier: MIT -->
# Status

The specification tier of the NES line (famicom-python → famicom-rust →
famicom-rust-fast). The full certification record, with every suite, pin and
seeded fault, is [validation.md](validation.md#certification-record); this page
is the gate a change must pass and the counts it was last measured at.

## The gate

| Step | Command | Count | Measured at |
| --- | --- | --- | --- |
| Lint | `ruff check .` and `ruff format --check .` | clean, 153 files | `fa30248`, 2026-11-24 |
| Quick suite (PyPy, CI's) | `PYPY_GC_NURSERY=1M nice .venv-pypy/bin/python -m pytest -q` | 347 passed, 205 deselected (with `MAME_ROMPATH` set and `PC10_IMAGES_DIR` naming `scripts/pc10_images.py`'s output; without the BIOS, 346 and 1 skipped) | `fa30248`, 2026-11-24 |
| The PlayChoice-10's slow cases | `pytest -m slow tests/test_playchoice.py` | 2 of 2 | `c52a6d3`, 2026-11-23 |
| The slow suites (CPU, PPU, APU, mappers) | `pytest -m slow`, `scripts/run_test_roms.py --suite ...` | not rerun on 2026-11-23 (no behaviour changed; see validation.md for the last full run) | |

## What changed on 2026-11-24

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
