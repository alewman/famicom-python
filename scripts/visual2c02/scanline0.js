// scanline0.py's schedule on Visual 2C02 (see there). Starts from one of the
// simulator's saved pre-render states, so that state's frame parity decides
// which frame skips; run it from both.
//
//   python scripts/visual2c02/scanline0.py schedule --frames 2 > s.json
//   node scripts/visual2c02/scanline0.js s.json resetStatePrerenderEven

'use strict';
const fs = require('fs');
const v = require('./v2c02.js');

const events = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
v.boot(process.argv[3]);
v.memory[0xC6 * 16 + 5] = 0x80;  // tile $C6, plane 0, row 5: column 0

// The schedule as Visual 2C02 CPU commands: idles (0x00NN, NN half-steps,
// 1-2047) up to each access, which takes 24 half-steps with /CE low for the
// 9th to 23rd (cpucmd.js).
const program = [];
let t = 0;
for (const [at, rnw, register, value] of events) {
	let gap = at - t;
	if (gap < 0) throw new Error('schedule overlaps');
	while (gap > 0) {
		const n = Math.min(gap, 2047);
		program.push(n);
		gap -= n;
	}
	program.push((rnw ? 0x3000 : 0x2000) | (register << 8) | value);
	t = at + 24;
}
v.cpu(program);

const frames = Math.max(...events.map((e) => e[0])) / (262 * 341 * 8);
const end = (Math.ceil(frames) * 262 + 2) * 341 * 8;
let previous = [v.v(), v.h()];
let skipped = false;
const row = new Array(256).fill(0x0F);
const began = Date.now();
v.run(end, (h, line, colour) => {
	if (line === 0 && h >= 4 && h < 260) row[h - 4] = colour;
	if (line !== previous[0] || h !== previous[1]) {
		if (previous[0] === 261 && line === 0) skipped = previous[1] === 339;
		if (previous[0] === 0 && line === 1) {
			const lit = [];
			row.forEach((c, x) => { if (c !== 0x0F) lit.push(x); });
			console.log(`Visual2C02 line 0: pre-render skipped dot 340: ${skipped}; non-backdrop x: [${lit}]` +
			            ` (${Math.round((Date.now() - began) / 1000)} s)`);
			row.fill(0x0F);
		}
		previous = [line, h];
	}
});
