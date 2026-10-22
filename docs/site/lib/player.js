/* player.js — plays a recorded fixture: summary and detail modes, captions,
   step, scrub, speed, restart, sequence choice, download, keyboard.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   Summary mode walks the captions in 10 to 25 seconds. Detail mode moves
   through the trace one change at a time. Every value under the cursor is
   also in a table, and the blocks a caption is about are listed by name, so
   nothing depends on colour or hover. */
(function (root) {
  "use strict";
  const W = root.TQWave;
  const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "on") for (const ev in attrs.on) e.addEventListener(ev, attrs.on[ev]);
      else if (k === "text") e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    kids.flat().forEach(k => k != null && e.append(k));
    return e;
  }

  // Drawn icons, one 16 px grid and one stroke weight, so the controls do not
  // depend on which symbol glyphs the reader's fonts happen to have.
  const ICONS = {
    restart: "<path d='M3.5 3v10'/><path d='M13 3.5 6.5 8l6.5 4.5z' fill='currentColor'/>",
    prevcap: "<path d='M8 3.5 2 8l6 4.5zM14 3.5 8 8l6 4.5z' fill='currentColor'/>",
    back: "<path d='M11.5 3.5 5 8l6.5 4.5z' fill='currentColor'/>",
    fwd: "<path d='M4.5 3.5 11 8l-6.5 4.5z' fill='currentColor'/>",
    nextcap: "<path d='M2 3.5 8 8l-6 4.5zM8 3.5 14 8l-6 4.5z' fill='currentColor'/>",
    play: "<path d='M4.5 2.5 13 8l-8.5 5.5z' fill='currentColor'/>",
    pause: "<path d='M4.5 3h2.5v10H4.5zM9 3h2.5v10H9z' fill='currentColor'/>",
    download: "<path d='M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10'/>"
  };
  function ico(name) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 16 16"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "ico");
    s.innerHTML = ICONS[name];
    return s;
  }
  // on-screen movement accelerates and settles; it never starts or stops dead
  const easeInOut = f => f < 0.5 ? 4 * f * f * f : 1 - Math.pow(-2 * f + 2, 3) / 2;

  function us(c, ns) { if (c < 0) return "reset held"; return (c * ns / 1000).toFixed(c * ns < 100000 ? 2 : 1) + " µs"; }

  // Every cycle at which any signal changes, inside [lo, hi]: what "step" visits.
  function stops(fx) {
    const set = new Set([fx.cycles[0], fx.cycles[1]]);
    fx.signals.forEach(s => s.changes.forEach(c => set.add(c[0])));
    (fx.captions || []).forEach(c => set.add(c.at));
    (fx.bytes || []).forEach(b => set.add(b.at));
    return [...set].filter(c => c >= fx.cycles[0] && c <= fx.cycles[1]).sort((a, b) => a - b);
  }

  function mount(host, cfg) {
    const fixtures = cfg.fixtures, byId = {};
    fixtures.forEach(f => byId[f.id] = f);
    const ns = cfg.clockNs || 20;
    let fx = null, st = [], cur = 0, playing = false, mode = "summary", speed = 1, raf = 0, t0 = 0, plan = null, handle = null, showCaps = true;

    const seqs = h("div", { class: "seqs", role: "group", "aria-label": "Choose a sequence" });
    fixtures.forEach(f => seqs.append(h("button", { type: "button", "data-id": f.id, "aria-pressed": "false", on: { click: () => select(f.id, true) } },
      h("b", { text: f.title }), h("span", { text: f.summary }))));

    const title = h("h2", { id: "seq-title", tabindex: "-1" });
    const kind = h("span", { class: "ev recorded kind" });
    const summary = h("p", { class: "summary" });
    const modeSel = h("select", { "aria-label": "Playback mode", on: { change: e => { mode = e.target.value; stop(); } } },
      h("option", { value: "summary", text: "Summary tour" }), h("option", { value: "detail", text: "Detail: every change" }));
    const wave = h("div", { class: "wave" });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    wave.append(svg);
    const caption = h("p", { class: "caption", "aria-live": "polite" });
    const values = h("table", { class: "values" });
    const blocks = h("ul", { class: "blocks", "aria-label": "Blocks this moment is about" });
    const side = h("div", { class: "side" }, h("h3", { text: "At the cursor" }), values, h("h3", { text: "Blocks involved" }), blocks);

    const btn = (label, title, fn, extra) => h("button", Object.assign({ type: "button", title, "aria-label": title, on: { click: fn } }, extra || {}), label);
    const bPlay = btn([ico("play"), "Play"], "Play or pause (Space)", () => playing ? stop() : play(), { "aria-pressed": "false" });
    const scrub = h("input", { type: "range", min: 0, max: 1, step: 1, value: 0, "aria-label": "Cycle", on: { input: e => { stop(); seek(+e.target.value); } } });
    const readout = h("span", { class: "readout", "aria-hidden": "true" });
    const speedSel = h("select", { "aria-label": "Speed", on: { change: e => { speed = +e.target.value; if (playing) { stop(); play(); } } } },
      ...[0.25, 0.5, 1, 2, 4].map(s => h("option", Object.assign({ value: s, text: s + "×" }, s === 1 ? { selected: "" } : {}))));
    const bCaps = btn("Captions on", "Show or hide captions (C)", () => { showCaps = !showCaps; bCaps.textContent = showCaps ? "Captions on" : "Captions off"; bCaps.setAttribute("aria-pressed", String(showCaps)); caption.hidden = !showCaps; }, { "aria-pressed": "true" });
    const bDown = btn([ico("download"), "Trace data"], "Download this sequence's recorded data as JSON", download);
    const controls = h("div", { class: "controls" },
      btn(ico("restart"), "Restart (Home)", () => { stop(); seek(fx.cycles[0]); }),
      btn(ico("prevcap"), "Previous caption (Shift+Left)", () => { stop(); jumpCaption(-1); }),
      btn(ico("back"), "Step back one change (Left)", () => { stop(); step(-1); }),
      bPlay,
      btn(ico("fwd"), "Step forward one change (Right)", () => { stop(); step(1); }),
      btn(ico("nextcap"), "Next caption (Shift+Right)", () => { stop(); jumpCaption(1); }),
      h("span", { class: "scrub" }, scrub, readout), modeSel, speedSel, bCaps, bDown);
    const checks = h("ul", { class: "checks" });
    const prov = h("details", { class: "prov" }, h("summary", { text: "Where this comes from" }), h("div", { class: "provbody" }));
    const keys = h("p", { class: "small", style: "padding: 0 1rem .8rem" },
      "Keys, with the player focused: ", h("kbd", { text: "Space" }), " play/pause, ", h("kbd", { text: "←" }), h("kbd", { text: "→" }), " step, ",
      h("kbd", { text: "Shift" }), "+", h("kbd", { text: "←" }), h("kbd", { text: "→" }), " captions, ", h("kbd", { text: "Home" }), " restart, ",
      h("kbd", { text: "C" }), " captions. Click or drag on the waveform to move the cursor.");
    const box = h("section", { class: "player", tabindex: "0", "aria-labelledby": "seq-title" },
      h("header", {}, title, kind), summary, controls, caption, h("div", { class: "split" }, wave, side), keys, prov);
    host.append(seqs, box);

    box.addEventListener("keydown", e => {
      if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT" && e.target.type !== "range") return;
      if (e.key === " " && e.target.tagName !== "BUTTON") { e.preventDefault(); playing ? stop() : play(); }
      else if (e.key === "ArrowRight" && e.target.type !== "range") { e.preventDefault(); stop(); e.shiftKey ? jumpCaption(1) : step(1); }
      else if (e.key === "ArrowLeft" && e.target.type !== "range") { e.preventDefault(); stop(); e.shiftKey ? jumpCaption(-1) : step(-1); }
      else if (e.key === "Home") { e.preventDefault(); stop(); seek(fx.cycles[0]); }
      else if (e.key === "c" || e.key === "C") bCaps.click();
    });
    let resizeT = 0;
    root.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { redraw(); seek(cur); }, 150); });

    function redraw() {
      handle = W.draw(svg, fx, fx.cycles[0], fx.cycles[1], { width: wave.clientWidth - 2, onSeek: c => { stop(); seek(c); } });
    }

    function select(id, focus) {
      stop();
      fx = byId[id] || fixtures[0];
      seqs.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.id === fx.id)));
      title.textContent = fx.title;
      kind.textContent = fx.kind === "recorded" ? "Recorded from RTL simulation" : fx.kind_text;
      kind.title = fx.kind_text;
      summary.textContent = fx.summary;
      st = stops(fx);
      scrub.min = fx.cycles[0]; scrub.max = fx.cycles[1]; scrub.value = fx.cycles[0];
      redraw();
      checks.replaceChildren(...(fx.checks || []).map(c => h("li", { class: c.ok ? "" : "bad", text: c.text })));
      const p = fx.provenance || {};
      prov.querySelector(".provbody").replaceChildren(
        h("p", {}, "Recorded by ", h("code", { text: p.testbench || "?" }), p.program ? [" running ", h("code", { text: p.program })] : "", " with ", h("code", { text: p.simulator || "?" }), "."),
        h("p", {}, "Regenerate: ", h("code", { text: p.command || "" })),
        h("p", { text: "Sampling: " + (p.sampling || "") }),
        h("p", { text: "The testbench checks this sequence passed:" }), checks,
        h("p", { class: "small", text: "SHA-256 of every source the recording came from; docs/tools/traces.py --check fails if any of them changes without the fixtures being regenerated:" }),
        h("ul", { class: "small mono" }, ...Object.entries(p.sources || {}).map(([f, s]) => h("li", {}, h("code", { text: f + "  " + s.slice(0, 16) + "…" })))));
      seek(fx.cycles[0], true);
      if (cfg.onSelect) cfg.onSelect(fx);
      if (focus) { title.focus(); updateHash(); }
    }

    function captionAt(c) {
      let k = null;
      (fx.captions || []).forEach(x => { if (x.at <= c) k = x; });
      return k;
    }

    function seek(c, quiet) {
      cur = Math.max(fx.cycles[0], Math.min(fx.cycles[1], c));
      scrub.value = cur;
      readout.textContent = "cycle " + cur + " · " + us(cur, ns);
      const cap = captionAt(cur);
      const active = new Set(cap ? cap.blocks || [] : []);
      handle.setCursor(cur, active);
      const text = cap ? cap.text : "Press play for the summary tour, or step through it.";
      if (caption.dataset.text !== text) {
        caption.dataset.text = text;
        caption.replaceChildren(h("span", { class: "at", text: cap ? "cycle " + cap.at + " · " + us(cap.at, ns) : "start" }), text);
        // a new caption fades in, so the eye notices the text changed; opacity only, kept with reduced motion
        if (caption.animate) caption.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 180, easing: "cubic-bezier(0.23, 1, 0.32, 1)" });
      }
      values.replaceChildren(...fx.signals.map(s => {
        const v = W.valueAt(s, cur);
        return h("tr", { class: W.changedAt(s, cur) ? "changed" : "", title: s.meaning || "" },
          h("td", { text: s.label }), h("td", { class: "v", text: v === undefined ? "–" : W.fmt(s, v) }));
      }));
      const all = cfg.blocks || [];
      blocks.replaceChildren(...all.map(b => h("li", { class: active.has(b) ? "on" : "", text: b })));
      if (cfg.onSeek) cfg.onSeek(fx, cur, cap);
      if (!quiet && !playing) updateHash();
    }

    function step(dir) {
      const i = dir > 0 ? st.findIndex(c => c > cur) : st.length - 1 - [...st].reverse().findIndex(c => c < cur);
      if (i >= 0 && i < st.length) seek(st[i]);
    }

    function jumpCaption(dir) {
      const caps = (fx.captions || []).map(c => c.at);
      const t = dir > 0 ? caps.find(c => c > cur) : [...caps].reverse().find(c => c < cur);
      if (t !== undefined) seek(t);
    }

    // The summary: a path through the caption anchors, 10 to 25 s in all at 1×.
    function summaryPlan() {
      const caps = (fx.captions || []).map(c => c.at).filter((c, i, a) => a.indexOf(c) === i);
      const n = Math.max(1, caps.length);
      const total = Math.min(25, Math.max(10, n * 2.6));
      const dwell = total / n;
      const pts = [{ t: 0, c: Math.min(cur, caps[0] ?? cur) }];
      let t = reduce ? 0 : 0.6;
      caps.forEach(c => { if (c >= pts[pts.length - 1].c) { pts.push({ t, c }); t += dwell; } });
      pts.push({ t, c: caps.length ? caps[caps.length - 1] : fx.cycles[1] });
      return { pts, total: t };
    }

    function play() {
      if (cur >= fx.cycles[1] || (mode === "summary" && (fx.captions || []).length && cur >= fx.captions[fx.captions.length - 1].at)) seek(fx.cycles[0]);
      playing = true;
      bPlay.replaceChildren(ico("pause"), "Pause"); bPlay.setAttribute("aria-pressed", "true");
      plan = mode === "summary" ? summaryPlan() : null;
      t0 = performance.now();
      const startC = cur, si = st.indexOf(cur) >= 0 ? st.indexOf(cur) : st.findIndex(c => c > cur);
      const perSec = Math.max(4, st.length / 40) * speed;   // detail: changes per second
      const tick = now => {
        if (!playing) return;
        const el = (now - t0) / 1000 * (mode === "summary" ? speed : 1);
        if (mode === "summary") {
          const p = plan.pts;
          if (el >= plan.total) { seek(p[p.length - 1].c); return stop(); }
          let k = 0;
          while (k + 1 < p.length && p[k + 1].t <= el) k++;
          const a = p[k], b = p[k + 1] || a;
          // glide between anchors over the first 60% of a dwell, then hold for reading
          let c = a.c;
          if (!reduce && b.t > a.t) {
            const f = easeInOut(Math.min(1, (el - a.t) / ((b.t - a.t) * 0.6)));
            c = Math.round(a.c + (b.c - a.c) * f);
          }
          if (k === 0 && p.length > 1) c = reduce ? p[1].c : Math.round(startC + (p[1].c - startC) * Math.min(1, el / Math.max(0.01, p[1].t)));
          if (c !== cur) seek(c);
        } else {
          const idx = si + Math.floor(el * perSec);
          if (idx >= st.length) { seek(fx.cycles[1]); return stop(); }
          if (st[idx] !== cur) seek(st[idx]);
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }

    function stop() {
      if (!playing) return;
      playing = false;
      cancelAnimationFrame(raf);
      bPlay.replaceChildren(ico("play"), "Play"); bPlay.setAttribute("aria-pressed", "false");
      updateHash();
    }

    function download() {
      const blob = new Blob([JSON.stringify(fx, null, 1)], { type: "application/json" });
      const a = h("a", { href: URL.createObjectURL(blob), download: (cfg.chip || "tiqora").toLowerCase() + "-" + fx.id + ".json" });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }

    function updateHash() {
      try { history.replaceState(null, "", "#seq=" + fx.id + "&c=" + cur); } catch (e) { /* file:// in some browsers */ }
    }

    const m = /seq=([\w-]+)(?:&c=(-?\d+))?/.exec(location.hash);
    select(m && byId[m[1]] ? m[1] : (cfg.initial || fixtures[0].id));
    if (m && m[2] !== undefined) seek(+m[2], true);
    return { select, seek, get fixture() { return fx; } };
  }

  root.TQPlayer = { mount };
})(window);
