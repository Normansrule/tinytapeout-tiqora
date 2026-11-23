#!/usr/bin/env python3
"""netlist_v.py — turn docs/views/netlist.json back into Verilog, plus cell models.

The cell models come from the liberty functions stored in cells.json (which
views_switch.py has already checked against the transistors), so a proof
that this Verilog equals the RTL closes the chain RTL == gates == transistors.

    python3 test/views/netlist_v.py OUT_DIR [PREFIX]   writes OUT_DIR/{cells.v,netlist.v};
        PREFIX renames every design module (G_ lets the RTL and the gates share one simulation)
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def vexpr(f):
    e = f.replace("*", "&").replace("+", "|")
    e = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)'", r"(!\1)", e)
    e = re.sub(r"([A-Za-z0-9_\)])\s+(?=[A-Za-z_!\(])", r"\1&", e)
    return e


def cell_models(cells):
    out = []
    for name, c in sorted(cells.items()):
        pins = c["liberty"]["pins"]
        ports = sorted(pins)
        decl = [f"  {'input' if pins[p]['dir'] == 'input' else 'output'} {p}" for p in ports]
        out.append(f"module {name}(\n" + ",\n".join(decl) + ");")
        seq = c["liberty"].get("seq")
        if seq:
            iq = "IQ"
            out.append(f"  reg {iq};")
            out.append(f"  always @(posedge {seq['clocked_on']}) {iq} <= {vexpr(seq['next_state'])};")
        for p in ports:
            if pins[p]["dir"] == "output":
                out.append(f"  assign {p} = {vexpr(pins[p]['function'])};")
        out.append("endmodule\n")
    return "\n".join(out)


def esc(n):
    return n if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", n) else "\\" + n + " "


def bitref(b):
    if isinstance(b, str):
        return {"0": "1'b0", "1": "1'b1"}.get(b, "1'bx")
    return f"n{b}"


def netlist(net, prefix=""):
    out = []
    for mname, m in sorted(net["modules"].items()):
        mname = prefix + mname
        bits = set()
        for p in m["ports"].values():
            bits |= {b for b in p["bits"] if not isinstance(b, str)}
        for c in m["cells"].values():
            for bb in c["pins"].values():
                bits |= {b for b in bb if not isinstance(b, str)}
        ports = []
        for pn, p in m["ports"].items():
            ports.append(f"  {p['dir']} [{len(p['bits']) - 1}:0] {esc(pn)}")
        out.append(f"module {mname}(\n" + ",\n".join(ports) + ");")
        for b in sorted(bits):
            out.append(f"  wire n{b};")
        # named nets keep their names so equivalence can pair registers by name
        for nn, n in m["nets"].items():
            if nn in m["ports"]:
                continue
            w = len(n["bits"])
            out.append(f"  wire [{w - 1}:0] {esc(nn)};")
            out.append(f"  assign {esc(nn)} = {{{', '.join(bitref(b) for b in reversed(n['bits']))}}};")
        for pn, p in m["ports"].items():
            for i, b in enumerate(p["bits"]):
                if p["dir"] == "input":
                    if not isinstance(b, str):
                        out.append(f"  assign n{b} = {esc(pn)}[{i}];")
                else:
                    out.append(f"  assign {esc(pn)}[{i}] = {bitref(b)};")
        for cn, c in sorted(m["cells"].items()):
            conns = []
            for p, bb in sorted(c["pins"].items()):
                sig = bitref(bb[0]) if len(bb) == 1 else "{" + ", ".join(bitref(b) for b in reversed(bb)) + "}"
                conns.append(f".{esc(p)}({sig})")
            ctype = c['type'] if c['type'].startswith('sky130_') else prefix + c['type']
            out.append(f"  {ctype} {esc(cn)} ({', '.join(conns)});")
        out.append("endmodule\n")
    return "\n".join(out)


def main():
    od = sys.argv[1]
    os.makedirs(od, exist_ok=True)
    net = json.load(open(os.path.join(ROOT, "docs", "views", "netlist.json")))
    cells = json.load(open(os.path.join(ROOT, "docs", "views", "cells.json")))["cells"]
    open(os.path.join(od, "cells.v"), "w").write(cell_models(cells))
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    open(os.path.join(od, "netlist.v"), "w").write(netlist(net, prefix))


if __name__ == "__main__":
    main()
