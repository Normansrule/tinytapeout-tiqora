#!/usr/bin/env python3
"""switch_ref.py — the Python switch-level results, for page_test.js to compare with the page's.

Prints JSON: for every cell type, every input combination (combinational)
or the flip-flop clocking pattern views_switch.py uses, from internal nodes
at 0 and at 1, the value of every node. page_test.js runs the page's own
settle() on the same inputs and requires every node to match.
"""
import itertools, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "docs", "tools"))
import views_switch as vs  # noqa: E402

FF_PATTERN = [0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0]


def main():
    cells = json.load(open(os.path.join(ROOT, "docs", "views", "cells.json")))["cells"]
    out = {}
    for name, cell in sorted(cells.items()):
        fets = cell["spice"]["fets"]
        ins, _ = vs.cell_io(cell)
        runs = {}
        for init in (0, 1):
            steps = []
            if "seq" in cell["liberty"]:
                state = None
                for d in FF_PATTERN:
                    for clk, dd in ((0, d), (1, d), (1, 1 - d), (0, 1 - d)):
                        fixed = dict(vs.RAILS, CLK=clk, D=dd)
                        state = vs.settle(fets, fixed, state, init=init)
                        steps.append([fixed, state])
            else:
                for bits in itertools.product((0, 1), repeat=len(ins)):
                    fixed = dict(vs.RAILS, **dict(zip(ins, bits)))
                    steps.append([fixed, vs.settle(fets, fixed, init=init)])
            runs[init] = steps
        out[name.replace("sky130_fd_sc_hd__", "")] = {"seq": "seq" in cell["liberty"], "runs": runs}
    json.dump(out, sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main()
