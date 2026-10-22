/* model.js — the small, checkable models the explorer computes in the browser.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   Everything here is labelled "computed" on the page, never "recorded".
   docs/tools/check_site.py runs these functions under Node against every
   operation the RTL tour recorded, so a model that drifts from the RTL fails
   `make docs` instead of misleading a reader. */
(function (root) {
  "use strict";

  // One RV32 add or sub through Tiqora's single 4-bit adder (tp_ncore):
  // eight phases, least significant nibble first, the carry held in a
  // flip-flop between phases. sub feeds ~b and a carry-in of 1 at phase 0.
  function nibbleOp(a, b, op) {
    a >>>= 0; b >>>= 0;
    const sub = op === "sub";
    const phases = [];
    let carry = sub ? 1 : 0, result = 0;
    for (let p = 0; p < 8; p++) {
      const an = (a >>> (4 * p)) & 0xF;
      const bn = (b >>> (4 * p)) & 0xF;
      const bx = sub ? (~bn) & 0xF : bn;
      const s = an + bx + carry;
      phases.push({ phase: p, a_n: an, bx_n: bx, cin: carry, sum_n: s & 0xF, cout: s >> 4, rf_wd: s & 0xF });
      result |= (s & 0xF) << (4 * p);
      carry = s >> 4;
    }
    return { op: sub ? "sub" : "add", a, b, result: result >>> 0, phases };
  }

  // "0x1234", "1234", "-5": a 32-bit value, or null when it is not one.
  function parseWord(text) {
    const t = String(text).trim().replace(/_/g, "");
    let v;
    if (/^0x[0-9a-f]{1,8}$/i.test(t)) v = parseInt(t.slice(2), 16);
    else if (/^-?\d{1,10}$/.test(t)) v = parseInt(t, 10);
    else return null;
    if (v > 0xFFFFFFFF || v < -0x80000000) return null;
    return v >>> 0;
  }

  // 8N1 framing as the UARTs send it: start 0, data least significant bit first, stop 1.
  function uartBits(byte) {
    const bits = [0];
    for (let i = 0; i < 8; i++) bits.push((byte >> i) & 1);
    bits.push(1);
    return bits;
  }

  // The 32-bit event word that TPOP (or a read of EVENT) returns.
  function decodeEvent(w) {
    w >>>= 0;
    if (w === 0) return { empty: true, text: "empty: the queue had nothing (0)" };
    const src = w >>> 31, ch = (w >>> 28) & 7, rising = (w >>> 27) & 1, ts = w & 0x7FFFFFF;
    return { empty: false, source: src ? "TMARK" : "pin", channel: ch, rising: !!rising, timestamp: ts,
      text: (src ? "TMARK tag " : "pin channel ") + ch + ", " + (rising ? "rising" : "falling") + ", timestamp " + ts };
  }

  // Tiqora-Serial's host port (src/uart/tp_host_uart.sv), byte by byte. Feed
  // it what the host sends; it returns each complete command with the reply
  // the chip sends, and what a half-sent command is still waiting for. A read
  // answers four bytes of register value, which only the chip knows.
  const REGS = { 0: "TIME", 1: "EVENT", 2: "STAT", 3: "CFG", 4: "CMP0", 5: "CMP1", 7: "PW", 8: "ADJ", 9: "RATE", 10: "PULSE" };
  const WRITABLE = new Set([3, 4, 5, 7, 8, 9, 10]);
  function hostPort(bytes) {
    const out = [];
    let st = "CMD", cmd = null, seq = [], data = [], addr = 0;
    for (const b of bytes) {
      if (st === "CMD") {
        seq = [b];
        if (b === 0x01) { st = "ADDR"; cmd = "write"; }
        else if (b === 0x02) { st = "ADDR"; cmd = "read"; }
        else if (b === 0x03) out.push({ bytes: seq, cmd: "ping", reply: [0x5A, 0x01], text: "ping: magic 0x5A, version 0x01" });
        else out.push({ bytes: seq, cmd: "unknown", reply: [0x15], text: "not a command: NAK 0x15" });
      } else if (st === "ADDR") {
        seq.push(b); addr = b & 0xF;
        const name = REGS[addr] || ("offset " + addr + ", which does nothing");
        if (cmd === "read") {
          const readable = addr <= 2;
          out.push({ bytes: seq, cmd: "read", addr, reply: "4 bytes", text: "read " + name + (addr === 1 ? ", which pops the queue head (0 if empty)" : "") + (readable ? "" : ": only offsets 0 to 2 read back; this returns 0") + (b > 0x0F ? " (the top four address bits are ignored)" : "") });
          st = "CMD";
        } else { st = "DATA"; data = []; }
      } else {
        seq.push(b); data.push(b);
        if (data.length === 4) {
          const v = (data[0] | data[1] << 8 | data[2] << 16 | data[3] << 24) >>> 0;
          out.push({ bytes: seq, cmd: "write", addr, value: v, reply: [0x06], text: "write " + (REGS[addr] || ("offset " + addr)) + " = " + hex(v, 32) + ": ACK 0x06" + (WRITABLE.has(addr) ? "" : ", but offset " + addr + " has no write effect, so nothing changes") });
          st = "CMD";
        }
      }
    }
    const waiting = st === "CMD" ? null : { bytes: seq, state: st === "ADDR" ? "H_ADDR" : "H_DATA",
      need: st === "ADDR" ? 1 : 4 - data.length,
      text: (cmd === "write" ? "write" : "read") + " still waiting for " + (st === "ADDR" ? "its address byte" : (4 - data.length) + " more data byte" + (4 - data.length === 1 ? "" : "s")) + ". There is no timeout: the next bytes the host sends are taken as these, and only reset clears it." };
    return { commands: out, waiting };
  }

  function hex(v, width) {
    if (v === null || v === undefined) return "x";
    const digits = Math.max(1, Math.ceil((width || 32) / 4));
    return "0x" + (v >>> 0).toString(16).toUpperCase().padStart(digits, "0");
  }

  const api = { nibbleOp, parseWord, uartBits, decodeEvent, hostPort, REGS, hex };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TQModel = api;
})(typeof window !== "undefined" ? window : globalThis);
