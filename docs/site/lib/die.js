/* die.js — the die zoom: from a grain of salt down to one flip-flop's layers,
   driven by scrolling. Shared unchanged by tiqora-skywater130 and
   tinytapeout-tiqora; the data is docs/site/data/die.json (docs/tools/die_map.py).

   Drawn the way Visual 6502 draws a die: each layer is translucent colour on
   black, so a transistor shows where red polysilicon crosses yellow
   diffusion. The cells and their geometry are real sky130 cells; their
   positions come from a row packer, not a placer, and the stage says so.

   Motion: the scroll position is the target and the camera follows it on a
   critically damped spring, so a flick of the wheel glides and settles
   without overshoot. With prefers-reduced-motion the section becomes four
   still views with buttons, and the camera cuts. */
(function (root) {
  "use strict";

  const LAYER_STYLE = {          // Visual 6502's convention: colour per layer, translucent, on black
    nwell: "rgba(84, 110, 96, .22)", diff: "rgba(232, 200, 64, .55)", tap: "rgba(232, 200, 64, .32)",
    poly: "rgba(232, 72, 58, .62)", licon: "rgba(245, 245, 240, .75)", li1: "rgba(86, 150, 255, .42)",
    mcon: "rgba(255, 255, 255, .85)", met1: "rgba(190, 202, 214, .32)"
  };
  const SCREEN = "#0b0d0c", AMBER = "#ffb000", PROBE = "#9ad8f7", DIM = "#8e968f";
  // the atlas categories in the dark theme's colours (exhibit.css --cat-*): the stage is always dark
  const CAT = { interface: "#3987e5", compute: "#d95926", memory: "#199e70", timing: "#c98500", control: "#d55181", pins: "#008300" };
  const catColour = c => CAT[c] || "rgba(229, 232, 227, .5)";
  const BITMAP_PX_PER_UM = 6;    // below this zoom the die is drawn from one pre-rendered bitmap
  const lerp = (a, b, t) => a + (b - a) * t;
  const smoother = t => t * t * t * (t * (t * 6 - 15) + 10);

  // paths per cell kind and layer, in µm, built once per die
  function geometry(die) {
    const um = die.q_nm / 1000;
    const paths = die.cells.map(c => {
      const out = {};
      for (const k in c.geo) {
        const p = new Path2D();
        c.geo[k].forEach(a => {
          if (a.length === 4) p.rect(a[0] * um, a[1] * um, (a[2] - a[0]) * um, (a[3] - a[1]) * um);
          else { p.moveTo(a[0] * um, a[1] * um); for (let i = 2; i < a.length; i += 2) p.lineTo(a[i] * um, a[i + 1] * um); p.closePath(); }
        });
        out[k] = p;
      }
      return out;
    });
    const inst = die.inst.map(i => ({ k: i[0], x: i[1] * um, y: i[2] * um, f: i[3], w: die.cells[i[0]].w * um }));
    const RH = die.row_um;
    const core = die.regions.reduce((b, r) => [Math.min(b[0], r.um[0]), Math.min(b[1], r.um[1]), Math.max(b[2], r.um[0] + r.um[2]), Math.max(b[3], r.um[1] + r.um[3])], [1e9, 1e9, -1e9, -1e9]);
    return { paths, inst, core, RH, die };
  }
  function drawCellsOf(G, g, list, s) {
    const { paths, core, RH, die } = G;
    g.fillStyle = LAYER_STYLE.met1;
    for (let y = core[1]; y <= core[3] + 1e-6; y += RH) g.fillRect(core[0], y - 0.24, core[2] - core[0], 0.48);
    for (const L of die.layers) {
      const key = L.key; if (s < 3 && (key === "licon" || key === "mcon")) continue;
      g.fillStyle = LAYER_STYLE[key];
      for (const i of list) {
        const p = paths[i.k][key]; if (!p) continue;
        g.save();
        if (i.f) { g.translate(i.x, i.y + RH); g.scale(1, -1); } else g.translate(i.x, i.y);
        g.fill(p);
        g.restore();
      }
    }
  }
  // the whole tile as one bitmap at ppu pixels per µm, with its outline and block colours
  function tileCanvas(die, ppu, outline) {
    const G = geometry(die), [TW, TH] = die.tile_um;
    const c = document.createElement("canvas");
    c.width = Math.ceil(TW * ppu); c.height = Math.ceil(TH * ppu);
    const g = c.getContext("2d");
    g.fillStyle = SCREEN; g.fillRect(0, 0, c.width, c.height);
    g.setTransform(ppu, 0, 0, -ppu, 0, c.height);
    drawCellsOf(G, g, G.inst, ppu);
    if (outline) {
      g.lineWidth = 2 / ppu;
      die.regions.forEach(r => { g.strokeStyle = catColour(r.category); g.globalAlpha = .7; g.strokeRect(r.um[0], r.um[1], r.um[2], r.um[3]); });
      g.globalAlpha = 1; g.strokeStyle = AMBER; g.lineWidth = 3 / ppu; g.strokeRect(0, 0, TW, TH);
    }
    return c;
  }

  function mount(host, die, cfg) {
    cfg = cfg || {};
    const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const um = die.q_nm / 1000;
    const [TW, TH] = die.tile_um;
    const canvas = host.querySelector("canvas"), ctx = canvas.getContext("2d");
    const steps = [...host.querySelectorAll("[data-stage]")];
    const scaleBar = host.querySelector(".zoom-scale"), scaleTxt = host.querySelector(".zoom-scale span");
    const label = host.querySelector(".zoom-label");
    const legend = host.querySelector(".zoom-legend");

    const G = geometry(die), { paths, inst, core, RH } = G;
    const f = die.focus, fc = die.cells.find(c => c.name === f.cell);
    const focus = { x: f.at[0] * um, y: f.at[1] * um, w: fc.w * um, h: RH };
    const tiles = cfg.tiles || [TW > 300 ? 2 : 1, 2];
    const SALT = 300;            // a grain of table salt, about 0.3 mm on a side (illustrative)
    const salt = { x: -SALT - 140, y: (TH - SALT) / 2 };

    // the four views the scroll moves between: [centre x, centre y, width, height in µm];
    // each is shown as large as fits both ways
    const K = [
      [(salt.x + TW) / 2, TH / 2, (TW - salt.x) * 1.25, Math.max(TH, SALT * 1.18) * 1.3],
      [TW / 2, TH / 2, TW * 1.12, TH * 1.1],
      [focus.x + focus.w / 2, focus.y + RH / 2, 46, 12],
      [focus.x + focus.w / 2, focus.y + RH / 2, focus.w * 1.7, RH * 2.5]
    ];

    // a bitmap of the whole tile for the zoomed-out views
    let bitmap = null;
    function prerender() {
      const c = document.createElement("canvas");
      c.width = Math.ceil(TW * BITMAP_PX_PER_UM); c.height = Math.ceil(TH * BITMAP_PX_PER_UM);
      const g = c.getContext("2d");
      g.setTransform(BITMAP_PX_PER_UM, 0, 0, -BITMAP_PX_PER_UM, 0, c.height);
      drawCells(g, inst, BITMAP_PX_PER_UM);
      bitmap = c;
    }
    const drawCells = (g, list, s) => drawCellsOf(G, g, list, s);

    // camera
    let W = 0, H = 0, dpr = 1, t = 0, target = 0, vel = 0, raf = 0, last = 0;
    function cam(tt) {
      const i = Math.min(2, Math.floor(tt)), s = smoother(Math.min(1, tt - i));
      const a = K[i], b = K[i + 1];
      const w = Math.exp(lerp(Math.log(a[2]), Math.log(b[2]), s)), h = Math.exp(lerp(Math.log(a[3]), Math.log(b[3]), s));
      // zoom towards the next view's centre: the centre moves in step with the scale, not the clock
      const k = Math.abs(a[2] - b[2]) < 1e-9 ? s : (a[2] / w - 1) / (a[2] / b[2] - 1);
      return [lerp(a[0], b[0], k), lerp(a[1], b[1], k), w, h];
    }
    function resize() {
      dpr = Math.min(2, root.devicePixelRatio || 1);
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      draw();
    }
    function draw() {
      if (!W) return;
      // the view sits beside the caption: right of it on a wide screen, above it on a narrow one
      // (only while scrolling: captions then pass over the screen)
      const over = !reduce, avail = over && W > 900 ? W * 0.62 : W, [cx, cy, w, h] = cam(t);
      const s = Math.min(avail / w, H * (over && W <= 700 ? 0.6 : 0.92) / h);
      const ox = W - avail / 2, oy = H / 2 - (over && W <= 700 ? H * 0.16 : 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = SCREEN; ctx.fillRect(0, 0, W, H);
      // world: x right, y up, in µm
      ctx.setTransform(dpr * s, 0, 0, -dpr * s, dpr * (ox - cx * s), dpr * (oy + cy * s));
      const vx0 = cx - ox / s, vx1 = cx + (W - ox) / s, vy0 = cy - (H - oy) / s, vy1 = cy + oy / s;
      // the salt grain, drawn only as an outline to scale
      if (vx0 < salt.x + SALT) {
        ctx.lineWidth = 1.5 / s; ctx.strokeStyle = "rgba(229, 232, 227, .55)"; ctx.fillStyle = "rgba(229, 232, 227, .06)";
        ctx.beginPath();
        const o = SALT * 0.18;
        ctx.moveTo(salt.x, salt.y); ctx.lineTo(salt.x + SALT, salt.y); ctx.lineTo(salt.x + SALT + o, salt.y + o); ctx.lineTo(salt.x + SALT + o, salt.y + SALT + o);
        ctx.lineTo(salt.x + o, salt.y + SALT + o); ctx.lineTo(salt.x, salt.y + SALT); ctx.closePath(); ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(salt.x, salt.y + SALT); ctx.lineTo(salt.x + SALT, salt.y + SALT); ctx.lineTo(salt.x + SALT, salt.y);
        ctx.moveTo(salt.x + SALT, salt.y + SALT); ctx.lineTo(salt.x + SALT + o, salt.y + SALT + o); ctx.stroke();
      }
      // the cells
      if (s * dpr <= BITMAP_PX_PER_UM && bitmap) {
        // the bitmap's first row is the top of the tile: draw it in screen space
        ctx.save(); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.drawImage(bitmap, ox - cx * s, oy - (TH - cy) * s, TW * s, TH * s);
        ctx.restore();
      } else {
        const vis = inst.filter(i => i.x + i.w >= vx0 && i.x <= vx1 && i.y + RH >= vy0 && i.y <= vy1);
        drawCells(ctx, vis, s);
      }
      // the tile outline and the tile boundaries
      ctx.lineWidth = 1.5 / s; ctx.strokeStyle = AMBER; ctx.strokeRect(0, 0, TW, TH);
      ctx.setLineDash([6 / s, 5 / s]); ctx.strokeStyle = "rgba(255, 176, 0, .45)"; ctx.beginPath();
      for (let c = 1; c < tiles[0]; c++) { ctx.moveTo(TW * c / tiles[0], 0); ctx.lineTo(TW * c / tiles[0], TH); }
      for (let r = 1; r < tiles[1]; r++) { ctx.moveTo(0, TH * r / tiles[1]); ctx.lineTo(TW, TH * r / tiles[1]); }
      ctx.stroke(); ctx.setLineDash([]);
      // blocks: named while the whole tile is in view, fading as you go in
      const blockAlpha = Math.max(0, Math.min(1, 2.2 - t * 1.2)) * Math.min(1, t * 2);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const X = x => ox + (x - cx) * s, Y = y => oy - (y - cy) * s;
      if (blockAlpha > 0.02) {
        ctx.globalAlpha = blockAlpha;
        ctx.font = "600 12px " + (cfg.font || "sans-serif"); ctx.textBaseline = "top";
        die.regions.forEach(r => {
          const [x, y, w, h] = r.um, px = X(x), py = Y(y + h), pw = w * s, ph = h * s, col = catColour(r.category);
          ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.strokeRect(px + .75, py + .75, pw - 1.5, ph - 1.5);
          if (pw > 70 && ph > 30) {
            // the name on a dark chip, led by a swatch of the block's atlas category
            const name = r.label.replace(/\s*\(.*\)$/, "");
            ctx.fillStyle = "rgba(11, 13, 12, .82)";
            const tw = Math.min(pw - 8, ctx.measureText(name).width + 24);
            ctx.fillRect(px + 4, py + 4, tw, 18);
            ctx.fillStyle = col; ctx.fillRect(px + 9, py + 9, 8, 8);
            ctx.fillStyle = "#e5e8e3"; ctx.save(); ctx.beginPath(); ctx.rect(px + 4, py + 4, tw, 18); ctx.clip();
            ctx.fillText(name, px + 22, py + 7); ctx.restore();
          }
        });
        ctx.globalAlpha = 1;
      }
      // the flip-flop the zoom ends on
      const fa = Math.max(0, Math.min(1, (t - 1.6) * 2));
      if (fa > 0) {
        ctx.globalAlpha = fa; ctx.strokeStyle = PROBE; ctx.lineWidth = 2;
        ctx.strokeRect(X(focus.x), Y(focus.y + RH), focus.w * s, RH * s);
        ctx.globalAlpha = 1;
      }
      // labels and the scale bar
      if (scaleBar) {
        const want = 120 / s, p = Math.pow(10, Math.floor(Math.log10(want))), n = [1, 2, 5, 10].find(m => m * p >= want * 0.6) * p;
        scaleBar.style.setProperty("--w", Math.round(n * s) + "px");
        scaleTxt.textContent = (n >= 1000 ? n / 1000 + " mm" : n >= 1 ? n + " µm" : Math.round(n * 1000) + " nm");
      }
      const stage = Math.min(3, Math.round(t));
      steps.forEach((el, i) => el.toggleAttribute("data-on", i === stage));
      if (label) label.textContent = stage === 0 ? cfg.labels[0] : cfg.labels[1];
      if (legend) legend.hidden = t < 2.4;
    }

    // scroll drives the target; a critically damped spring moves the camera to it
    function progress() {
      const r = host.getBoundingClientRect(), span = host.offsetHeight - innerHeight;
      return Math.max(0, Math.min(3, (-r.top / Math.max(1, span)) * 3));
    }
    function tick(now) {
      const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
      const k = 120, c = 2 * Math.sqrt(k);            // stiffness; damping = critical
      const a = k * (target - t) - c * vel;
      vel += a * dt; t += vel * dt;
      if (Math.abs(target - t) < 1e-4 && Math.abs(vel) < 1e-4) { t = target; vel = 0; draw(); raf = 0; return; }
      draw(); raf = requestAnimationFrame(tick);
    }
    function onScroll() {
      target = progress();
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(tick); }
    }

    function go(i) { t = target = i; steps.forEach((b, j) => b.toggleAttribute("data-on", j === i)); buttons.forEach((b, j) => b.setAttribute("aria-pressed", String(j === i))); draw(); }
    const buttons = [...host.querySelectorAll(".zoom-go button")];
    buttons.forEach((b, i) => b.addEventListener("click", () => go(i)));

    const start = () => {
      if (!bitmap) prerender();
      resize();
      if (reduce) { host.classList.add("stepped"); go(0); }
      else { host.classList.add("scrolly"); t = target = progress(); draw(); addEventListener("scroll", onScroll, { passive: true }); }
    };
    addEventListener("resize", () => { if (bitmap) resize(); });
    if ("IntersectionObserver" in root) {
      const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); start(); } }, { rootMargin: "200px" });
      io.observe(host);
    } else start();
    host.classList.add(reduce ? "stepped" : "scrolly");
    // until the screen is drawn, the first caption is the one shown
    if (reduce) { steps.forEach((el, i) => el.toggleAttribute("data-on", i === 0)); buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(i === 0))); }
    return { go };
  }

  // the opening shot: the tile lies tilted in perspective and settles flat as you scroll, the
  // copy above it lifting away, so the page falls straight into the zoom below. Scroll sets the
  // target and the same critically damped spring follows it. With reduced motion the tile rests
  // flat and nothing is tied to scrolling; without JavaScript only the copy shows.
  // art, if given, is {canvas, ar}: another picture of the die (layout.js passes the routed one)
  function reveal(host, die, art) {
    const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const slot = host.querySelector(".chip3d");
    const ar = art ? art.ar : die.tile_um[0] / die.tile_um[1];
    host.style.setProperty("--ar", ar.toFixed(3));   // the tile's shape, so a tall tile still fits the screen
    const c = art ? art.canvas : tileCanvas(die, Math.min(6, 1400 / die.tile_um[0]), true);
    c.setAttribute("aria-hidden", "true");
    slot.prepend(c);
    host.classList.add("on", reduce ? "still" : "live");
    if (reduce) { host.style.setProperty("--p", 1); return; }
    let p = 0, target = 0, vel = 0, raf = 0, last = 0;
    const progress = () => {
      const r = host.getBoundingClientRect(), span = host.offsetHeight - innerHeight;
      return Math.max(0, Math.min(1, -r.top / Math.max(1, span)));
    };
    const set = () => host.style.setProperty("--p", p.toFixed(4));
    const tick = now => {
      const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
      const k = 90, cc = 2 * Math.sqrt(k);
      vel += (k * (target - p) - cc * vel) * dt; p += vel * dt;
      if (Math.abs(target - p) < 1e-4 && Math.abs(vel) < 1e-4) { p = target; set(); raf = 0; return; }
      set(); raf = requestAnimationFrame(tick);
    };
    p = target = progress(); set();
    addEventListener("scroll", () => { target = progress(); if (!raf) { last = performance.now(); raf = requestAnimationFrame(tick); } }, { passive: true });
  }

  root.TQDie = { mount, reveal, tileCanvas };
})(window);
