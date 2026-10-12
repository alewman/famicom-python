// A minimal CPU-side NES board around Breaknes's APUSim (the whole RP2A03G:
// its gate-level 6502 and the APU), for scripts/apusim_board.py.
//
// APUSim and M6502Core are CC0-1.0 (emu-russia/breaknes, pinned in
// scripts/pinned_repos.json); this file is ours. The board here has only what
// blargg's APU test ROMs touch: 2 KiB of work RAM, NROM PRG (16 or 32 KiB) with
// 8 KiB of PRG-RAM at $6000 (the $6000 text protocol), a stub PPU whose $2002
// sets bit 7 once a frame and clears it when read, and nothing on the pads.
// Every master-clock half cycle is one APU::sim() call, as Breaknes's NESBoard
// does (Breaknes/BreaksCore/NESBoard.cpp). Memory responds while M2 is high:
// reads drive the data bus for the next half cycle, writes take it. At each M2
// fall (the end of a CPU cycle) the five channels' digital outputs can be
// recorded, for a cycle-by-cycle comparison with the board's APU.

#include "pch.h"

#include <cstdint>
#include <cstring>
#include <vector>

using namespace BaseLogic;

namespace {

struct Board {
	M6502Core::M6502* core = nullptr;
	APUSim::APU* apu = nullptr;
	uint8_t ram[0x800]{};
	uint8_t prg_ram[0x2000]{};
	std::vector<uint8_t> prg;
	uint8_t data_bus = 0;
	uint16_t addr_bus = 0;
	TriState clk = TriState::Zero;
	TriState prev_m2 = TriState::Zero;
	int reset_halfcycles = 0;
	uint64_t cycles = 0;  // M2 falls since power
	uint64_t next_vbl = 0;
	bool vbl = false;
	bool recording = false;
	std::vector<uint8_t> raw;  // 5 bytes per CPU cycle: sqa, sqb, tri, rnd, dmc
	APUSim::AudioOutSignal aux{};
	uint16_t last_addr = 0;
	bool last_read = true;
	uint16_t trace_addr = 0;  // debugging: record the bus while this address is out
	std::vector<uint32_t> trace;

	void drive_or_take(TriState m2, TriState rnw) {
		uint16_t a = addr_bus;
		bool read = rnw == TriState::One;
		if (m2 != TriState::One) {
			return;
		}
		if (a < 0x2000) {
			if (read) data_bus = ram[a & 0x7FF]; else ram[a & 0x7FF] = data_bus;
		} else if (a < 0x4000) {
			if (read && (a & 7) == 2) data_bus = (vbl ? 0x80 : 0x00) | (data_bus & 0x1F);
		} else if (a >= 0x6000 && a < 0x8000) {
			if (read) data_bus = prg_ram[a & 0x1FFF]; else prg_ram[a & 0x1FFF] = data_bus;
		} else if (a >= 0x8000) {
			if (read) data_bus = prg[(a - 0x8000) % prg.size()];
		}
	}

	void half_cycle() {
		TriState inputs[(size_t)APUSim::APU_Input::Max]{};
		TriState outputs[(size_t)APUSim::APU_Output::Max]{};
		inputs[(size_t)APUSim::APU_Input::CLK] = clk;
		inputs[(size_t)APUSim::APU_Input::n_NMI] = TriState::One;
		inputs[(size_t)APUSim::APU_Input::n_IRQ] = TriState::One;
		inputs[(size_t)APUSim::APU_Input::n_RES] = reset_halfcycles > 0 ? TriState::Zero : TriState::One;
		inputs[(size_t)APUSim::APU_Input::DBG] = TriState::Zero;
		if (reset_halfcycles > 0) reset_halfcycles--;
		apu->sim(inputs, outputs, &data_bus, &addr_bus, aux);
		TriState m2 = outputs[(size_t)APUSim::APU_Output::M2];
		TriState rnw = outputs[(size_t)APUSim::APU_Output::RnW];
		drive_or_take(m2, rnw);
		if (trace_addr && addr_bus == trace_addr && trace.size() < 4096) {
			trace.push_back(((uint32_t)(m2 == TriState::One) << 9) | ((uint32_t)(rnw == TriState::One) << 8) | data_bus);
		}
		if (m2 == TriState::One) {
			last_addr = addr_bus;
			last_read = rnw == TriState::One;
		}
		if (prev_m2 == TriState::One && m2 != TriState::One) {
			// The end of a CPU cycle.
			cycles++;
			if (last_read && last_addr >= 0x2000 && last_addr < 0x4000 && (last_addr & 7) == 2) {
				vbl = false;
			}
			if (cycles >= next_vbl) {
				vbl = true;
				next_vbl += 29781;
			}
			if (recording) {
				raw.push_back(aux.RAW.sqa);
				raw.push_back(aux.RAW.sqb);
				raw.push_back(aux.RAW.tri);
				raw.push_back(aux.RAW.rnd);
				raw.push_back(aux.RAW.dmc);
			}
		}
		prev_m2 = m2;
		clk = NOT(clk);
	}
};

}  // namespace

extern "C" {

void* apusim_new(const uint8_t* prg, int prg_len) {
	Board* b = new Board();
	// HLE off: the gate-level decoder, the die-derived model (HLE is its faster stand-in).
	b->core = new M6502Core::M6502(false, true);
	b->apu = new APUSim::APU(b->core, APUSim::Revision::RP2A03G);
	b->apu->SetRAWOutput(true);
	b->prg.assign(prg, prg + prg_len);
	b->reset_halfcycles = 64 * 24;  // 64 CPU cycles of /RES low
	b->next_vbl = 27384;  // PPU_power_up_state.wiki: VBL first sets ~27384 cycles in
	return b;
}

void apusim_free(void* h) {
	Board* b = (Board*)h;
	delete b->apu;
	delete b->core;
	delete b;
}

// Run until ``cycles`` more CPU cycles (M2 falls) have passed.
void apusim_run(void* h, uint64_t cycles) {
	Board* b = (Board*)h;
	uint64_t end = b->cycles + cycles;
	while (b->cycles < end) b->half_cycle();
}

uint64_t apusim_cycles(void* h) { return ((Board*)h)->cycles; }

uint8_t apusim_peek(void* h, uint16_t a) {
	Board* b = (Board*)h;
	if (a < 0x2000) return b->ram[a & 0x7FF];
	if (a >= 0x6000 && a < 0x8000) return b->prg_ram[a & 0x1FFF];
	if (a >= 0x8000) return b->prg[(a - 0x8000) % b->prg.size()];
	return 0;
}

void apusim_record(void* h, int on) {
	Board* b = (Board*)h;
	b->recording = on != 0;
	if (on) b->raw.clear();
}

uint64_t apusim_raw_len(void* h) { return ((Board*)h)->raw.size(); }

void apusim_raw_copy(void* h, uint8_t* out, uint64_t n) {
	Board* b = (Board*)h;
	memcpy(out, b->raw.data(), n < b->raw.size() ? n : b->raw.size());
}

// The CPU address of the last cycle, for alignment.
uint16_t apusim_last_addr(void* h) { return ((Board*)h)->last_addr; }

// Debugging: (M2 << 9 | R/W << 8 | data) per half cycle while ``address`` is on the bus.
void apusim_trace(void* h, uint16_t address) { ((Board*)h)->trace_addr = address; ((Board*)h)->trace.clear(); }
uint64_t apusim_trace_copy(void* h, uint32_t* out, uint64_t n) {
	Board* b = (Board*)h;
	uint64_t m = n < b->trace.size() ? n : b->trace.size();
	memcpy(out, b->trace.data(), m * 4);
	return m;
}

// APUSim's registers and counters (APUSim::APU_Registers, 35 uint32 fields).
void apusim_debug_regs(void* h, uint32_t* out) {
	APUSim::APU_Registers regs{};
	((Board*)h)->apu->GetDebugInfo_Regs(regs);
	memcpy(out, &regs, sizeof(regs));
}

}
