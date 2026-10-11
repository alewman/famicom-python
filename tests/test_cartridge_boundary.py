"""Mappers know the console only through the connector (docs/cartridge.md)."""

from __future__ import annotations

import ast
from pathlib import Path

CARTRIDGE = Path(__file__).resolve().parents[1] / "src" / "famicom_python" / "cartridge"


def test_cartridge_modules_import_nothing_of_the_board() -> None:
    offenders = []
    for module in sorted(CARTRIDGE.glob("*.py")):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.ImportFrom):
                name = node.module or ""
                if node.level > 1 or name.startswith("famicom_python"):
                    offenders.append(f"{module.name}: from {'.' * node.level}{name}")
            elif isinstance(node, ast.Import):
                offenders += [
                    f"{module.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("famicom_python")
                ]
    assert not offenders, offenders
