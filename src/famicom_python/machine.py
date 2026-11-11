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

from dataclasses import dataclass, field, replace


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
    # PAL video's black border reaches into the picture: its top line and two
    # pixels at each side, rendering or not, emphasis and greyscale not applied
    # (PPU_rendering.wiki "PAL", Overscan.wiki "PAL": PAL NES and famiclones;
    # PPUSim's RP2C07-0 blanks exactly these, scripts/ppusim_compare.py frame).
    border: bool = False
    # The 2C07's forced OAM refresh (PPU_OAM.wiki, BreakingNESWiki PPU/pal.md
    # "EvenOddOut"): on these lines, rendering or not, OAMADDR steps on every
    # even dot 2-340, 170 a line, as PPUSim's RP2C07-0 does
    # (scripts/ppusim_compare.py pal_oam). The Dendy's UA6538 has no such
    # circuit (PPUSim ties its EvenOddOut to 0).
    oam_refresh: tuple[int, int] | None = None
    # A $2003 write reaches OAMADDR through a chain of PCLK latches, a few dots
    # late (ppu.DELAYS "2003_delayed"; BreakingNESWiki PPU/pal.md "W3 Enabler",
    # PPUSim's RP2C07_0 and UMC_UA6538), where the 2C02 loads it in the access.
    delayed_oamaddr: bool = False
    # The window's colours: a .pal under reference/nesdev-wiki/images, made by
    # pally (PPU_palettes.wiki), and whether $2001's bits 5 and 6 tint the other
    # channels than the palette's index bits 6 and 7 say. The picture keeps the
    # bits as written (PPUSim's RAW does too); the 2C07 and the Dendy's PPU
    # swap red and green in their colour decoder (Errata.wiki; BreakingNESWiki
    # PPU/pal.md "Mixed RG Emphasis"), and pally's 2C07 file indexes by
    # channel.
    palette: str = "2C02G_U_wiki.pal"
    swapped_emphasis: bool = False
    # Master ticks into a CPU cycle at which the PPU sees a register access.
    # NTSC's 8 is pinned by ppu_vbl_nmi (board.PPU_ACCESS_TICKS). PAL's 9 is
    # die-derived: the board's pictures equal PPUSim's RP2C07-0 driven with the
    # 2A07's M2 (docs/validation.md milestone 10); no PAL test ROM pins it.
    ppu_access_ticks: int = 8
    # An RGB PPU (2C03, 2C04, 2C05): ``palette`` names a DAC table of
    # video.RGB_DAC instead of a file, and an emphasis bit drives its channel
    # to full brightness instead of dimming the others (PPU_palettes.wiki
    # "2C03 and 2C05"; Errata.wiki l.17).
    rgb: bool = False
    # Rendering switched off mid-line corrupts an OAM row when it next starts
    # (ppu._corrupt_oam): "OAM corruption added in revision E"
    # (PPU_variants.wiki, RC2C05-99). The arcade RGB PPUs are 2C02B, C and D
    # cores (the same table), and "in the 2C03, 2C04, 2C05 ... OAMADDR works as
    # intended" (PPU_registers.wiki "OAMADDR precautions", lidnariq on a Vs.
    # System, forum p=179676): specification tier, no test ROM run on one.
    oam_corruption: bool = True
    # The RC2C05's copy protection (PPU_registers.wiki "2C05 identifier",
    # NES_2.0.wiki "Vs. System Type", Vs._System.wiki): $2000 and $2001 change
    # places, and a $2002 read returns ``identifier`` on the bits of
    # ``identifier_mask`` instead of the I/O latch. The values are what the
    # games expect: "we haven't yet collected data directly from the PPUs".
    swapped_control: bool = False
    identifier: int = 0
    identifier_mask: int = 0


# CPU.wiki "Frequencies", Cycle_reference_chart.wiki (specification tier).
NTSC = Timing("NTSC", 236.25e6 / 11, 12, 4, 262, 241, True)
PAL = Timing(
    "PAL",
    26.601712e6,
    16,
    5,
    312,
    241,
    False,
    border=True,
    oam_refresh=(265, 310),
    delayed_oamaddr=True,
    palette="2C07_wiki.pal",
    swapped_emphasis=True,
    ppu_access_ticks=9,
)
# The Dendy's VBL line (its 51 post-render lines): PPUSim's UMC UA6538 sets VBL
# on (291, 1) and clears it on (311, 1), 20 lines (docs/validation.md
# milestone 10, part 5). Not a certified machine: its DMC timing and pad
# clocking are unverified (docs/undocumented-behavior.md open item 22).
DENDY = Timing(
    "Dendy",
    26.601712e6,
    15,
    5,
    312,
    291,
    False,
    border=True,
    delayed_oamaddr=True,
    palette="2C07_wiki.pal",
    swapped_emphasis=True,
)


# The arcade RGB PPUs: "All official RGB PPUs are NTSC and expect a 21.477272
# MHz master clock" (PPU_variants.wiki "RGB"), and "never have the missing dot
# that the 2C02 does" (Vs._System.wiki "Synchronization"; PPU_variants.wiki:
# the 2C04 "keeps 2C03 timing (no skipped dot)"). Not modelled, each on the
# wiki's "believed" only: OAMDATA and the palette unreadable (the 2C03B as the
# 2C02B), and the 2C02A/B's stray sprite pixels at x = 255
# (docs/undocumented-behavior.md C76).
RGB = replace(NTSC, odd_frame_skip=False, rgb=True, oam_corruption=False, palette="RP2C03")


def _rc2c05(identifier: int, mask: int = 0x1F) -> Timing:
    return replace(RGB, swapped_control=True, identifier=identifier, identifier_mask=mask)


#: The Vs. System's PPUs by NES 2.0 "Vs. PPU type" (header byte 13's low
#: nibble, nes20db's ``<vs ppu=>``): the chip's name and its row. The RC2C05-01's
#: identifier is unknown (its one game, Ninja Jajamaru-kun, never looks:
#: NES_2.0.wiki); $1B is MAME's choice (ppu2c0x.cpp, emulator-derived).
VS_PPUS: dict[int, tuple[str, Timing]] = {
    0: ("RP2C03B", RGB),
    2: ("RP2C04-0001", replace(RGB, palette="RP2C04-0001")),
    3: ("RP2C04-0002", replace(RGB, palette="RP2C04-0002")),
    4: ("RP2C04-0003", replace(RGB, palette="RP2C04-0003")),
    5: ("RP2C04-0004", replace(RGB, palette="RP2C04-0004")),
    8: ("RC2C05-01", _rc2c05(0x1B)),
    9: ("RC2C05-02", _rc2c05(0x3D, 0x3F)),
    10: ("RC2C05-03", _rc2c05(0x1C)),
    11: ("RC2C05-04", _rc2c05(0x1B)),
}


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
    # Master ticks after the CPU's first cycle begins at which the PPU's dot
    # begins: on PAL (3.2 dots a CPU cycle) the start can fall inside a dot.
    # 0 by default; scripts/mesen_lockstep.py fits Mesen2's.
    ppu_ticks: int = 0
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
    # The PPU's /RST is held at power, so $2000, $2001, $2005 and $2006 ignore
    # writes until the first pre-render line. On the NES-001 the CPU and PPU are
    # released together (blargg's 29658 cycles). The Famicom ties the PPU's /RST
    # to 5V: no such window, and F-1 Race, Metal Gear, Argus and more write $2000
    # inside it and hang without NMI, as Magic John and The Lord of King do on an
    # NES (PPU_power_up_state.wiki "Famicom", specification tier; hardware
    # reports, forum p=247896). The PPU there starts at least 11.4 ms before the
    # CPU, unmeasured; taken as a frame or more, no window is left (C72).
    ppu_reset_at_power: bool
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
    # The hard-wired player-2 controller's microphone, read at $4016 D2
    # (Standard_controller.wiki; the RF Famicom only: the AV Famicom's second
    # pad is a standard one).
    microphone: bool = False
    # Data lines D0-D4 of $4016 and $4017 left to open bus rather than pulled
    # to 0 when nothing drives them (Controller_reading.wiki "Unconnected data
    # lines"): the Famicom's $4016 D3-D4, the NES-101's $4016 D2.
    pad_open_bus: tuple[int, int] = (0, 0)
    # The APU's noise, DMC and frame-counter tables (apu.TABLES): "PAL" on the
    # RP2A07; the Dendy's UMC CPU keeps the NTSC ones on PAL timing
    # (docs/undocumented-behavior.md, CPU revisions).
    apu_tables: str = "NTSC"
    # DMA (OAM and DMC) halts the CPU only on an opcode fetch, the first read of
    # an instruction or interrupt entry: the RP2A07's fix for the 2A03's
    # repeated register reads (APU_DMC.wiki: "forcing DMA to halt on the first
    # cycle of an instruction"; DMA.wiki: "the mechanism is not yet
    # understood"; Mesen2 does the same). Specification tier: BreakingNESWiki
    # leaves the 2A07's RDY "TBD".
    dma_halts_on_opcode: bool = False
    # A sample ends 1 APU cycle late: $4015's DMC bit clears 1 APU cycle later
    # than on RP2A03 CPUs, which moves the implicit-stop glitches 1 APU cycle
    # earlier (the UA6527P: CPU_variants.wiki, DMA.wiki "Bugs"; specification
    # tier, no test ROM answer). The DMC IRQ, which the wiki "suspects" is late
    # too, is not moved.
    dmc_late_stop: bool = False
    # The Famicom's 15-pin expansion port, where its Zapper, Vaus and four-player
    # adapters plug in (Expansion_port.wiki); the NES takes its versions on the
    # controller ports. The Dendy is taken as the NES: its light guns and pads
    # plug into 9-pin ports (UNVERIFIED for every Dendy model).
    famicom_expansion_port: bool = False
    # A Vs. System mainboard (Vs._System.wiki, vs.py): $4016/$4017 carry coins,
    # the service button and DIP switches on D2-D7, driven, not open bus;
    # $4020-$5FFF is the coin counter; 2 KiB of RAM answers at $6000-$7FFF;
    # OUT2 reaches the ROM sockets. "primary" or "secondary" is the side of
    # the board the CPU sits on ($4016 D7; C75), None any other console.
    vs_side: str | None = None
    certified: bool = True


NES_001 = Machine(
    name="NES-001",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=True,
    ppu_reset_at_power=True,
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
    ppu_reset_at_power=False,
    joypad_oe_per_cycle=True,
    famicom_audio_through_cart=True,
    dmc_unexpected_reload_bug=False,
    audio_high_pass_hz=(37.0,),
    audio_low_pass_hz=None,
    microphone=True,
    pad_open_bus=(0x18, 0),
    famicom_expansion_port=True,
)

AV_FAMICOM = Machine(
    name="AV Famicom HVC-101",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=False,  # booted through resets and power cycles (forum p=247896)
    ppu_reset_at_power=False,  # the same report, rev. H
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=True,
    dmc_unexpected_reload_bug=False,
    pad_open_bus=(0x18, 0),  # the wiki's "Famicom" column: UNVERIFIED for this model
    famicom_expansion_port=True,
)

NES_101 = Machine(
    name="NES-101",
    timing=NTSC,
    cpu_variant="RP2A03G",
    ppu_variant="RP2C02G",
    reset_resets_ppu=False,
    ppu_reset_at_power=False,  # Magic John: boots on rev. H; rev. G only when warm (forum p=247896)
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
    pad_open_bus=(0x04, 0),
)

# Data only until a later milestone certifies them (docs/handoff-brief.md).
PAL_NES = Machine(
    name="PAL NES",
    timing=PAL,
    cpu_variant="RP2A07",
    ppu_variant="RP2C07",
    reset_resets_ppu=True,
    ppu_reset_at_power=True,  # about 33132 cycles (PPU_power_up_state.wiki)
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
    apu_tables="PAL",
    dma_halts_on_opcode=True,
    certified=False,
)

DENDY_CLONE = Machine(
    name="Dendy",
    timing=DENDY,
    cpu_variant="UA6527P",
    ppu_variant="UA6538",
    reset_resets_ppu=False,
    ppu_reset_at_power=False,  # UNVERIFIED: as the reset button
    joypad_oe_per_cycle=True,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=True,  # "both the aborted DMA and unexpected DMA bugs" (DMA.wiki)
    dmc_late_stop=True,
    certified=False,
)

# The Vs. UniSystem (Vs._System.wiki; MAME's vsnes.cpp, BSD-3, emulator-derived).
# - "The CPUs are always the letterless revision, and the arcade board is
#   incompatible with a 2A03G, so tonal noise is not supported" (apu.TABLES
#   "RP2A03"; CPU_variants.wiki's row adds the frame counter that a reset
#   leaves alone, and an M2 duty of 17/24, not modelled: the board's $2002
#   races are the RP2A03G's 15/24).
# - Reset is the watchdog's: it "will reset both CPUs, both PPUs", and "all four
#   are released from reset by the watchdog at the same time", so the PPU has
#   the NES-001's power-on window.
# - UNVERIFIED, taken as the NES-001's for want of a source: how back-to-back
#   reads clock the mainboard's 4021s, and the audio amplifier's filter.
# - The side: a UniSystem game's CPU is in the secondary socket ($4016 D7 = 1),
#   the one whose $4017 reads hold the watchdog off; MAME and Mesen2 both answer
#   0 there, and the RAM and /IRQ that follow from the socket are C75's.
# One row per PPU, since the game's ROMs name the chip they need:
# ``vs_machine`` picks the row.
VS_UNISYSTEM = Machine(
    name="Vs. UniSystem (RP2C03B)",
    timing=RGB,
    cpu_variant="RP2A03",
    ppu_variant="RP2C03B",
    reset_resets_ppu=True,
    ppu_reset_at_power=True,
    joypad_oe_per_cycle=False,
    famicom_audio_through_cart=False,
    dmc_unexpected_reload_bug=False,
    apu_tables="RP2A03",
    vs_side="secondary",
    certified=False,
)

VS_MACHINES: dict[int, Machine] = {
    0: VS_UNISYSTEM,
    **{
        number: replace(
            VS_UNISYSTEM, name=f"Vs. UniSystem ({chip})", timing=timing, ppu_variant=chip
        )
        for number, (chip, timing) in VS_PPUS.items()
        if number
    },
}


def vs_machine(ppu: int) -> Machine:
    """The Vs. UniSystem with the PPU of NES 2.0 "Vs. PPU type" ``ppu``; a
    reserved number gets the RP2C03B, whose colours are the home consoles'."""
    return VS_MACHINES.get(ppu, VS_UNISYSTEM)


MACHINES = {
    "nes": NES_001,
    "famicom": FAMICOM,
    "av-famicom": AV_FAMICOM,
    "nes-101": NES_101,
    "pal": PAL_NES,
    "dendy": DENDY_CLONE,
    "vs": VS_UNISYSTEM,
    **{
        "vs-" + machine.ppu_variant.lower(): machine
        for number, machine in VS_MACHINES.items()
        if number
    },
}
