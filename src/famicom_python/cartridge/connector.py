"""The cartridge connector, as signals: the only thing a mapper knows of the console.

docs/cartridge.md "The connector" has the pins and the reasons; this is the
protocol milestone 1 settled. A mapper module imports this module and nothing
else of the board (``tests/test_cartridge_boundary.py`` enforces it).

- **One timeline.** Every call carries ``t``, the master-clock tick at which the
  access completes: for a CPU cycle the end of the cycle (M2's fall, when read
  data are latched and a write is done), for a PPU access the dot of its /RD or
  /WR. The board delivers CPU and PPU events in ``t`` order, so a mapper
  counts CPU cycles between PPU events (the MMC3's M2 filter) from the
  timestamps alone. A CPU cycle is ``Machine.timing.cpu_divider`` ticks.
- **What the cartridge sees of the CPU.** Every write, whatever its address
  (MMC5 snoops $2000-$2006 and $4014). Every read of $4020-$FFFF. Reads of
  $0000-$401F only when the mapper sets :attr:`Cartridge.snoops_cpu_reads`:
  no licensed mapper needs them, and they are most of the cycles. A mapper that
  counts M2 cycles and must raise IRQ on an exact cycle sets
  :attr:`Cartridge.counts_m2` and receives :meth:`Cartridge.m2` every cycle;
  the others reconstruct cycle counts from ``t`` when they are next called.
- **"Not driven" is a value**: a read returns ``None`` and the board supplies
  open bus (the CPU data latch, or on the PPU side the address's low byte).
- **Nametables**: the cartridge drives CIRAM /CE and CIRAM A10.
  :meth:`Cartridge.ciram_a10` returns A10 for a PPU address in $2000-$3EFF, or
  ``None`` when the cartridge disables CIRAM and answers itself through
  :meth:`Cartridge.ppu_read` and :meth:`Cartridge.ppu_write`.
- **No reset**: the reset button never reaches the cartridge (MMC5 sees it as a
  gap in M2, which the timestamps show).
"""

from __future__ import annotations


class Cartridge:
    """The connector's defaults: nothing driven, nothing snooped, no IRQ, no sound."""

    snoops_cpu_reads = False  # also receive reads of $0000-$401F
    counts_m2 = False  # receive m2(t) every CPU cycle

    def __init__(self) -> None:
        self.irq = False  # /IRQ, wired-OR on the board: True asserts it

    # -- the CPU side ----------------------------------------------------

    def cpu_read(self, address: int, t: int) -> int | None:
        """The byte the cartridge drives for a CPU read, or None."""
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        """A CPU write; bus conflicts (value AND the ROM byte) are the mapper's."""

    def m2(self, t: int) -> None:
        """One CPU cycle ended at ``t`` (only when :attr:`counts_m2` is set)."""

    # -- the PPU side ----------------------------------------------------

    def ppu_address(self, address: int, t: int) -> None:
        """The PPU put ``address`` on its bus (ALE), rendering or not."""

    def ciram_a10(self, address: int) -> int | None:
        """CIRAM A10 for a nametable address, or None to disable CIRAM."""
        return None

    def ppu_read(self, address: int, t: int) -> int | None:
        """The byte the cartridge drives for a PPU read, or None."""
        return None

    def ppu_write(self, address: int, value: int, t: int) -> None:
        """A PPU write (palette writes never reach the connector)."""

    # -- outputs the board samples --------------------------------------

    def audio(self, apu_in: float, t: int) -> float:
        """Famicom pin 45 in, pin 46 out: the cartridge may mix its own sound."""
        return apu_in

    def battery_ram(self) -> bytes | None:
        """The battery-backed memory to persist, if any."""
        return None
