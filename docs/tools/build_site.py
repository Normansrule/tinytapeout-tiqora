#!/usr/bin/env python3
"""build_site.py — build the explorer site: self-contained pages in docs/site/.

    python3 docs/tools/build_site.py           write docs/site/*.html and docs/images/explorer/*.svg
    python3 docs/tools/build_site.py --check   fail if any of them is out of date

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. What differs
lives in each repository's docs/site/site.json (chip, pages, the flow
diagram) and docs/site/pages/*.html (the words).

Every page is one HTML file with the stylesheet, the scripts and its data
inlined, so it opens from disk, from GitHub Pages, or through an HTML
preview link, with nothing fetched from anywhere. A page template starts
with a JSON comment naming its data and scripts; {{static:NAME}} marks
static HTML the builder renders here in Python, which is also what a reader
without JavaScript sees.
"""
import base64, html, json, math, os, re, sys

SITE = "docs/site"
LIB = SITE + "/lib"
MEDIA = "docs/images/explorer"
SCRIPTS = ["model", "wave", "player", "atlas", "die", "labs", "board"]
esc = lambda s: html.escape(str(s), quote=True)


def load(path):
    return json.load(open(path))


def fmt_um2(v):
    return f"{v:,.0f}" if v >= 100 else f"{v:,.1f}"


# ------------------------------------------------------------------ static renderers
def static_atlas_table(ctx):
    a = ctx["atlas"]
    area = a.get("area", {}).get("modules_um2", {})
    rows = "".join(
        f"<tr><td>{esc(b['title'])}</td><td><code>{esc(b['module'])}</code></td><td>{esc(b['category'])}</td>"
        f"<td>{esc(', '.join(b['builds']))}</td><td class=num>{b['ff_bits']}</td>"
        f"<td class=num>{fmt_um2(area[b['module']]) if b['module'] in area else '–'}</td><td>{esc(b['summary'])}</td></tr>"
        for b in a["blocks"])
    return ("<div class=tablewrap><table><caption class=sr>Every block in the chip</caption><thead><tr><th>Block</th><th>Module</th>"
            "<th>Category</th><th>Builds</th><th class=num>Flip-flop bits</th><th class=num>Area µm² (measured)</th><th>What it does</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>")


def static_pins(ctx):
    pins = ctx["atlas"]["pins"]
    order = sorted(pins, key=lambda p: (["ui", "uo", "uio"].index(p.split("[")[0]), int(p.split("[")[1][:-1])))
    rows = "".join(f"<tr><td><code>{esc(p)}</code></td><td>{esc(pins[p])}</td></tr>" for p in order)
    return f"<div class=tablewrap><table><caption class=sr>Pinout from info.yaml</caption><thead><tr><th>Pin</th><th>Function (info.yaml)</th></tr></thead><tbody>{rows}</tbody></table></div>"


def badge(kind, text=None):
    word = {"done": "measured", "measured": "measured", "pass": "measured", "est": "estimate", "estimate": "estimate",
            "fail": "failed", "blocked": "blocked", "todo": "not yet", "none": "not yet"}.get(kind, kind)
    return f"<span class='ev {esc(kind)}'>{esc(text or word)}</span>"


def static_progress(ctx):
    p = ctx["progress"]
    out = []
    for m in p["milestones"]:
        items = []
        for s in m["steps"]:
            ev = s.get("evidence") or {}
            if s["state"] == "done":
                why = f"{esc(ev.get('result', ''))} <span class=small>({esc(ev.get('label', ''))}, {esc(ev.get('version', ''))}: <code>{esc(ev.get('command', ''))}</code>)</span>"
            else:
                why = esc(s.get("next", ""))
            items.append(f"<li><span class=what>{esc(s['step'])}</span>{badge(s['state'])}<span class=why>{why}</span></li>")
        out.append(f"<h3>{esc(m['name'])}</h3><ul class='ladder plain'>{''.join(items)}</ul>")
    return "".join(out)


def static_ladder(ctx):
    """The evidence ladder for each target, from site.json: every rung states its evidence."""
    out = []
    for t in ctx["site"]["ladder"]:
        rungs = "".join(f"<li><span class=n>{i + 1}</span><span class=what>{esc(r['rung'])}</span>{badge(r['state'], r.get('word'))}"
                        f"<span class=why>{r['why']}</span></li>" for i, r in enumerate(t["rungs"]))
        out.append(f"<h3>{esc(t['target'])}</h3><p class=small>{t.get('note', '')}</p><ol class=ladder>{rungs}</ol>")
    return "".join(out)


def static_flow(ctx):
    return flow_svg(ctx, inline=True)


def static_treemap(ctx):
    return treemap_svg(ctx, inline=True)


def static_motion(ctx):
    """Every reel docs/tools/motion.py drew, inlined so the pause button can stop it.
    Each reel names its classes after its tour, so they do not collide here."""
    m = ctx["site"]["motion"]
    out = []
    for r in m["reels"]:
        fx = next(t for t in ctx["data"]["traces"] if t["id"] == r["fixture"])
        svg = open(f"{m['out']}/{fx['id']}.svg", encoding="utf-8").read().strip()
        out.append(f"<figure class=reel>{svg}<figcaption><a href='tours.html#seq={esc(fx['id'])}'>Step through “{esc(fx['title'])}”</a> "
                   f"<span class='ev measured'>recorded</span> <span class=small>{esc(fx['kind_text'])}; drawn by <code>docs/tools/motion.py</code></span></figcaption></figure>")
    return ("<p class=reel-bar><button class='btn ghost' type=button id=reel-pause aria-pressed=false>Pause the animations</button> "
            "<span class=small>With reduced motion turned on in your system, each one is a still of the whole recording.</span></p>"
            f"<div class=reels id=reels>{''.join(out)}</div>")


STATIC = {"atlas_table": static_atlas_table, "pins": static_pins, "progress": static_progress,
          "ladder": static_ladder, "flow": static_flow, "treemap": static_treemap, "motion": static_motion}


# ------------------------------------------------------------------ diagram styling
# The diagrams take their colours from exhibit.css: inlined in a page they use
# the page's tokens, so they follow its light or dark theme. Written out as
# files for the README they carry their own <style>: the token blocks and the
# .fl-, .tm- and .cat- rules copied from exhibit.css, so there is one source.
def diagram_style():
    css = open(f"{LIB}/exhibit.css").read()
    blocks = re.findall(r"^:root \{.*?^\}|^@media \(prefers-color-scheme: dark\) \{.*?^\}|^:root\[data-theme=\"dark\"\] \{.*?^\}", css, re.S | re.M)
    rules = [ln for ln in css.splitlines() if re.match(r"\.(fl|tm|cat)-", ln)]
    return re.sub(r"\s+", " ", "\n".join(blocks + rules)).replace("> ", ">")


def fonts_css():
    """The two variable fonts, inlined so a page stays one file with no
    network loads. Latin only; anything else falls back to the system face."""
    out = []
    for fam, f, wt in (("Atkinson Hyperlegible Next", "atkinson-hyperlegible-next-latin-wght-normal.woff2", "200 800"),
                       ("Atkinson Hyperlegible Mono", "atkinson-hyperlegible-mono-latin-wght-normal.woff2", "200 800"),
                       ("Barlow Semi Condensed", "barlow-semi-condensed-latin-600-normal.woff2", "600")):
        b64 = base64.b64encode(open(f"{LIB}/fonts/{f}", "rb").read()).decode()
        out.append(f"@font-face {{ font-family: \"{fam}\"; font-style: normal; font-weight: {wt}; font-display: swap; "
                   f"src: url(data:font/woff2;base64,{b64}) format(\"woff2\"); }}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ the flow diagram
def flow_svg(ctx, inline=False):
    """What enters, what happens inside, what comes out: nodes and edges from
    site.json; every node that names a block must exist in the atlas. Each
    part carries --d, its position from left to right, so the page can let
    the diagram read in in the order a signal travels."""
    f = ctx["site"]["flow"]
    mods = {b["module"] for b in ctx["atlas"]["blocks"]}
    for n in f["nodes"]:
        for m in n.get("blocks", []):
            if m not in mods:
                sys.exit(f"build_site.py: flow node {n['id']} names {m}, which is not in the atlas")
    W, H = f["size"]
    nodes = {n["id"]: n for n in f["nodes"]}
    xs = sorted({n["x"] for n in f["nodes"]})
    rank = lambda x: max([i for i, v in enumerate(xs) if v <= x] or [0])
    p = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' role='img' aria-labelledby='flow-t flow-d'>",
         f"<title id='flow-t'>{esc(f['title'])}</title><desc id='flow-d'>{esc(f['desc'])}</desc>",
         "<defs><marker id='ar' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'><path class='fl-arrow' d='M0 0 L10 5 L0 10 z'/></marker></defs>"]
    if not inline:
        p.append(f"<style>{diagram_style()} svg {{ font-family: var(--sans); }}</style>")
        p.append(f"<rect width='{W}' height='{H}' rx='6' fill='var(--surface)' stroke='var(--line)'/>")
    if f.get("chip_box"):
        x, y, w, h = f["chip_box"]
        p.append(f"<g class='fl-g' style='--d:1'><rect class='fl-chip' x='{x}' y='{y}' width='{w}' height='{h}' rx='6'/>"
                 f"<text class='fl-chiplbl' x='{x + 12}' y='{y + h - 12}'>{esc(f['chip_label'])}</text></g>")
    for col in f.get("columns", []):
        p.append(f"<text class='fl-g fl-col' style='--d:{rank(col['x'])}' x='{col['x']}' y='26'>{esc(col['label'])}</text>")
    labels = []
    box = f.get("chip_box")
    inside = lambda x, y: box and box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]
    for e in f["edges"]:
        a, b = nodes[e[0]], nodes[e[1]]
        x1, y1 = a["x"] + a["w"], a["y"] + a["h"] / 2
        x2, y2 = b["x"] - 2, b["y"] + b["h"] / 2
        if b["x"] + b["w"] <= a["x"]:
            x1, x2 = a["x"], b["x"] + b["w"] + 2
        overlap = a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
        if overlap:
            x1, y1, x2, y2 = a["x"] + a["w"] / 2, a["y"] + (a["h"] if b["y"] > a["y"] else 0), b["x"] + b["w"] / 2, b["y"] + (-2 if b["y"] > a["y"] else b["h"] + 2)
            d = f"M{x1} {y1} L{x2} {y2}"
        else:
            mx = (x1 + x2) / 2
            d = f"M{x1} {y1} C{mx} {y1} {mx} {y2} {x2} {y2}"
        dd = rank(a["x"]) + 0.5
        p.append(f"<path class='fl-g fl-edge' style='--d:{dd}' d='{d}' marker-end='url(#ar)'/>")
        # a label goes on the edge only where the edge is long enough to carry it
        if len(e) > 2 and overlap and abs(y2 - y1) > 24:
            lx, ly = x1 + 7, (y1 + y2) / 2 + 4
            labels.append(f"<text class='fl-g fl-elbl{' in' if inside(lx, ly) else ''}' style='--d:{dd}' x='{lx}' y='{ly}'>{esc(e[2])}</text>")
        elif len(e) > 2 and abs(x2 - x1) > 6.2 * len(e[2]) + 12:
            lx, ly = x1 + (x2 - x1) * 0.7, y1 + (y2 - y1) * 0.7 - 6
            labels.append(f"<text class='fl-g fl-elbl{' in' if inside(lx, ly) else ''}' style='--d:{dd}' x='{lx}' y='{ly}' text-anchor='middle'>{esc(e[2])}</text>")
    for n in f["nodes"]:
        cls = f"fl-node cat-{n['cat']}" if n.get("blocks") and n.get("cat") else ("fl-node" if n.get("blocks") else "fl-ext")
        p.append(f"<g class='fl-g' style='--d:{rank(n['x'])}'><rect class='{cls}' x='{n['x']}' y='{n['y']}' width='{n['w']}' height='{n['h']}' rx='5'/>")
        p.append(f"<text class='fl-title' x='{n['x'] + 10}' y='{n['y'] + 19}'>{esc(n['label'])}</text>")
        for i, line in enumerate(n.get("lines", [])):
            p.append(f"<text class='fl-sub' x='{n['x'] + 10}' y='{n['y'] + 35 + 14 * i}'>{esc(line)}</text>")
        p.append("</g>")
    p.extend(labels)
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------ the area treemap
def squarify(items, x, y, w, h):
    """Squarified treemap: [(value, key)] -> {key: (x, y, w, h)}."""
    items = sorted([i for i in items if i[0] > 0], reverse=True)
    out, total = {}, sum(v for v, _ in items)
    if not items or total <= 0:
        return out
    scale = w * h / total
    rest = [(v * scale, k) for v, k in items]

    def worst(row, side):
        s = sum(v for v, _ in row)
        return max(max(side * side * v / (s * s), (s * s) / (side * side * v)) for v, _ in row)

    while rest:
        side = min(w, h)
        row = [rest.pop(0)]
        while rest and worst(row + [rest[0]], side) <= worst(row, side):
            row.append(rest.pop(0))
        s = sum(v for v, _ in row)
        if w >= h:
            cw, cy = s / h, y
            for v, k in row:
                out[k] = (x, cy, cw, v / cw); cy += v / cw
            x, w = x + cw, w - cw
        else:
            ch, cx = s / w, x
            for v, k in row:
                out[k] = (cx, y, v / ch, ch); cx += v / ch
            y, h = y + ch, h - ch
    return out


def treemap_svg(ctx, inline=False):
    """Each block's measured cell area, drawn to scale inside the tile's die
    outline. Proportional area only: it is not where the cells would sit."""
    a = ctx["atlas"]
    area = a["area"]["modules_um2"]
    die_w, die_h = ctx["site"]["die_um"]
    die = die_w * die_h
    blocks = [b for b in a["blocks"] if "tile" in b["builds"] and b["module"] in area]
    total = sum(area[b["module"]] for b in blocks)
    W = 760
    S = W / die_w
    H = die_h * S
    side = math.sqrt(total / die)
    tw, th = die_w * side * S, die_h * side * S
    tx, ty = (W - tw) / 2, (H - th) / 2
    rects = squarify([(area[b["module"]], b["path"]) for b in blocks], tx, ty + 0, tw, th)
    byp = {b["path"]: b for b in blocks}
    p = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='-2 -2 {W + 4} {H + 44}' role='img' aria-labelledby='tm-t tm-d'>",
         f"<title id='tm-t'>{esc(a['chip'])}: measured cell area per block, to scale against the {esc(a['tiles'])} tile</title>",
         f"<desc id='tm-d'>The outer rectangle is the Tiny Tapeout {esc(a['tiles'])} die, {die_w} by {die_h} µm. The inner rectangles add up to the {fmt_um2(total)} µm² of standard cells "
         f"Yosys synthesis measured, module by module, {100 * total / die:.0f}% of the die. Sizes are to scale; positions are not a floorplan.</desc>"]
    if not inline:
        p.append(f"<style>{diagram_style()}</style><rect x='-2' y='-2' width='{W + 4}' height='{H + 44}' fill='var(--surface)'/>")
    p.append(f"<rect class='tm-die' x='0' y='0' width='{W}' height='{H}'/>")
    for path, (x, y, w, h) in rects.items():
        b = byp[path]
        p.append(f"<g><title>{esc(b['title'])} ({esc(b['module'])}): {fmt_um2(area[b['module']])} µm²</title>"
                 f"<rect class='tm-cell cat-{esc(b['category'])}' x='{x + 1:.1f}' y='{y + 1:.1f}' width='{max(0, w - 2):.1f}' height='{max(0, h - 2):.1f}'/>")
        if w > 76 and h > 34:
            p.append(f"<text class='tm-name' x='{x + 7:.1f}' y='{y + 18:.1f}'>{esc(b['module'])}</text>"
                     f"<text class='tm-val' x='{x + 7:.1f}' y='{y + 33:.1f}'>{fmt_um2(area[b['module']])} µm²</text>")
        elif w > 38 and h > 18:
            p.append(f"<text class='tm-short' x='{x + 5:.1f}' y='{y + 14:.1f}'>{esc(b['module'][:max(3, int(w / 6.8))])}</text>")
        p.append("</g>")
    p.append(f"<text class='tm-note' x='0' y='{H + 19}'>dashed: the {esc(a['tiles'])} die, {die_w} × {die_h} µm = {fmt_um2(die)} µm² (Tiny Tapeout template)</text>")
    p.append(f"<text class='tm-note' x='0' y='{H + 36}'>filled: {fmt_um2(total)} µm² of cells, summed per module ({100 * total / die:.0f}% of the die) · sizes to scale, positions are not a floorplan</text>")
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------ board
BOARD_REC = "docs/fpga/basys3_demo.rec"


def board_data(site):
    """The recorded Basys 3 run as change lists, plus what the board's parts are called.
    An undriven bit (x or z) reads as off, as docs/tools/fpga_media.py draws it."""
    ch, uart, end, div = {}, [], 0, None
    for line in open(BOARD_REC):
        if line.startswith("#"):
            m = re.search(r"UART (\d+) clocks per bit", line)
            div = int(m.group(1)) if m else div
            continue
        c, k, v = line.split()
        c = int(c); end = max(end, c)
        if k in ("tx", "rx"):
            uart.append([c, 1 if k == "tx" else 0, int(v, 16)])
            continue
        bits = "".join("0" if q in "xXzZ" else q for q in v)
        ch.setdefault(k, []).append([c, int(bits, 2 if k == "led" else 16)])
    uart.sort()
    return {"end": end, "uart_div": div, "uart": uart, **{k: ch.get(k, []) for k in ("rst", "led", "in", "out", "btn")},
            "cfg": site["fpga"]}


# ------------------------------------------------------------------ pages
def die_facts(d):
    """The numbers the die zoom's captions quote, from die.json (docs/tools/die_map.py)."""
    q = d["q_nm"] / 1000
    fc = next(c for c in d["cells"] if c["name"] == d["focus"]["cell"])
    big = d["regions"][0]
    fx, fy = (v * q for v in d["focus"]["at"][:2])
    home = next(r for r in d["regions"] if r["um"][0] <= fx <= r["um"][0] + r["um"][2] and r["um"][1] <= fy <= r["um"][1] + r["um"][3])
    name = lambda r: esc(re.sub(r"\s*\(.*\)$", "", r["label"]).lower())
    return {"tile": f"{d['tile_um'][0]:.2f} × {d['tile_um'][1]:.2f}", "tile_r": f"{d['tile_um'][0]:.0f} × {d['tile_um'][1]:.0f}", "cells": f"{len(d['inst']):,}", "kinds": str(len(d["cells"])),
            "area": f"{d['cell_area_um2']:,.0f}", "blocks": str(len(d["regions"])), "row": f"{d['row_um']:.2f}",
            "focus": "sky130_fd_sc_hd__" + fc["name"], "focus_w": f"{fc['w'] * q:.2f}",
            "big": name(big), "home": name(home), "synth": esc(d["synth"]), "big_area": f"{big['cell_area_um2']:,.0f}",
            # the categories the outlines use, in the order the atlas lists them
            "cats": " ".join(f'<span style="white-space:nowrap"><span class="swatch cat-{c}"></span>{c}</span>' for c in
                             sorted({r.get("category", "control") for r in d["regions"]}, key=CAT_ORDER.index))}


CAT_ORDER = ["interface", "compute", "memory", "timing", "control", "pins"]


def page(ctx, tpl_path):
    src = open(tpl_path).read()
    m = re.match(r"\s*<!--\s*(\{.*?\})\s*-->\s*", src, re.S)
    if not m:
        sys.exit(f"build_site.py: {tpl_path} must start with a JSON comment")
    meta = json.loads(m.group(1))
    body = src[m.end():]
    site = ctx["site"]
    pid = os.path.splitext(os.path.basename(tpl_path))[0]

    def sub(mm):
        name = mm.group(1)
        if name not in STATIC:
            sys.exit(f"build_site.py: {tpl_path}: unknown {{{{static:{name}}}}}")
        return STATIC[name](ctx)
    body = re.sub(r"\{\{static:(\w+)\}\}", sub, body)
    # {{die:NAME}}: a number from docs/site/data/die.json, so the zoom's captions read the same without JavaScript
    if "{{die:" in body:
        facts = die_facts(ctx["data"]["die"])
        def dsub(mm):
            if mm.group(1) not in facts:
                sys.exit(f"build_site.py: {tpl_path}: unknown {{{{die:{mm.group(1)}}}}}")
            return facts[mm.group(1)]
        body = re.sub(r"\{\{die:(\w+)\}\}", dsub, body)
    # {{img:path}}: an image in the repository, inlined so the page stays one file
    body = re.sub(r"\{\{img:([\w./-]+)\}\}", lambda mm: "data:image/" + {"jpg": "jpeg", "gif": "gif", "svg": "svg+xml"}.get(mm.group(1).rsplit(".", 1)[-1], "png") + ";base64," +
                  base64.b64encode(open(mm.group(1), "rb").read()).decode(), body)
    body = body.replace("{{repo}}", site["repo"]).replace("{{chip}}", esc(site["chip"]))
    # a page's own scripts run last, after its data and the library
    tail = "".join(re.findall(r"<script>.*?</script>\s*", body, re.S))
    body = re.sub(r"<script>.*?</script>\s*", "", body, flags=re.S)
    left = re.findall(r"\{\{[^}]*\}\}", body)
    if left:
        sys.exit(f"build_site.py: {tpl_path}: unfilled {left}")

    data = []
    for name in meta.get("data", []):
        v = ctx["data"][name]
        txt = json.dumps(v, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
        data.append(f"<script type=application/json id=data-{name}>{txt}</script>")
    scripts = "".join(f"<script>\n{open(f'{LIB}/{s}.js').read()}</script>\n" for s in SCRIPTS if s in meta.get("scripts", []))
    nav = "".join(f"<a href='{p['id']}.html'{' aria-current=page' if p['id'] == pid else ''}>{esc(p['nav'])}</a>" for p in site["pages"])
    css = fonts_css() + open(f"{LIB}/exhibit.css").read()
    # the mark: a tile outline with one pulse, the pulse in the accent
    icon = ("<svg viewBox='0 0 24 24' aria-hidden='true'><rect x='3' y='3' width='18' height='18' rx='2' fill='none' stroke='currentColor' stroke-width='2'/>"
            "<path d='M6.5 15h3.5V9h4v6h3.5' fill='none' stroke='var(--accent)' stroke-width='2'/></svg>")
    theme_icon = ("<svg class=ico viewBox='0 0 16 16' aria-hidden='true'><circle cx='8' cy='8' r='5.5'/>"
                  "<path d='M8 2.5a5.5 5.5 0 0 1 0 11z' fill='currentColor' stroke='none'/></svg>")
    # the GitHub mark (simplified, one path), for the link back to the source
    gh_icon = ("<svg class=ico viewBox='0 0 16 16' aria-hidden='true'><path fill='currentColor' stroke='none' d='M8 .2a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38v-1.33"
               "c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.8.06 1.23.83 1.23.83.72 1.22 1.88.87 2.34.66.07-.52.28-.87.5-1.07"
               "-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.03 2.2-.82 2.2-.82"
               ".44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 8 .2z'/></svg>")
    # the browser-tab icon: the same mark, with the light theme's colours written out (a favicon cannot read CSS variables)
    favicon = "data:image/svg+xml," + (icon.replace("currentColor", "#141816").replace("var(--accent)", "#0b5f86").replace("'", "%27").replace("<", "%3C").replace(">", "%3E")
                                       .replace(" aria-hidden=%27true%27", " xmlns=%27http://www.w3.org/2000/svg%27"))
    # optional site.json keys: "url" (the published copy, for link previews) and "sibling" ({"name", "url"}: the other Tiqora chip)
    url = site.get("url", "")
    head_extra = (f'<meta property=og:type content=website>\n<meta property=og:site_name content="{esc(site["chip"])}">\n'
                  f'<meta property=og:title content="{esc(meta["title"])} · {esc(site["chip"])}">\n'
                  f'<meta property=og:description content="{esc(meta.get("description", ""))}">\n'
                  f'<meta property=og:url content="{url}{"" if pid == "index" else pid + ".html"}">\n') if url else ""
    sib = site.get("sibling")
    sibling = f' Its sibling: <a href="{sib["url"]}">{esc(sib["name"])}</a>.' if sib else ""
    return f"""<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{esc(meta['title'])} · {esc(site['chip'])}</title>
<meta name=description content="{esc(meta.get('description', ''))}">
<meta name=generator content="docs/tools/build_site.py; edit docs/site/pages/{pid}.html, not this file">
<meta name=theme-color content="#f5f5f2" media="(prefers-color-scheme: light)">
<meta name=theme-color content="#0b0d0c" media="(prefers-color-scheme: dark)">
<link rel=icon href="{favicon}">
{head_extra}<style>
{css}</style>
<script>try {{ const t = localStorage.getItem("tq-theme"); if (t) document.documentElement.dataset.theme = t; }} catch (e) {{}}</script>
</head>
<body>
<a class=skip href=#main>Skip to content</a>
<header class=top><div class=in>
<a class=brand href=index.html>{icon}{esc(site['chip'].upper())}</a>
<nav aria-label="Explorer pages">{nav}</nav>
<div class=tools><a class=src href="{site['repo']}" aria-label="Source code on GitHub">{gh_icon}<span>GitHub</span></a>
<button class=theme type=button id=theme aria-label="Switch between light and dark">{theme_icon}Theme</button></div>
</div><div class=ruler aria-hidden=true><svg id=ruler-svg></svg><span class=now></span></div></header>
<main id=main>
{body}
</main>
<footer><div class=in>
<p>{site['footer']}</p>
<p>Built by <code>docs/tools/build_site.py</code> from the RTL's own recordings and measurements. Maintained by <a href="https://github.com/Normansrule">@Normansrule</a>. Source, tests and issues: <a href="{site['repo']}">{esc(site['repo'].replace('https://', ''))}</a>.{sibling}</p>
</div></footer>
{''.join(data)}
{scripts}<script>
document.getElementById("theme").addEventListener("click", () => {{
  const r = document.documentElement, dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  r.dataset.theme = dark ? "light" : "dark";
  try {{ localStorage.setItem("tq-theme", r.dataset.theme); }} catch (e) {{}}
}});
const DATA = n => JSON.parse(document.getElementById("data-" + n).textContent);
{{  // on a phone the page links scroll sideways: start with the current page in view
  const nav = document.querySelector(".top nav"), cur = nav.querySelector("[aria-current]");
  if (cur && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = cur.offsetLeft - nav.offsetLeft - 10;
}}
(function () {{  // the cycle ruler: minor ticks every 16 px, a taller tick per section, the cursor at your place
  const r = document.querySelector(".ruler"), s = document.getElementById("ruler-svg"), now = r.querySelector(".now");
  function draw() {{
    const w = r.clientWidth, doc = document.documentElement.scrollHeight - innerHeight, NS = "http://www.w3.org/2000/svg";
    s.replaceChildren();
    for (let x = 0; x < w; x += 16) {{ const l = document.createElementNS(NS, "line"); l.setAttribute("class", "minor"); l.setAttribute("x1", x + .5); l.setAttribute("x2", x + .5); l.setAttribute("y1", x % 128 ? 9 : 5); l.setAttribute("y2", 14); s.append(l); }}
    document.querySelectorAll("main h2").forEach(h => {{
      const x = Math.round(Math.min(1, (h.getBoundingClientRect().top + scrollY) / Math.max(1, doc + innerHeight)) * (w - 2)) + .5;
      const l = document.createElementNS(NS, "line"); l.setAttribute("class", "sec"); l.setAttribute("x1", x); l.setAttribute("x2", x); l.setAttribute("y1", 2); l.setAttribute("y2", 14); s.append(l);
    }});
    place();
  }}
  function place() {{ const doc = document.documentElement.scrollHeight - innerHeight; now.style.setProperty("--x", (doc > 0 ? scrollY / doc : 0) * (r.clientWidth - 2) + "px"); }}
  addEventListener("scroll", place, {{ passive: true }});
  addEventListener("resize", draw);
  addEventListener("load", draw);
  draw();
}})();
</script>
{tail}
</body>
</html>
"""


def main():
    check = "--check" in sys.argv
    site = load(SITE + "/site.json")
    atlas = load(SITE + "/data/atlas.json")
    traces = []
    idx = load(SITE + "/data/traces/index.json")
    for f in idx["fixtures"]:
        traces.append(load(SITE + "/data/traces/" + f["file"]))
    data = {"atlas": atlas, "traces": traces, "progress": load("docs/progress.json"),
            "site": {k: site[k] for k in ("chip", "repo", "ref", "clock_ns")},
            "blocks": [b["module"] for b in atlas["blocks"] if "tile" in b["builds"]],
            "tours": [{"id": t["id"], "title": t["title"], "summary": t["summary"], "cycles": t["cycles"], "captions": len(t["captions"])} for t in traces]}
    # the recorded deadline tour alone, for the overview's "fire a deadline" lab
    data["deadline"] = next(t for t in traces if t["id"] == "deadline")
    # the simulated Basys 3 run (fpga/basys3/rec_basys3.sv), for the overview's live board
    if os.path.exists(BOARD_REC):
        data["board"] = board_data(site)
    for name, path in site.get("data", {}).items():
        data[name] = load(path)
    ctx = {"site": site, "atlas": atlas, "progress": data["progress"], "data": data}
    out = {}
    for p in site["pages"]:
        out[f"{SITE}/{p['id']}.html"] = page(ctx, f"{SITE}/pages/{p['id']}.html")
    out[f"{MEDIA}/flow.svg"] = flow_svg(ctx) + "\n"
    out[f"{MEDIA}/area_treemap.svg"] = treemap_svg(ctx) + "\n"
    stale = []
    for path, text in out.items():
        if check:
            if not os.path.exists(path) or open(path).read() != text:
                stale.append(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(text)
    if check:
        if stale:
            print("build_site: out of date, run python3 docs/tools/build_site.py: " + ", ".join(stale))
            sys.exit(1)
        print(f"site: {len(out)} files up to date")
    else:
        for path, text in out.items():
            print(f"wrote {path} ({len(text) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
