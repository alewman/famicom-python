"""The consoles, as data: one board, many machines.

Every console this project models is the same board with different chips and
quirks, so each is a row of :data:`MACHINES` and the board reads its fields;
adding PAL or the Dendy is adding rows, not code paths. Each quirk field names
its source and that source's tier (docs/validation.md). Paths are as in
docs/start-here.md: a bare ``Name.wiki`` is the pinned NESdev wiki page.

The reference model is the NES-001 with an RP2A03G and RP2C02G, the console
AccuracyCoin, Visual 2A03/2C02 and PPUSim all target (docs/start-here.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Timing:
    """A video standard's clocks, in master-clock ticks (docs/start-here.md "Clocks")."""

    name: str
    master_hz: float
    cpu_divider: int  # master ticks per CPU cycle
    dot_divider: int  # master ticks per PPU dot
    lines: int  # scanlines per frame, the pre-render line included
    vblank_line: int  # the line on whose dot 1 the VBL flag sets
    odd_frame_skip: bool  # with rendering on, odd frames are one dot short


# CPU.wiki "Frequencies", Cycle_reference_chart.wiki (specification tier).
NTSC = Timing("NTSC", 236.25e6 / 11, 12, 4, 262, 241, True)
PAL = Timing("PAL", 26.601712e6, 16, 5, 312, 241, False)
# The Dendy's VBL line (its 51 post-render lines) is UNVERIFIED here: it is a row
# for later, not a certified machine.
DENDY = Timing("Dendy", 26.601712e6, 15, 5, 312, 291, False)


@dataclass(frozen=True)
class PowerOn:
    """What a console holds when it is switched on; real consoles vary.

    ``alignment`` is where the PPU's dot clock falls inside the CPU cycle, in
    master ticks (0 to ``dot_divider - 1``): the CPU and PPU dividers start
    independently, so a console powers on in one of four NTSC alignments
    (blargg, hardware-captured over 50-60 power cycles, nesdev-forum/6186.html).
    Which value is blargg's preferred third is settled against ``ppu_vbl_nmi``
    in milestone 2. ``apu_put_first`` says whether the CPU's first cycle is an
    APU put rather than a get (DMA.wiki "Cadence": either happens).
    ``ram_fill`` is the byte the 2 KiB of work RAM holds (undefined on
    hardware). ``a``/``x``/``y`` are the registers before the reset sequence:
    0 by CPU_power_up_state.wiki (measured on an RP2A03G), noisy on many
    consoles by AccuracyCoin's README l.829.
    """

    alignment: int = 0
    apu_put_first: bool = False
    ram_fill: int = 0x00
    a: int = 0
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class Machine:
    """One console model (docs/start-here.md "The machines")."""

    name: str
    timing: Timing
    cpu_variant: str
    ppu_variant: str
    # The reset button resets the PPU too: on the NES-001 through the CIC's
    # reset line; on the Famicom and NES-101 it reaches the CPU only
    # (PPU_power_up_state.wiki l.49/76, specification tier).
    reset_resets_ppu: bool
    # Every read cycle of $4016/$4017 clocks the pad (RF Famicom), rather than a
    # run of back-to-back reads clocking it once (hardware-captured by Fiskbit,
    # cited in DMA.wiki "Register conflicts"; AccuracyCoin "Controller Clocking").
    joypad_oe_per_cycle: bool
    # The 2A03's audio leaves on cartridge pin 45 and returns on pin 46
    # (Cartridge_connector.wiki, Family_Computer.wiki).
    famicom_audio_through_cart: bool
    # An implicit DMC stop on a reload's APU cycle schedules one more reload, on
    # late RP2A03G and RP2A03H (hardware-captured by Fiskbit, DMA.wiki "Bugs").
    dmc_unexpected_reload_bug: bool
    power_on: PowerOn = field(default_factory=PowerOn)
    # The "magic constant" ANE ($8B) and LXA ($AB) OR into A varies from chip to
    # chip. LXA's is $FF: blargg's instr_test-v5 03-immediate, whose CRCs were
    # taken on an NES (hardware-corrected), passes only with $FF. ANE's is no
    # test's: $EE, SingleStepTests nes6502's value (emulator-derived);
    # AccuracyCoin tests only what the constant cannot change.
    ane_constant: int = 0xEE
    lxa_constant: int = 0xFF
    certified: bool = True


NES_001 = Machine(
    name="NES-001",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=True,
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
)

FAMICOM = Machine(
    name="Famicom HVC-001",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=False,
    joypad_oe_per_cycle=True,
    famicom_audio_through_cart=True,
    dmc_unexpected_reload_bug=False,
)

AV_FAMICOM = Machine(
    name="AV Famicom HVC-101",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=False,  # UNVERIFIED for this model (docs/start-here.md)
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=True,
    dmc_unexpected_reload_bug=False,
)

NES_101 = Machine(
    name="NES-101",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=False,
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
)

# Data only until a later milestone certifies them (docs/handoff-brief.md).
PAL_NES = Machine(
    name="PAL NES",
    timing=PAL,
    cpu_variant="RP2A07",
    ppu_variant="RP2C07",
    reset_resets_ppu=True,
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
    certified=False,
)

DENDY_CLONE = Machine(
    name="Dendy",
    timing=DENDY,
    cpu_variant="UA6527P",
    ppu_variant="UA6538",
    reset_resets_ppu=False,
    joypad_oe_per_cycle=True,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
    certified=False,
)

MACHINES = {
    "nes": NES_001,
    "famicom": FAMICOM,
    "av-famicom": AV_FAMICOM,
    "nes-101": NES_101,
    "pal": PAL_NES,
    "dendy": DENDY_CLONE,
}
