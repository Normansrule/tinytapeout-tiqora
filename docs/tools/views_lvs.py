#!/usr/bin/env python3
"""views_lvs.py — layout versus schematic for every standard cell the design uses.

Rebuilds each cell from the polygons stored in docs/views/cells.json (not
from the PDK, so CI can run it), and asks KLayout's netlist extractor what
circuit those polygons make:

  * where poly crosses diffusion there is a transistor: inside the n-well a
    PMOS, outside an NMOS; its W and L come from the crossing's shape;
  * the diffusion left over on either side is its source and drain;
  * licon joins diffusion and poly to local interconnect (li1), mcon joins
    li1 to metal 1, and the cell's pin labels name the nets they sit on.

KLayout's NetlistComparer then matches that circuit against the SkyWater
SPICE netlist of the same cell, transistor by transistor and net by net
(topology, type, W and L), and every pin must land on the layout net that
carries its label (the comparer alone matches by topology, so a pin cut off
from its transistors would otherwise still pass through an unnamed net). For each SPICE transistor it also reports where
the matching gate is in the layout, which the views page uses to light the
right transistor when you click it.

    python3 docs/tools/views_lvs.py [cells.json]     all cells; exit 1 on any mismatch
"""
import json, os, sys
import klayout.db as db

DBU = 0.001
CONDUCTORS = ["nwell", "diff", "tap", "poly", "licon", "li1", "mcon", "met1"]


def _layout(name, gds):
    ly = db.Layout()
    ly.dbu = DBU
    top = ly.create_cell(name)
    li = {}
    for ln in CONDUCTORS:
        li[ln] = ly.layer(db.LayerInfo(ln))
        for pts in gds["layers"].get(ln, []):
            top.shapes(li[ln]).insert(db.Polygon([db.Point(round(x / DBU), round(y / DBU)) for x, y in pts]))
    for lab, lay, x, y in gds["labels"]:
        key = lay + "_lbl"
        if key not in li:
            li[key] = ly.layer(db.LayerInfo(key))
        top.shapes(li[key]).insert(db.Text(lab, db.Trans(db.Point(round(x / DBU), round(y / DBU)))))
    return ly, top, li


def extract(name, gds):
    """The circuit the polygons make: (KLayout netlist, the extractor that owns it)."""
    ly, top, li = _layout(name, gds)
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(ly, top, []))
    L = {n: l2n.make_layer(li[n], n) for n in CONDUCTORS}
    pdiff, ndiff = L["diff"] & L["nwell"], L["diff"] - L["nwell"]
    pgate, ngate = pdiff & L["poly"], ndiff & L["poly"]
    psd, nsd = pdiff - pgate, ndiff - ngate
    for reg, nm in ((pgate, "pgate"), (ngate, "ngate"), (psd, "psd"), (nsd, "nsd")):
        l2n.register(reg, nm)
    l2n.extract_devices(db.DeviceExtractorMOS3Transistor("PMOS"), {"SD": psd, "G": pgate, "P": L["poly"]})
    l2n.extract_devices(db.DeviceExtractorMOS3Transistor("NMOS"), {"SD": nsd, "G": ngate, "P": L["poly"]})
    for r in (psd, nsd, L["poly"], L["licon"], L["li1"], L["mcon"], L["met1"]):
        l2n.connect(r)
    for a, b in ((psd, L["licon"]), (nsd, L["licon"]), (L["poly"], L["licon"]), (L["licon"], L["li1"]),
                 (L["li1"], L["mcon"]), (L["mcon"], L["met1"])):
        l2n.connect(a, b)
    for lay in ("li1", "met1"):
        if lay + "_lbl" in li:
            l2n.connect(L[lay], l2n.make_text_layer(li[lay + "_lbl"], lay + "_lbl"))
    l2n.extract_netlist()
    nl = l2n.netlist()
    nl.make_top_level_pins()
    nl.purge()
    return nl, l2n


def reference(name, spice):
    """The SkyWater SPICE subcircuit as a KLayout netlist (bulk terminals dropped:
    every PMOS body is VPB and every NMOS body VNB in these cells)."""
    nl = db.Netlist()
    cir = db.Circuit()
    cir.name = name
    nl.add(cir)
    cls = {}
    for k in ("PMOS", "NMOS"):
        dc = db.DeviceClassMOS3Transistor()
        dc.name = k
        nl.add(dc)
        cls[k] = dc
    nets = {}
    def net(n):
        if n not in nets:
            nets[n] = cir.create_net(n)
        return nets[n]
    for p in spice["ports"]:
        if p in ("VPB", "VNB"):
            continue
        cir.connect_pin(cir.create_pin(p), net(p))
    for f in spice["fets"]:
        d = cir.create_device(cls["PMOS" if f["type"] == "p" else "NMOS"], f["name"])
        for term, key in (("S", "s"), ("G", "g"), ("D", "d")):
            d.connect_terminal(term, net(f[key]))
        d.set_parameter("L", f["l"])
        d.set_parameter("W", f["w"])
    return nl


def lvs(name, cell):
    """(ok, {spice transistor name: [x, y] of its gate centre in the layout})."""
    (a, keep), b = extract(name, cell["gds"]), reference(name, cell["spice"])
    xref = db.NetlistCrossReference()
    ok = db.NetlistComparer().compare(a, b, xref)
    where = {}
    ports = {p for p in cell["spice"]["ports"] if p not in ("VPB", "VNB")}
    named = set()
    for cp in xref.each_circuit_pair():
        # NetlistComparer matches nets by topology; a pin is only right if the
        # layout net it matched carries the pin's own label. Without this, a
        # pin whose contact is missing still "matches" through an unnamed net.
        for np_ in xref.each_net_pair(cp):
            lay, sch = np_.first(), np_.second()
            if sch is not None and sch.name in ports:
                if lay is None or lay.name != sch.name:
                    ok = False
                else:
                    named.add(sch.name)
        for dp in xref.each_device_pair(cp):
            lay, sch = dp.first(), dp.second()
            if lay is not None and sch is not None:
                where[sch.name] = [round(lay.trans.disp.x, 3), round(lay.trans.disp.y, 3)]
    if len(where) != len(cell["spice"]["fets"]) or named != ports:
        ok = False
    return ok, dict(sorted(where.items()))


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "docs", "views", "cells.json")
    cells = json.load(open(path))["cells"]
    bad, fets = [], 0
    for name, c in sorted(cells.items()):
        ok, where = lvs(name, c)
        fets += len(where)
        stored = {f["name"]: f.get("at") for f in c["spice"]["fets"]}
        if not ok:
            bad.append(f"{name}: layout and SPICE netlist differ")
        elif any(stored[k] != v for k, v in where.items()):
            bad.append(f"{name}: stored transistor positions differ from this extraction")
    for b in bad:
        print("FAIL", b)
    print(f"views_lvs: {len(cells)} cells, {fets} transistors matched layout-to-schematic, {len(bad)} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
