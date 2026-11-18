#!/usr/bin/env python3
"""tt_floorplan.py: where this design sits on the Tiny Tapeout chip, to scale, in mm and µm.

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

    python3 docs/tools/tt_floorplan.py            write the drawings (below)
    python3 docs/tools/tt_floorplan.py --check    fail if a drawing is stale or a number disagrees
    python3 docs/tools/tt_floorplan.py --mutants  break the facts on purpose; --check must catch each
    python3 docs/tools/tt_floorplan.py --refresh CARAVEL TT_MUX TT_SUPPORT OPENFRAME
                                                  rebuild docs/tools/tt_chip.json from git
                                                  checkouts of those four repositories

Writes, deterministically (same inputs, same bytes):
  docs/images/tt_floorplan.svg     four panels, package to tile, every length labelled; light
                                   and dark follow the reader's colour scheme
  docs/images/tt_floorplan_print.svg  the same with the light colours written out, for the PDF
                                   datasheet (docs/info.md): typst reads no CSS variables
  docs/site/data/floorplan.html    the same four panels for the site's physical page, where
                                   docs/site/lib/floorplan.js turns them into steps

Inputs, nothing typed in by hand:
  info.yaml                        this design's top module and tile count
  docs/tools/tt_chip.json          every chip-level number, each with its file and commit:
    die and pads                   efabless/caravel mag/caravel_openframe.mag and
                                   mag/chip_io_openframe.mag (Magic layout, 0.005 µm units)
    user area                      efabless/openframe_user_project lef/openframe_project_wrapper.lef
    tile grid                      TinyTapeout/tt-multiplexer cfg/sky130.yaml; the grid is
                                   computed here with the arithmetic of py/tt/layout.py
                                   global_layout(), and --check proves it reproduces every
                                   size in tt-support-tools tech/sky130A/tile_sizes.yaml
    package                        TinyTapeout/breakout-pcb footprint name (QFN-64, 9 x 9 mm)
    this design's die              the routed run's design__die__bbox, with the run named

What is not known, and is drawn as such: Tiny Tapeout assigns a project's position on the
shuttle at tape-out, so the block is drawn in one example slot, labelled as an example;
the die's position inside the package is not published, so the die is drawn centred.
"""
import json, math, os, re, subprocess, sys

FIXTURE = "docs/tools/tt_chip.json"
OUT_SVG = "docs/images/tt_floorplan.svg"
OUT_PRINT = "docs/images/tt_floorplan_print.svg"
OUT_SITE = "docs/site/data/floorplan.html"
CSS_FILE = "docs/site/lib/exhibit.css"


# ------------------------------------------------------------------ refresh (needs the source checkouts)
def git_head(path):
    return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def mag_uses(path):
    """Every subcell placement in a Magic .mag file: (cell, instance, transform, box)."""
    out, cur = [], None
    for ln in open(path):
        w = ln.split()
        if not w:
            continue
        if w[0] == "use":
            cur = {"cell": w[1], "inst": w[2].replace("\\", "")}
        elif w[0] == "transform" and cur is not None:
            cur["t"] = list(map(int, w[1:7]))
        elif w[0] == "box" and cur is not None and "t" in cur:
            cur["box"] = list(map(int, w[1:5]))
            out.append(cur)
            cur = None
    return out


def mag_bbox(path):
    m = re.search(r"^string FIXED_BBOX (-?\d+) (-?\d+) (-?\d+) (-?\d+)", open(path).read(), re.M)
    return list(map(int, m.groups()))


def place(u, unit):
    a, b, c, d, e, f = u["t"]
    x0, y0, x1, y1 = u["box"]
    xs = [a * x + b * y + c for x, y in ((x0, y0), (x1, y1))]
    ys = [d * x + e * y + f for x, y in ((x0, y0), (x1, y1))]
    return [round(min(xs) * unit, 3), round(min(ys) * unit, 3), round((max(xs) - min(xs)) * unit, 3), round((max(ys) - min(ys)) * unit, 3)]


def pad_kind(cell):
    if "gpiov2" in cell:
        return "gpio"
    if "corner" in cell:
        return "corner"
    if "xres" in cell:
        return "reset"
    return "power"


def refresh(caravel, ttmux, ttsup, openframe):
    import yaml
    old = json.load(open(FIXTURE)) if os.path.exists(FIXTURE) else {}
    top = os.path.join(caravel, "mag/caravel_openframe.mag")
    io = os.path.join(caravel, "mag/chip_io_openframe.mag")
    txt = open(top).read()
    if not re.search(r"^magscale 1 2$", txt, re.M):
        sys.exit("refresh: caravel_openframe.mag is not at magscale 1 2")
    unit = 0.005                                             # sky130 Magic: lambda 0.01 µm, magscale 1 2
    bx = mag_bbox(top)
    wrap = next(u for u in mag_uses(top) if u["cell"] == "openframe_project_wrapper")
    lef = open(os.path.join(openframe, "lef/openframe_project_wrapper.lef")).read()
    lw, lh = map(float, re.search(r"SIZE ([\d.]+) BY ([\d.]+)", lef).groups())
    pads = []
    for u in mag_uses(io):
        if re.search(r"_pad$|xres4v2$", u["cell"]):
            x, y, w, h = place(u, unit)
            pads.append({"cell": u["cell"], "inst": u["inst"], "kind": pad_kind(u["cell"]), "x": x, "y": y, "w": w, "h": h})
    pads.sort(key=lambda p: (p["y"], p["x"], p["inst"]))
    cfg = yaml.safe_load(open(os.path.join(ttmux, "cfg/sky130.yaml")))
    p, t = cfg["pdk"], cfg["tt"]
    grid = {"die_w": p["die"]["width"], "die_h": p["die"]["height"], "margin": p["die"]["margin"],
            "site_w": p["site"]["width"], "site_h": p["site"]["height"],
            "vlayer": t["spine"]["vlayer"], "hlayer": t["spine"]["hlayer"],
            "vpitch": p["tracks"][t["spine"]["vlayer"]]["x"]["pitch"], "hpitch": p["tracks"][t["spine"]["hlayer"]]["y"]["pitch"],
            "pg_vdd_w": p["pwrgate"]["vdd"]["width"], "grid_x": t["grid"]["x"], "grid_y": t["grid"]["y"],
            "margin_x_sites": t["margin"]["x"], "margin_y_sites": t["margin"]["y"], "uio": t["uio"],
            "analog_mux": sorted(m for g in t.get("analog", []) for m in g["mux_id"]), "units": "nm (DEF database units, 1000 per µm)"}
    sizes = yaml.safe_load(open(os.path.join(ttsup, "tech/sky130A/tile_sizes.yaml")))
    fx = {
        "_about": "Chip-level facts for docs/tools/tt_floorplan.py. Regenerate with --refresh; never edit by hand, except 'designs' and 'package', which name their evidence.",
        "sources": {
            "chip": {"repo": "efabless/caravel", "commit": git_head(caravel), "files": ["mag/caravel_openframe.mag", "mag/chip_io_openframe.mag"],
                     "how": "FIXED_BBOX of caravel_openframe and the placement of openframe_project_wrapper in it; every *_pad and xres cell placed in chip_io_openframe; Magic units at magscale 1 2 are 0.005 µm"},
            "user_area": {"repo": "efabless/openframe_user_project", "commit": git_head(openframe), "files": ["lef/openframe_project_wrapper.lef"], "how": "SIZE"},
            "grid": {"repo": "TinyTapeout/tt-multiplexer", "commit": git_head(ttmux), "files": ["cfg/sky130.yaml", "py/tt/layout.py"],
                     "how": "config read here; global_layout() arithmetic re-done in tt_floorplan.py"},
            "tiles": {"repo": "TinyTapeout/tt-support-tools", "commit": git_head(ttsup), "files": ["tech/sky130A/tile_sizes.yaml", "shuttle.py"],
                      "how": "tile sizes; shuttle.py names openframe_project_wrapper as the sky130 top-level macro"},
        },
        "die_um": [round((bx[2] - bx[0]) * unit, 3), round((bx[3] - bx[1]) * unit, 3)],
        "user_area_um": {"x": round(wrap["t"][2] * unit, 3), "y": round(wrap["t"][5] * unit, 3), "w": lw, "h": lh},
        "pads": pads,
        "grid": grid,
        "tile_sizes_um": {k: [float(v.split()[2]), float(v.split()[3])] for k, v in sizes.items()},
        "package": old.get("package"),
        "designs": old.get("designs", {}),
    }
    json.dump(fx, open(FIXTURE, "w"), indent=1, sort_keys=True)
    open(FIXTURE, "a").write("\n")
    print(f"wrote {FIXTURE}: die {fx['die_um']} µm, {len(pads)} pads, user area {lw} x {lh} µm")


# ------------------------------------------------------------------ the tile grid (tt-multiplexer py/tt/layout.py, global_layout)
def lcm_align(v, pitch, site, ceil=False):
    a = math.lcm(pitch, site)
    if ceil:
        v += a - 1
    return int(v // a) * a


def grid_layout(g):
    """All lengths in nm, exactly as Layout.global_layout() computes them."""
    ax = lambda v, c=False: lcm_align(v, g["vpitch"], g["site_w"], c)
    ay = lambda v, c=False: lcm_align(v, g["hpitch"], g["site_h"], c)
    u = g["uio"]
    L = {}
    L["mx"] = g["margin_x_sites"] * g["site_w"]
    L["my"] = ay(g["margin_y_sites"] * g["site_h"], True)
    avail_w = g["die_w"] - ax(g["margin"]["left"], True) - g["margin"]["right"]
    vspine = (u["i"] + u["io"] + 9 + 1 + 2) + (u["o"] + u["io"] * 2 + 2)
    iopads = u["o"] + u["i"] + 3 * u["io"] + 2
    rsvd = ax(2 * g["vpitch"] * (vspine + iopads), True)
    tmp_w = ax((avail_w - rsvd) // g["grid_x"])
    L["block_w"] = tmp_w - L["mx"]
    L["block_pitch"] = tmp_w
    L["mux_w"] = tmp_w * (g["grid_x"] // 2) - L["mx"]
    L["branch_w"] = L["mux_w"]
    L["ctrl_w"] = rsvd
    L["top_w"] = rsvd + 2 * (L["mux_w"] + L["mx"])
    L["top_x"] = ax((g["die_w"] - L["top_w"]) // 2)
    avail_h = g["die_h"] - ay(g["margin"]["bottom"], True) - g["margin"]["top"]
    tmp_h = ay(avail_h // (g["grid_y"] // 2) // 5)          # blocks twice as high as the mux row: 2 + 1 + 2
    L["block_h"] = tmp_h * 2 - L["my"]
    L["mux_h"] = tmp_h - L["my"]
    L["branch_pitch"] = tmp_h * 5
    L["branch_h"] = L["branch_pitch"] - L["my"]
    L["ctrl_h"] = L["mux_h"] * 2 + L["my"]
    L["top_h"] = L["branch_pitch"] * (g["grid_y"] // 2) - L["my"]
    L["top_y"] = ay((g["die_h"] - L["top_h"]) // 2)
    L["pg_off"] = ax(g["pg_vdd_w"], True) + L["mx"]
    return L


def module_size(L, mw, mh):
    """Block(mw, mh, pg_vdd=True): Tiny Tapeout's sky130 user tiles are all power gated."""
    w = mw * L["block_w"] + (mw - 1) * L["mx"] - L["pg_off"]
    h = mh * L["block_h"] + (mh // 4) * (L["mux_h"] + L["my"]) + (mh - 1) * L["my"]
    return w, h


def orient(rect, W, H, o):
    x, y, w, h = rect
    if o in ("FN", "S"):
        x = W - x - w
    if o in ("FS", "S"):
        y = H - y - h
    return x, y, w, h


def grid_elements(g, L):
    """Rectangles in user-area coordinates (nm): tiles, power switches, muxes, the controller.
    Mirrors elements.py: Top places branches by quadrant, Branch places a mux and 16 tiles."""
    tiles, switches, muxes, gaps = [], [], [], []
    my = g["grid_y"] // 4
    for mux_id in range(g["grid_y"]):
        q = mux_id & 3
        bx = 0 if q in (0, 1) else L["top_w"] - L["branch_w"]
        by = (my - (mux_id >> 2) - 1) * L["branch_pitch"] if q in (0, 2) else (my + (mux_id >> 2)) * L["branch_pitch"]
        o = {0: "N", 1: "FS", 2: "FN", 3: "S"}[q]
        if mux_id in g["analog_mux"]:
            gaps.append({"mux": mux_id, "r": [bx + L["top_x"], by + L["top_y"], L["branch_w"], L["branch_h"]]})
            continue
        mx, myy, mw, mh = orient((0, L["block_h"] + L["my"], L["mux_w"], L["mux_h"]), L["branch_w"], L["branch_h"], o)
        muxes.append({"mux": mux_id, "r": [bx + mx + L["top_x"], by + myy + L["top_y"], mw, mh]})
        for blk in range(g["grid_x"]):
            col = (g["grid_x"] // 2) - (blk >> 1) - 1
            x0 = col * L["block_pitch"]
            y0 = 0 if blk & 1 else L["branch_h"] - L["block_h"]
            sw = orient((x0, y0, g["pg_vdd_w"], L["block_h"]), L["branch_w"], L["branch_h"], o)
            tl = orient((x0 + L["pg_off"], y0, L["block_w"] - L["pg_off"], L["block_h"]), L["branch_w"], L["branch_h"], o)
            tiles.append({"mux": mux_id, "blk": blk, "r": [bx + tl[0] + L["top_x"], by + tl[1] + L["top_y"], tl[2], tl[3]]})
            switches.append([bx + sw[0] + L["top_x"], by + sw[1] + L["top_y"], sw[2], sw[3]])
    ctrl = [L["branch_w"] + L["mx"] + L["top_x"], my * L["branch_pitch"] - (L["mux_h"] + L["my"]) + L["top_y"], L["ctrl_w"], L["ctrl_h"]]
    return tiles, switches, muxes, gaps, ctrl


# ------------------------------------------------------------------ checks
def read_design():
    txt = open("info.yaml").read()
    top = re.search(r'^\s*top_module:\s*"([^"]*)"', txt, re.M).group(1)
    tiles = re.search(r'^\s*tiles:\s*"([^"]*)"', txt, re.M).group(1)
    return top, tiles


def verify(fx, top, tiles):
    """Every cross-check between the sources. Returns a list of problems (empty = all agree)."""
    bad = []
    g = fx["grid"]
    L = grid_layout(g)
    for key, (w, h) in fx["tile_sizes_um"].items():
        mw, mh = map(int, key.split("x"))
        cw, ch = module_size(L, mw, mh)
        if (round(cw / 1000, 2), round(ch / 1000, 2)) != (w, h):
            bad.append(f"tile grid: {key} computes to {cw / 1000:.2f} x {ch / 1000:.2f} µm, tile_sizes.yaml says {w} x {h}")
    ua = fx["user_area_um"]
    if (round(ua["w"] * 1000), round(ua["h"] * 1000)) != (g["die_w"], g["die_h"]):
        bad.append(f"user area: wrapper LEF {ua['w']} x {ua['h']} µm is not the tt-multiplexer die {g['die_w']} x {g['die_h']} nm")
    dw, dh = fx["die_um"]
    if abs(ua["x"] * 2 + ua["w"] - dw) > 0.001 or abs(ua["y"] * 2 + ua["h"] - dh) > 0.001:
        bad.append(f"user area: not centred in the {dw} x {dh} µm die (at {ua['x']}, {ua['y']})")
    for p in fx["pads"]:
        if p["x"] < 0 or p["y"] < 0 or p["x"] + p["w"] > dw + 1e-6 or p["y"] + p["h"] > dh + 1e-6:
            bad.append(f"pads: {p['inst']} lies outside the die")
        elif not (p["x"] + p["w"] <= ua["x"] + 1e-6 or p["x"] >= ua["x"] + ua["w"] - 1e-6 or p["y"] + p["h"] <= ua["y"] + 1e-6 or p["y"] >= ua["y"] + ua["h"] - 1e-6):
            bad.append(f"pads: {p['inst']} overlaps the user area")
    n_gpio = sum(p["kind"] == "gpio" for p in fx["pads"])
    if n_gpio != 44:
        bad.append(f"pads: {n_gpio} GPIO pads, the openframe padframe has 44")
    tl, sw, mx, gaps, ctrl = grid_elements(g, L)
    rects = [t["r"] for t in tl] + [m["r"] for m in mx] + [ctrl]
    for r in rects:
        if r[0] < 0 or r[1] < 0 or r[0] + r[2] > g["die_w"] or r[1] + r[3] > g["die_h"]:
            bad.append(f"tile grid: a rectangle at {r} leaves the user area")
            break
    # no two tiles overlap (sorted sweep is enough: they form rows)
    seen = {}
    for t in tl:
        k = (t["r"][0], t["r"][1])
        if k in seen:
            bad.append(f"tile grid: mux {t['mux']} block {t['blk']} lands on mux {seen[k][0]} block {seen[k][1]}")
            break
        seen[k] = (t["mux"], t["blk"])
    d = fx["designs"].get(top)
    if d is None:
        bad.append(f"designs: no measured die for {top}")
    else:
        if tiles not in fx["tile_sizes_um"]:
            bad.append(f"designs: info.yaml tiles {tiles} is not in tile_sizes.yaml")
        elif d["die_um"] != fx["tile_sizes_um"][tiles]:
            bad.append(f"designs: the run measured {d['die_um']} µm but {tiles} is {fx['tile_sizes_um'][tiles]} µm")
    return bad


# ------------------------------------------------------------------ drawing
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")


def f2(v):
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v - round(v, 2)) < 1e-9 else f"{v:.3f}"


def mm(um, d=3):
    return f"{um / 1000:.{d}f} mm"


def um(v, d=2):
    return f"{v:,.{d}f} µm"


FP_CSS = """
.fp-tabs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.fp-tabs[hidden]{display:none}
.fp-tabs button{font:600 14px var(--sans);padding:6px 12px;border:1px solid var(--line-2);border-radius:var(--radius,4px);background:var(--surface);color:var(--ink);cursor:pointer}
.fp-tabs button[aria-selected=true]{background:var(--button);color:var(--button-ink);border-color:var(--button)}
.fp-tabs button:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.fp-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:12px}
.fp-on .fp-steps{display:block}
.fp-step{margin:0;overflow-x:auto}
.fp-step svg{display:block;width:100%;min-width:520px;height:auto;max-width:720px}
@media (prefers-reduced-motion:no-preference){.fp-on .fp-step:not([hidden]){animation:fp-in .25s ease-out}}
@keyframes fp-in{from{opacity:0}to{opacity:1}}
.fp-panel{fill:var(--surface);stroke:var(--line-2)}
.fp-h{fill:var(--ink);font:700 19px var(--sans)}
.fp-s{fill:var(--muted);font:13px var(--sans)}
.fp-t{fill:var(--ink-2);font:13px var(--sans)}
.fp-n{fill:var(--ink);font:600 13px var(--mono)}
.fp-nl{fill:var(--ink);font:600 15px var(--mono)}
.fp-dim{stroke:var(--ink-2);stroke-width:1;fill:none}
.fp-ext{stroke:var(--muted);stroke-width:.6;stroke-dasharray:3 3;fill:none}
.fp-pkg{fill:#2a2e31;stroke:var(--line-2);stroke-width:1}
.fp-pin{fill:#a9aca6}
.fp-ep{fill:none;stroke:#a9aca6;stroke-width:1;stroke-dasharray:5 4}
.fp-die{fill:var(--surface-2);stroke:var(--muted);stroke-width:1}
.fp-die-on-pkg{fill:#d6d8d1;stroke:#ffb000;stroke-width:1.5}
.fp-on-die{fill:#121416;font:600 13px var(--mono)}
.fp-on-die-s{fill:#383d42;font:13px var(--sans)}
.fp-ua{fill:var(--surface);stroke:var(--muted);stroke-width:.8}
.fp-gpio{fill:var(--trace)}
.fp-power{fill:var(--cat-interface)}
.fp-corner{fill:var(--muted)}
.fp-reset{fill:var(--cat-control)}
.fp-tile{fill:var(--line);stroke:var(--line-2);stroke-width:.5}
.fp-sw{fill:var(--cat-memory);opacity:.7}
.fp-mux{fill:var(--cat-control);opacity:.35}
.fp-ctrl{fill:var(--cat-control);opacity:.7}
.fp-gap{fill:none;stroke:var(--muted);stroke-width:.6;stroke-dasharray:2 3}
.fp-me{fill:var(--accent);stroke:var(--accent);stroke-width:1}
.fp-me-o{fill:none;stroke:var(--accent);stroke-width:2.5}
.fp-me-l{fill:var(--accent);font:700 13px var(--sans)}
.fp-cut{fill:none;stroke:var(--accent);stroke-width:1.5;stroke-dasharray:6 4}
.fp-tdiv{stroke:var(--surface);stroke-width:1;stroke-dasharray:4 3}
.fp-key{font:12px var(--sans);fill:var(--ink-2)}
"""


def token_css():
    css = open(CSS_FILE).read()
    blocks = re.findall(r"^:root \{.*?^\}|^@media \(prefers-color-scheme: dark\) \{.*?^\}|^:root\[data-theme=\"dark\"\] \{.*?^\}", css, re.S | re.M)
    return re.sub(r"\s+", " ", "\n".join(blocks))


class Pen:
    """Collects SVG elements; dims draw a dimension line with ticks and its label."""
    def __init__(self):
        self.o = []

    def rect(self, x, y, w, h, cls, extra=""):
        self.o.append(f"<rect class='{cls}' x='{x:.2f}' y='{y:.2f}' width='{max(w, 0.3):.2f}' height='{max(h, 0.3):.2f}'{extra}/>")

    def text(self, x, y, s, cls, anchor="start", extra=""):
        self.o.append(f"<text class='{cls}' x='{x:.1f}' y='{y:.1f}' text-anchor='{anchor}'{extra}>{esc(s)}</text>")

    def line(self, x1, y1, x2, y2, cls):
        self.o.append(f"<path class='{cls}' d='M{x1:.2f} {y1:.2f}L{x2:.2f} {y2:.2f}'/>")

    def hdim(self, x1, x2, y, label, sub=None, above=True, ext_from=None):
        """Horizontal dimension from x1 to x2 at height y; ext_from: y the extension lines start at."""
        if ext_from is not None:
            self.line(x1, ext_from, x1, y, "fp-ext")
            self.line(x2, ext_from, x2, y, "fp-ext")
        self.line(x1, y, x2, y, "fp-dim")
        for x in (x1, x2):
            self.line(x - 3.5, y + 3.5, x + 3.5, y - 3.5, "fp-dim")
        ty = y - 6 if above else y + 16
        self.text((x1 + x2) / 2, ty, label, "fp-n", "middle")
        if sub:
            self.text((x1 + x2) / 2, ty + (-15 if above else 15), sub, "fp-s", "middle")

    def vdim(self, x, y1, y2, label, sub=None, right=True, ext_from=None):
        if ext_from is not None:
            self.line(ext_from, y1, x, y1, "fp-ext")
            self.line(ext_from, y2, x, y2, "fp-ext")
        self.line(x, y1, x, y2, "fp-dim")
        for y in (y1, y2):
            self.line(x - 3.5, y + 3.5, x + 3.5, y - 3.5, "fp-dim")
        tx = x + 8 if right else x - 8
        cy = (y1 + y2) / 2
        self.text(tx, cy + 4, label, "fp-n", "start" if right else "end")
        if sub:
            self.text(tx, cy + 19, sub, "fp-s", "start" if right else "end")

    def svg(self):
        return "".join(self.o)


PW, PH = 580, 620          # one panel


def wrap(text, n):
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + ([cur] if cur else [])


def para(p, x, y, text, cls="fp-s", n=80, lh=17):
    for ln in wrap(text, n):
        p.text(x, y, ln, cls)
        y += lh
    return y


def panel_frame(p, n, title, scale_note):
    p.rect(0.5, 0.5, PW - 1, PH - 1, "fp-panel", " rx='8'")
    p.text(22, 34, f"{n}  {title}", "fp-h")
    p.text(22, 54, scale_note, "fp-s")


def panel_package(fx):
    p = Pen()
    pk = fx["package"]
    body = pk["body_mm"] * 1000
    s = 340 / body                                           # px per µm
    panel_frame(p, 1, "The package", f"QFN-64 · to scale · 1 mm = {1000 * s:.1f} px")
    ox, oy = 100, 120
    B = body * s
    pitch = pk["pitch_mm"] * 1000 * s
    n = pk["pins"] // 4
    span = (n - 1) * pitch
    for i in range(n):
        c = (B - span) / 2 + i * pitch
        L, W = 0.4 * 1000 * s, 0.25 * 1000 * s
        p.rect(ox + c - W / 2, oy - L, W, L, "fp-pin")
        p.rect(ox + c - W / 2, oy + B, W, L, "fp-pin")
        p.rect(ox - L, oy + c - W / 2, L, W, "fp-pin")
        p.rect(ox + B, oy + c - W / 2, L, W, "fp-pin")
    p.rect(ox, oy, B, B, "fp-pkg", " rx='4'")
    ep = pk["exposed_pad_mm"] * 1000 * s
    p.rect(ox + (B - ep) / 2, oy + (B - ep) / 2, ep, ep, "fp-ep")
    dw, dh = fx["die_um"]
    p.rect(ox + (B - dw * s) / 2, oy + (B - dh * s) / 2, dw * s, dh * s, "fp-die-on-pkg")
    p.text(ox + B / 2, oy + B / 2 - 6, "die", "fp-on-die-s", "middle")
    p.text(ox + B / 2, oy + B / 2 + 12, f"{dw / 1000:.3f} × {dh / 1000:.3f} mm", "fp-on-die", "middle")
    p.hdim(ox, ox + B, oy - 30, f"{pk['body_mm']:.2f} mm", ext_from=oy - 16)
    p.vdim(ox + B + 30, oy, oy + B, f"{pk['body_mm']:.2f} mm", ext_from=ox + B + 16)
    y = oy + B + 46
    y = para(p, 22, y, f"{pk['pins']} pins at a {pk['pitch_mm']} mm pitch. Dashed: the {pk['exposed_pad_mm']} mm exposed pad underneath.", "fp-t", 80, 19)
    y = para(p, 22, y + 2, "Where the die sits inside the package is not published, so it is drawn centred.", "fp-s")
    para(p, 22, PH - 40, f"Source: {pk['source']}.", "fp-s", 80, 16)
    return p.svg()


def panel_die(fx, L, els, me, cut):
    p = Pen()
    dw, dh = fx["die_um"]
    s = 360 / dh
    panel_frame(p, 2, "The die: every project's tiles", f"to scale · 1 mm = {1000 * s:.1f} px")
    ox, oy = 150, 98
    Y = lambda y: oy + (dh - y) * s                          # layout y grows up, SVG y grows down
    p.rect(ox, oy, dw * s, dh * s, "fp-die")
    for pd in fx["pads"]:
        p.rect(ox + pd["x"] * s, Y(pd["y"] + pd["h"]), pd["w"] * s, pd["h"] * s, "fp-" + pd["kind"])
    ua = fx["user_area_um"]
    p.rect(ox + ua["x"] * s, Y(ua["y"] + ua["h"]), ua["w"] * s, ua["h"] * s, "fp-ua")
    tiles, switches, muxes, gaps, ctrl = els
    k = 1 / 1000
    U = lambda r: (ox + (ua["x"] + r[0] * k) * s, Y(ua["y"] + (r[1] + r[3]) * k), r[2] * k * s, r[3] * k * s)
    for t in tiles:
        p.rect(*U(t["r"]), "fp-tile")
    for m in muxes:
        p.rect(*U(m["r"]), "fp-mux")
    for gp in gaps:
        p.rect(*U(gp["r"]), "fp-gap")
    p.rect(*U(ctrl), "fp-ctrl")
    p.rect(*U(me), "fp-me")
    cx, cy, cw, ch = U(cut)
    p.rect(cx, cy, cw, ch, "fp-cut")
    p.hdim(ox, ox + dw * s, oy - 22, f"{dw / 1000:.3f} mm", ext_from=oy - 8)
    p.vdim(ox - 22, oy, oy + dh * s, f"{dh / 1000:.3f} mm", "die", right=False, ext_from=ox - 8)
    p.vdim(ox + dw * s + 22, Y(ua["y"] + ua["h"]), Y(ua["y"]), f"{ua['h'] / 1000:.3f} mm", "user area", ext_from=ox + (ua["x"] + ua["w"]) * s)
    p.text(cx + cw + 6, cy + ch / 2 + 4, "panel 3", "fp-me-l")
    n_t = len(tiles)
    gpio = sum(pd["kind"] == "gpio" for pd in fx["pads"])
    others = len(fx["pads"]) - gpio
    lx, ly = 22, oy + dh * s + 30
    for i, (cls, lab) in enumerate((("fp-gpio", f"{gpio} GPIO pads"), ("fp-power", f"{others} power, ground, corner and reset pads"),
                                    ("fp-tile", f"{n_t} tile slots"), ("fp-mux", "multiplexer rows and controller"),
                                    ("fp-me", "this design, in an example slot"), ("fp-gap", "rows kept for analog"))):
        x = lx + (i % 2) * 250
        y = ly + (i // 2) * 19
        p.rect(x, y - 10, 12, 12, cls)
        p.text(x + 18, y, lab, "fp-key")
    p.text(22, ly + 64, f"User area {ua['w'] / 1000:.3f} × {ua['h'] / 1000:.3f} mm, {ua['x']:.3f} µm in from each die edge.", "fp-s")
    para(p, 22, PH - 40, "Sources: efabless/caravel caravel_openframe.mag and chip_io_openframe.mag; TinyTapeout/tt-multiplexer cfg/sky130.yaml.", "fp-s", 80, 16)
    return p.svg()


def panel_grid(fx, L, els, me, cut, mw, mh):
    p = Pen()
    k = 1 / 1000
    s = 400 / (cut[2] * k)
    panel_frame(p, 3, "The tile grid around it", f"to scale · 100 µm = {100 * s:.1f} px")
    ox, oy = 30, 128
    WW, HH = cut[2] * k * s, cut[3] * k * s
    y0 = cut[1] + cut[3]
    X = lambda x: ox + (x - cut[0]) * k * s
    Y = lambda y: oy + (y0 - y) * k * s
    inside = lambda r: r[0] + r[2] > cut[0] and r[0] < cut[0] + cut[2] and r[1] + r[3] > cut[1] and r[1] < cut[1] + cut[3]
    clip = "fpclip"
    p.o.append(f"<clipPath id='{clip}'><rect x='{ox}' y='{oy}' width='{WW:.2f}' height='{HH:.2f}'/></clipPath><g clip-path='url(#{clip})'>")
    tiles, switches, muxes, gaps, ctrl = els
    R = lambda r: (X(r[0]), Y(r[1] + r[3]), r[2] * k * s, r[3] * k * s)
    for t in tiles:
        if inside(t["r"]):
            p.rect(*R(t["r"]), "fp-tile")
    for r in switches:
        if inside(r):
            p.rect(*R(r), "fp-sw")
    for m in muxes:
        if inside(m["r"]):
            p.rect(*R(m["r"]), "fp-mux")
    p.rect(*R(me), "fp-me")
    p.o.append("</g>")
    p.rect(ox, oy, WW, HH, "fp-cut")
    bx, by, bw_, bh_ = R(me)
    p.text(bx + bw_ / 2, by + bh_ / 2 + 5, "this design", "fp-t", "middle", " style='fill:var(--accent-ink);font-weight:700'")
    bw, bh, pit = L["block_w"] - L["pg_off"], L["block_h"], L["block_pitch"]
    # a plain tile in the top row, the first whole one from the left
    ref = min((t["r"] for t in tiles if inside(t["r"]) and t["r"][1] > me[1] + me[3] and t["r"][0] >= cut[0] + pit), key=lambda r: (-r[1], r[0]))
    tx, ty = X(ref[0]), Y(ref[1] + ref[3])
    p.hdim(tx, tx + bw * k * s, oy - 12, f"{bw / 1000:.2f} µm", ext_from=ty)
    swx = X(ref[0] - L["pg_off"])
    p.hdim(swx, swx + pit * k * s, oy - 46, f"pitch {pit / 1000:.2f} µm", ext_from=oy - 12)
    p.text(tx + bw * k * s / 2, ty + bh * k * s / 2 + 5, "one tile", "fp-t", "middle")
    rx = ox + WW + 14
    p.vdim(rx, ty, ty + bh * k * s, f"{bh / 1000:.2f} µm", "a tile")
    mrow = max((m["r"] for m in muxes if inside(m["r"]) and m["r"][1] + m["r"][3] <= ref[1] + 1), key=lambda r: r[1])
    _, my_, _, mh_ = R(mrow)
    p.vdim(rx, my_, my_ + mh_, f"{mrow[3] / 1000:.2f} µm", "multiplexer")
    p.vdim(rx, by, by + bh_, f"{me[3] / 1000:.2f} µm", "this design")
    y = para(p, 22, oy + HH + 30, f"Green: each tile's power switch, {fx['grid']['pg_vdd_w'] / 1000:.2f} µm wide; with the {L['mx'] / 1000:.2f} µm gap it takes "
             f"{L['pg_off'] / 1000:.2f} µm of the {pit / 1000:.2f} µm pitch. Between tile rows run the multiplexer rows. Tile rows that meet are {L['my'] / 1000:.2f} µm apart, "
             f"so a {mw}x{mh} block spans {mw} column{'s' if mw > 1 else ''} and that gap.", "fp-t", 80, 19)
    para(p, 22, PH - 40, "Computed from tt-multiplexer cfg/sky130.yaml with its own layout arithmetic, and checked against tt-support-tools tile_sizes.yaml by make docs.", "fp-s", 80, 16)
    return p.svg()


def panel_design(fx, L, me, top, tiles_s, dsg):
    p = Pen()
    k = 1 / 1000
    w_um, h_um = dsg["die_um"]
    s = min(360 / w_um, 270 / h_um)
    panel_frame(p, 4, "This design", f"{top} · {tiles_s} tiles · to scale · 100 µm = {100 * s:.1f} px")
    W, H = w_um * s, h_um * s
    ox, oy = (PW - W) / 2 - 40, 140 + (270 - H) / 2
    p.rect(ox, oy, W, H, "fp-me")
    mw, mh = map(int, tiles_s.split("x"))
    # where the tile boundaries fall inside the block (it is one macro)
    for i in range(1, mw):
        x = ox + (i * L["block_pitch"] - L["pg_off"] - L["mx"] / 2) * k * s
        p.line(x, oy, x, oy + H, "fp-tdiv")
    for j in range(1, mh):
        y = oy + H - (j * (L["block_h"] + L["my"]) - L["my"] / 2) * k * s
        p.line(ox, y, ox + W, y, "fp-tdiv")
    p.text(ox + W / 2, oy + H / 2 - 4, f"{w_um * h_um / 1e6:.4f} mm²", "fp-nl", "middle", " style='fill:var(--accent-ink)'")
    p.text(ox + W / 2, oy + H / 2 + 15, f"{w_um * h_um:,.0f} µm²", "fp-n", "middle", " style='fill:var(--accent-ink)'")
    p.hdim(ox, ox + W, oy - 26, f"{w_um:.2f} µm", f"{w_um / 1000:.4f} mm", ext_from=oy - 6)
    p.vdim(ox + W + 26, oy, oy + H, f"{h_um:.2f} µm", f"{h_um / 1000:.4f} mm", ext_from=ox + W + 6)
    ua = fx["user_area_um"]
    dw, dh = fx["die_um"]
    y = para(p, 22, 470, f"{100 * w_um * h_um / (ua['w'] * ua['h']):.2f}% of the {ua['w'] * ua['h'] / 1e6:.2f} mm² user area, "
             f"{100 * w_um * h_um / (dw * dh):.2f}% of the {dw * dh / 1e6:.2f} mm² die.", "fp-t", 80, 19)
    y = para(p, 22, y + 2, "Dashed: where the tile boundaries fall. The block is one macro, so its cells cross them.", "fp-s")
    para(p, 22, PH - 40, f"Measured: {dsg['evidence']}.", "fp-s", 80, 16)
    return p.svg()


def example_slot(g, L, els, mw, mh):
    """One slot a mw x mh block could take: lower-left quadrant, second branch from the
    centre, columns 4.. from the die edge. Tiny Tapeout's placer decides the real one."""
    tiles = els[0]
    mux = 4                                                  # mux_id & 3 == 0: lower left, orientation N
    col0 = 3
    blk = (g["grid_x"] // 2 - col0 - 1) << 1 | 1             # odd: the bottom row of the branch
    t = next(t for t in tiles if t["mux"] == mux and t["blk"] == blk)
    w, h = module_size(L, mw, mh)
    x, y = t["r"][0], t["r"][1] + L["block_h"] - h          # grows down into the next branch's top row
    me = [x, y, w, h]
    pit = L["block_pitch"]
    cut = [x - pit - L["pg_off"], y - L["block_h"] - L["mux_h"] - 2 * L["my"], 0, 0]
    cut[2] = max(4, mw + 2) * pit
    cut[3] = h + 2 * (L["block_h"] + L["mux_h"] + 2 * L["my"])
    return me, cut


def render(fx, top, tiles_s):
    g = fx["grid"]
    L = grid_layout(g)
    els = grid_elements(g, L)
    mw, mh = map(int, tiles_s.split("x"))
    me, cut = example_slot(g, L, els, mw, mh)
    dsg = fx["designs"][top]
    panels = [panel_package(fx), panel_die(fx, L, els, me, cut), panel_grid(fx, L, els, me, cut, mw, mh),
              panel_design(fx, L, me, top, tiles_s, dsg)]
    titles = ["The package", "The die", "The tile grid", "This design"]
    alts = [f"The QFN-64 package, {fx['package']['body_mm']:.2f} mm square, with the {fx['die_um'][0] / 1000:.3f} by {fx['die_um'][1] / 1000:.3f} mm die drawn inside it.",
            f"The {fx['die_um'][0] / 1000:.3f} by {fx['die_um'][1] / 1000:.3f} mm die: the pad ring, the user area and {len(els[0])} tile slots, with this design in an example slot.",
            f"Close-up of the tile grid: tiles {(L['block_w'] - L['pg_off']) / 1000:.2f} by {L['block_h'] / 1000:.2f} µm at a {L['block_pitch'] / 1000:.2f} µm pitch, multiplexer rows between them.",
            f"This design's {tiles_s} block: {dsg['die_um'][0]:.2f} by {dsg['die_um'][1]:.2f} µm."]
    return panels, titles, alts


def light_tokens():
    css = open(CSS_FILE).read()
    root = re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", root))


def resolve(css, tok):
    """var(--x) and var(--x,fallback) written out with the light theme's values, for renderers
    without CSS custom properties (typst's SVG reader, for the PDF datasheet)."""
    css = re.sub(r"var\(--([\w-]+)(?:,([^)]*))?\)", lambda m: tok.get(m.group(1), m.group(2) or "").split("/*")[0].strip(), css)
    return css


def file_svg(panels, alts, title, printable=False):
    gap = 20
    W, H = 2 * PW + gap, 2 * PH + gap + 60
    body = [f"<rect width='{W}' height='{H}' style='fill:var(--bg)'/>",
            f"<text class='fp-h' x='0' y='30' style='font-size:24px'>{esc(title)}</text>",
            "<text class='fp-s' x='0' y='50'>Every length to scale within its panel and measured from the sources named; the slot on the die is an example.</text>"]
    for i, svg in enumerate(panels):
        x, y = (i % 2) * (PW + gap), 60 + (i // 2) * (PH + gap)
        body.append(f"<g transform='translate({x} {y})' role='img' aria-label='{esc(alts[i])}'>{svg}</g>")
    style = token_css() + re.sub(r"\s+", " ", FP_CSS)
    if printable:
        tok = light_tokens()
        css = "\n".join(ln for ln in FP_CSS.splitlines() if ln.startswith(".fp-") and not ln.startswith(".fp-tabs") and not ln.startswith(".fp-step") and not ln.startswith(".fp-on"))
        style = resolve(re.sub(r"\s+", " ", css), tok)
        body = [resolve(b, tok) for b in body]
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='{W}' height='{H}' role='img' aria-labelledby='fp-title'>"
            f"<title id='fp-title'>{esc(title)}</title><style>{style}</style>{''.join(body)}</svg>\n")


def site_fragment(panels, titles, alts):
    style = re.sub(r"\s+", " ", FP_CSS)
    tabs = "".join(f"<button type=button role=tab id=fp-tab-{i} aria-controls=fp-panel-{i} aria-selected={'true' if i == 0 else 'false'} tabindex={0 if i == 0 else -1}>{i + 1} {esc(t)}</button>"
                   for i, t in enumerate(titles))
    figs = "".join(f"<figure class=fp-step id=fp-panel-{i} role=tabpanel aria-labelledby=fp-tab-{i}>"
                   f"<svg viewBox='0 0 {PW} {PH}' role=img aria-label='{esc(alts[i])}'>{svg}</svg></figure>"
                   for i, svg in enumerate(panels))
    return (f"<div class=fp id=fp><style>{style}</style>"
            f"<div class=fp-tabs role=tablist aria-label='Zoom from the package to this design' hidden>{tabs}</div>"
            f"<div class=fp-steps>{figs}</div></div>\n")


# ------------------------------------------------------------------ main
MUTANTS = [
    ("a tile grid with one column more", lambda f: f["grid"].__setitem__("grid_x", f["grid"]["grid_x"] + 4)),
    ("a die margin 100 µm wider", lambda f: f["grid"]["margin"].__setitem__("left", f["grid"]["margin"]["left"] + 100000)),
    ("a measured die from the wrong tile count", lambda f: [d.__setitem__("die_um", [d["die_um"][0] + 173.88, d["die_um"][1]]) for d in f["designs"].values()]),
    ("a wrapper not centred on the die", lambda f: f["user_area_um"].__setitem__("x", f["user_area_um"]["x"] + 10)),
    ("a pad moved into the user area", lambda f: next(p for p in f["pads"] if p["x"] == 0 and p["kind"] == "gpio").__setitem__("x", 400.0)),
    ("a GPIO pad lost", lambda f: f["pads"].pop(next(i for i, p in enumerate(f["pads"]) if p["kind"] == "gpio"))),
    ("a tile size edited in tile_sizes", lambda f: f["tile_sizes_um"].__setitem__("1x1", [161.0, 111.0])),
    ("a user area of the wrong size", lambda f: f["user_area_um"].__setitem__("w", f["user_area_um"]["w"] + 1)),
]


def main():
    a = sys.argv[1:]
    if a[:1] == ["--refresh"]:
        if len(a) != 5:
            sys.exit(__doc__)
        refresh(*a[1:])
        return
    fx = json.load(open(FIXTURE))
    top, tiles_s = read_design()
    if a[:1] == ["--mutants"]:
        caught = 0
        for name, breakit in MUTANTS:
            f = json.loads(json.dumps(fx))
            breakit(f)
            bad = verify(f, top, tiles_s)
            print(f"  {'caught' if bad else 'MISSED'}: {name}" + (f" ({bad[0]})" if bad else ""))
            caught += bool(bad)
        print(f"tt floorplan: --check caught {caught} of {len(MUTANTS)} broken copies")
        sys.exit(0 if caught == len(MUTANTS) else 1)
    bad = verify(fx, top, tiles_s)
    if bad:
        print("tt_floorplan.py: the sources disagree:\n  " + "\n  ".join(bad))
        sys.exit(1)
    panels, titles, alts = render(fx, top, tiles_s)
    name = top.replace("tt_um_normansrule_", "").replace("_", "-")
    title = f"Where {'Tiqora-Serial' if name.endswith('serial') else 'Tiqora'} sits on the Tiny Tapeout chip, in millimetres"
    out = {OUT_SVG: file_svg(panels, alts, title), OUT_PRINT: file_svg(panels, alts, title, printable=True),
           OUT_SITE: site_fragment(panels, titles, alts)}
    L = grid_layout(fx["grid"])
    if a[:1] == ["--facts"]:
        dw, dh = fx["die_um"]
        side = {}
        for pd in fx["pads"]:
            if pd["kind"] == "corner":
                continue
            cx, cy = pd["x"] + pd["w"] / 2, pd["y"] + pd["h"] / 2
            k = "bottom" if pd["y"] == 0 else "top" if pd["y"] + pd["h"] >= dh - 0.01 else "left" if pd["x"] == 0 else "right"
            side.setdefault(k, []).append(cx if k in ("bottom", "top") else cy)
        for k in ("bottom", "right", "top", "left"):
            v = sorted(side[k])
            d = [b - a for a, b in zip(v, v[1:])]
            print(f"pads, {k} edge: {len(v)}, centre to centre {min(d):.3f} to {max(d):.3f} µm")
        ua = fx["user_area_um"]
        print(f"die {dw} x {dh} µm; user area {ua['w']} x {ua['h']} µm at ({ua['x']}, {ua['y']}); "
              f"tiles {(L['block_w'] - L['pg_off']) / 1000:.2f} x {L['block_h'] / 1000:.2f} µm, pitch {L['block_pitch'] / 1000:.2f} x {L['branch_pitch'] / 1000:.2f} µm per branch, "
              f"multiplexer rows {L['mux_h'] / 1000:.2f} µm, {len(grid_elements(fx['grid'], L)[0])} tile slots")
        return
    if a[:1] == ["--check"]:
        stale = [p for p, t in out.items() if not os.path.exists(p) or open(p).read() != t]
        if stale:
            print("tt_floorplan: out of date, run python3 docs/tools/tt_floorplan.py: " + ", ".join(stale))
            sys.exit(1)
        print(f"tt floorplan: {len(fx['tile_sizes_um'])} tile sizes reproduced from the tile grid, "
              f"{len(fx['pads'])} pads inside the {fx['die_um'][0]} x {fx['die_um'][1]} µm die, {tiles_s} = measured die; drawings up to date")
        return
    for p, t in out.items():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(t)
        print(f"wrote {p} ({len(t) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
