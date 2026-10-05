-- Stop Mesen2 when a blargg-shell test ROM reports a result through $6000.
-- Used by scripts/mesen_run.py --lua; docs/validation.md has the protocol:
-- $6001-$6003 = DE B0 61 once the data is valid, $6000 = $80 while running,
-- $81 when it wants a reset, else the result code ($00 = passed).
-- nesDebug reads without side effects, so this never disturbs the test.

local function status()
  local mem = emu.memType.nesDebug
  if emu.read(0x6001, mem) ~= 0xDE or emu.read(0x6002, mem) ~= 0xB0
      or emu.read(0x6003, mem) ~= 0x61 then
    return nil
  end
  return emu.read(0x6000, mem)
end

local function text()
  local mem, chars = emu.memType.nesDebug, {}
  for address = 0x6004, 0x6FFF do
    local byte = emu.read(address, mem)
    if byte == 0 then break end
    chars[#chars + 1] = string.char(byte)
  end
  return table.concat(chars)
end

emu.addEventCallback(function()
  local code = status()
  if code ~= nil and code < 0x80 then
    emu.log(text())
    emu.stop(code)
  end
end, emu.eventType.endFrame)
