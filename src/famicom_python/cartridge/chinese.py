"""Chinese, Taiwanese and Korean discrete-logic and simple ASIC boards, each from its NESdev
wiki page.

No judge ROM exists for any of them; the claims rest on sweeps against Mesen2,
a detector (docs/claims.md). The TMS5220-compatible speech chips some
educational cartridges mount are not modelled: their status reads are open bus.
"""

from __future__ import annotations

from dataclasses import replace

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage
from .konami import VRC24
from .mmc1 import MMC1
from .mmc3 import MMC3


class Hengge(Banked):
    """Mappers 241 (BxROM with WRAM) and 177 (Hénggé Diànzǐ's, with mirroring).

    INES_Mapper_241.wiki, _177.wiki: a write to $8000-$FFFF (no bus conflicts:
    241 is mostly a target for mapper hacks that ignore them) selects the 32
    KiB PRG bank. 177 ``WWMPPPPP``: D4-D0 the bank, D5 the mirroring (0
    vertical, 1 horizontal; on 177.1 the 16 KiB CHR-RAM mode instead, where
    $0000-$0FFF follows PPU A9-A8 of the last nametable access and $1000 is
    the last 4 KiB), D7-D6 the 8 KiB PRG-RAM bank. 8 KiB of WRAM at $6000.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.mirroring_control = image.board.mapper == 177
        self.chr_ram_mode = self.mirroring_control and image.board.submapper == 1
        if self.chr_ram_mode and len(self.chr) < 0x4000:
            self.chr = bytearray(0x4000)
        self.latch = 0
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)
        if self.chr_ram_mode:
            self.map_chr(4, 4, 3)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self.latch = value
        if self.mirroring_control:
            self.map_prg(0, 32, value & 0x1F)
            self.prg_ram_offset = ((value >> 6) * 0x2000) % max(len(self.prg_ram), 1)
            if not self.chr_ram_mode:
                self.set_mirroring(HORIZONTAL if value & 0x20 else VERTICAL)
        else:
            self.map_prg(0, 32, value)

    def ppu_address(self, address: int, t: int) -> None:
        if self.chr_ram_mode and address & 0x3000 == 0x2000:
            self.map_chr(0, 4, (address >> 8) & 3)


class Education178(Banked):
    """Mapper 178: the educational-computer and Waixing FS305 board.

    INES_Mapper_178.wiki: $4800 ``.....SSM``: the arrangement (0 vertical, 1
    horizontal) and the PRG mode (0 32 KiB, 1 UNROM with 111 fixed, 2 16 KiB
    mirrored, 3 UNROM with the low bit of the fixed bank selectable); $4801
    PRG A16-A14, $4802 PRG A24-A17, $4803 the 8 KiB PRG-RAM bank. The bank
    commits on any $480x write (the wiki: committing only on $4801 breaks
    Ping Pong). 178.3: after a write of D0 set to $6000-$7FFF, PRG-ROM reads
    return the solder pads (0 here). Not modelled: 178.1's infrared sensor,
    178.2's speech chip. 8 KiB of CHR-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.solder_pads = image.board.submapper == 3
        self.pads_shown = False
        self.regs = [0, 0, 0, 0]
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        mode, low, high = self.regs[0], self.regs[1], self.regs[2]
        self.set_mirroring(HORIZONTAL if mode & 1 else VERTICAL)
        base = high << 3 | low & 7  # 16 KiB banks
        kind = (mode >> 1) & 3
        if kind == 0:
            self.map_prg(0, 32, base >> 1)
        elif kind == 2:
            self.map_prg(0, 16, base)
            self.map_prg(2, 16, base)
        else:
            self.map_prg(0, 16, base)
            fixed = 7 if kind == 1 else 6 | low & 1
            self.map_prg(2, 16, high << 3 | fixed)
        if self.prg_ram:
            self.prg_ram_offset = (self.regs[3] * 0x2000) % len(self.prg_ram)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.pads_shown:
            return 0
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x4800 <= address <= 0x4FFF:
            self.regs[address & 3] = value
            self._update()
            return
        if self.solder_pads and 0x6000 <= address < 0x8000:
            self.pads_shown = bool(value & 1)
        super().cpu_write(address, value, t)


class Asder112(Banked):
    """Mapper 112: Asder's Namco 108-like board with its own register layout.

    INES_Mapper_112.wiki (mask $E001): $8000 selects a register, $A000 writes
    it: 0/1 the 8 KiB PRG banks at $8000/$A000 (the last 16 KiB fixed), 2/3
    the 2 KiB CHR banks at $0000/$0800, 4-7 the 1 KiB banks at $1000-$1C00;
    $E000 D0 CIRAM A10 from PPU A10 (0) or A11 (1). Power-on registers 0, so
    PPU A10, whatever the header says: Master Shooter's header says horizontal
    but it never writes $E000 and fills two nametables.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.select = 0
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(2, 8, last - 1)
        self.map_prg(3, 8, last)
        self.set_mirroring(VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0xE001
        if register == 0x8000:
            self.select = value & 7
        elif register == 0xA000:
            index = self.select
            if index < 2:
                self.map_prg(index, 8, value)
            elif index < 4:
                self.map_chr((index - 2) * 2, 2, value >> 1)
            else:
                self.map_chr(index, 1, value)
        elif register == 0xE000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        else:
            super().cpu_write(address, value, t)


class HuangMMC1(MMC1):
    """116.2's MMC1: the Huang-2 counts its PRG register in 8 KiB units (a value twice a
    normal MMC1's for the same 16 KiB bank)."""

    def _update_prg(self, control: int) -> None:
        written = self.prg_bank
        self.prg_bank = (written & 0x10) | (written & 0x0F) >> 1
        super()._update_prg(control)
        self.prg_bank = written


class Huang116(Banked):
    """Mapper 116: Gouder's SOMARI-P board, whose Huang ASIC acts as a VRC2, an MMC3 or an MMC1.

    INES_Mapper_116.wiki: $4100 (mask $E100) ``.....CMM``: the chip to act
    as (0 VRC2b, 1 MMC3, 2/3 MMC1) and CHR A18. Each simulated chip keeps its
    own registers, banks and (MMC3) IRQ, so switching swaps the whole state:
    here three mapper objects over the one image, the active one answering.
    The VRC2's CHR registers power on as $FF (a Somari revision needs it);
    116.0 resets the MMC1's shift register on switching to it, 116.1 does
    not; 116.2 (Huang-2) gives the MMC1's PRG register 8 KiB units. The
    supervisor powers on as $01 (MMC3). Not modelled: 116.3, the reset-based
    5-in-1 (its first game, 256 KiB, runs).
    """

    watches_ppu_address = True
    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.submapper = image.board.submapper
        vrc2b = image.with_board(replace(image.board, mapper=23, submapper=3))
        self.vrc2 = VRC24(vrc2b, cpu_cycle_ticks)
        self.vrc2.chr_registers = [0xFF] * 8
        for bank in range(8):
            self.vrc2.map_chr(bank, 1, 0xFF)
        self.mmc3 = MMC3(image, cpu_cycle_ticks)
        self.mmc1 = (HuangMMC1 if self.submapper == 2 else MMC1)(image, cpu_cycle_ticks)
        self.chips = (self.vrc2, self.mmc3, self.mmc1, self.mmc1)
        self.supervisor = 1

    @property
    def active(self) -> Banked:
        return self.chips[self.supervisor & 3]

    def cpu_read(self, address: int, t: int) -> int | None:
        return self.active.cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE100 == 0x4100:
            was_mmc1 = self.supervisor & 2
            self.supervisor = value
            if value & 2 and not was_mmc1 and self.submapper != 1:
                self.mmc1.cpu_write(0x8000, 0x80, t)
            return
        self.active.cpu_write(address, value, t)
        self.irq = self.mmc3.irq

    def m2(self, t: int) -> None:
        self.irq = self.mmc3.irq

    def ppu_address(self, address: int, t: int) -> None:
        if self.active is self.mmc3:
            self.mmc3.ppu_address(address, t)
            self.irq = self.mmc3.irq

    def ciram_a10(self, address: int) -> int | None:
        return self.active.ciram_a10(address)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            chip = self.active
            offset = chip.chr_offsets[address >> 10] + (address & 0x3FF)
            return chip.chr[(offset + (self.supervisor >> 2 & 1) * 0x40000) % len(chip.chr)]
        return self.active.ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        self.active.ppu_write(address, value, t)


class SL1632(Huang116):
    """Mapper 14: Gouder's SL-1632 (Samurai Spirits, 8 characters): the Huang-1 as VRC2b or MMC3.

    INES_Mapper_014.wiki: the supervisor is at $A131 (overlapping the chips'
    registers, which also take the write): D1 the chip (0 VRC2b, 1 MMC3), and
    CHR A18 for PPU $0000-$0FFF (D3), $1000-$17FF (D5) and $1800-$1FFF (D7).
    Power-on supervisor 0 (VRC2b).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.supervisor = 0

    @property
    def active(self) -> Banked:
        return self.mmc3 if self.supervisor & 2 else self.vrc2

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address == 0xA131:
            self.supervisor = value
        self.active.cpu_write(address, value, t)
        self.irq = self.mmc3.irq

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            chip, s = self.active, self.supervisor
            a18 = (s >> 3) & 1 if address < 0x1000 else (s >> 5) & 1 if address < 0x1800 else s >> 7
            offset = chip.chr_offsets[address >> 10] + (address & 0x3FF) + a18 * 0x40000
            return chip.chr[offset % len(chip.chr)]
        return self.active.ppu_read(address, t)


class FDSConversion108(Banked):
    """Mapper 108: Whirlwind Manu's and others' FDS-to-cartridge conversions.

    INES_Mapper_108.wiki: PRG $8000-$FFFF is the last 32 KiB; an 8 KiB bank at
    $6000. 108.1: $F000-$FFFF selects it, CHR-RAM. 108.2: $E000-$FFFF selects
    it and the 8 KiB CHR-ROM bank. 108.3: $8000-$FFFF selects it, CHR-RAM.
    108.4: $8000-$FFFF selects the CHR bank, $6000 the last 8 KiB. Writes
    elsewhere are ignored (the games make them). Without a submapper, the
    wiki's disambiguation: CHR-RAM and horizontal mirroring 1, CHR-RAM 3,
    more than 16 KiB of CHR-ROM 2, else 4.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        sub = image.board.submapper
        if sub == 0:
            if not image.chr:
                sub = 1 if image.board.mirroring == "H" else 3
            else:
                sub = 2 if len(image.chr) > 0x4000 else 4
        self.submapper = sub
        self.prg_ram_enabled = False
        self.map_prg(0, 32, len(self.prg) // 0x8000 - 1)
        self.map_chr(0, 8, 0)
        self.bank6000 = len(self.prg) // 0x2000 - 1

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        sub = self.submapper
        if (sub == 1 and address >= 0xF000) or (sub == 3 and address >= 0x8000):
            self.bank6000 = value
        elif sub == 2 and address >= 0xE000:
            self.bank6000 = value
            self.map_chr(0, 8, value)
        elif sub == 4 and address >= 0x8000:
            self.map_chr(0, 8, value)


class Daou156(Banked):
    """Mapper 156: Daou Infosys' DIS23C01 (Metal Force, Buzz & Waldog).

    INES_Mapper_156.wiki (from FCEUX's implementation, fully decoded):
    $C000-$C003/$C008-$C00B the low bytes and $C004-$C007/$C00C-$C00F the
    high bits of the eight 1 KiB CHR banks; $C010 the 16 KiB PRG bank at
    $8000 (the last fixed); $C014 the mirroring (vertical, horizontal,
    one-screen 0), one-screen 0 at power-on. 8 KiB of RAM at $6000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr_regs = [0] * 8
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.set_mirroring(SCREEN_A)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0xC000 <= address <= 0xC00F:
            window = (address & 3) | (address >> 1) & 4
            if address & 4:
                self.chr_regs[window] = (self.chr_regs[window] & 0xFF) | (value & 1) << 8
            else:
                self.chr_regs[window] = (self.chr_regs[window] & 0x100) | value
            self.map_chr(window, 1, self.chr_regs[window])
        elif address == 0xC010:
            self.map_prg(0, 16, value & 0x0F)
        elif address == 0xC014:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_A)[value & 3])
        else:
            super().cpu_write(address, value, t)


class Latch240(Banked):
    """Mapper 240 (Jing Ke Xin Zhuan, Sheng Huo Lie Zhuan): a register in $4020-$5FFF.

    INES_Mapper_240.wiki: ``PPPPCCCC``, the 32 KiB PRG and 8 KiB CHR banks;
    the two boards decode it at (address AND $E800) = $4800 and (address AND
    $E100) = $4100, both taken here. PRG-RAM at $6000. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE800 == 0x4800 or address & 0xE100 == 0x4100:
            self.map_prg(0, 32, value >> 4)
            self.map_chr(0, 8, value & 0x0F)
        else:
            super().cpu_write(address, value, t)


class TC112(Banked):
    """Mapper 193: NTDEC's TC-112 (Fighting Hero, War in the Gulf).

    INES_Mapper_193.wiki: registers at $6000-$7FFF (mask $E007; no PRG-RAM):
    $6000 the 4 KiB CHR bank at $0000 (D7-D2, 2 KiB units of a 4 KiB
    window), $6001/$6002 the 2 KiB banks at $1000/$1800, $6003 the 8 KiB PRG
    bank at $8000 (the last three fixed), $6004 D0 the mirroring (0
    vertical, 1 horizontal). Power-on registers 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        last = len(self.prg) // 0x2000 - 1
        for window in range(1, 4):
            self.map_prg(window, 8, last - 3 + window)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x6000 <= address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xE007
        if register == 0x6000:
            self.map_chr(0, 4, value >> 2)
        elif register in (0x6001, 0x6002):
            self.map_chr(4 + (register - 0x6001) * 2, 2, value >> 1)
        elif register == 0x6003:
            self.map_prg(0, 8, value & 0x0F)
        elif register == 0x6004:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)


class Fengshenbang246(Banked):
    """Mapper 246 (Fengshenbang): four 8 KiB PRG and four 2 KiB CHR banks at $6000-$6007.

    INES_Mapper_246.wiki: $6000-$6003 the PRG banks at $8000-$E000 (D5-D0),
    $6004-$6007 the CHR banks; reads of the vectors' areas ($FFE4-$FFE7,
    $FFEC-$FFEF, $FFF4-$FFF7, $FFFC-$FFFF) force PRG A17 high, as if $6003
    were ORed with $10; $6003 is $FF at power-on. 2 KiB of battery-backed
    PRG-RAM at $6800-$6FFF. Mirroring hard-wired.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.ram = bytearray(0x800)
        self.prg_regs = [0, 0, 0, 0xFF]
        self.prg_ram_enabled = False
        for window, bank in enumerate(self.prg_regs):
            self.map_prg(window, 8, bank & 0x3F)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6800 <= address < 0x7000:
            return self.ram[address & 0x7FF]
        if address >= 0xFFE0 and address & 4:
            bank = (self.prg_regs[3] | 0x10) & 0x3F
            return self.prg[(bank * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6800 <= address < 0x7000:
            self.ram[address & 0x7FF] = value
        elif address & 0xFFF8 == 0x6000:
            register = address & 7
            if register < 4:
                self.prg_regs[register] = value
                self.map_prg(register, 8, value & 0x3F)
            else:
                self.map_chr((register - 4) * 2, 2, value)
        else:
            super().cpu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.ram) if self.battery else None

    def _restore(self, data: bytes) -> None:
        self.ram[:] = data


class MiHunChe27(Banked):
    """Mapper 27 as FCEUX r2947 reassigned it ("Mi Hun Che"; INES_Mapper_027.wiki).

    A write to $8000 puts data D0, and a write to $8001-$FFFF address A0, into
    one latch: the 4 KiB CHR bank (shown at both $0000 and $1000) and the
    one-screen nametable (A or B). PRG unbanked. (The page's other reading,
    an unlicensed VRC4 for World Hero, fits no No-Intro dump set to 27.)
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window in range(4):
            self.map_prg(window, 8, window)
        self._latch(0)

    def _latch(self, bit: int) -> None:
        self.map_chr(0, 4, bit)
        self.map_chr(4, 4, bit)
        self.set_mirroring(SCREEN_B if bit else SCREEN_A)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address == 0x8000:
            self._latch(value & 1)
        elif address > 0x8000:
            self._latch(address & 1)
        else:
            super().cpu_write(address, value, t)


class MagicDragon107(Banked):
    """Mapper 107 (Magicseries' Magic Dragon): one register for both banks.

    INES_Mapper_107.wiki: a write to $8000-$FFFF selects the 8 KiB CHR bank
    (D7-D0) and the 32 KiB PRG bank (D7-D1); bus conflicts unknown (none
    here). Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.map_prg(0, 32, value >> 1)
        self.map_chr(0, 8, value)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(value)
        else:
            super().cpu_write(address, value, t)


class Zemina190(Banked):
    """Mapper 190 (Zemina's Magic Kid Googoo): the first 16 KiB fixed at $C000.

    INES_Mapper_190.wiki: writes to $8000-$9FFF and $C000-$DFFF select the 16
    KiB bank at $8000 (D2-D0, with A14 as bit 3); $A000-$BFFF A1-A0 pick a 2
    KiB CHR window and the data its bank. 8 KiB of RAM. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xE000
        if region in (0x8000, 0xC000):
            self.map_prg(0, 16, (address >> 11) & 8 | value & 7)
        elif region == 0xA000:
            self.map_chr((address & 3) * 2, 2, value)
        else:
            super().cpu_write(address, value, t)


class RT01(Banked):
    """NES 2.0 mapper 328 (UNL-RT-01: a TV test cartridge): 16 KiB PRG, 2 KiB CHR, weak bits.

    NES_2.0_Mapper_328.wiki: reads of $CE80-$CEFF and $FE80-$FEFF return
    ``1111RR1R`` with random bits, standing in for the EPROM's copy-protected
    "weak bits" (the program loops until their checksum changes). The bits
    come from a fixed 16-bit LFSR here, so runs repeat.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window in range(4):
            self.map_prg(window, 8, window)
        for window in range(8):
            self.map_chr(window, 1, window)
        self.lfsr = 0xACE1

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xCF80 == 0xCE80:
            bit = (self.lfsr ^ self.lfsr >> 2 ^ self.lfsr >> 3 ^ self.lfsr >> 5) & 1
            self.lfsr = self.lfsr >> 1 | bit << 15
            random = self.lfsr & 0x0D
            return 0xF2 | random
        return super().cpu_read(address, t)


class Dance2000(Banked):
    """NES 2.0 mapper 518 (UNL-DANCE2000: Subor 999, Subor V, Dance 2000 12-in-1).

    NES_2.0_Mapper_518.wiki: $5000 ``REPPPPPP``: the 16/32 KiB PRG bank (E is
    PRG A20 of the combined main+expansion image; R, the SB-97's secondary
    RAM, is not modelled); $5200 ``.....SBM``: the arrangement (M: 0 vertical
    mirroring), CHR-RAM auto-bankswitch (B), 32 KiB banks (S; else 16 KiB at
    $8000 with $C000 the first bank). CHR-RAM: $0000-$0FFF 4 KiB (with B,
    reads take CHR A12 from the CIRAM A10 latched at PPU A13's last rise),
    $1000-$1FFF the second 4 KiB. 8 KiB of WRAM. The LPC speech chip and the
    floppy controller are not modelled. Power-on 0.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x2000)
        self.chr_writable = True
        self.prg_reg = self.mode = 0
        self.a13 = 0
        self.latched_a10 = 0
        self._update()

    def _update(self) -> None:
        bank = self.prg_reg & 0x7F
        if self.mode & 4:
            self.map_prg(0, 32, bank)
        else:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, 0)
        self.set_mirroring(HORIZONTAL if self.mode & 1 else VERTICAL)
        self.map_chr(0, 4, 0)
        self.map_chr(4, 4, 1)

    def ppu_address(self, address: int, t: int) -> None:
        a13 = (address >> 13) & 1
        if a13 and not self.a13:
            self.latched_a10 = super().ciram_a10(address) or 0
        self.a13 = a13

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x1000 and self.mode & 2:
            return self.chr[self.latched_a10 << 12 | address]
        return super().ppu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address == 0x5000:
            self.prg_reg = value
        elif address == 0x5200:
            self.mode = value
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class Jncota551(Education178):
    """NES 2.0 mapper 551: Jncota's re-releases on a variant of mapper 178's board.

    NES_2.0_Mapper_551.wiki: as 178, but the mirroring is hard-wired and
    $4803 selects the 8 KiB CHR-ROM bank.
    """

    def _update(self) -> None:
        mirroring = self.mirroring
        super()._update()
        self.set_mirroring(mirroring)
        self.prg_ram_offset = 0
        self.map_chr(0, 8, self.regs[3])


class Noraebang515(Banked):
    """NES 2.0 mapper 515: Family Noraebang (Korean karaoke): UNROM-style with an expansion ROM.

    NES_2.0_Mapper_515.wiki (mask $E00F): $8000 ``RBBBBBBB``: the 16 KiB bank
    at $8000 from the internal ROM (R set) or the expansion; $C000 the
    internal ROM's last bank. The file holds the expansion first, the
    internal ROM as its last 1 MiB. Not modelled: the K-663A (YM2413) at
    $6000/$6001 and the microphone's ADC (reads of $6003 give 0): no
    expansion-audio route exists for this board here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.internal_base = max(len(self.prg) - 0x100000, 0) // 0x4000
        self.map_prg(0, 16, self.internal_base)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)
        self.prg_ram_enabled = False

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE00F == 0x8000:
            bank = value & 0x7F
            self.map_prg(0, 16, self.internal_base + bank if value & 0x80 else bank)


class FineStudio417(Banked):
    """Mapper 417: the Fine Studio bootlegs of Batman (0) and RoboCop (1).

    NES_2.0_Mapper_417.wiki (mask $8073): $8000-$8002 the 8 KiB banks at $8000, $A000,
    $C000; $8010-$8013, $8020-$8023 the eight 1 KiB CHR banks; the four
    CIRAM banks at $8050-$8053, or on submapper 1 D7 of $8010-$8013. $8030
    (mask $8070) clears the counter and enables, $8040 disables and
    acknowledges. The counter steps every M2 whatever the enable, 10 bits
    (12 on submapper 1), and enabled, overflowing asserts /IRQ.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.robocop = image.board.submapper == 1
        self.ciram = [0, 1, 0, 1] if self.mirroring == VERTICAL else [0, 0, 1, 1]
        self.counter = 0
        self.irq_enabled = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0x8073
        low = register & 3
        if register < 0x8003 and address >= 0x8000:
            self.map_prg(low, 8, value)
        elif 0x8010 <= register < 0x8014:
            self.map_chr(low, 1, value)
            if self.robocop:
                self.ciram[low] = value >> 7
        elif 0x8020 <= register < 0x8024:
            self.map_chr(4 + low, 1, value)
        elif register & 0x8070 == 0x8030:
            self.counter = 0
            self.irq_enabled = True
        elif register & 0x8070 == 0x8040:
            self.irq_enabled = False
            self.irq = False
        elif 0x8050 <= register < 0x8054 and not self.robocop:
            self.ciram[low] = value & 1

    def m2(self, t: int) -> None:
        self.counter = (self.counter + 1) & (0xFFF if self.robocop else 0x3FF)
        if self.counter == 0 and self.irq_enabled:
            self.irq = True

    def ciram_a10(self, address: int) -> int | None:
        return self.ciram[(address >> 10) & 3]


class Sangokushi330(Banked):
    """Mapper 330 (a bootleg Sangokushi II): a subset of the Namco 163.

    From the forum's analysis (t=17469; the wiki has none), mask $FC00: $8000-$B800 in steps
    of $800 the 1 KiB CHR banks; $C000-$D800 D0 CIRAM A10 for each nametable
    (assumed: the post names only the bit); $E000/$E800/$F000 the 8 KiB banks,
    the last fixed; $8400 (mask $E400: the game uses $8C00) the counter's low
    byte, $A400 (mask $E400) its high seven bits and E in D7. A 15-bit counter
    counts M2 while E, stops at the wrap from $7FFF to 0 and asserts /IRQ;
    reloading the high byte acknowledges.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.nametables = [0, 0, 1, 1]
        self.counter = 0
        self.counting = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xFC00
        if address & 0xE400 == 0x8400:
            self.counter = (self.counter & 0x7F00) | value
        elif address & 0xE400 == 0xA400:
            self.counter = (self.counter & 0xFF) | (value & 0x7F) << 8
            self.counting = bool(value & 0x80)
            self.irq = False
        elif register < 0xC000:
            if not register & 0x400:
                self.map_chr((register - 0x8000) >> 11, 1, value)
        elif register < 0xE000:
            if not register & 0x400:
                self.nametables[(register >> 11) & 3] = value & 1
        elif register < 0xF800 and not register & 0x400:
            self.map_prg((register - 0xE000) >> 11, 8, value & 0x1F)

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter + 1) & 0x7FFF
            if not self.counter:
                self.counting = False
                self.irq = True

    def ciram_a10(self, address: int) -> int | None:
        return self.nametables[(address >> 10) & 3]


class FutureMedia117(Banked):
    """Mapper 117 (Future Media's Crayon Shin-Chan, San Guo Zhi 4): 8 KiB PRG, 1 KiB CHR.

    INES_Mapper_117.wiki: $8000-$8002 the 8 KiB banks, the last fixed; $A000-$A007 the 1 KiB
    CHR banks; $C000-$C002 the counter and its latch, and acknowledge;
    $E000 D0 enable. The page has the IRQ only loosely, as a match against the
    scanline: here PPU A12's rises, filtered as an MMC3 does, count it down
    to 0 and the IRQ fires, once, if the latch is not 0.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.counter = self.latch = 0
        self.irq_enabled = False
        self.a12 = self.a12_ready = 0
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
        elif address < 0x8003:
            self.map_prg(address & 3, 8, value)
        elif 0xA000 <= address < 0xA008:
            self.map_chr(address & 7, 1, value)
        elif 0xC000 <= address < 0xC003:
            self.counter = self.latch = value
            self.irq = False
        elif address == 0xE000:
            self.irq_enabled = bool(value & 1)

    def ppu_address(self, address: int, t: int) -> None:
        if address & 0x1000:
            if not self.a12:
                self.a12 = 1
                if t >= self.a12_ready and self.counter:
                    self.counter -= 1
                    if not self.counter and self.irq_enabled and self.latch:
                        self.irq = True
        elif self.a12:
            self.a12 = 0
            self.a12_ready = (t // self.cpu_cycle_ticks + 3) * self.cpu_cycle_ticks
