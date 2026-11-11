#!/usr/bin/env python3
"""site_lint.py — read the built site the way a visitor sees it, and fail on design faults.

    python3 docs/tools/site_lint.py              audit docs/site/*.html (part of make docs)
    python3 docs/tools/site_lint.py --mutants    prove each rule catches the fault it names

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. It opens every built
page in headless Chromium, in the light and the dark theme, at a desktop width
(1280 px) and a phone width (390 px), and measures what is on screen. It runs
with reduced motion, so every animation is at its end state; one more pass, light
theme at 1280 px with motion on, scrolls down the page to check the reveals.

  script-error       a script threw, or logged an error, while the page loaded
  broken-image       an <img> that did not load
  horizontal-scroll  the page itself is wider than the window
  hidden-at-rest     with reduced motion, more than a tenth of the text is invisible
  hidden-in-view     with motion on, text in the middle of the window is still faded
                     after its scroll reveal has had time to run
  low-contrast       page text under WCAG AA: 4.5:1, or 3:1 for large text
  undersized-text    page text under 11 px
  tight-leading      a wrapped paragraph whose line height is under 1.3 times its size
  line-length        a wrapped paragraph averaging more than 90 characters a line
  skipped-heading    a heading level skipped (h2 then h4)
  overshoot-easing   a cubic-bezier easing that overshoots (bounce or elastic)
  label-contrast     a label inside a drawing under 3:1 against what it is drawn on
  label-size         a label inside a drawing under 9 px on screen

The drawings (schematics, waveforms, the board) are SVG. A label's background is
the last filled shape drawn under its centre, composited over the page behind the
drawing. A drawing wider than a phone may scroll sideways inside its own box, so
label-size measures the drawing at the width it is actually shown.

The rules are re-implemented here from the descriptions in the detector catalogue
of Impeccable (github.com/pbakaus/impeccable, Apache-2.0); no code is taken from it.

Needs Node with Playwright (npm install playwright-core) and a Chromium. Set
CHROMIUM=/path/to/chrome to use one that is already installed. Without Playwright
it says so and exits 0, as the atlas check does without Yosys.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = ROOT / "docs/site"

AUDIT = r"""
() => {
  const out = [];
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const parse = s => {
    let m = /rgba?\(([^)]+)\)/.exec(s || "");
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = /color\(srgb ([^)]+)\)/.exec(s || "");
    if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return null;
  };
  const over = (a, b) => [0, 1, 2].map(i => a[i] * a[3] + b[i] * (1 - a[3])).concat(1);
  // the page colour behind an HTML element, or null where an image or gradient is behind it
  const bgOf = el => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== "none") return null;
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; }
    }
    let base = [255, 255, 255, 1];
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const shown = el => {
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const name = el => {
    const one = e => e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.classList.length ? "." + e.classList[0] : "");
    return (el.parentElement ? one(el.parentElement) + " > " : "") + one(el);
  };
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim();

  // ---- page text
  let total = 0, hidden = 0;
  for (const el of document.body.querySelectorAll("*")) {
    if (el instanceof SVGElement || el.closest("[hidden], template, noscript, dialog:not([open]), [aria-hidden=true]")) continue;
    const txt = own(el);
    if (txt.length < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || !el.getClientRects().length) continue;
    total += txt.length;
    if (!shown(el)) { hidden += txt.length; continue; }
    const fs = parseFloat(cs.fontSize);
    if (fs < 11) out.push({ rule: "undersized-text", where: name(el), detail: `${fs}px "${txt.slice(0, 32)}"` });
    const fg = parse(cs.color), bg = bgOf(el);
    if (fg && bg) {
      let a = +cs.opacity; for (let e = el.parentElement; e; e = e.parentElement) a *= +getComputedStyle(e).opacity;
      const c = over([fg[0], fg[1], fg[2], fg[3] * a], bg);
      const large = fs >= 24 || (fs >= 18.66 && +cs.fontWeight >= 700), need = large ? 3 : 4.5, r = ratio(c, bg);
      if (r < need) out.push({ rule: "low-contrast", where: name(el), detail: `${r.toFixed(2)}:1, needs ${need}:1, "${txt.slice(0, 32)}"` });
    }
  }
  if (total && hidden / total > 0.1) out.push({ rule: "hidden-at-rest", where: "page", detail: `${Math.round(100 * hidden / total)}% of the text is invisible with reduced motion on` });

  // ---- paragraphs: measured on the rendered lines
  const blockOf = n => { let e = n.parentElement; while (e && getComputedStyle(e).display.startsWith("inline")) e = e.parentElement; return e; };
  for (const p of document.querySelectorAll("p, li, dd, figcaption")) {
    if (!shown(p)) continue;
    const cs = getComputedStyle(p), fs = parseFloat(cs.fontSize), lh = cs.lineHeight === "normal" ? fs * 1.2 : parseFloat(cs.lineHeight);
    const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let chars = 0; const rows = new Set();
    for (let n; (n = walk.nextNode());) {
      if (blockOf(n) !== p || !n.textContent.trim()) continue;
      chars += n.textContent.replace(/\s+/g, " ").length;
      const r = document.createRange(); r.selectNodeContents(n);
      for (const q of r.getClientRects()) if (q.width > 1) rows.add(Math.round(q.bottom / (lh / 2)));
    }
    if (rows.size >= 2 && lh / fs < 1.3) out.push({ rule: "tight-leading", where: name(p), detail: `line height ${(lh / fs).toFixed(2)} times the size` });
    if (rows.size >= 3 && chars / rows.size > 90) out.push({ rule: "line-length", where: name(p), detail: `${Math.round(chars / rows.size)} characters a line` });
  }

  // ---- structure
  let last = 0;
  for (const h of document.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
    const n = +h.tagName[1];
    if (last && n > last + 1) out.push({ rule: "skipped-heading", where: name(h), detail: `h${last} then h${n}` });
    last = n;
  }
  if (document.documentElement.scrollWidth > innerWidth + 1)
    out.push({ rule: "horizontal-scroll", where: "page", detail: `${document.documentElement.scrollWidth}px wide in a ${innerWidth}px window` });
  for (const i of document.images) if (!i.naturalWidth && !i.closest("[hidden]")) out.push({ rule: "broken-image", where: name(i), detail: i.getAttribute("src") });
  const css = [...document.styleSheets].map(s => { try { return [...s.cssRules].map(r => r.cssText).join("\n"); } catch (e) { return ""; } }).join("\n") +
              [...document.querySelectorAll("[style]")].map(e => e.getAttribute("style")).join("\n");
  for (const m of css.matchAll(/cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/g))
    if (+m[2] < 0 || +m[2] > 1 || +m[4] < 0 || +m[4] > 1) out.push({ rule: "overshoot-easing", where: "stylesheet", detail: m[0] });

  // ---- labels inside drawings
  const SHAPES = "rect, circle, ellipse, path, polygon";
  for (const svg of document.querySelectorAll("svg")) {
    if (!shown(svg) || svg.closest("[aria-hidden=true]") && !svg.querySelector("text")) continue;
    const vb = svg.viewBox && svg.viewBox.baseVal, w = svg.getBoundingClientRect().width;
    const scale = vb && vb.width ? w / vb.width : 1;
    const behind = bgOf(svg);
    // every filled, visible shape once, in paint order, with its box on screen
    const shapes = [];
    for (const s of svg.querySelectorAll(SHAPES)) {
      const ss = getComputedStyle(s), f = parse(ss.fill);
      if (!f || f[3] === 0 || ss.display === "none" || ss.visibility === "hidden") continue;
      const b = s.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) continue;
      shapes.push({ s, b, c: [f[0], f[1], f[2], f[3] * +ss.fillOpacity * +ss.opacity] });
    }
    for (const t of svg.querySelectorAll("text")) {
      const txt = t.textContent.trim();
      if (!txt || !shown(t)) continue;
      const cs = getComputedStyle(t), px = parseFloat(cs.fontSize) * scale;
      if (px < 9) out.push({ rule: "label-size", where: name(svg.parentElement) + " text", detail: `${px.toFixed(1)}px on screen, "${txt.slice(0, 24)}"` });
      const fg = parse(cs.fill);
      if (!fg || !behind) continue;
      const tb = t.getBoundingClientRect(), cx = tb.x + tb.width / 2, cy = tb.y + tb.height / 2;
      let bg = behind;
      for (const { s, b, c } of shapes) {
        if (cx < b.left || cx > b.right || cy < b.top || cy > b.bottom) continue;
        if (!(t.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_PRECEDING)) continue;
        bg = over(c, bg);
      }
      const c = over([fg[0], fg[1], fg[2], fg[3] * +cs.fillOpacity * +cs.opacity], bg), r = ratio(c, bg);
      if (r < 3) out.push({ rule: "label-contrast", where: name(svg.parentElement) + " text", detail: `${r.toFixed(2)}:1, needs 3:1, "${txt.slice(0, 24)}"` });
    }
  }
  return out;
}
"""

# With motion on, the reveals are tied to scrolling: text below the fold may rest at
# opacity 0 until it is scrolled to. What must hold is that text in the middle of the
# window, after the reveal has had time to run, is readable.
INVIEW = r"""
() => {
  const out = [];
  for (const el of document.body.querySelectorAll("*")) {
    if (el instanceof SVGElement || el.closest("[hidden], template, noscript, dialog:not([open]), [aria-hidden=true]")) continue;
    const txt = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim();
    if (txt.length < 2) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.top < innerHeight * 0.3 || r.bottom > innerHeight * 0.7) continue;
    // a pinned scroll scene cross-fades its copy on purpose
    let pinned = false; for (let e = el; e; e = e.parentElement) if (getComputedStyle(e).position === "sticky") { pinned = true; break; }
    if (pinned) continue;
    let a = 1, gone = false;
    for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === "none") { gone = true; break; } if (cs.visibility === "hidden") a = 0; a *= +cs.opacity; }
    if (!gone && a < 0.6) out.push({ rule: "hidden-in-view", where: (el.parentElement && el.parentElement.id ? "#" + el.parentElement.id + " > " : "") + el.tagName.toLowerCase() + (el.classList.length ? "." + el.classList[0] : ""), detail: `opacity ${a.toFixed(2)} in the middle of the window, "${txt.slice(0, 32)}"` });
  }
  return out;
}
"""

RUNNER = r"""
let pw; try { pw = require("playwright-core"); } catch (e) { pw = require("playwright"); }
const AUDIT = %s;
const INVIEW = %s;
const [pages, configs] = JSON.parse(process.argv[1]);
(async () => {
  const b = await pw.chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const all = [];
  for (const f of pages) for (const [scheme, width, motion] of configs) {
    const ctx = await b.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: motion ? "no-preference" : "reduce" });
    const pg = await ctx.newPage(), errs = [];
    pg.on("pageerror", e => errs.push(e.message));
    pg.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
    await pg.goto("file://" + f);
    await pg.waitForTimeout(300);
    const H = await pg.evaluate(() => document.documentElement.scrollHeight);
    const found = [];
    if (motion) {
      for (let y = 0; y < H; y += 450) { await pg.evaluate(y => scrollTo(0, y), y); await pg.waitForTimeout(700); found.push(...await pg.evaluate(INVIEW)); }
    } else {
      for (let y = 0; y < H; y += 900) { await pg.evaluate(y => scrollTo(0, y), y); await pg.waitForTimeout(20); }
      await pg.evaluate(() => scrollTo(0, 0));
      await pg.waitForTimeout(300);
      found.push(...await pg.evaluate(AUDIT));
    }
    for (const e of errs) found.push({ rule: "script-error", where: "page", detail: e.slice(0, 160) });
    for (const x of found) all.push({ page: f.split("/").pop(), scheme: scheme + (motion ? " with motion" : ""), width, ...x });
    await ctx.close();
  }
  await b.close();
  process.stdout.write(JSON.stringify(all));
})().catch(e => { console.error(e.message); process.exit(2); });
"""

# theme, width, motion on; the audit runs with reduced motion so every reveal is at
# its end state, and one pass with motion on checks the scroll reveals
CONFIGS = [["light", 1280, False], ["dark", 1280, False], ["light", 390, False], ["dark", 390, False], ["light", 1280, True]]


def have_playwright():
    for mod in ("playwright-core", "playwright"):
        if subprocess.run(["node", "-e", f"require({mod!r})"], cwd=ROOT, capture_output=True).returncode == 0:
            return True
    return False


def audit(pages, configs=CONFIGS):
    js = RUNNER % (AUDIT.strip(), INVIEW.strip())
    r = subprocess.run(["node", "-e", js, json.dumps([[str(p) for p in pages], configs])],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit("site_lint: the browser run failed:\n" + r.stderr)
    return json.loads(r.stdout)


def report(found):
    """One line per fault and place, naming every theme and width it shows in."""
    seen = {}
    for x in found:
        k = (x["page"], x["rule"], x["where"])
        seen.setdefault(k, [x["detail"], set()])[1].add(f"{x['scheme']} {x['width']}px")
    return [f"{p}: {rule} at {where}: {d} ({', '.join(sorted(w))})" for (p, rule, where), (d, w) in sorted(seen.items())]


# Each mutant injects one fault into a copy of the overview page and names the rule
# that must catch it, with the theme and width it is measured at.
MUTANTS = [
    ("low-contrast", "light", 1280, "<style>main p{color:#c4c4c4!important}</style>"),
    ("undersized-text", "light", 1280, "<style>main p{font-size:9px!important}</style>"),
    ("tight-leading", "light", 1280, "<style>main p{line-height:1.05!important}</style>"),
    ("line-length", "light", 1280, "<style>main *{max-width:none!important}</style>"),
    ("skipped-heading", "light", 1280, "<h2>Mutant</h2><h4>Mutant</h4>"),
    ("horizontal-scroll", "light", 390, '<div style="width:1400px;height:4px"></div>'),
    ("script-error", "light", 1280, "<script>null.mutant()</script>"),
    ("broken-image", "light", 1280, '<img src="mutant-missing.png" alt="">'),
    ("hidden-at-rest", "light", 1280, "<style>main p, main li{opacity:0!important}</style>"),
    ("hidden-in-view", "light", 1280, "<style>main h2{opacity:.2!important}</style>"),
    ("overshoot-easing", "light", 1280, "<style>.mutant{transition-timing-function:cubic-bezier(.3,1.6,.6,1)}</style>"),
    ("label-size", "light", 390, "<style>svg{width:120px!important;min-width:0!important}</style>"),
    ("label-contrast", "dark", 1280, "<style>svg text{fill:#1d201f!important}</style>"),
]


def mutants():
    base = report(audit([SITE / "index.html"], CONFIGS))
    if base:
        sys.exit("site_lint --mutants: the page must pass before it is mutated:\n  " + "\n  ".join(base))
    caught = 0
    with tempfile.TemporaryDirectory() as tmp:
        site = pathlib.Path(tmp) / "site"
        shutil.copytree(SITE, site)
        page = (SITE / "index.html").read_text()
        for rule, scheme, width, inject in MUTANTS:
            (site / "index.html").write_text(re.sub(r"</body>", lambda m: inject + "</body>", page, count=1))
            got = {x["rule"] for x in audit([site / "index.html"], [[scheme, width, rule == "hidden-in-view"]])}
            if rule in got:
                caught += 1
            else:
                print(f"site_lint --mutants: MISSED {rule} (the audit found {sorted(got) or 'nothing'})")
    print(f"site_lint --mutants: {caught}/{len(MUTANTS)} caught")
    sys.exit(0 if caught == len(MUTANTS) else 1)


def main():
    if not have_playwright():
        print("site_lint: Playwright for Node not found (npm install playwright-core), design audit skipped")
        return
    if "--mutants" in sys.argv:
        mutants()
    pages = sorted(SITE.glob("*.html"))
    lines = report(audit(pages))
    for ln in lines:
        print("site_lint:", ln)
    if lines:
        sys.exit(f"site_lint: {len(lines)} design fault(s) on the built site")
    print(f"site_lint: {len(pages)} pages, light and dark, 1280 and 390 px wide: no design faults")


if __name__ == "__main__":
    main()
