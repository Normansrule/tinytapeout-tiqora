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

  // A frame is the part of the die a canvas shows: px canvas pixels per unit, and the canvas's
  // top-left corner at (ox, oy) pixels from the die's top-left. The whole die is the frame at 0, 0.
  function wholeFrame(d, px) { return { px, ox: 0, oy: 0, W: Math.ceil(d.W * px), H: Math.ceil(d.H * px) }; }
  function useFrame(g, d, f) { g.setTransform(f.px, 0, 0, -f.px, -f.ox, d.H * f.px - f.oy); }
  // the frame's extent in die units, for skipping what lies outside it
  function bounds(d, f, pad) {
    return { x0: f.ox / f.px - pad, x1: (f.ox + f.W) / f.px + pad, y0: d.H - (f.oy + f.H) / f.px - pad, y1: d.H - f.oy / f.px + pad };
  }

  // one layer's wires, white on transparent, then tinted by its film gradient (fixed to the die, so a zoomed frame keeps its colours)
  function layerCanvas(d, li, f, minW) {
    const a = d.wires[li];
    if (!a.length) return null;
    const c = document.createElement("canvas"); c.width = f.W; c.height = f.H;
    const g = c.getContext("2d");
    useFrame(g, d, f);
    g.fillStyle = "#fff";
    const w = Math.max(d.width[li], minW / f.px), h = w / 2, B = bounds(d, f, w);
    for (let i = 0; i < a.length; i += 4) {
      if (a[i + 2] < B.x0 || a[i] > B.x1 || a[i + 3] < B.y0 || a[i + 1] > B.y1) continue;
      g.fillRect(a[i] - h, a[i + 1] - h, a[i + 2] - a[i] + w, a[i + 3] - a[i + 1] + w);
    }
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = "source-in";
    const k = FILM[d.layers[li]] || ["#fff", "#fff"];
    const gr = g.createLinearGradient(-f.ox, d.H * f.px - f.oy, d.W * f.px - f.ox, -f.oy);
    gr.addColorStop(0, k[0]); gr.addColorStop(.5, k[1]); gr.addColorStop(1, k[0]);
    g.fillStyle = gr; g.fillRect(0, 0, c.width, c.height);
    return c;
  }

  // the die (or a frame of it): cells by class, the power grid, the metal layers added together
  function render(R, px, opt) {
    opt = opt || {};
    const d = decode(R), f = opt.frame || wholeFrame(d, px);
    const c = document.createElement("canvas"); c.width = f.W; c.height = f.H;
    const g = c.getContext("2d");
    g.fillStyle = SCREEN; g.fillRect(0, 0, c.width, c.height);
    useFrame(g, d, f);
    const B = bounds(d, f, R.row * 4);
    const rowH = R.row - Math.min(R.row * .3, .8 / f.px);   // a hairline between rows, so the rows read
    d.cells.forEach((a, k) => {
      if (opt.classes && !opt.classes[k]) return;
      g.fillStyle = CLASS_FILL[k];
      for (let i = 0; i < a.length; i += 3) {
        if (a[i] > B.x1 || a[i] + a[i + 2] < B.x0 || a[i + 1] > B.y1 || a[i + 1] + R.row < B.y0) continue;
        g.fillRect(a[i], a[i + 1], a[i + 2], rowH);
      }
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
      const lc = layerCanvas(d, li, f, opt.minWirePx || .6);
      if (lc) { mg.globalAlpha = opt.alpha || .62; mg.drawImage(lc, 0, 0); }
    });
    g.globalCompositeOperation = "lighter";
    if (opt.bloom !== false && "filter" in g) {   // a soft glow under the wires (browsers without canvas filters skip it)
      g.filter = `blur(${Math.min(14, Math.max(2, 60 * f.px)).toFixed(1)}px)`; g.globalAlpha = .4; g.drawImage(metal, 0, 0);
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
    const W = g.canvas.width, H = g.canvas.height;
    g.clearRect(0, 0, W, H);
    const cx = -0.2 * W + t * 1.4 * W, band = W * .16;
    g.save();
    g.drawImage(base._metal, 0, 0, W, H);
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
  // k: how much the context is scaled up on screen, so lines and dots keep their size when zoomed
  function drawClock(g, d, px, H, t, all, k) {
    k = k || 1;
    const D = d.depth + 1, front = all ? D + 1 : t * (D + 1.2);
    g.save(); g.globalCompositeOperation = "lighter"; g.lineCap = "round";
    for (const c of d.clock) {
      const lit = Math.max(0, Math.min(1, front - c.depth));
      if (lit <= 0) continue;
      const s = c.segs, fade = all ? 1 : Math.max(.35, 1 - (front - c.depth - 1) * .45);
      for (const [w, a] of [[5, .18], [1.8, .95]]) {
        g.strokeStyle = `rgba(255, ${190 + 40 * (c.depth % 2)}, 90, ${(a * fade).toFixed(3)})`;
        g.lineWidth = w / k;
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
        for (let i = 0; i < f.length; i += 2) g.fillRect(f[i] * px - 1.5 / k, H - f[i + 1] * px - 1.5 / k, 3 / k, 3 / k);
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
    // the light is drawn at no more than 820 px wide and stretched over the die: it is a soft
    // band, so the detail is not missed, and each frame then costs a quarter of the pixels.
    // It is only drawn while the hero is on screen and only when the light has moved.
    const q = Math.min(1, 820 / base.width);
    const light = document.createElement("canvas"); light.width = Math.round(base.width * q); light.height = Math.round(base.height * q);
    light.className = "glint"; light.setAttribute("aria-hidden", "true");
    base.after(light);
    const g = light.getContext("2d"), sparks = sparkPoints(d, 900);
    let raf = 0, pointer = 0, seen = true, key = "";
    const draw = () => {
      raf = 0;
      const p = parseFloat(host.style.getPropertyValue("--p")) || 0, k = p.toFixed(3) + "," + pointer.toFixed(3);
      if (k === key) return;
      key = k;
      drawLight(g, base, d, sparks, Math.min(1.05, .12 + p * .95 + pointer * .14), p * 6 + pointer * 3);
    };
    const ask = () => { if (!raf && seen) raf = requestAnimationFrame(draw); };
    if ("IntersectionObserver" in root) new IntersectionObserver(es => { seen = es[es.length - 1].isIntersecting; ask(); }).observe(slot);
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
    // zoomed in, the prerendered die would blur, so the visible part is drawn again at the
    // zoom's own scale once the view rests for a moment
    let sharp = null, sharpTimer = 0;
    const viewKey = () => `${view.s.toFixed(4)},${view.x.toFixed(1)},${view.y.toFixed(1)},${canvas.width}`;
    function sharpen() {
      sharpTimer = 0;
      const pe = view.s * base.width / d.W;
      sharp = render(R, pe, { layers: onL, classes: onC, minWirePx: .8,
        frame: { px: pe, ox: -view.x, oy: -view.y, W: canvas.width, H: canvas.height } });
      sharp._key = viewKey();
      paint();
    }
    function paint() {
      if (!base) return;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = SCREEN; g.fillRect(0, 0, canvas.width, canvas.height);
      const dim = edge !== null || still ? .32 : 1;   // the layout dims while the clock tree shows
      g.globalAlpha = dim;
      if (sharp && sharp._key === viewKey()) g.drawImage(sharp, 0, 0);
      else {
        g.setTransform(view.s, 0, 0, view.s, view.x, view.y);
        g.imageSmoothingEnabled = view.s < 1.5;
        g.drawImage(base, 0, 0);
        clearTimeout(sharpTimer);
        if (view.s > 1.25) sharpTimer = setTimeout(sharpen, 160);
      }
      g.globalAlpha = 1;
      g.setTransform(view.s, 0, 0, view.s, view.x, view.y);
      if (edge !== null || still) drawClock(g, d, base.width / d.W, base.height, edge || 0, still, view.s);
      g.setTransform(1, 0, 0, 1, 0, 0);
      scaleBar();
      if (readout) readout.textContent = `${Math.round(view.s / fitScale() * 100)}%`;
    }
    // a scale bar in the corner, a round number of micrometres long
    function scaleBar() {
      const um = 1000 / R.unit_nm * view.s * base.width / d.W, r = dpr();   // canvas pixels per micrometre
      const L = [1, 2, 5, 10, 20, 50, 100, 200].find(v => v * um >= 70 * r) || 200, w = L * um, x = 14 * r, y = canvas.height - 16 * r;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = "rgba(5, 7, 10, .65)"; g.fillRect(x - 6 * r, y - 20 * r, w + 12 * r, 28 * r);
      g.fillStyle = "#dfe4f2"; g.fillRect(x, y, w, 2 * r); g.fillRect(x, y - 4 * r, 1.5 * r, 6 * r); g.fillRect(x + w - 1.5 * r, y - 4 * r, 1.5 * r, 6 * r);
      g.font = `${11 * r}px ui-monospace, monospace`; g.textBaseline = "bottom"; g.fillText(`${L} µm`, x, y - 4 * r);
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
      const L = b.dataset.layer; onL[L] = !onL[L]; b.setAttribute("aria-pressed", onL[L]); sharp = null; rebuild();
    }));
    host.querySelectorAll("[data-class]").forEach(b => b.addEventListener("click", () => {
      const k = +b.dataset.class; onC[k] = !onC[k]; b.setAttribute("aria-pressed", onC[k]); sharp = null; rebuild();
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

  // the stack: the cells, then each metal layer the router used, each on its own plane.
  // Scrolling tilts the die and pulls the planes apart, then brings each layer forward in turn,
  // from the cells up to met4. The planes move by CSS transforms only, so the browser
  // composites them on the GPU; their pictures are drawn once. With reduced motion the stack
  // rests tilted and apart and nothing is tied to scrolling. Without JavaScript the legend
  // (written by build_site.py from routed.json) is the whole section.
  function stack(host, R) {
    const box = host.querySelector(".stack"); if (!box) return;
    const d = decode(R), reduce = reduceMotion();
    const wpx = Math.min(1300, Math.max(700, (root.innerWidth || 1200) * .62) * Math.min(2, root.devicePixelRatio || 1));
    const px = wpx / d.W, f = wholeFrame(d, px);
    const planes = [...box.querySelectorAll(".plane")];
    const items = [...host.querySelectorAll(".stack-legend li")];
    host.style.setProperty("--ar", (d.W / d.H).toFixed(3));
    host.style.setProperty("--mid", ((planes.length - 1) / 2).toString());   // the stack opens about its middle
    // one plane per idle moment, so drawing them never holds up scrolling
    let built = false;
    const idle = root.requestIdleCallback ? fn => root.requestIdleCallback(fn, { timeout: 300 }) : fn => setTimeout(fn, 16);
    function build() {
      if (built) return; built = true;
      host.classList.add("on");
      let i = 0;
      const next = () => {
        const pl = planes[i++]; if (!pl) return;
        const L = pl.dataset.layer;
        const c = L === "cells" ? render(R, px, { layers: {}, bloom: false }) : layerCanvas(d, d.layers.indexOf(L), f, .9);
        if (c) { c.setAttribute("aria-hidden", "true"); pl.prepend(c); } else pl.hidden = true;
        idle(next);
      };
      idle(next);
    }
    const n = planes.length;
    let shown = -1;
    function set(p) {
      // 0 to .3: tilt and pull apart; .3 to 1: each plane in turn comes to the front
      const e = Math.min(1, p / .3), sm = e * e * (3 - 2 * e);
      host.style.setProperty("--e", sm.toFixed(4));
      const k = p < .3 ? -1 : Math.min(n - 1, Math.floor((p - .3) / .7 * n));
      if (k !== shown) {
        shown = k;
        planes.forEach((pl, i) => pl.classList.toggle("dim", k >= 0 && i !== k));
        items.forEach((li, i) => li.toggleAttribute("data-on", i === k));
      }
    }
    // the legend's items act as buttons
    const press = (li, fn) => {
      li.tabIndex = 0; li.setAttribute("role", "button");
      li.addEventListener("click", fn);
      li.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
    };
    // the items take focus from the start; what choosing one does is set once the stack runs
    let act = null, went = false;
    items.forEach((li, i) => press(li, () => { go(); act(li, i); }));
    const go = () => {
      if (went) return; went = true;
      build();
      if (reduce) {
        // at rest, tilted and apart; choosing a layer in the legend brings it forward
        host.classList.add("still"); host.style.setProperty("--e", "1");
        act = (li, i) => {
          const on = !li.hasAttribute("data-on");
          items.forEach((x, j) => x.toggleAttribute("data-on", on && j === i));
          planes.forEach((pl, j) => pl.classList.toggle("dim", on && j !== i));
        };
        return;
      }
      let p = 0, target = 0, vel = 0, raf = 0, last = 0;
      const progress = () => {
        const r = host.getBoundingClientRect(), span = host.offsetHeight - innerHeight;
        return Math.max(0, Math.min(1, -r.top / Math.max(1, span)));
      };
      const tick = now => {
        const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
        const kk = 110, cc = 2 * Math.sqrt(kk);
        vel += (kk * (target - p) - cc * vel) * dt; p += vel * dt;
        if (Math.abs(target - p) < 1e-4 && Math.abs(vel) < 1e-4) { p = target; set(p); raf = 0; return; }
        set(p); raf = requestAnimationFrame(tick);
      };
      p = target = progress(); set(p);
      addEventListener("scroll", () => {
        const t = progress();
        if (t === target && !raf) return;     // off the section: nothing moves, nothing is drawn
        target = t;
        if (!raf) { last = performance.now(); raf = requestAnimationFrame(tick); }
      }, { passive: true });
      // the legend's items jump to their layer
      act = (li, i) => {
        const span = host.offsetHeight - innerHeight, top = host.getBoundingClientRect().top + scrollY;
        scrollTo({ top: top + span * (.3 + (i + .5) / n * .7), behavior: "smooth" });
      };
    };
    // the section takes its scrolling height at once, so nothing below it moves later
    if (!reduce) host.classList.add("live");
    if ("IntersectionObserver" in root) {
      const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: "100% 0px" });
      io.observe(host);
    } else go();
  }

  root.TQLayout = { hero, explore, stack, render, decode, drawClock };
})(window);
