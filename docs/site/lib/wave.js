/* wave.js — draws a recorded fixture as an SVG waveform.
   Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

   A fixture (docs/site/data/traces/*.json, written by docs/tools/traces.py)
   lists each signal as [[cycle, value], ...] at every change. The static
   part is drawn once per window; moving the cursor only moves one line and
   updates which rows are marked as active, so playback stays cheap. */
(function (root) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const LABEL = 168, ROW = 26, TOP = 22, PAD = 10;

  function valueAt(sig, cycle) {
    const ch = sig.changes;
    let lo = 0, hi = ch.length - 1, k = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (ch[mid][0] <= cycle) { k = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return k < 0 ? undefined : ch[k][1];
  }

  function changedAt(sig, cycle) {
    return sig.changes.some(c => c[0] === cycle);
  }

  function fmt(sig, v) {
    if (v === null || v === undefined) return "x";
    if (sig.kind === "enum") return (sig.enum && sig.enum[v]) || String(v);
    if (sig.kind === "text") return String(v);
    if (sig.kind === "bit") return String(v);
    const d = Math.max(1, Math.ceil(sig.width / 4));
    return (sig.width > 4 ? "0x" : "") + (v >>> 0).toString(16).toUpperCase().padStart(sig.width > 4 ? d : 1, "0");
  }

  function niceStep(span, px) {
    const raw = span / Math.max(1, px / 90);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 5, 10]) if (m * p >= raw) return m * p;
    return 10 * p;
  }

  function el(name, attrs, text) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // Draw fixture fx into the <svg> element svg over cycles [lo, hi].
  // Returns a handle with setCursor(cycle, activeBlocks).
  function draw(svg, fx, lo, hi, opts) {
    opts = opts || {};
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const width = Math.max(640, opts.width || svg.parentNode.clientWidth || 900);
    const bytes = fx.bytes || [];
    const nrows = fx.signals.length + (bytes.length ? 2 : 0);
    const height = TOP + nrows * ROW + 18;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Waveform of " + fx.title + ", cycles " + lo + " to " + hi + ". The table beside it lists every value at the cursor.");
    const span = Math.max(1, hi - lo + 1);
    const x = c => LABEL + (Math.min(Math.max(c, lo), hi + 1) - lo) / span * (width - LABEL - PAD);

    const defs = el("defs", {});
    const pat = el("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    pat.appendChild(el("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "currentColor", "stroke-width": 1.5, class: "s-x-line", style: "stroke: var(--sig-unknown)" }));
    defs.appendChild(pat);
    svg.appendChild(defs);

    // time axis
    const step = niceStep(span, width - LABEL);
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      svg.appendChild(el("line", { x1: x(t), x2: x(t), y1: TOP - 6, y2: height - 18, class: "grid" }));
      svg.appendChild(el("text", { x: x(t) + 3, y: TOP - 9, class: "axis" }, String(t)));
    }
    svg.appendChild(el("text", { x: 8, y: TOP - 9, class: "axis" }, "cycle"));

    const rows = [];
    let r = 0;
    function rowY(i) { return TOP + i * ROW; }

    fx.signals.forEach(sig => {
      const y = rowY(r++), g = el("g", { "data-sig": sig.id, "data-block": sig.block || "" });
      g.appendChild(el("text", { x: 8, y: y + 16, class: "lbl" }, sig.label));
      const ch = sig.changes.filter(c => c[0] <= hi);
      for (let k = 0; k < ch.length; k++) {
        const c0 = Math.max(ch[k][0], lo), c1 = k + 1 < ch.length ? ch[k + 1][0] : hi + 1;
        if (c1 <= lo) continue;
        const v = ch[k][1], x0 = x(c0), x1 = x(c1), w = x1 - x0;
        if (v === null || v === undefined) {
          g.appendChild(el("rect", { x: x0, y: y + 4, width: Math.max(1, w), height: ROW - 8, class: "s-x" }));
          continue;
        }
        if (sig.kind === "bit") {
          const yy = v ? y + 4 : y + ROW - 4;
          const prev = k > 0 ? ch[k - 1][1] : v;
          const py = prev ? y + 4 : y + ROW - 4;
          g.appendChild(el("path", { d: "M" + x0 + " " + (c0 === ch[k][0] && k > 0 ? py : yy) + " L" + x0 + " " + yy + " L" + x1 + " " + yy, class: "s-bit" }));
        } else {
          const s = Math.min(3, w / 3);
          const d = "M" + x0 + " " + (y + ROW / 2) + " L" + (x0 + s) + " " + (y + 4) + " L" + (x1 - s) + " " + (y + 4) + " L" + x1 + " " + (y + ROW / 2) +
                    " L" + (x1 - s) + " " + (y + ROW - 4) + " L" + (x0 + s) + " " + (y + ROW - 4) + " Z";
          g.appendChild(el("path", { d, class: "s-" + sig.kind }));
          const label = fmt(sig, v);
          if (w > label.length * 6.8 + 8) g.appendChild(el("text", { x: x0 + s + 3, y: y + 17, class: "val" }, label));
        }
      }
      svg.appendChild(g);
      rows.push(g);
    });

    if (bytes.length) {
      ["host", "chip"].forEach(dir => {
        const y = rowY(r++), g = el("g", { "data-sig": "bytes-" + dir, "data-block": dir === "host" ? "tp_uart_rx" : "tp_uart_tx" });
        g.appendChild(el("text", { x: 8, y: y + 16, class: "lbl" }, dir === "host" ? "byte host → chip" : "byte chip → host"));
        bytes.filter(b => b.dir === dir && b.end >= lo && b.at <= hi).forEach(b => {
          const x0 = x(b.at), x1 = x(b.end);
          g.appendChild(el("rect", { x: x0, y: y + 4, width: Math.max(2, x1 - x0), height: ROW - 8, rx: 3, class: dir === "host" ? "byte-h" : "byte-c" }));
          const t = b.byte.toString(16).toUpperCase().padStart(2, "0");
          if (x1 - x0 > 20) g.appendChild(el("text", { x: x0 + 4, y: y + 17, class: "val" }, t));
        });
        svg.appendChild(g);
        rows.push(g);
      });
    }

    // marks and caption anchors
    (fx.marks || []).forEach(m => {
      if (m.at < lo || m.at > hi) return;
      svg.appendChild(el("line", { x1: x(m.at), x2: x(m.at), y1: TOP - 4, y2: height - 18, class: "mark" }));
      // a label near the right edge sits to the left of its line, so it is never cut off
      const right = x(m.at) + 3 + 7 * m.label.length > width;
      svg.appendChild(el("text", { x: x(m.at) + (right ? -3 : 3), y: height - 6, class: "marklbl", "text-anchor": right ? "end" : "start" }, m.label));
    });
    (fx.captions || []).forEach(c => {
      if (c.at < lo || c.at > hi) return;
      svg.appendChild(el("circle", { cx: x(c.at), cy: TOP - 3, r: 3.2, class: "capdot" }));
    });

    const cursor = el("line", { x1: x(lo), x2: x(lo), y1: TOP - 6, y2: height - 18, class: "cursor" });
    svg.appendChild(cursor);
    const hit = el("rect", { x: LABEL, y: 0, width: width - LABEL - PAD, height, class: "hit" });
    svg.appendChild(hit);
    if (opts.onSeek) {
      let dragging = false;
      const seek = ev => {
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX; pt.y = ev.clientY;
        const p = pt.matrixTransform(svg.getScreenCTM().inverse());
        opts.onSeek(Math.round(lo + (p.x - LABEL) / (width - LABEL - PAD) * span));
      };
      hit.addEventListener("pointerdown", ev => { dragging = true; hit.setPointerCapture(ev.pointerId); seek(ev); });
      hit.addEventListener("pointermove", ev => { if (dragging) seek(ev); });
      hit.addEventListener("pointerup", () => { dragging = false; });
    }

    return {
      setCursor(c, active) {
        const xc = x(c) + (x(c + 1) - x(c)) / 2;
        cursor.setAttribute("x1", xc); cursor.setAttribute("x2", xc);
        rows.forEach(g => g.classList.toggle("hot", !!active && active.has(g.getAttribute("data-block"))));
      }
    };
  }

  root.TQWave = { draw, valueAt, changedAt, fmt };
})(window);
