/* labs.js — two small instruments, computed in the browser from recorded data.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   TQLabs.deadline: "fire a deadline". Everything it draws is derived from
   the recorded deadline tour: the tick channel 0 was armed on, the offset
   between clock cycles and timebase ticks, and the pulse width. Choose how
   many ticks after arming TRIG0 should fire; the lab shows the pin rising on
   exactly that tick, as the recording does for its own value. It is labelled
   computed, and links to the recording it comes from.

   TQLabs.ring: the rotating register file as a ring of eight nibbles turning
   past the single 4-bit adder, for the nibble lab.

   Both move the way the player does: a critically damped spring, so motion
   arrives quickly and settles without overshoot; with prefers-reduced-motion
   they jump straight to the end state. */
(function (root) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const el = (n, a, txt) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; return e; };

  // a critically damped spring from the current value to a target; calls step(value) per frame
  function spring(from, to, step, k) {
    if (reduce) { step(to); return () => {}; }
    k = k || 90;
    const c = 2 * Math.sqrt(k);
    let x = from, v = 0, last = performance.now(), raf = 0, done = false;
    const tick = now => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      v += (k * (to - x) - c * v) * dt; x += v * dt;
      if (Math.abs(to - x) < 1e-3 * Math.max(1, Math.abs(to - from)) && Math.abs(v) < 1e-2) { step(to); return; }
      step(x); if (!done) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { done = true; cancelAnimationFrame(raf); };
  }

  const at = (sig, c) => { let v = null; for (const [cc, vv] of sig.changes) { if (cc > c) break; v = vv; } return v; };
  const rise = sig => { const ch = sig.changes; for (let i = 1; i < ch.length; i++) if (ch[i][1] && !ch[i - 1][1]) return ch[i][0]; return null; };
  const fall = (sig, after) => { for (const [c, v] of sig.changes) if (c > after && !v) return c; return null; };

  // ------------------------------------------------------------ fire a deadline
  function deadline(host, fx, cfg) {
    cfg = cfg || {};
    const S = id => fx.signals.find(s => s.id === id);
    const trig = S("trig0"), armed = S("armed0"), dl = S("deadline0"), now = S("now");
    const armC = rise(armed), riseC = rise(trig), fallC = fall(trig, riseC);
    const D = at(dl, riseC), off = D - riseC;          // timebase tick = clock cycle + off
    const A = armC + off, width = fallC - riseC, recN = D - A;
    const ns = cfg.clockNs || 20;
    const MIN = 8, MAX = 0x7fffffff;

    host.innerHTML = "";
    const form = document.createElement("form"); form.className = "dl-form"; form.noValidate = true;
    form.innerHTML = "<div class=dl-in><label for=dl-n>Fire TRIG0 this many ticks after it is armed</label>" +
      "<div class=row><input id=dl-n inputmode=numeric autocomplete=off spellcheck=false aria-describedby=dl-msg>" +
      "<button class=btn type=submit>Arm and fire</button><button class='btn ghost' type=button id=dl-rec>Use the recorded value</button></div></div>" +
      "<p id=dl-msg class=small role=status></p>";
    const svg = el("svg", { viewBox: "0 0 760 156", class: "dl-scope", role: "img", "aria-labelledby": "dl-sum" });
    const sum = document.createElement("p"); sum.id = "dl-sum"; sum.className = "dl-sum";
    const facts = document.createElement("dl"); facts.className = "kv dl-facts";
    host.append(form, svg, sum, facts);
    const input = form.querySelector("#dl-n"), msg = form.querySelector("#dl-msg");
    input.value = String(recN);
    let stop = () => {};

    function parse(t) {
      t = String(t).trim().replace(/[_,\s]/g, "");
      if (!t) return { err: "Type a number of ticks." };
      if (!/^\d+$/.test(t)) return { err: "Whole ticks only: digits, no sign or decimal point." };
      const n = Number(t);
      if (n < MIN) return { err: "At least " + MIN + " ticks: the recording does not show what a shorter offset does, so this lab does not guess." };
      if (n > MAX) return { err: "At most 2^31 − 1 = 2,147,483,647 ticks: the comparator is wrap-safe within 2^31 ticks." };
      return { n };
    }

    function draw(n, cursorTick) {
      svg.replaceChildren();
      const d = A + n, X0 = 120, X1 = 744;
      // one window, or two with a break when the wait is long
      const split = n > 70;
      const win = split ? [[A - 8, A + 26], [d - 14, d + width + 20]] : [[A - 8, d + width + 20]];
      const gap = split ? 34 : 0, span = X1 - X0 - gap;
      const lens = win.map(w => w[1] - w[0]), tot = lens.reduce((a, b) => a + b, 0);
      const x = t => {
        let x = X0;
        for (let i = 0; i < win.length; i++) {
          const w = win[i], px = span * lens[i] / tot;
          if (t <= w[1] || i === win.length - 1) return x + px * Math.max(0, Math.min(1, (t - w[0]) / lens[i]));
          x += px + gap;
        }
        return x;
      };
      const rows = [["tick", 30], ["armed 0", 78], ["TRIG0 (uo_out[0])", 126]];
      rows.forEach(([name, y]) => svg.append(el("text", { x: 8, y: y + 4, class: "dl-lbl" }, name)));
      // tick ruler, with labels at the moments that matter
      win.forEach(w => {
        for (let t = Math.ceil(w[0] / 2) * 2; t <= w[1]; t += 2) svg.append(el("line", { x1: x(t), x2: x(t), y1: 34, y2: t % 10 ? 38 : 42, class: "dl-tk" }));
      });
      [[A, "armed " + A.toLocaleString("en-US")], [d, "deadline " + d.toLocaleString("en-US")]].forEach(([t, s], i) => {
        svg.append(el("line", { x1: x(t), x2: x(t), y1: 44, y2: 150, class: "dl-mark" }));
        svg.append(el("text", { x: x(t) + (i ? -4 : 4), y: 24, class: "dl-ann", "text-anchor": i ? "end" : "start" }, s));
      });
      if (split) {
        const bx = x(win[0][1]) + gap / 2;
        svg.append(el("text", { x: bx, y: 24, class: "dl-ann", "text-anchor": "middle" }, "≈"));
        [78, 126].forEach(y => svg.append(el("path", { d: `M${bx - 7} ${y + 10} l6 -20 M${bx + 1} ${y + 10} l6 -20`, class: "dl-brk" })));
      }
      // waveforms, segment by segment so the break stays empty
      const wave = (y, segs, cls) => {
        let p = "";
        segs.forEach(([t0, t1, v]) => { const yy = v ? y - 14 : y + 10; p += (p ? "L" : "M") + x(t0) + " " + yy + "L" + x(t1) + " " + yy; });
        svg.append(el("path", { d: p, class: cls }));
      };
      const clip = segs => segs.flatMap(([t0, t1, v]) => win.map(w => [Math.max(t0, w[0]), Math.min(t1, w[1]), v]).filter(s => s[0] < s[1]));
      const pieces = segs => { const c = clip(segs); return c.reduce((acc, s, i) => { if (i && c[i - 1][1] !== s[0]) acc.push([]); acc[acc.length - 1].push(s); return acc; }, [[]]); };
      pieces([[A - 8, A, 0], [A, d, 1], [d, d + width + 20, 0]]).forEach(s => wave(78, s, "dl-bit"));
      pieces([[A - 8, d, 0], [d, d + width, 1], [d + width, d + width + 20, 0]]).forEach(s => wave(126, s, "dl-trig"));
      // the cursor: where the timebase is now
      const ct = cursorTick == null ? d : cursorTick;
      svg.append(el("line", { x1: x(ct), x2: x(ct), y1: 40, y2: 150, class: "dl-cur" }));
    }

    function show(n, animate) {
      stop();
      const d = A + n, us = n * ns / 1000;
      sum.textContent = "Armed on tick " + A.toLocaleString("en-US") + " for " + n.toLocaleString("en-US") + " ticks later: TRIG0 rises on tick " +
        d.toLocaleString("en-US") + ", " + (us < 1000 ? us.toLocaleString("en-US", { maximumFractionDigits: 2 }) + " µs" : (us / 1000).toLocaleString("en-US", { maximumFractionDigits: 3 }) + " ms") +
        " after arming at " + (1000 / ns) + " MHz, and stays high for " + width + " ticks.";
      facts.replaceChildren(...[
        ["Kind", "<span class='ev computed'>computed</span> from the recorded deadline tour, not simulated"],
        ["From the recording", "armed on tick " + A.toLocaleString("en-US") + ", deadline tick " + D.toLocaleString("en-US") + " (" + recN.toLocaleString("en-US") + " later), TRIG0 high for " + width + " ticks; tick = clock cycle + " + off],
        cfg.resume ? ["Software", "after <code>tp_wait</code>, the next instruction runs " + cfg.resume[0] + " to " + cfg.resume[1] + " clocks after the deadline, depending on the register rotation phase (<code>make latency</code>); the pin itself needs no software"] : null,
        ["See it recorded", "<a href='" + (cfg.recordedHref || "#seq=deadline") + "'>the deadline tour</a>, cycle by cycle"]
      ].filter(Boolean).flatMap(([k, v]) => { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = k; dd.innerHTML = v; return [dt, dd]; }));
      if (animate) stop = spring(A, d, t => draw(n, t), 60);
      else draw(n);
    }

    function submit(animate) {
      const r = parse(input.value);
      input.setAttribute("aria-invalid", r.err ? "true" : "false");
      msg.textContent = r.err || "";
      msg.classList.toggle("err", !!r.err);
      if (!r.err) show(r.n, animate);
    }
    form.addEventListener("submit", e => { e.preventDefault(); submit(true); });
    form.querySelector("#dl-rec").addEventListener("click", () => { input.value = String(recN); submit(true); });
    input.addEventListener("input", () => { if (input.getAttribute("aria-invalid") === "true") submit(false); });
    show(recN, false);
    return { show };
  }

  // ------------------------------------------------------------ the register ring
  function ring(host) {
    const svg = el("svg", { viewBox: "-130 -130 260 260", class: "ring", role: "img", "aria-labelledby": "ring-t" });
    const title = el("title", { id: "ring-t" });
    const turn = el("g", { class: "ring-turn" });
    const adder = el("g", { class: "ring-adder" });
    svg.append(title, turn, adder);
    host.replaceChildren(svg);
    const slots = [];
    for (let i = 0; i < 8; i++) {
      const g = el("g", { transform: `rotate(${i * 45}) translate(0 -92)` });
      const r = el("rect", { x: -19, y: -15, width: 38, height: 30, rx: 3, class: "ring-slot" });
      // the slot travels round the ring but stays upright, so its digits stay readable
      const up = el("g");
      const t = el("text", { y: 1, class: "ring-a", "text-anchor": "middle", "dominant-baseline": "middle" });
      const s = el("text", { y: 27, class: "ring-s", "text-anchor": "middle", "dominant-baseline": "middle" });
      const n = el("text", { y: -21, class: "ring-n", "text-anchor": "middle" }, "n" + i);
      up.append(r, t, s, n); g.append(up); turn.append(g); slots.push({ r, t, s, up, base: i * 45 });
    }
    adder.append(el("rect", { x: -34, y: -130, width: 68, height: 24, rx: 3, class: "ring-add" }),
      el("text", { y: -114, class: "ring-addt", "text-anchor": "middle" }, "4-bit adder"),
      el("path", { d: "M0 -106 L0 -112", class: "ring-tick" }));
    const carry = el("text", { x: 0, y: 4, class: "ring-c", "text-anchor": "middle" });
    const mid = el("text", { x: 0, y: 24, class: "ring-mid", "text-anchor": "middle" }, "carry flip-flop");
    svg.append(carry, mid);
    let angle = 0, stop = () => {};
    function update(op, shown, hi) {
      const phase = hi !== undefined ? hi : Math.min(7, shown - 1);
      op.phases.forEach((p, i) => {
        slots[i].t.textContent = p.a_n.toString(16).toUpperCase();
        slots[i].s.textContent = i < shown ? "= " + p.sum_n.toString(16).toUpperCase() : "";
        slots[i].r.classList.toggle("on", i === phase);
        slots[i].r.classList.toggle("done", i < shown && i !== phase);
      });
      const p = op.phases[phase];
      carry.textContent = "carry " + p.cout;
      title.textContent = "The register file as a ring of eight nibbles turning past one 4-bit adder: phase " + phase + " is at the adder, A nibble " +
        p.a_n.toString(16).toUpperCase() + " plus " + p.bx_n.toString(16).toUpperCase() + " plus carry " + p.cin + " gives " + p.sum_n.toString(16).toUpperCase() + ".";
      stop();
      const target = -phase * 45;
      stop = spring(angle, target, a => {
        angle = a; turn.setAttribute("transform", `rotate(${a})`);
        slots.forEach(sl => sl.up.setAttribute("transform", `rotate(${-(sl.base + a)})`));
      }, 140);
    }
    return { update };
  }

  root.TQLabs = { deadline, ring };
})(window);
