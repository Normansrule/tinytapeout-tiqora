#!/usr/bin/env python3
"""die_map.py — the data behind the explorer's die zoom (docs/site/data/die.json).

    python3 docs/tools/die_map.py <sky130_fd_sc_hd dir>     write docs/site/data/die.json
    python3 docs/tools/die_map.py --check                  fail if die.json is malformed

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; the chip, the
tile size and the blocks come from each repository's docs/tools/layout_preview.py.

What it exports: every standard cell of the synthesized design, packed into
rows block by block by layout_preview.pack() (the same illustration as
docs/images/layout_blocks.png), plus the real GDS geometry of each kind of
cell used, layer by layer. The page draws it the way Visual 6502 draws a die:
diffusion, polysilicon, local interconnect and metal 1 as translucent colour
on black. No Visual 6502 code or data is used; only the idea of the view.
A polygon with four numbers is a rectangle [x0, y0, x1, y1]; longer ones are
point lists. Coordinates are in units of q_nm (5 nm) from the cell's origin.

What it is NOT: a placement. There is no routed layout at the configured tile
size, so positions are illustrative; the cells, their sizes and their
geometry are real. The page says so at every zoom level.

Needs Yosys (yowasp-yosys) and KLayout's Python module (pip install klayout
yowasp-yosys) and the sky130_fd_sc_hd library: <dir>/lef, <dir>/gds, <dir>/lib.
"""
import json, os, shutil, subprocess, sys

OUT = "docs/site/data/die.json"
Q = 5        # coordinates are stored in units of 5 nm (sky130 shapes sit on a 5 nm grid)
LAYERS = [   # (key, GDS layer, datatype, what it is): drawn bottom to top
    ("nwell", 64, 20, "n-well"),
    ("diff", 65, 20, "diffusion: where transistors' sources and drains are"),
    ("tap", 65, 44, "well taps"),
    ("poly", 66, 20, "polysilicon: a transistor's gate where it crosses diffusion"),
    ("licon", 66, 44, "contacts up from diffusion and poly"),
    ("li1", 67, 20, "local interconnect"),
    ("mcon", 67, 44, "contacts from local interconnect to metal 1"),
    ("met1", 68, 20, "metal 1: the power rails and short wires"),
]


def check():
    d = json.load(open(OUT))
    for k in ("chip", "synth", "tile_um", "row_um", "cells", "inst", "regions", "focus", "layers", "note"):
        if k not in d:
            sys.exit(f"die_map.py: {OUT} has no '{k}'")
    n = len(d["cells"])
    bad = [i for i in d["inst"] if not 0 <= i[0] < n]
    if bad:
        sys.exit(f"die_map.py: {len(bad)} instances name a cell that is not in the table")
    print(f"die map: {len(d['inst'])} cell instances of {n} kinds, {len(d['regions'])} blocks, {os.path.getsize(OUT) / 1024:.0f} KB")


def main():
    if "--check" in sys.argv:
        return check()
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    libdir = sys.argv[1]
    sys.path.insert(0, "docs/tools")
    import layout_preview as LP
    import klayout.db as db
    fresh = not os.path.exists("syn/_w")
    P = LP.pack(libdir)
    if fresh:                  # pack() synthesizes in syn/_w: leave the tree as it was
        shutil.rmtree("syn/_w")
    ly = db.Layout()
    ly.read(f"{libdir}/gds/sky130_fd_sc_hd.gds")
    dbu = ly.dbu
    # filler and decap cells are left out: the page draws the empty sites as bare rows with their power rails
    names = sorted({p[0] for p in P["placements"]})
    cells = []
    for name in names:
        c = ly.cell(name)
        if c is None:
            sys.exit(f"die_map.py: {name} is not in the GDS")
        w = round(c.dbbox().width() / dbu / Q)
        geo = {}
        for key, l, dt, _ in LAYERS:
            li = ly.find_layer(l, dt)
            if li is None:
                continue
            reg = db.Region(c.begin_shapes_rec(li)).merged()
            polys = []
            for poly in reg.each():
                if poly.is_box():      # most shapes are rectangles: stored as [x0, y0, x1, y1]
                    bx = poly.bbox()
                    polys.append([round(bx.left / Q), round(bx.bottom / Q), round(bx.right / Q), round(bx.top / Q)])
                    continue
                pts = []
                for pt in poly.to_simple_polygon().each_point():
                    pts += [round(pt.x / Q), round(pt.y / Q)]
                polys.append(pts)
            if polys:
                geo[key] = polys
        cells.append({"name": name.replace("sky130_fd_sc_hd__", ""), "w": w, "geo": geo})
    index = {n: i for i, n in enumerate(names)}
    um = lambda v: round(v * 1000 / Q)
    inst = [[index[t], um(x), um(y), 1 if flip else 0] for t, x, y, flip in P["placements"]]
    # each block's atlas category, so the zoom outlines it in the atlas's colour
    atlas = json.load(open("docs/site/data/atlas.json"))
    mod_cat = {b["module"]: b["category"] for b in atlas["blocks"]}
    lab_cat = {lab: mod_cat.get(mod, "control") for mod, lab, _ in LP.BLOCKS}
    regions = [{"label": lab, "category": lab_cat.get(lab, "control"), "um": [round(v, 2) for v in r], "cell_area_um2": round(P["area"][lab], 1)}
               for lab, r in sorted(P["regions"].items(), key=lambda kv: -P["area"][kv[0]])]
    # the flip-flop the zoom ends on: the D flip-flop nearest the middle of the register file
    # (or of the largest block), so the close-up is surrounded by cells on every side
    rf = next((r for r in regions if "Register" in r["label"]), regions[0])
    mx, my = rf["um"][0] + rf["um"][2] / 2, rf["um"][1] + rf["um"][3] / 2
    dff = [i for i in inst if cells[i[0]]["name"].startswith(("dfxtp", "dfrtp", "dfstp", "dfrbp"))] or inst
    pick = min(dff, key=lambda i: ((i[1] * Q / 1000 - mx) ** 2 + (i[2] * Q / 1000 - my) ** 2, i[1], i[2]))
    yosys = " ".join(subprocess.run(["yowasp-yosys", "-V"], capture_output=True, text=True, check=True).stdout.split()[:2])
    d = {"chip": LP.TOP, "synth": yosys + " (yowasp-yosys), hierarchy kept, not flattened; docs/tools/die_map.py", "tile_um": [LP.TILE_W, LP.TILE_H], "row_um": LP.ROW_H, "q_nm": Q,
         "cell_area_um2": round(P["total"], 1), "core_utilization": round(P["util"], 4),
         "layers": [{"key": k, "gds": f"{l}/{dt}", "what": w} for k, l, dt, w in LAYERS],
         "cells": cells, "inst": inst, "regions": regions, "fill_instances": len(P["fills"]),
         "focus": {"cell": cells[pick[0]]["name"], "at": pick[1:]},
         "note": "Real sky130_fd_sc_hd cells and geometry, packed into rows block by block by docs/tools/layout_preview.py: "
                 "an illustration of size and density, not a placement. Synthesized with Yosys from the files info.yaml submits."}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(d, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    check()


if __name__ == "__main__":
    main()
