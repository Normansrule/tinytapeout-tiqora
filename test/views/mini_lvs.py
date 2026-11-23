#!/usr/bin/env python3
"""mini_lvs.py — every transistor in the layout is in the netlist, and the reverse.

A MOSFET is where polysilicon crosses diffusion: the poly is the gate, the
diffusion on either side is source and drain. Inside the n-well the
diffusion is p+ (a PMOS), outside it is n+ (an NMOS). This check finds every
such crossing in the GDS polygons stored in docs/views/cells.json, measures
its width W (along the gate) and length L (across it), and compares the
multiset {(type, W, L)} with the transistors in the cell's SPICE netlist.

It is not a full layout-versus-schematic run (it does not trace which
terminal connects to which net), and says so on the page. What it catches:
a missing or extra transistor, a PMOS drawn as an NMOS, a wrong width.

    python3 test/views/mini_lvs.py [cells.json]     exit 1 on any mismatch
"""
import collections, json, os, sys
import klayout.db as db

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DBU = 0.001


def region(polys):
    r = db.Region()
    for pts in polys:
        r.insert(db.Polygon([db.Point(round(x / DBU), round(y / DBU)) for x, y in pts]))
    return r.merged()


def channels(gds):
    L = gds["layers"]
    diff, poly = region(L.get("diff", [])), region(L.get("poly", []))
    nwell = region(L.get("nwell", []))
    gates = (diff & poly)
    out = []
    for g in gates.each():
        gr = db.Region(g)
        kind = "p" if not (gr & nwell).is_empty() else "n"
        # width: the gate edge length lying on the diffusion boundary is 2*L (poly
        # edges cross it); the edges shared with poly boundary are 2*W.
        poly_edges = (gr.edges() & poly.edges()).length() * DBU   # source/drain sides lie on poly edges
        perim = gr.perimeter() * DBU
        w_sum = poly_edges / 2
        l_sum = (perim - poly_edges) / 2
        out.append((kind, round(w_sum, 3), round(l_sum, 3)))
    return out


def check(cells):
    bad, total = [], 0
    for name, c in sorted(cells.items()):
        lay = collections.Counter(channels(c["gds"]))
        net = collections.Counter((f["type"], round(f["w"], 3), round(f["l"], 3)) for f in c["spice"]["fets"])
        total += sum(net.values())
        if lay != net:
            bad.append(f"{name}: layout {sorted((lay - net).elements())} not in netlist; "
                       f"netlist {sorted((net - lay).elements())} not in layout")
    return bad, total


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "views", "cells.json")
    cells = json.load(open(path))["cells"]
    bad, total = check(cells)
    for b in bad:
        print("FAIL", b)
    print(f"mini_lvs: {len(cells)} cells, {total} transistors, {len(bad)} cells mismatched")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
