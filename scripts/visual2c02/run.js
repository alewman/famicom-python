// A compare.py scenario on Visual 2C02: its register schedule from a saved
// pre-render state, CHR from the scenario; prints JSON {reads, lines, skips}.
//
//   node scripts/visual2c02/run.js SCENARIO.json

'use strict';
const fs = require('fs');
const v = require('./v2c02.js');

const s = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
v.boot(s.state || 'resetStatePrerenderEven');
for (const [address, value] of s.chr) v.memory[address] = value;

// Idles (0x00NN: NN half-steps, 1-2047) up to each access, which takes 24
// half-steps with /CE low for the 9th to the 23rd (cpucmd.js).
const program = [];
let t = 0;
for (const [at, rnw, register, value] of s.events) {
	let gap = at - t;
	if (gap < 0) throw new Error('schedule overlaps at ' + at);
	while (gap > 0) {
		const n = Math.min(gap, 2047);
		program.push(n);
		gap -= n;
	}
	program.push((rnw ? 0x3000 : 0x2000) | (register << 8) | (value & 0xFF));
	t = at + 24;
}
v.cpu(program);

const want = new Set(s.lines || []);
const probe = new Set(s.probe || []);
const lines = {};
const probes = {};
const skips = [];
// Half-step traces of the signals compare.py's SIGNALS names (Visual 2C02 node numbers).
const signals = [];
const windows = s.signals ? s.signals.windows : [];
const sigNodes = s.signals ? s.signals.nodes : [];
v.context.halfStepHook = function () {
	const line = v.context.readBits('vpos', 9), h = v.context.readBits('hpos', 9);
	if (windows.some(([l, from, to]) => line === l && h >= from && h <= to)) {
		let bits = 0;
		sigNodes.forEach((n, i) => { if (v.context.nodes[n].state) bits |= 1 << i; });
		signals.push([h, bits]);
	}
};
let previous = [v.v(), v.h()];
v.run(s.end, (h, line, colour) => {
	if (want.has(line) && h >= 4 && h < 260) {
		(lines[line] = lines[line] || new Array(256).fill(0))[h - 4] = colour;
	}
	if (probe.has(line)) {
		// OAM address (secondary OAM: | $100) and the OAM data bus, as the browser's readSpriteAddr.
		probes[line + ':' + h] = [v.context.readSpriteAddr(), v.context.readBits('spr_d', 8)];
	}
	if (line !== previous[0] || h !== previous[1]) {
		if (previous[0] === 261 && line === 0) skips.push(previous[1] === 339);
		previous = [line, h];
	}
});
console.log(JSON.stringify({ reads: v.reads(), lines, skips, probes, signals }));
