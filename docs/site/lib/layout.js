/* layout.js — the real routed chip: every placed cell and every wire LibreLane drew.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; the data is
   docs/site/data/routed.json (docs/tools/routed_map.py, from a LibreLane run's DEF).

   The look: each metal layer is drawn alone, then tinted with a gradient that drifts in
   hue across the die, the way thin oxide films turn a real die into a rainbow under a
   microscope lamp; the layers are then added together, so where wires cross they glow.
   A band of light sweeps the metal and the vias catch it. All of it is the real
   geometry; only the colours are chosen.

   Motion: the light follows scrolling and the pointer, never runs on its own, and stops
   with prefers-reduced-motion. "Send a clock edge" lights the clock tree net by net in
   the order of its depth below the clk pin, then the flip-flops it reaches; with reduced
   motion it shows the whole tree at once. */
(function (root) {
  "use strict";

  const SCREEN = "#05070a";
  // per layer: two ends of a thin-film gradient that runs across the die
  const FILM = {
    li1: ["#3b4bff", "#7a3bff"], met1: ["#6b5bff", "#00d0ff"], met2: ["#00e0c0", "#3c8cff"],
    met3: ["#ffc04d", "#ff5fa2"], met4: ["#ff4f8b", "#b06bff"], met5: ["#ffffff", "#aaaaaa"]
  };
  // cells sit under the metal, quiet: flip-flops a little green, clock buffers amber
  const CLASS_FILL = ["rgba(70, 210, 150, .26)", "rgba(140, 160, 200, .13)", "rgba(110, 130, 255, .20)", "rgba(255, 176, 0, .62)", "rgba(120, 130, 160, .05)"];
  const reduceMotion = () => root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function u16(s) {
    const bin = atob(s), a = new Uint16Array(bin.length >> 1);
    for (let i = 0; i < a.length; i++) a[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    return a;
  }
  function decode(R) {
    if (R._d) return R._d;
    const d = {
      W: R.die[0], H: R.die[1],
      cells: R.cells.map(u16), wires: R.wires.map(u16), vias: u16(R.vias), power: u16(R.power),
      clock: R.clock.map(c => ({ net: c.net, depth: c.depth, segs: u16(c.segs), flops: u16(c.flops) })),
      layers: R.layers, width: R.width_nm.map(w => Math.max(1, w / R.unit_nm))
    };
    d.depth = d.clock.reduce((m, c) => Math.max(m, c.depth), 0);
    d.flops = d.clock.reduce((n, c) => n + c.flops.length / 2, 0);
    return (R._d = d);
  }

  // one layer's wires, white on transparent, then tinted by its film gradient
  function layerCanvas(d, li, px, minW) {
    const c = document.createElement("canvas"); c.width = Math.ceil(d.W * px); c.height = Math.ceil(d.H * px);
    const g = c.getContext("2d"), a = d.wires[li];
    if (!a.length) return null;
    g.setTransform(px, 0, 0, -px, 0, c.height);
    g.fillStyle = "#fff";
    const w = Math.max(d.width[li], minW / px), h = w / 2;
    for (let i = 0; i < a.length; i += 4) g.fillRect(a[i] - h, a[i + 1] - h, a[i + 2] - a[i] + w, a[i + 3] - a[i + 1] + w);
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = "source-in";
    const f = FILM[d.layers[li]] || ["#fff", "#fff"], gr = g.createLinearGradient(0, c.height, c.width, 0);
    gr.addColorStop(0, f[0]); gr.addColorStop(.5, f[1]); gr.addColorStop(1, f[0]);
    g.fillStyle = gr; g.fillRect(0, 0, c.width, c.height);
    return c;
  }

  // the whole die, pre-rendered once: cells by class, the power grid, the metal layers added together
  function render(R, px, opt) {
    opt = opt || {};
    const d = decode(R);
    const c = document.createElement("canvas"); c.width = Math.ceil(d.W * px); c.height = Math.ceil(d.H * px);
    const g = c.getContext("2d");
    g.fillStyle = SCREEN; g.fillRect(0, 0, c.width, c.height);
    g.setTransform(px, 0, 0, -px, 0, c.height);
    const rowH = R.row - Math.min(R.row * .3, .8 / px);   // a hairline between rows, so the rows read
    d.cells.forEach((a, k) => {
      if (opt.classes && !opt.classes[k]) return;
      g.fillStyle = CLASS_FILL[k];
      for (let i = 0; i < a.length; i += 3) g.fillRect(a[i], a[i + 1], a[i + 2], rowH);
    });
    // power: rails and straps, faint, so the grid reads as the chip's skeleton
    const p = d.power;
    g.fillStyle = "rgba(200, 210, 230, .10)";
    for (let i = 0; i < p.length; i += 6) { const w = p[i + 5] / 2; g.fillRect(p[i + 1] - w, p[i + 2] - w, p[i + 3] - p[i + 1] + 2 * w, p[i + 4] - p[i + 2] + 2 * w); }
    g.setTransform(1, 0, 0, 1, 0, 0);
    const metal = document.createElement("canvas"); metal.width = c.width; metal.height = c.height;
    const mg = metal.getContext("2d");
    mg.globalCompositeOperation = "lighter";
    d.layers.forEach((L, li) => {
      if (opt.layers && !opt.layers[L]) return;
      const lc = layerCanvas(d, li, px, opt.minWirePx || .6);
      if (lc) { mg.globalAlpha = opt.alpha || .62; mg.drawImage(lc, 0, 0); }
    });
    g.globalCompositeOperation = "lighter";
    if (opt.bloom !== false && "filter" in g) {   // a soft glow under the wires (browsers without canvas filters skip it)
      g.filter = `blur(${Math.max(2, 6 * px * 10).toFixed(1)}px)`; g.globalAlpha = .4; g.drawImage(metal, 0, 0);
      g.filter = "none"; g.globalAlpha = 1;
    }
    g.drawImage(metal, 0, 0);
    g.globalCompositeOperation = "source-over";
    c._metal = metal;
    return c;
  }

  // seeded, so the same vias sparkle on every visit
  function sparkPoints(d, n) {
    const v = d.vias, out = [], cnt = v.length / 3;
    let s = 2463534242;
    const rnd = () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
    for (let i = 0; i < Math.min(n, cnt); i++) { const j = Math.floor(rnd() * cnt) * 3; out.push([v[j], v[j + 1], rnd()]); }
    return out;
  }

  // a light band over the metal at angle a and position t (0..1), with the vias near it glinting
  function drawLight(g, base, d, sparks, t, glint) {
    const W = base.width, H = base.height;
    g.clearRect(0, 0, W, H);
    const cx = -0.2 * W + t * 1.4 * W, band = W * .16;
    g.save();
    g.drawImage(base._metal, 0, 0);
    g.globalCompositeOperation = "source-in";
    const gr = g.createLinearGradient(cx - band, 0, cx + band * .6, H * .35);
    gr.addColorStop(0, "rgba(255,255,255,0)"); gr.addColorStop(.5, "rgba(255,250,235,.85)"); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.restore();
    g.save(); g.globalCompositeOperation = "lighter";
    const sx = W / d.W;
    for (const [x, y, ph] of sparks) {
      const X = x * sx, Y = H - y * sx, near = Math.max(0, 1 - Math.abs(X - (cx + (Y / H) * band * .3)) / band);
      const a = near * (.35 + .65 * Math.abs(Math.sin(glint * 2.1 + ph * 40)));
      if (a < .05) continue;
      const r = 1.2 + 2.4 * a;
      g.fillStyle = `rgba(255, 248, 230, ${a.toFixed(3)})`;
      g.fillRect(X - r, Y - .5, 2 * r, 1); g.fillRect(X - .5, Y - r, 1, 2 * r);
    }
    g.restore();
  }

  // the clock tree at time t (0..1): nets up to the current depth glow, then the flip-flops flash
  function drawClock(g, d, px, H, t, all) {
    const D = d.depth + 1, front = all ? D + 1 : t * (D + 1.2);
    g.save(); g.globalCompositeOperation = "lighter"; g.lineCap = "round";
    for (const c of d.clock) {
      const lit = Math.max(0, Math.min(1, front - c.depth));
      if (lit <= 0) continue;
      const s = c.segs, fade = all ? 1 : Math.max(.35, 1 - (front - c.depth - 1) * .45);
      for (const [w, a] of [[5, .18], [1.8, .95]]) {
        g.strokeStyle = `rgba(255, ${190 + 40 * (c.depth % 2)}, 90, ${(a * fade).toFixed(3)})`;
        g.lineWidth = w;
        g.beginPath();
        for (let i = 0; i < s.length; i += 5) {
          g.moveTo(s[i + 1] * px, H - s[i + 2] * px); g.lineTo(s[i + 3] * px, H - s[i + 4] * px);
        }
        g.stroke();
      }
    }
    const flash = all ? .9 : Math.max(0, Math.min(1, front - D)) * Math.max(0, 1.6 - (front - D));
    if (flash > 0.02) {
      g.fillStyle = `rgba(150, 255, 200, ${Math.min(1, flash).toFixed(3)})`;
      for (const c of d.clock) {
        const f = c.flops;
        for (let i = 0; i < f.length; i += 2) g.fillRect(f[i] * px - 1.5, H - f[i + 1] * px - 1.5, 3, 3);
      }
    }
    g.restore();
  }

  // the opening shot: the routed die in die.js's tilted, scroll-settling slot, with a light
  // that moves with scrolling and the pointer
  function hero(host, R) {
    const slot = host.querySelector(".chip3d"); if (!slot) return;
    const d = decode(R);
    const px = Math.min(2400, (root.innerWidth || 1200) * Math.min(2, root.devicePixelRatio || 1)) / d.W;
    const base = render(R, px);
    root.TQDie.reveal(host, null, { canvas: base, ar: d.W / d.H });
    host.classList.add("routed-hero");
    if (reduceMotion()) return;
    const light = document.createElement("canvas"); light.width = base.width; light.height = base.height;
    light.className = "glint"; light.setAttribute("aria-hidden", "true");
    base.after(light);
    const g = light.getContext("2d"), sparks = sparkPoints(d, 1400);
    let raf = 0, pointer = 0;
    const draw = () => {
      raf = 0;
      const p = parseFloat(host.style.getPropertyValue("--p")) || 0;
      drawLight(g, base, d, sparks, Math.min(1.05, .12 + p * .95 + pointer * .14), p * 6 + pointer * 3);
    };
    const ask = () => { if (!raf) raf = requestAnimationFrame(draw); };
    host.addEventListener("pointermove", e => { const r = host.getBoundingClientRect(); pointer = (e.clientX - r.left) / Math.max(1, r.width) - .5; ask(); });
    new MutationObserver(ask).observe(host, { attributes: true, attributeFilter: ["style"] });
    ask();
  }

  // the explorer: pan and zoom over the routed die, layers on and off, and a clock edge to send
  function explore(host, R) {
    const d = decode(R);
    const canvas = host.querySelector("canvas.routed"), g = canvas.getContext("2d");
    const readout = host.querySelector(".routed-readout");
    const onL = {}; d.layers.forEach(L => (onL[L] = true));
    const onC = [true, true, true, true, true];
    let base = null, view = { x: 0, y: 0, s: 1 }, edge = null, raf = 0, still = false;
    const dpr = () => root.devicePixelRatio || 1;
    let fitted = false;
    function rebuild() {
      size();
      const w = canvas.width;
      base = render(R, Math.min(3, (w * 2.2) / d.W), { layers: onL, classes: onC, minWirePx: .8 });
      if (!fitted) { fit(); fitted = true; }
      paint();
    }
    function size() {
      const w = canvas.clientWidth, h = Math.min(w * d.H / d.W, (root.innerHeight || 800) * .78);
      canvas.style.height = h + "px";
      canvas.width = Math.round(w * dpr()); canvas.height = Math.round(h * dpr());
    }
    const fitScale = () => Math.min(canvas.width / base.width, canvas.height / base.height);
    function fit() {
      const s = fitScale();
      view = { x: (canvas.width - base.width * s) / 2, y: (canvas.height - base.height * s) / 2, s };
    }
    function paint() {
      if (!base) return;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = SCREEN; g.fillRect(0, 0, canvas.width, canvas.height);
      g.setTransform(view.s, 0, 0, view.s, view.x, view.y);
      g.imageSmoothingEnabled = view.s < 1.5;
      g.globalAlpha = edge !== null || still ? .32 : 1;   // the layout dims while the clock tree shows
      g.drawImage(base, 0, 0);
      g.globalAlpha = 1;
      if (edge !== null || still) drawClock(g, d, base.width / d.W, base.height, edge || 0, still);
      g.setTransform(1, 0, 0, 1, 0, 0);
      if (readout) readout.textContent = `${Math.round(view.s / fitScale() * 100)}%`;
    }
    function zoomAt(f, cx, cy) {
      const s = Math.max(fitScale(), Math.min(view.s * f, 12));
      view.x = cx - (cx - view.x) * (s / view.s); view.y = cy - (cy - view.y) * (s / view.s); view.s = s;
      clamp(); paint();
    }
    function clamp() {
      const W = base.width * view.s, H = base.height * view.s;   // pan within the die; centre it where it is smaller than the view
      view.x = W <= canvas.width ? (canvas.width - W) / 2 : Math.min(0, Math.max(canvas.width - W, view.x));
      view.y = H <= canvas.height ? (canvas.height - H) / 2 : Math.min(0, Math.max(canvas.height - H, view.y));
    }
    canvas.addEventListener("wheel", e => { e.preventDefault(); const r = canvas.getBoundingClientRect(); zoomAt(Math.exp(-e.deltaY * .0015), (e.clientX - r.left) * dpr(), (e.clientY - r.top) * dpr()); }, { passive: false });
    let drag = null;
    const pts = new Map();
    canvas.addEventListener("pointerdown", e => { canvas.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; });
    canvas.addEventListener("pointermove", e => {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 2) {   // pinch
        const [a, b] = [...pts.values()], r = canvas.getBoundingClientRect();
        const other = [...pts.entries()].find(([k]) => k !== e.pointerId)[1];
        const before = Math.hypot(prev[0] - other[0], prev[1] - other[1]), after = Math.hypot(a[0] - b[0], a[1] - b[1]);
        zoomAt(after / Math.max(1, before), ((a[0] + b[0]) / 2 - r.left) * dpr(), ((a[1] + b[1]) / 2 - r.top) * dpr());
        return;
      }
      if (drag) { view.x = drag.vx + (e.clientX - drag.x) * dpr(); view.y = drag.vy + (e.clientY - drag.y) * dpr(); clamp(); paint(); }
    });
    const up = e => { pts.delete(e.pointerId); if (!pts.size) drag = null; };
    canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("keydown", e => {
      const c = [canvas.width / 2, canvas.height / 2], step = 60 * dpr();
      const k = { "+": () => zoomAt(1.4, ...c), "=": () => zoomAt(1.4, ...c), "-": () => zoomAt(1 / 1.4, ...c), "0": () => { fit(); paint(); },
        ArrowLeft: () => { view.x += step; clamp(); paint(); }, ArrowRight: () => { view.x -= step; clamp(); paint(); },
        ArrowUp: () => { view.y += step; clamp(); paint(); }, ArrowDown: () => { view.y -= step; clamp(); paint(); } }[e.key];
      if (k) { e.preventDefault(); k(); }
    });
    host.querySelectorAll("[data-layer]").forEach(b => { const li = d.layers.indexOf(b.dataset.layer); if (li < 0 || !d.wires[li].length) b.hidden = true; });
    host.querySelectorAll("[data-layer]").forEach(b => b.addEventListener("click", () => {
      const L = b.dataset.layer; onL[L] = !onL[L]; b.setAttribute("aria-pressed", onL[L]); const v = view; rebuild(); view = v; paint();
    }));
    host.querySelectorAll("[data-class]").forEach(b => b.addEventListener("click", () => {
      const k = +b.dataset.class; onC[k] = !onC[k]; b.setAttribute("aria-pressed", onC[k]); const v = view; rebuild(); view = v; paint();
    }));
    const send = host.querySelector("[data-clock]");
    if (send) send.addEventListener("click", () => {
      if (reduceMotion()) { still = !still; send.setAttribute("aria-pressed", still); paint(); return; }
      still = false; cancelAnimationFrame(raf);
      const t0 = performance.now(), dur = 2200;
      const tick = now => { edge = Math.min(1.25, (now - t0) / dur); paint(); if (edge < 1.25) raf = requestAnimationFrame(tick); else { edge = null; paint(); } };
      raf = requestAnimationFrame(tick);
    });
    addEventListener("resize", () => { fitted = false; rebuild(); });
    host.classList.add("on");
    rebuild();
  }

  root.TQLayout = { hero, explore, render, decode, drawClock };
})(window);
