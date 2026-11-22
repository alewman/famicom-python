# SPDX-License-Identifier: MIT
"""Find the GPL tools kept outside this repository (docs/provenance.md).

Mesen2's ctypes driver (``mesen_run.py``, and ``mesen_audio.py`` beside it) and the Mesen2
patch (``mesen2-detector-fixes.patch``) are GPL tools: they left this repository with its
history rewrite of 2026-11-21 and are kept with the family's other GPL tools. Importing this
module puts the directory named by ``FAMICOM_GPL_TOOLS`` on ``sys.path``, so the scripts that
drive Mesen2 as a closed box find ``mesen_run``, and tells the tools where this checkout is
(``FAMICOM_PYTHON_ROOT``).
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("FAMICOM_PYTHON_ROOT", str(Path(__file__).resolve().parents[1]))

TOOLS = os.environ.get("FAMICOM_GPL_TOOLS")
if TOOLS and TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
