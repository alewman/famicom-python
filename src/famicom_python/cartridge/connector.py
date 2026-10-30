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
- **What the cartridge sees of the PPU.** Every /RD and /WR, with its address.
  The address phase of each access (ALE: rendering fetches, and v whenever a
  $2006 write or $2007 access moves it outside rendering) only when the mapper
  sets :attr:`Cartridge.watches_ppu_address`: MMC3 counts A12 rises in it,
  MMC5 counts repeated nametable addresses, and the others never look. The
  rendering fetches are about 4 million address phases a second.
- **"Not driven" is a value**: a read returns ``None`` and the board supplies
  open bus (the CPU data latch, or on the PPU side the address's low byte).
  A CPU read that drives only some data lines returns ``driven | undriven <<
  8``, the high byte the mask of lines left to open bus (Bandai's EEPROM
  port drives D4 alone; added in milestone 7, docs/cartridge.md). A mapper
  whose register latches the data bus on reads as on writes (GTROM's 74377)
  sets :attr:`Cartridge.latches_reads` and receives
  :meth:`Cartridge.read_data`, the byte on the bus as M2 falls, after every
  read of $4020-$FFFF.
- **Nametables**: the cartridge drives CIRAM /CE and CIRAM A10.
  :meth:`Cartridge.ciram_a10` returns A10 for a PPU address in $2000-$3EFF, or
  ``None`` when the cartridge disables CIRAM and answers itself through
  :meth:`Cartridge.ppu_read` and :meth:`Cartridge.ppu_write`.
- **No reset**: the reset button never reaches the cartridge (MMC5 sees it as a
  gap in M2, which the timestamps show).
- **Sound** (milestone 8): a mapper with a sound chip sets
  :attr:`Cartridge.expansion_audio`; on a console that routes the 2A03's sound
  through the cartridge (the Famicom's pins 45/46) the board connects
  :attr:`Cartridge.audio_out`, and the chip sets its ``expansion`` level, in
  the APU mixer's units, each time its output moves. The level includes the
  board's mix resistors: :func:`expansion_gain`. Elsewhere (the NES-001) the
  sound goes nowhere, as on the console.
"""

from __future__ import annotations

#: A full-volume APU square, alone, in the mixer's units (APU_Mixer.wiki:
#: 95.88 / (8128 / 15 + 100)).
APU_SQUARE = 95.88 / (8128 / 15 + 100)


def expansion_gain(db: float, full_square: int) -> float:
    """Mixer units per step of a chip whose full-volume square is ``full_square``
    steps and sounds ``db`` dB against a full-volume APU square (the measured
    mix levels, docs/undocumented-behavior.md)."""
    return APU_SQUARE * 10 ** (db / 20) / full_square


class Unplugged:
    """Where a chip's sound goes when the console does not route it (or before
    the board connects it)."""

    expansion = 0.0


class Cartridge:
    """The connector's defaults: nothing driven, nothing snooped, no IRQ, no sound."""

    snoops_cpu_reads = False  # also receive reads of $0000-$401F
    counts_m2 = False  # receive m2(t) every CPU cycle
    latches_reads = False  # receive read_data() after reads of $4020-$FFFF
    watches_ppu_address = False  # receive ppu_address(address, t) on every ALE
    expansion_audio = False  # has a sound chip: the board may connect audio_out

    def __init__(self) -> None:
        self.irq = False  # /IRQ, wired-OR on the board: True asserts it
        self.audio_out: Unplugged = Unplugged()  # the APU, on a Famicom

    # -- the CPU side ----------------------------------------------------

    def cpu_read(self, address: int, t: int) -> int | None:
        """The byte the cartridge drives for a CPU read, or None."""
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        """A CPU write; bus conflicts (value AND the ROM byte) are the mapper's."""

    def read_data(self, address: int, value: int, t: int) -> None:
        """The byte on the data bus as a read of ``address`` ($4020-$FFFF) ended,
        whoever drove it (only when :attr:`latches_reads` is set)."""

    def m2(self, t: int) -> None:
        """One CPU cycle ended at ``t`` (only when :attr:`counts_m2` is set)."""

    # -- the PPU side ----------------------------------------------------

    def ppu_address(self, address: int, t: int) -> None:
        """The PPU put ``address`` on its bus (ALE), rendering or not.

        Only for a mapper that sets :attr:`watches_ppu_address`.
        """

    def ciram_a10(self, address: int) -> int | None:
        """CIRAM A10 for a nametable address, or None to disable CIRAM."""
        return None

    def ppu_read(self, address: int, t: int) -> int | None:
        """The byte the cartridge drives for a PPU read, or None."""
        return None

    def ppu_write(self, address: int, value: int, t: int) -> None:
        """A PPU write (palette writes never reach the connector)."""

    # -- outputs the board samples --------------------------------------

    def battery_ram(self) -> bytes | None:
        """The battery-backed memory to persist, if any."""
        return None

    def restore_battery(self, data: bytes) -> bool:
        """Put back what :meth:`battery_ram` returned on an earlier run; False
        (and nothing changed) if this cartridge keeps no such memory."""
        return False
