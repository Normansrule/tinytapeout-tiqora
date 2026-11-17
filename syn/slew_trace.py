#!/usr/bin/env python3
"""Trace every max-slew violator at one corner back to the net the RTL made.

For each violating net: the driver cell, every load (instance and cell), and the
chain of buffers above it up to the first non-buffer driver, whose net name is
usually the RTL signal. Report only; it does not pass or fail anything.

    python3 syn/slew_trace.py runs/wokwi [corner]
"""
import glob, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signoff_audit import read_checks, OUT_PINS

BUF = re.compile(r"sky130_fd_sc_hd__(buf|clkbuf|dlygate|dlymetal|clkdlybuf)")


def netlist(path):
    text = open(path).read()
    pin_net, drv, loads, cell_of, ins = {}, {}, {}, {}, {}
    for m in re.finditer(r"^\s*(sky130_\w+)\s+(\S+)\s*\((.*?)\);", text, re.M | re.S):
        cell, inst, body = m.groups()
        cell_of[inst] = cell
        for pm in re.finditer(r"\.(\w+)\(([^()]*)\)", body):
            pin, net = pm.group(1), pm.group(2).strip()
            if not net:
                continue
            pin_net[(inst, pin)] = net
            if pin in OUT_PINS:
                drv[net] = (inst, pin)
            else:
                loads.setdefault(net, []).append((inst, pin))
                ins.setdefault(inst, []).append(net)
    return pin_net, drv, loads, cell_of, ins


def main():
    run = sys.argv[1]
    corner = sys.argv[2] if len(sys.argv) > 2 else "max_ss_100C_1v60"
    d = sorted(glob.glob(os.path.join(run, "*-openroad-stapostpnr")),
               key=lambda p: int(os.path.basename(p).split("-")[0]))[-1]
    v = read_checks(os.path.join(d, corner, "checks.rpt"))["slew"]
    nl = glob.glob(os.path.join(run, "final", "nl", "*.nl.v"))[0]
    pin_net, drv, loads, cell_of, ins = netlist(nl)
    by_net = {}
    for slack, pin, limit, value in v:
        inst, _, p = pin.rpartition("/")
        by_net.setdefault(pin_net.get((inst, p), "?"), []).append((value, pin))
    print(f"{corner}: {len(v)} slew violators on {len(by_net)} nets")
    for net, rows in sorted(by_net.items(), key=lambda kv: -max(r[0] for r in kv[1])):
        di, dp = drv.get(net, ("port", ""))
        print(f"\nNET {net}  worst {max(r[0] for r in rows):.3f} ns, {len(rows)} violating pins")
        print(f"  driver {di}/{dp} {cell_of.get(di, '')}")
        ld = loads.get(net, [])
        print(f"  {len(ld)} loads: " + ", ".join(f"{i}/{p}:{cell_of.get(i, '?').replace('sky130_fd_sc_hd__', '')}" for i, p in ld))
        # walk up through buffers to the RTL net
        chain, n, seen = [], net, set()
        while n in drv and n not in seen:
            seen.add(n)
            i, _ = drv[n]
            if not BUF.match(cell_of.get(i, "")):
                break
            n = ins.get(i, ["?"])[0]
            chain.append(n)
        if chain:
            oi, op = drv.get(n, ("port", ""))
            print(f"  upstream through buffers: {' <- '.join(chain)}; origin driver {oi}/{op} {cell_of.get(oi, '')}, {len(loads.get(n, []))} loads")
        if di in ins and not BUF.match(cell_of.get(di, "")):
            print(f"  driver inputs: " + ", ".join(ins[di]))


if __name__ == "__main__":
    main()
