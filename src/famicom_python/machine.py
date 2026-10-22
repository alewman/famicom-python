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

    One variation is not a field: the CPU and PPU dividers start
    independently, so an NTSC console powers on in one of four
    synchronizations (blargg, hardware-captured over 50-60 power cycles,
    nesdev-forum/6186.html). The board models his third, "the preferred one for
    emulators and test ROMs, due to the least special cases, and highest
    likelihood" (31 %), the one ``ppu_vbl_nmi`` and ``vbl_nmi_timing`` judge.
    The other three move single events (NMI, VBL set and clear, sprite-0 hit,
    overflow) by one dot each, in a pattern nothing pinned explains yet
    (docs/undocumented-behavior.md, open items).

    ``apu_put_first`` says whether the CPU's first cycle is an APU put rather
    than a get (DMA.wiki "Cadence": either happens). ``ram_fill`` is the byte
    the 2 KiB of work RAM holds (undefined on hardware). ``a``/``x``/``y`` are
    the registers before the reset sequence: 0 by CPU_power_up_state.wiki
    (measured on an RP2A03G), noisy on many consoles by AccuracyCoin's README
    l.829. ``palette`` is palette RAM at power: "unspecified"
    (PPU_power_up_state.wiki), "unique and consistent" per console
    (AccuracyCoin); the default is the one console's table that was published,
    blargg's (``blargg_ppu_tests_2005.09.15b/source/power_up_palette.asm``,
    hardware-captured, "probably unique to my NES"). ``ppustatus`` is PPUSTATUS's
    bits 7-5 at power, "+0+x xxxx" with + "often set" (PPU_power_up_state.wiki):
    the overflow bit set and VBL clear, as PPUSim powers on, by default.
    ``ppu_dot`` is the PPU's dot on line 0 as the CPU's first cycle begins:
    which CPU cycle the PPU's frame starts in is not pinned by any source here
    (0 by default; Mesen2 starts its PPU one CPU cycle, 3 dots, ahead).
    ``dmc_timer`` is the DMC's rate timer at power, in APU cycles: the DMC's
    output cycles run from power-on, silent, so it sets when the first fetch
    after an enable comes; no source pins it (0 by default: it reloads on the
    first APU cycle; Mesen2 starts it at a full period).
    """

    apu_put_first: bool = False
    ram_fill: int = 0x00
    a: int = 0
    x: int = 0
    y: int = 0
    palette: bytes = bytes.fromhex(
        "09 01 00 01 00 02 02 0D 08 10 08 24 00 00 04 2C"
        "09 01 34 03 00 04 00 14 08 3A 00 02 00 20 2C 08"
    )
    ppustatus: int = 0x20
    ppu_dot: int = 0
    dmc_timer: int = 0


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
    # How long a 1 bit of the PPU's I/O latch survives undriven (contradiction
    # C1, docs/undocumented-behavior.md): about 600 ms on blargg's NES, the
    # console his ppu_open_bus passes on (its readme; hardware-captured), and
    # "some decay sooner, depending on the NES and temperature": 4-21 ms for
    # the fastest bit on lidnariq's (nesdev-forum/24639.html). A per-console
    # analogue figure, not a constant of the chip.
    ppu_latch_decay_seconds: float = 0.6
    # The analogue stage after the 2A03's DACs, **fitted**: first-order filter
    # corners from APU_Mixer.wiki (NES-001: high-pass 90 Hz and 440 Hz, low-pass
    # 14 kHz, from blargg's measurements; Famicom: one high-pass at 37 Hz, before
    # an RF stage nobody has characterised). Other fits disagree
    # (undocumented-behavior.md C10): an assumption, cited, not a fact.
    audio_high_pass_hz: tuple[float, ...] = (90.0, 440.0)
    audio_low_pass_hz: float | None = 14_000.0
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
    audio_high_pass_hz=(37.0,),
    audio_low_pass_hz=None,
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
