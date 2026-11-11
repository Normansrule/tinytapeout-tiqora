/* schematic.js — steps a drawing of the RTL's logic through the recording:
   deadline channel 0 (docs/tools/schematic.py, both repos) and, in Tiqora,
   the core's 4-bit adder (docs/tools/adder_schematic.py).
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   The drawing arrives complete from docs/tools/schematic.py, written in at the
   clock the pin rises, so it reads without JavaScript. This script only moves
   it to another recorded clock: it lights the wires whose signal is 1, writes
   the recorded values into the registers, and moves the cursor on the timing
   strip. Nothing is computed here; every value comes from
   the figure's data file (docs/site/data/schematic.json, adder.json). A step
   may carry a label for the scrubber and hold: 1 to linger in play.

   Motion: a wire that turns on draws itself from source to sink, and a register
   whose value changes flashes as the clock edge reaches it. Play starts by
   itself the first time the drawing is in view, and stops when it leaves.
   With prefers-reduced-motion it never starts by itself and nothing draws or
   flashes: each step simply replaces the last. Keyboard: left and right step
   a clock, Home and End jump, space plays or pauses.

   Inspect: every part of the drawing is a button. Choosing one (a click, or Tab
   to it and Enter) lights the wires that touch it, dims the rest, and shows its
   RTL line and its value at the shown clock beside the drawing, as a schematic
   viewer does. Which wires touch a part is read from the drawing itself: a wire
   touches a part when one of its ends lies on the part's outline. Escape, or
   choosing it again, lets go. */
(function (root) {
  "use strict";
  const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = v => Number(v).toLocaleString("en-US");

  function mount(fig, d) {
    if (!fig || !d || !d.steps) return;
    const svg = fig.querySelector("svg.sc"), bar = fig.querySelector(".schem-bar");
    const range = bar.querySelector("input[type=range]"), out = bar.querySelector("output");
    const play = bar.querySelector("[data-play]"), cap = fig.querySelector(".schem-cap");
    const stage = fig.querySelector(".schem-stage"), cur = fig.querySelector(".schem-strip .cur");
    const xs = JSON.parse(fig.querySelector(".schem-strip .cursor").dataset.xs);
    const desc = svg.querySelector("desc");
    const wires = [...svg.querySelectorAll(".w[data-s]")];
    const glows = new Map([...svg.querySelectorAll(".glow[data-g]")].map(g => [g.dataset.g, g]));
    const dots = [...svg.querySelectorAll(".dot[data-s]")];
    const ons = [...svg.querySelectorAll("[data-on]")];
    const pad = svg.querySelector(".pad");
    const vals = [...svg.querySelectorAll("[data-v]")];
    const steps = d.steps, n = steps.length;
    let i = d.edge, timer = 0, playing = false, seen = false, inspect = null;
    bar.hidden = false;
    // on a phone the drawing and its timing strip each pan sideways; keep them lined up
    const strip = fig.querySelector(".schem-strip");
    if (strip) for (const [a, b] of [[stage, strip], [strip, stage]])
      a.addEventListener("scroll", () => { if (b.scrollLeft !== a.scrollLeft) b.scrollLeft = a.scrollLeft; }, { passive: true });

    const bit = (s, sig) => sig === "armed_reached" ? (s.armed & s.reached) : s[sig];
    const text = (s, k) => {
      switch (k) {
        case "arm_time": return s.arm_we ? fmt(s.arm_time) : "";
        case "arm_m1": return s.arm_we ? fmt(s.arm_m1) : "";
        case "now": case "dm1": case "diff": return fmt(s[k]);
        default: return s[k] == null ? "" : String(s[k]);
      }
    };

    function show(k, animate) {
      const s = steps[k], p = steps[k - 1];
      const flow = animate && !reduce && p && k === i + 1;
      for (const w of wires) {
        const on = !!bit(s, w.dataset.s), was = w.classList.contains("on");
        w.classList.toggle("on", on);
        w.classList.remove("flow");
        if (on && !was && flow) { void w.getBBox(); w.classList.add("flow"); }
        const g = glows.get(w.dataset.w); if (g) g.style.opacity = on ? ".18" : "0";
      }
      for (const c of dots) c.classList.toggle("on", !!bit(s, c.dataset.s));
      for (const c of ons) c.classList.toggle("on", !!s[c.dataset.on]);
      if (pad) pad.classList.toggle("on", !!s.pin);
      for (const v of vals) {
        const t = text(s, v.dataset.v);
        if (v.textContent !== t) {
          v.textContent = t;
          v.style.fontSize = t.length > 9 && v.classList.contains("vb") ? "15px" : "";
          const box = v.closest(".part");
          if (flow && box) { box.classList.remove("tick"); void box.getBBox(); box.classList.add("tick"); }
        }
      }
      i = k;
      if (inspect) inspect.refresh();
      range.value = k;
      const label = s.label || `cycle ${fmt(s.cycle)} · now ${fmt(s.now)}`;
      range.setAttribute("aria-valuetext", label.replace(/ · /g, ", "));
      out.textContent = label;
      cap.textContent = s.text;
      if (desc) desc.textContent = s.text;
      cur.setAttribute("x", xs[k]);
    }

    // a step lingers longer where something happens: the arm, the jump, the edge
    const dwell = k => {
      const s = steps[k], p = steps[k - 1];
      if (!p || s.part !== p.part || s.hold || s.fire || s.arm_we || (s.pin !== p.pin)) return 3200;
      return 1300;
    };
    function stop() {
      clearTimeout(timer); playing = false;
      play.textContent = "Play"; play.setAttribute("aria-pressed", "false");
    }
    function tick() {
      if (i >= n - 1) { stop(); return; }
      show(i + 1, true);
      timer = setTimeout(tick, dwell(i));
    }
    function start(from) {
      clearTimeout(timer); playing = true;
      play.textContent = "Pause"; play.setAttribute("aria-pressed", "true");
      if (from != null || i >= n - 1) show(from != null ? from : 0, false);
      timer = setTimeout(tick, dwell(i));
    }

    play.addEventListener("click", () => playing ? stop() : start(i >= n - 1 ? 0 : null));
    bar.querySelectorAll("[data-step]").forEach(b => b.addEventListener("click", () => {
      stop(); const k = Math.max(0, Math.min(n - 1, i + Number(b.dataset.step))); show(k, k === i + 1);
    }));
    range.addEventListener("input", () => { stop(); show(Number(range.value), false); });
    stage.addEventListener("keydown", e => {
      let k = null;
      if (e.key === "ArrowRight") k = Math.min(n - 1, i + 1);
      else if (e.key === "ArrowLeft") k = Math.max(0, i - 1);
      else if (e.key === "Home") k = 0;
      else if (e.key === "End") k = n - 1;
      else if (e.key === " " || e.key === "Enter") { e.preventDefault(); playing ? stop() : start(i >= n - 1 ? 0 : null); return; }
      if (k == null) return;
      e.preventDefault(); stop(); show(k, k === i + 1);
    });

    // play once, from the arming, the first time the drawing is mostly in view; pause when it leaves
    if ("IntersectionObserver" in root) {
      new IntersectionObserver(es => {
        for (const e of es) {
          if (e.isIntersecting && !seen && !reduce) { seen = true; start(0); }
          else if (!e.isIntersecting && playing) stop();
        }
      }, { threshold: 0.55 }).observe(stage);
    }
    inspect = inspector(fig, svg);
    show(i, false);
  }

  function inspector(fig, svg) {
    const panel = fig.querySelector(".schem-inspect");
    const groups = new Map();
    for (const g of svg.querySelectorAll(".part[data-part]")) {
      const id = g.dataset.part;
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(g);
    }
    if (!panel || !groups.size) return null;
    const entries = new Map([...fig.querySelectorAll(".schem-parts li[data-part]")].map(li => [li.dataset.part, li]));
    const wires = [...svg.querySelectorAll(".w[data-w]")];
    const glows = [...svg.querySelectorAll(".glow[data-g]")];
    const ends = w => {
      const v = (w.getAttribute("d").match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
      return v.length < 4 ? [] : [[v[0], v[1]], [v[v.length - 2], v[v.length - 1]]];
    };
    // measured once, the first time a part is chosen: the drawing does not move
    let touch = null;
    const measure = () => {
      touch = new Map();
      for (const [id, gs] of groups) {
        const bs = gs.map(g => g.getBBox()).filter(b => b.width || b.height);
        const near = ([x, y]) => bs.some(b => x >= b.x - 6 && x <= b.x + b.width + 6 && y >= b.y - 6 && y <= b.y + b.height + 6);
        touch.set(id, new Set(wires.filter(w => ends(w).some(near)).map(w => w.dataset.w)));
      }
    };
    let sel = null, hover = null;
    function paint() {
      const id = sel || hover;
      svg.classList.toggle("inspecting", !!id);
      if (id && !touch) measure();
      const ws = id ? touch.get(id) : null;
      for (const w of wires) w.classList.toggle("lit", !!ws && ws.has(w.dataset.w));
      for (const g of glows) g.classList.toggle("lit", !!ws && ws.has(g.dataset.g));
      for (const [k, gs] of groups) for (const g of gs) {
        g.classList.toggle("sel", k === id);
        if (g.hasAttribute("tabindex")) g.setAttribute("aria-pressed", String(k === sel));
      }
    }
    function refresh() {
      if (!sel) { panel.hidden = true; panel.textContent = ""; return; }
      const li = entries.get(sel), gs = groups.get(sel);
      const val = gs.map(g => g.querySelector("[data-v]")).find(Boolean);
      const a = li && li.querySelector("a"), code = li && li.querySelector("code");
      panel.textContent = "";
      const h = document.createElement("p"); h.className = "si-h";
      const b = document.createElement("strong"); b.textContent = a ? a.textContent : sel; h.append(b);
      if (a) { const l = a.cloneNode(true); l.textContent = `${fig.dataset.rtl || "source"} ${(li.querySelector(".small") || {}).textContent || ""}`.trim(); h.append(" · ", l); }
      panel.append(h);
      if (code) panel.append(code.cloneNode(true));
      const p = document.createElement("p"); p.className = "si-v";
      const ws = touch.get(sel).size;
      p.textContent = (val && val.textContent ? `At this clock: ${val.textContent}. ` : "") +
        `${ws} wire${ws === 1 ? "" : "s"} touch it, lit in the drawing. Escape lets go.`;
      panel.append(p);
      panel.hidden = false;
    }
    function choose(id) {
      sel = sel === id ? null : id;
      paint(); refresh();
    }
    for (const [id, gs] of groups) {
      const g = gs.find(x => x.querySelector("title")) || gs[0];
      const t = g.querySelector("title");
      g.setAttribute("tabindex", "0"); g.setAttribute("role", "button");
      g.setAttribute("aria-label", t ? t.textContent : id); g.setAttribute("aria-pressed", "false");
      g.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); choose(id); }
      });
      for (const x of gs) {
        x.addEventListener("click", e => { e.stopPropagation(); choose(id); });
        x.addEventListener("pointerenter", e => { if (e.pointerType === "mouse") { hover = id; paint(); } });
        x.addEventListener("pointerleave", () => { if (hover === id) { hover = null; paint(); } });
      }
    }
    fig.addEventListener("keydown", e => { if (e.key === "Escape" && sel) { sel = null; paint(); refresh(); } });
    svg.addEventListener("click", () => { if (sel) { sel = null; paint(); refresh(); } });
    return { refresh };
  }

  root.TQSchem = { mount };
})(window);
