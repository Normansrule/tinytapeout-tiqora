/* board.js — the simulated Basys 3, live: the recorded run of
   fpga/basys3/rec_basys3.sv played back on a drawn board, with a play button
   and a scrubber. Shared unchanged by tiqora-skywater130 and
   tinytapeout-tiqora; the data is the board recording, converted by
   docs/tools/build_site.py, and the part names come from site.json "fpga".

   Nothing here is invented: every LED, digit, button and terminal line at a
   given cycle is read from the recording, and the LEDs glow by the fraction
   of recent cycles they were on, as docs/tools/fpga_media.py draws them. The
   board is a simulation and the drawing says so.

   It plays once when it first comes into view; with prefers-reduced-motion it
   opens on the last cycle and only moves when you press play or drag. */
(function (root) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const el = (n, a, txt) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; return e; };
  const SEGS = { 0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc",
                 8: "abcdefg", 9: "abcdfg", 10: "abcefg", 11: "cdefg", 12: "adef", 13: "bcdeg", 14: "adefg", 15: "aefg" };
  const SEG = { a: [4, 0, 18, 4], g: [4, 20, 18, 4], d: [4, 40, 18, 4], f: [0, 3, 4, 18], b: [22, 3, 4, 18], e: [0, 23, 4, 18], c: [22, 23, 4, 18] };
  const PLAY_MS = 16000;           // the whole run plays in this long, whatever its length in cycles

  // the last value at or before cycle c in a [[cycle, value]] list (binary search)
  function idx(list, c) { let lo = 0, hi = list.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (list[m][0] <= c) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
  const at = (list, c) => { const i = idx(list, c); return i < 0 ? null : list[i][1]; };
  // the fraction of cycles c0..c1 in which bit b of the list's value was 1
  function duty(list, b, c0, c1) {
    let i = Math.max(0, idx(list, c0)), on = 0, t = c0;
    let v = i < list.length && list[i][0] <= c0 ? list[i][1] : 0;
    for (i = i + 1; i < list.length && list[i][0] < c1; i++) { if ((v >> b) & 1) on += list[i][0] - t; t = list[i][0]; v = list[i][1]; }
    if ((v >> b) & 1) on += c1 - t;
    return on / Math.max(1, c1 - c0);
  }

  function mount(host, rec) {
    const cfg = rec.cfg, end = rec.end, win = Math.max(1, Math.round(end / 120));
    const svg = el("svg", { viewBox: "0 0 900 476", class: "board-svg", role: "img",
      "aria-label": "A drawn Digilent Basys 3 showing the recorded simulation: LEDs, the 7-segment display, the buttons and the serial terminal at the chosen cycle" });
    const defs = el("defs");
    const glow = el("filter", { id: "bd-glow", x: "-150%", y: "-150%", width: "400%", height: "400%" });
    glow.append(el("feGaussianBlur", { stdDeviation: "5" }));
    defs.append(glow);
    const sheen = el("linearGradient", { id: "bd-pcb", x1: 0, y1: 0, x2: 1, y2: 1 });
    sheen.append(el("stop", { offset: 0, "stop-color": "#1d5238" }), el("stop", { offset: 1, "stop-color": "#123824" }));
    defs.append(sheen);
    svg.append(defs);

    // the board
    svg.append(el("rect", { x: 1, y: 1, width: 588, height: 404, rx: 16, fill: "url(#bd-pcb)", stroke: "#2f7752", "stroke-width": 1.5 }));
    [[18, 18], [572, 18], [18, 388], [572, 388]].forEach(([x, y]) => svg.append(el("circle", { cx: x, cy: y, r: 6, fill: "#0b0d0c", stroke: "#3d8d63" })));
    svg.append(el("text", { x: 34, y: 44, class: "bd-t bd-big" }, "BASYS 3"), el("text", { x: 34, y: 61, class: "bd-t bd-sub" }, "Artix-7 FPGA board"));
    // Pmod JA
    for (let r = 0; r < 2; r++) for (let i = 0; i < 6; i++) svg.append(el("rect", { x: 34 + i * 11, y: 78 + r * 11, width: 8, height: 8, fill: "#c9a227", rx: 1 }));
    svg.append(el("text", { x: 34, y: 116, class: "bd-t bd-sub" }, "Pmod JA"));
    wrap(cfg.pmod || "", 24).slice(0, 2).forEach((l, i) => svg.append(el("text", { x: 34, y: 130 + i * 13, class: "bd-t bd-tiny" }, l)));
    // USB and the clock
    svg.append(el("rect", { x: -4, y: 158, width: 30, height: 36, rx: 3, fill: "#5b6360", stroke: "#2b302e" }));
    const usb = el("circle", { cx: 40, cy: 176, r: 4, fill: "#1f4a33" });
    svg.append(usb, el("text", { x: 50, y: 173, class: "bd-t bd-sub" }, "USB serial"), el("text", { x: 50, y: 186, class: "bd-t bd-sub" }, "to the PC"));
    svg.append(el("rect", { x: 34, y: 212, width: 26, height: 16, rx: 2, fill: "#d9ddd6" }), el("text", { x: 34, y: 244, class: "bd-t bd-sub" }, "100 MHz clock, halved to 50"));
    // the FPGA
    const fx = 196, fy = 76;
    svg.append(el("rect", { x: fx - 6, y: fy - 6, width: 152, height: 152, rx: 4, fill: "none", stroke: "#4c9a70", "stroke-dasharray": "2 3" }));
    svg.append(el("rect", { x: fx, y: fy, width: 140, height: 140, rx: 6, fill: "#1a1d1c", stroke: "#3a403d" }));
    svg.append(el("text", { x: fx + 14, y: fy + 30, class: "bd-t bd-chip" }, "XC7A35T"), el("text", { x: fx + 14, y: fy + 50, class: "bd-t bd-amber" }, cfg.chip));
    wrap(cfg.inside, 22).slice(0, 4).forEach((l, i) => svg.append(el("text", { x: fx + 14, y: fy + 72 + i * 14, class: "bd-t bd-sub" }, l)));
    // 7-segment display: uo_out on the left two digits, ui_in on the right two
    const dx = 372, dy = 32;
    svg.append(el("rect", { x: dx, y: dy, width: 190, height: 76, rx: 6, fill: "#0b0d0c", stroke: "#2b302e" }));
    const digits = [0, 1, 2, 3].map(i => {
      const g = el("g", { transform: `translate(${dx + 18 + i * 42 + (i > 1 ? 4 : 0)},${dy + 14})` });
      const segs = {};
      for (const s in SEG) { const [x, y, w, h] = SEG[s]; segs[s] = el("rect", { x, y, width: w, height: h, rx: 1.5, class: "bd-seg" }); g.append(segs[s]); }
      const dot = el("circle", { cx: 31, cy: 42, r: 2.4, class: "bd-seg" }); g.append(dot);
      svg.append(g); return { segs, dot };
    });
    svg.append(el("text", { x: dx + 40, y: dy + 90, class: "bd-t bd-sub", "text-anchor": "middle" }, "uo_out"), el("text", { x: dx + 146, y: dy + 90, class: "bd-t bd-sub", "text-anchor": "middle" }, "ui_in"));
    // buttons: {U, R, L, C} in the recording, D drawn but not recorded
    const bx = 466, by = 198, B = { U: [0, -44, 3], L: [-48, 0, 1], C: [0, 0, 0], R: [48, 0, 2], D: [0, 44, -1] };
    const caps = {};
    for (const k in B) {
      const [ox, oy] = B[k];
      svg.append(el("rect", { x: bx + ox - 17, y: by + oy - 17, width: 34, height: 34, rx: 5, fill: "#2b302e", stroke: "#4a524e" }));
      caps[k] = el("circle", { cx: bx + ox, cy: by + oy, r: 11, class: "bd-cap" }); svg.append(caps[k]);
      const name = k === "C" ? "" : (cfg.buttons || {})[k] || "";
      if (name) svg.append(el("text", { x: bx + ox + (ox < 0 ? -24 : ox > 0 ? 24 : 24), y: by + oy + 4, class: "bd-t bd-sub", "text-anchor": ox < 0 ? "end" : "start" }, name));
    }
    svg.append(el("text", { x: bx - 24, y: by + 48, class: "bd-t bd-sub", "text-anchor": "end" }, "centre: reset"));
    // LEDs, LD15 on the left as on the board
    const leds = [];
    for (let i = 15; i >= 0; i--) {
      const x = 44 + (15 - i) * 33, y = 304;
      const name = (cfg.leds || [])[i] || "";
      if (name) svg.append(el("text", { x, y: y - 14 - ((15 - i) % 2) * 13, class: "bd-t bd-sub", "text-anchor": "middle" }, name));
      const halo = el("circle", { cx: x, cy: y, r: 9, class: "bd-halo", filter: "url(#bd-glow)", opacity: 0 });
      const led = el("rect", { x: x - 6, y: y - 4, width: 12, height: 8, rx: 2, class: "bd-led" });
      svg.append(halo, led, el("text", { x, y: y + 20, class: "bd-t bd-tiny", "text-anchor": "middle" }, "LD" + i));
      leds[i] = { halo, led };
      svg.append(el("rect", { x: x - 5, y: 346, width: 10, height: 22, rx: 2, fill: "#d9ddd6" }), el("rect", { x: x - 3, y: 356, width: 6, height: 9, fill: "#2b302e" }));
    }
    // the corner tag: this is a simulation
    svg.append(el("rect", { x: 352, y: 376, width: 224, height: 20, rx: 4, fill: "#0b0d0c", stroke: "#ffb000" }), el("text", { x: 464, y: 390, class: "bd-t bd-amber bd-tag", "text-anchor": "middle" }, "Simulated board, not a real one"));

    // the terminal
    svg.append(el("rect", { x: 604, y: 1, width: 295, height: 404, rx: 10, fill: "#0b0d0c", stroke: "#2b302e" }));
    svg.append(el("text", { x: 620, y: 26, class: "bd-t bd-sub" }, cfg.terminal_title || "PC terminal"), el("line", { x1: 604, y1: 38, x2: 899, y2: 38, stroke: "#2b302e" }));
    const LINES = 21, termLines = [];
    for (let i = 0; i < LINES; i++) { const t = el("text", { x: 618, y: 60 + i * 15.5, class: "bd-term" }); svg.append(t); termLines.push(t); }
    const keys = el("text", { x: 618, y: 396, class: "bd-t bd-probe" }); svg.append(keys);

    // the whole-run strip of LD0, with the bench's actions marked and the cursor
    const sy = 428, sh = 26, sx0 = 110, sx1 = 896, X = c => sx0 + (sx1 - sx0) * c / end;
    svg.append(el("text", { x: 0, y: sy + 4, class: "bd-t bd-sub" }, "LD0 (" + ((cfg.leds || [])[0] || "") + ")"), el("text", { x: 0, y: sy + 18, class: "bd-t bd-tiny" }, "whole run"));
    let d = "", v0 = 0, lastX = sx0;
    rec.led.forEach(([c, v]) => { const b = v & 1; if (b !== v0) { const x = X(c); d += (b ? `M${lastX.toFixed(1)},${sy + sh}H${x.toFixed(1)}V${sy}` : `H${Math.max(x, lastX + 3).toFixed(1)}V${sy + sh}`); lastX = b ? x : Math.max(x, lastX + 3); v0 = b; } });
    d += v0 ? `H${sx1}` : `M${lastX.toFixed(1)},${sy + sh}H${sx1}`;
    svg.append(el("path", { d, class: "bd-trace" }));
    const marks = [];
    let prev = 0;
    rec.btn.forEach(([c, v]) => { [["C", 0], ["L", 1], ["R", 2], ["U", 3]].forEach(([k, b]) => { if ((v >> b) & 1 && !((prev >> b) & 1)) marks.push([c, "BTN" + k]); }); prev = v; });
    if (!marks.length || cfg.terminal === "text") rec.uart.forEach(([c, tx]) => { if (!tx) marks.push([c, "typed"]); });
    marks.forEach(([c, name]) => svg.append(el("line", { x1: X(c), x2: X(c), y1: sy + sh + 4, y2: sy + sh + 14, class: "bd-mark" }), el("text", { x: X(c) + 3, y: sy + sh + 16, class: "bd-t bd-tiny bd-probe" }, name)));
    const cursor = el("line", { y1: sy - 6, y2: sy + sh + 4, class: "bd-cursor" }); svg.append(cursor);

    // controls
    const bar = document.createElement("div"); bar.className = "board-bar";
    const play = document.createElement("button"); play.type = "button"; play.className = "btn"; play.textContent = "Play";
    const range = document.createElement("input"); range.type = "range"; range.min = 0; range.max = end; range.step = 1;
    range.setAttribute("aria-label", "Recorded cycle");
    const read = document.createElement("output"); read.className = "mono";
    bar.append(play, range, read);
    host.replaceChildren(svg, bar);

    let c = reduce ? end : 0, raf = 0, last = 0;
    function terminal(upto) {
      const out = [];
      if (cfg.terminal === "text") {
        let cur = "";
        for (const [cc, tx, b] of rec.uart) { if (cc > upto) break; if (!tx) continue; if (b === 10) { out.push([cur, "chip"]); cur = ""; } else if (b >= 32 && b < 127) cur += String.fromCharCode(b); }
        out.push([cur, "chip"]);
      } else {
        let run = [], who = null;
        for (const [cc, tx, b] of rec.uart) {
          if (cc > upto) break;
          const w = tx ? "chip" : "host";
          if (w !== who && run.length) { out.push([(who === "host" ? cfg.host_prefix : cfg.chip_prefix) + run.join(" "), who]); run = []; }
          who = w; run.push(b.toString(16).toUpperCase().padStart(2, "0"));
        }
        if (run.length) out.push([(who === "host" ? cfg.host_prefix : cfg.chip_prefix) + run.join(" "), who]);
      }
      return out.flatMap(([t, w]) => wrap(t, 36).map(l => [l, w]));
    }
    function draw() {
      const ci = Math.round(c);
      const out = at(rec.out, ci), inn = at(rec.in, ci), btn = at(rec.btn, ci) || 0;
      [out == null ? null : out >> 4, out == null ? null : out & 15, inn == null ? null : inn >> 4, inn == null ? null : inn & 15].forEach((v, i) => {
        const lit = v == null ? "g" : SEGS[v];
        for (const s in digits[i].segs) digits[i].segs[s].classList.toggle("on", lit.includes(s));
        digits[i].dot.classList.toggle("on", i === 1);
      });
      for (const k in B) caps[k].classList.toggle("on", B[k][2] >= 0 && ((btn >> B[k][2]) & 1) === 1);
      const c0 = Math.max(0, ci - win);
      for (let i = 0; i < 16; i++) {
        const f = ci === 0 ? ((at(rec.led, 0) >> i) & 1) : duty(rec.led, i, c0, Math.max(ci, c0 + 1));
        const b = f > 0 ? 0.35 + 0.65 * f : 0;
        leds[i].led.style.setProperty("--on", b.toFixed(3)); leds[i].halo.setAttribute("opacity", (b * 0.9).toFixed(3));
      }
      const lines = terminal(ci), show = lines.slice(-LINES);
      termLines.forEach((t, i) => {
        const l = show[i]; t.textContent = l ? l[0] + (i === show.length - 1 ? " █" : "") : "";
        t.setAttribute("class", "bd-term" + (l && l[1] === "host" ? " host" : ""));
      });
      const typed = cfg.terminal === "text" ? rec.uart.filter(([cc, tx]) => !tx && cc <= ci).map(u => String.fromCharCode(u[2])).join("") : "";
      keys.textContent = typed ? "keys the PC sent: " + typed : "";
      const busy = rec.uart.some(([cc]) => cc <= ci && cc > ci - win * 2);
      usb.setAttribute("fill", busy ? "#9ad8f7" : "#1f4a33");
      cursor.setAttribute("x1", X(ci)); cursor.setAttribute("x2", X(ci));
      range.value = ci;
      const us = (ci * 20 / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 });
      read.textContent = `cycle ${ci.toLocaleString("en-US")} · ${us} µs`;
      range.setAttribute("aria-valuetext", read.textContent);
    }
    function tick(now) {
      const dt = Math.min(50, now - last); last = now;
      c = Math.min(end, c + end * dt / PLAY_MS); draw();
      if (c >= end) { stop(); return; }
      raf = requestAnimationFrame(tick);
    }
    function start() { if (c >= end) c = 0; play.textContent = "Pause"; last = performance.now(); raf = requestAnimationFrame(tick); }
    function stop() { cancelAnimationFrame(raf); raf = 0; play.textContent = c >= end ? "Play again" : "Play"; }
    play.addEventListener("click", () => (raf ? stop() : start()));
    range.addEventListener("input", () => { if (raf) stop(); c = +range.value; draw(); });
    svg.addEventListener("pointerdown", e => {
      const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
      const q = p.matrixTransform(svg.getScreenCTM().inverse());
      if (q.y > sy - 10 && q.x >= sx0) { if (raf) stop(); c = Math.max(0, Math.min(end, (q.x - sx0) / (sx1 - sx0) * end)); draw(); }
    });
    draw(); stop();
    if (!reduce && "IntersectionObserver" in root) {
      const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); start(); } }, { threshold: 0.5 });
      io.observe(host);
    }
    return { draw };
  }

  function wrap(text, n) {
    const out = []; let cur = "";
    String(text).split(" ").forEach(w => { if (cur && (cur + " " + w).length > n) { out.push(cur); cur = w; } else cur = cur ? cur + " " + w : w; });
    out.push(cur); return out;
  }

  root.TQBoard = { mount };
})(window);
