#!/usr/bin/env python3
"""routed_map.py — the real routed layout, for the explorer (docs/site/data/routed.json).

    python3 docs/tools/routed_map.py <LibreLane run dir> <sky130_fd_sc_hd.lef> [--pdk "label"]   write routed.json
    python3 docs/tools/routed_map.py --check                                   fail if routed.json is malformed
    python3 docs/tools/routed_map.py --mutants                                 show that --check catches eight broken copies

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.

Where die_map.py packs the synthesized cells into rows as an illustration, this
reads the DEF a LibreLane run wrote after detailed routing and fill insertion,
so every position here is where the placer put the cell and every wire is a
segment the router drew. It keeps:

  cells   every placed instance: x, y, width and a class (flip-flop, logic,
          buffer, clock tree, physical-only: taps, fill, decap, diodes)
  wires   every routed segment of every signal net, by metal layer (li1..met4)
  vias    the via positions between metal layers
  power   the power grid (special nets), drawn as the grid it is
  clock   the clock tree, net by net, with each net's depth below the clk pin
          and the flip-flops each leaf net reaches, so the page can light it
          up from the pin outward in the order a clock edge travels
  pins    the I/O pins on the die edge

Coordinates are in units of 10 nm, stored as base64 of little-endian uint16
arrays (a 3x2 Tiny Tapeout die is 50,876 x 22,576 units, which fits). The run
it came from (LibreLane version, PDK, design) is recorded in "source"; the
output is deterministic for a given DEF.
"""
import base64, glob, json, os, re, struct, sys

OUT = "docs/site/data/routed.json"
U = 10                                  # one unit = 10 nm; DEF distances are in nm (UNITS 1000 per µm)
LAYERS = ["li1", "met1", "met2", "met3", "met4", "met5"]
WIDTH_NM = {"li1": 170, "met1": 140, "met2": 140, "met3": 300, "met4": 300, "met5": 1600}   # sky130 minimum widths


def b64(nums):
    for n in nums:
        if not 0 <= n < 65536:
            sys.exit(f"routed_map.py: coordinate {n} does not fit 16 bits")
    return base64.b64encode(struct.pack(f"<{len(nums)}H", *nums)).decode()


def unb64(s):
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 2}H", raw))


def cell_class(cell, name):
    c = cell.replace("sky130_fd_sc_hd__", "")
    c = re.sub(r"_\d+$", "", c)
    if c.startswith(("tap", "fill", "decap", "diode")):
        return 4                                            # physical only
    if name.startswith(("clkbuf_", "clkload", "clkinv_")) or c.startswith("clkbuf"):
        return 3                                            # clock tree
    if c.startswith(("df", "edf", "sdf", "dl")) and not c.startswith("dlygate") and not c.startswith("dlymetal"):
        return 0                                            # flip-flops and latches
    if c.startswith(("buf", "dlygate", "dlymetal", "clkdly")):
        return 2                                            # buffers: timing, hold and fanout repair
    return 1                                                # logic


def lef_sizes(lef):
    sizes, cur = {}, None
    for ln in open(lef):
        m = re.match(r"\s*MACRO\s+(\S+)", ln)
        if m:
            cur = m.group(1)
        m = re.match(r"\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", ln)
        if m and cur:
            sizes[cur] = (round(float(m.group(1)) * 1000), round(float(m.group(2)) * 1000))
    return sizes


def section(text, name):
    m = re.search(rf"^{name} \d+ ;\n(.*?)^END {name}", text, re.S | re.M)
    return m.group(1) if m else ""


def points(seg):
    """'( x y ) ( * y2 )' -> [(x, y), ...] with '*' meaning 'same as before'."""
    out, last = [], (0, 0)
    for a, b in re.findall(r"\(\s*(\S+)\s+(\S+)(?:\s+\S+)?\s*\)", seg):
        x = last[0] if a == "*" else int(a)
        y = last[1] if b == "*" else int(b)
        out.append((x, y)); last = (x, y)
    return out


def main():
    if "--check" in sys.argv:
        return check()
    if "--mutants" in sys.argv:
        return mutants()
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    run, lef = sys.argv[1], sys.argv[2]
    pdk_label = sys.argv[sys.argv.index("--pdk") + 1] if "--pdk" in sys.argv else None   # e.g. which open_pdks build, which the run does not record
    defs = sorted(glob.glob(os.path.join(run, "*-openroad-fillinsertion", "*.def")))
    if not defs:
        sys.exit(f"routed_map.py: no fill-insertion DEF under {run} (the run must reach detailed routing and fill)")
    text = open(defs[-1]).read()
    sizes = lef_sizes(lef)
    design = re.search(r"^DESIGN (\S+) ;", text, re.M).group(1)
    (x0, y0), (x1, y1) = points(re.search(r"^DIEAREA (.*?);", text, re.M).group(1))

    # cells
    comps, cells = {}, {0: [], 1: [], 2: [], 3: [], 4: []}
    for name, cell, x, y, orient in re.findall(r"^\s*- (\S+) (\S+) .*?\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \) (\S+) ;", section(text, "COMPONENTS"), re.M):
        w, h = sizes.get(cell, (460, 2720))
        k = cell_class(cell, name)
        comps[name] = (int(x), int(y), w, k, cell)
        cells[k] += [int(x) // U, int(y) // U, max(1, w // U)]
    counts = {k: len(v) // 3 for k, v in cells.items()}

    # signal wires, vias, clock nets
    wires = {L: [] for L in LAYERS}
    vias = []
    nets, routes = {}, {}
    for blk in re.split(r"\n\s*- ", "\n" + section(text, "NETS"))[1:]:
        name = blk.split()[0]
        head = blk.split("+")[0]
        nets[name] = re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", head)
        segs = []
        for part in re.split(r"\+ ROUTED|\bNEW\b", blk)[1:]:
            part = part.strip().rstrip(";").strip()
            m = re.match(r"(\w+)\s+(.*)", part, re.S)
            if not m or m.group(1) not in wires:
                continue
            layer, rest = m.group(1), m.group(2)
            toks = re.findall(r"\([^)]*\)|\S+", rest)
            if len(toks) > 1 and toks[1] == "RECT":
                continue                                    # a small patch, not a wire
            pts, i = [], 0
            while i < len(toks) and toks[i].startswith("("):
                pts.append(toks[i]); i += 1
            pts = points(" ".join(pts))
            if len(pts) == 2:
                (ax, ay), (bx, by) = pts
                seg = [min(ax, bx) // U, min(ay, by) // U, max(ax, bx) // U, max(ay, by) // U]
                wires[layer] += seg
                segs.append((LAYERS.index(layer), seg))
            if i < len(toks) and pts:                       # a via named after the last point
                vias += [pts[-1][0] // U, pts[-1][1] // U, LAYERS.index(layer)]
        routes[name] = segs

    # power grid
    power = []
    for layer, wd, a, b in re.findall(r"(met\d|li1) (\d+) \+ SHAPE \w+ (\( [^)]+\)) (\( [^)]+\))", section(text, "SPECIALNETS")):
        (ax, ay), (bx, by) = points(a + " " + b)
        power += [LAYERS.index(layer), min(ax, bx) // U, min(ay, by) // U, max(ax, bx) // U, max(ay, by) // U, max(1, int(wd) // U)]

    # the clock tree: start at the net on the clk pin, follow clock buffers down
    driver_of = {}
    for n, conns in nets.items():
        for comp, pin in conns:
            if pin in ("X", "Y", "Q") and comp in comps:
                driver_of.setdefault(comp, []).append(n)
    root = next((n for n, c in nets.items() if ("PIN", "clk") in c), None)
    clock, depth, frontier = [], {root: 0} if root else {}, [root] if root else []
    while frontier:
        nxt = []
        for n in frontier:
            flops = []
            for comp, pin in nets.get(n, []):
                if comp not in comps:
                    continue
                cx, cy, cw, k, cell = comps[comp]
                if k == 3 and pin == "A":
                    for out in driver_of.get(comp, []):
                        if out not in depth:
                            depth[out] = depth[n] + 1; nxt.append(out)
                elif pin == "CLK":
                    flops += [(cx + cw // 2) // U, (cy + 1360) // U]
            segs = []
            for li, s in routes.get(n, []):
                segs += [li] + s
            clock.append({"net": n, "depth": depth[n], "segs": b64(segs), "flops": b64(flops)})
        frontier = nxt
    clock.sort(key=lambda c: (c["depth"], c["net"]))

    # pins
    pins = []
    for name, x, y in re.findall(r"^\s*- (\S+) \+ NET .*?\+ PLACED \( (-?\d+) (-?\d+) \)", section(text, "PINS"), re.M | re.S):
        pins.append([name, int(x) // U, int(y) // U])
    pins.sort()

    cfg = {}
    for f in sorted(glob.glob(os.path.join(run, "resolved.json"))):
        cfg = json.load(open(f))
    meta = cfg.get("meta", {})
    out = {
        "design": design,
        "unit_nm": U,
        "die": [(x1 - x0) // U, (y1 - y0) // U],
        "row": 272,
        "source": {"flow": "LibreLane " + str(meta.get("librelane_version", "?")), "pdk": pdk_label or cfg.get("PDK", "?"),
                   "def": os.path.basename(os.path.dirname(defs[-1])) + "/" + os.path.basename(defs[-1]),
                   "density_pct": cfg.get("PL_TARGET_DENSITY_PCT"), "clock_ns": cfg.get("CLOCK_PERIOD")},
        "classes": ["flip-flop", "logic", "buffer", "clock tree", "physical only"],
        "counts": [counts[k] for k in range(5)],
        "cells": [b64(cells[k]) for k in range(5)],
        "layers": [L for L in LAYERS],
        "width_nm": [WIDTH_NM[L] for L in LAYERS],
        "wires": [b64(wires[L]) for L in LAYERS],
        "segments": [len(wires[L]) // 4 for L in LAYERS],
        "wire_um": [round(sum((wires[L][i + 2] - wires[L][i]) + (wires[L][i + 3] - wires[L][i + 1]) for i in range(0, len(wires[L]), 4)) * U / 1000) for L in LAYERS],
        "vias": b64(vias),
        "power": b64(power),
        "clock": clock,
        "pins": pins,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    open(OUT, "a").write("\n")
    check()


def check(d=None):
    quiet = d is not None
    d = d if quiet else json.load(open(OUT))
    for k in ("design", "die", "cells", "wires", "layers", "clock", "pins", "source", "counts"):
        if k not in d:
            sys.exit(f"routed_map.py: {OUT} has no '{k}'")
    W, H = d["die"]
    for k, s in enumerate(d["cells"]):
        a = unb64(s)
        if len(a) % 3 or len(a) // 3 != d["counts"][k]:
            sys.exit(f"routed_map.py: cell class {k} is malformed")
        if any(a[i] > W or a[i + 1] > H for i in range(0, len(a), 3)):
            sys.exit(f"routed_map.py: a {d['classes'][k]} lies outside the die")
    for li, s in enumerate(d["wires"]):
        a = unb64(s)
        if len(a) % 4 or len(a) // 4 != d["segments"][li]:
            sys.exit(f"routed_map.py: the {d['layers'][li]} wires are malformed")
        if any(a[i] > a[i + 2] or a[i + 1] > a[i + 3] or a[i + 2] > W or a[i + 3] > H for i in range(0, len(a), 4)):
            sys.exit(f"routed_map.py: a {d['layers'][li]} wire is reversed or lies outside the die")
    segs = sum(len(unb64(s)) // 4 for s in d["wires"])
    flops = sum(len(unb64(c["flops"])) // 2 for c in d["clock"])
    depth = max((c["depth"] for c in d["clock"]), default=0)
    if not d["clock"] or sorted({c["depth"] for c in d["clock"]}) != list(range(depth + 1)) or not flops:
        sys.exit("routed_map.py: the clock tree is missing, skips a level, or reaches no flip-flop")
    if flops != d["counts"][0]:
        sys.exit(f"routed_map.py: the clock tree reaches {flops} flip-flops but the layout has {d['counts'][0]}")
    if quiet:
        return
    print(f"routed map: {d['design']}, {sum(d['counts'])} cells, {segs} wire segments, clock tree {len(d['clock'])} nets "
          f"{depth + 1} levels deep reaching {flops} flip-flops; {d['source']['flow']}; {os.path.getsize(OUT) / 1024:.0f} KB")


def mutants():
    """Break routed.json eight ways, in memory; check() must reject every one."""
    d0 = json.load(open(OUT))
    def edit(key, i, f):
        def m(d):
            a = unb64(d[key][i]); f(a, d); d[key][i] = b64(a)
        return m
    def drop_level(d): d["clock"] = [c for c in d["clock"] if c["depth"] != 1]
    def lose_flop(d): c = d["clock"][-1]; c["flops"] = b64(unb64(c["flops"])[:-2])
    def bump(key, i): return lambda d: d[key].__setitem__(i, d[key][i] + 1)
    cases = [("no clock tree", lambda d: d.pop("clock")),
             ("a cell moved off the die", edit("cells", 1, lambda a, d: a.__setitem__(0, d["die"][0] + 5))),
             ("a cell count that does not match", bump("counts", 2)),
             ("a wire running off the die", edit("wires", 1, lambda a, d: a.__setitem__(2, d["die"][0] + 9))),
             ("a reversed wire", edit("wires", 2, lambda a, d: a.__setitem__(slice(0, 3, 2), [a[2] + 1, a[0]]))),
             ("a clock level missing", drop_level),
             ("a flip-flop the clock misses", lose_flop),
             ("a segment count that does not match", bump("segments", 1))]
    caught = 0
    for name, m in cases:
        d = json.loads(json.dumps(d0)); m(d)
        try:
            check(d); print(f"  not caught: {name}")
        except SystemExit as e:
            caught += 1; print(f"  caught: {name} ({e})")
    if caught != len(cases):
        sys.exit(f"routed_map.py: --check missed {len(cases) - caught} of {len(cases)} broken copies")
    print(f"routed map: --check caught {caught} of {len(cases)} broken copies")


if __name__ == "__main__":
    main()
