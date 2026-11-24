# SPDX-License-Identifier: MIT
"""Find Mesen2's old in-process driver, a GPL tool outside this repository (docs/provenance.md).

Most Mesen2 runs now go through the family's mesen2-runner as a separate program
(scripts/mesen2_tool.py). Four scripts still need what that tool does not offer yet, and keep
importing the old driver (``mesen_run``) in process, from its documented path in emu-tools-gpl,
``$EMU_TOOLS_GPL/tools/famicom-python/`` (emu-tools' contract, section 5):

- ``mesen_accuracycoin.py`` and ``vs_judge.py``: they collect Lua log lines as they pass, more
  than the last 500 that Mesen2's script log keeps;
- ``provenance_probes.py``: the Famicom Disk System BIOS, written into Mesen2's home (the tool
  takes no BIOS input yet);
- ``compat_sweep.py``: several runs in one invocation, and MesenCE as a second library.

Importing this module puts that folder on ``sys.path`` and tells the driver where this checkout
is (``FAMICOM_PYTHON_ROOT``); without ``EMU_TOOLS_GPL``, or without the folder, it stops with exit
status 3 (a missing input) naming what it expected.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("FAMICOM_PYTHON_ROOT", str(Path(__file__).resolve().parents[1]))

_ROOT = os.environ.get("EMU_TOOLS_GPL")
TOOLS = str(Path(_ROOT or "$EMU_TOOLS_GPL") / "tools" / "famicom-python")
if not _ROOT or not (Path(TOOLS) / "mesen_run.py").is_file():
    print(
        f"Mesen2's driver not found at {TOOLS}/mesen_run.py: set EMU_TOOLS_GPL to a checkout "
        "of emu-tools-gpl (a GPL tool kept outside this repository)",
        file=sys.stderr,
    )
    sys.exit(3)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
