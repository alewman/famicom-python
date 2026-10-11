"""A readable, pure-Python Famicom and NES, built on 6502-python."""

from famicom_python.machine import MACHINES, NES_001, Machine
from famicom_python.system import System

__all__ = ["MACHINES", "NES_001", "Machine", "System"]
