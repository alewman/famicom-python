// Visual 2C02 (Quietust's transistor-level RP2C02G netlist on the visual6502
// simulator, reference/docs/visual2c02, fetched by scripts/fetch_references.py
// and never committed) run headless under Node: an independent die-level
// judge beside PPUSim. The simulator's own files are loaded unchanged into
// this context with their user-interface hooks stubbed out, so node
// resolution (including Visual 2C02's area-weighted charge sharing) is exactly
// the browser's.
//
//   const v = require('./v2c02.js');
//   v.boot('resetStatePrerenderEven');   // or null for a power-on reset
//   v.memory[...] = ...;                 // CHR and nametables, as mWrite stores them
//   v.cpu([0x2000, 0x211E, 0x0018]);     // Visual 2C02 CPU commands (cpucmd.js)
//   v.run(halfSteps, onDot);             // onDot(h, v, colour) once per dot

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HOME = path.resolve(__dirname, '../../reference/docs/visual2c02');
const FILES = ['segdefs.js', 'transdefs.js', 'nodenames.js', 'wires.js', 'chipsim.js',
               'memtable.js', 'states.js', 'macros.js', 'cpucmd.js'];

const stub = () => {};
const element = { getContext: () => new Proxy({}, { get: () => stub }), style: {} };
const context = {
	console, Math, Array, Object, String, Number, parseInt, Date, setTimeout: stub,
	document: { getElementById: () => element, getElementsByName: () => [] },
	navigator: { appVersion: '', appName: '' },
	alert: (m) => { throw new Error(m); },
	now: () => Date.now(),
};
vm.createContext(context);
for (const f of FILES) vm.runInContext(fs.readFileSync(path.join(HOME, f), 'utf8'), context, { filename: f });
// The simulator's UI hooks.
vm.runInContext(`
	cpucmd_highlightCurrent = function(){};
	cpucmd_setCellValue = function(addr, d){ cpucmd_reads.push(d); };
	vram_setCellValue = function(){};
	vram_selectCell = function(){};
	palette_reset = palette_updateTable = palette_selectCell = function(){};
	sprite_reset = sprite_updateTable = sprite_selectCell = function(){};
	refresh = chipStatus = updateLogList = function(){};
	var cpucmd_reads = [];
	setupNodes();
	setupTransistors();
`, context);

const pal = ['+++pal_d0_out', '+++pal_d1_out', '+++pal_d2_out', '+++pal_d3_out', '+++pal_d4_out', '+++pal_d5_out'];

function run(js) { return vm.runInContext(js, context); }

module.exports = {
	context,
	get memory() { return context.memory; },
	// Reset (power-on, 4 cycles of RESET) or load one of Visual 2C02's saved states.
	boot(state) {
		run(`
			var stateName = ${JSON.stringify(state)};
			if (stateName) {
				setState(eval(stateName));
			} else {
				for (var nn in nodes) { nodes[nn].state = false; nodes[nn].float = true; }
				nodes[ngnd].state = false; nodes[npwr].state = true;
				for (var tn in transistors) transistors[tn].on = (transistors[tn].gate == npwr);
				setLow(nodenamereset); setLow('clk0'); setHigh('io_ce'); setHigh('int');
				recalcNodeList(allNodes());
				for (var i = 0; i < 4; i++) { setHigh('clk0'); setLow('clk0'); }
				setHigh(nodenamereset);
			}
			cycle = 0; chrAddress = 0; chrStatus = {rd: 1, wr: 1, ale: 0};
		`);
	},
	// Queue CPU commands: 0x2RDD write DD to register R, 0x3R00 read, 0x00NN idle NN half-steps.
	cpu(program) {
		run(`cpucmd_program = ${JSON.stringify(program)}; cpucmd_address = 0; cpucmd_counter = 0;
		     cpucmd_reads = [];`);
	},
	reads() { return run('cpucmd_reads.slice()'); },
	busy() { return run('cpucmd_address < cpucmd_program.length || cpucmd_counter > 0'); },
	h() { return run(`readBits('hpos', 9)`); },
	v() { return run(`readBits('vpos', 9)`); },
	node(name) { return run(`isNodeHigh(nodenames[${JSON.stringify(name)}]) ? 1 : 0`); },
	// Run half-steps (8 a dot); onDot(h, v, colour) on each dot's last half-step,
	// where the browser's updateVideo samples (pixel x is at h = x + 4).
	run(halfSteps, onDot) {
		const c = context;
		const palNodes = pal.map((n) => c.nodenames[n]);
		for (let i = 0; i < halfSteps; i++) {
			c.halfStep();
			c.cycle++;
			if (c.halfStepHook) c.halfStepHook();
			if (onDot && c.cycle % 8 === 7) {
				let colour = 0;
				for (let b = 0; b < 6; b++) if (c.nodes[palNodes[b]].state) colour |= 1 << b;
				onDot(c.readBits('hpos', 9), c.readBits('vpos', 9), colour);
			}
		}
	},
};
