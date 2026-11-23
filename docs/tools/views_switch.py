#!/usr/bin/env python3
"""views_switch.py — a switch-level simulator for sky130 standard cells.

A CMOS transistor is a switch: an n-type one conducts when its gate is 1, a
p-type one when its gate is 0. Give every input a value, tie VPWR to 1 and
VGND to 0, and every other node takes the value of whichever rail it is
connected to through conducting switches. Repeat until nothing changes
(cells have several stages: an inverter driving a NAND driving an inverter).

That is enough to read the logic function straight out of the SkyWater
transistor netlist, with no liberty file involved, and to compare it with
the function the liberty file *claims*. A node that reaches both rails at
once is a short ("C"); one that reaches neither keeps the charge it had (a
flip-flop's storage node does exactly this between clock edges); one that
has never been driven is unknown ("X").

    python3 docs/tools/views_switch.py [docs/views/cells.json]   check every cell, print counts

Used by test/views (the gates == transistors step) and by views_build.py,
which stores the truth tables the page animates.
"""
import itertools, json, os, re, sys

RAILS = {"VPWR": 1, "VGND": 0}
BODIES = {"VPB", "VNB"}


# ---------------------------------------------------------------- liberty functions
def lib_expr_to_py(expr):
    """Liberty Boolean syntax -> Python: !a, a', a&b, a*b, a b (AND), a|b, a+b, a^b."""
    e = expr.replace("*", "&").replace("+", "|")
    e = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)'", r"(!\1)", e)
    # implicit AND: two operands separated only by spaces
    e = re.sub(r"([A-Za-z0-9_\)])\s+(?=[A-Za-z_!\(])", r"\1&", e)
    e = e.replace("!", " not ").replace("&", " and ").replace("|", " or ").replace("^", " != ")
    return e


def lib_eval(expr, env):
    py = lib_expr_to_py(expr)
    return int(bool(eval(py, {"__builtins__": {}}, {k: bool(v) for k, v in env.items()})))


# ---------------------------------------------------------------- switch level
def settle(fets, fixed, prev=None, init=0, max_iter=200):
    """Return {node: 0|1|'C'} once the network stops changing.

    fixed: rails and inputs. prev: node values before this step (charge
    storage). Nodes never seen before start at `init`; callers try both 0
    and 1, and a correct cell must give the same answer from either.

    Every node is updated at once from the previous values (unit delay), so
    a clock edge ripples through the cell's clock buffers the way it does on
    silicon. During that ripple a node can briefly see both rails (a
    transient fight); it keeps its old value until the fight ends. A fight
    that is still there once nothing else moves is a real short: "C".
    """
    nodes = set()
    for f in fets:
        nodes |= {f["d"], f["s"], f["g"]}
    val = {n: init for n in nodes}
    if prev:
        val.update({n: v for n, v in prev.items() if n in val and v in (0, 1)})
    val.update(fixed)
    for _ in range(max_iter):
        on = [f for f in fets if (f["type"] == "n" and val[f["g"]] == 1) or (f["type"] == "p" and val[f["g"]] == 0)]
        src = _drivers(nodes, fixed, val, on)
        new, fight = dict(val), set()
        for n in nodes:
            if n in fixed:
                continue
            if src[n] == {0, 1}:
                fight.add(n)                  # keep the old value while it lasts
            elif src[n]:
                new[n] = next(iter(src[n]))
            # no driver: keeps its charge
        if new == val:
            for n in fight:
                val[n] = "C"
            return val
        val = new
    # Still moving after max_iter unit delays: a loop that started in an
    # impossible state (both sides of a latch at the same value at power-up)
    # rings forever when every node moves at once. Silicon breaks the tie
    # with mismatch; here nodes are updated one at a time, in name order.
    for _ in range(max_iter):
        changed = False
        for n in sorted(nodes - set(fixed)):
            on = [f for f in fets if (f["type"] == "n" and val[f["g"]] == 1) or (f["type"] == "p" and val[f["g"]] == 0)]
            s = _drivers(nodes, fixed, val, on)[n]
            if len(s) == 1 and val[n] != next(iter(s)):
                val[n] = next(iter(s))
                changed = True
        if not changed:
            on = [f for f in fets if (f["type"] == "n" and val[f["g"]] == 1) or (f["type"] == "p" and val[f["g"]] == 0)]
            src = _drivers(nodes, fixed, val, on)
            return {n: ("C" if n not in fixed and src[n] == {0, 1} else v) for n, v in val.items()}
    return {n: ("X" if n not in fixed else v) for n, v in val.items()}  # never settled: oscillation


def _drivers(nodes, fixed, val, fets):
    """For each free node, the set of fixed values it reaches through `fets`.
    Fixed nodes (rails, inputs) are ends, never bridges: two nodes that both
    touch VPWR are not thereby connected to each other."""
    parent = {n: n for n in nodes if n not in fixed}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    touch = []
    for f in fets:
        a, b = f["d"], f["s"]
        if a in fixed and b in fixed:
            continue
        if a in fixed:
            touch.append((b, val[a]))
        elif b in fixed:
            touch.append((a, val[b]))
        else:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    src = {}
    for n, v in touch:
        src.setdefault(find(n), set()).add(v)
    return {n: src.get(find(n), set()) for n in parent}


def cell_io(cell):
    lib = cell["liberty"]["pins"]
    ins = sorted(p for p, i in lib.items() if i["dir"] == "input")
    outs = sorted(p for p, i in lib.items() if i["dir"] == "output")
    return ins, outs


def truth_table(cell, init=0):
    """Every input combination of a combinational cell: (inputs, switch outputs, liberty outputs, nodes)."""
    ins, outs = cell_io(cell)
    fets = cell["spice"]["fets"]
    rows = []
    for bits in itertools.product((0, 1), repeat=len(ins)):
        env = dict(zip(ins, bits))
        fixed = dict(RAILS, **env)
        v = settle(fets, fixed, init=init)
        sw = {o: v.get(o, "X") for o in outs}
        lb = {o: lib_eval(cell["liberty"]["pins"][o]["function"], env) for o in outs}
        rows.append((env, sw, lb, v))
    return rows


def check_comb(name, cell):
    bad = []
    for init in (0, 1):
        for env, sw, lb, nodes in truth_table(cell, init):
            if sw != lb:
                bad.append(f"{name} {env} (internal nodes from {init}): transistors give {sw}, liberty says {lb}")
            shorts = sorted(n for n, v in nodes.items() if v not in (0, 1))
            if shorts:
                bad.append(f"{name} {env}: nodes {shorts} fight or float")
    return bad


def check_ff(name, cell):
    """Rising-edge D flip-flop: after CLK 0->1 with D=d, Q==d, and Q holds while
    CLK stays high or low whatever D does. Run from an unknown start."""
    seq = cell["liberty"]["seq"]
    if seq.get("kind") != "ff" or seq.get("next_state") != "D" or seq.get("clocked_on") != "CLK" \
            or "clear" in seq or "preset" in seq:
        return [f"{name}: only plain rising-edge D flip-flops are modelled (got {seq})"]
    fets = cell["spice"]["fets"]
    qfun = cell["liberty"]["pins"]["Q"]["function"]
    if qfun != "IQ":
        return [f"{name}: Q function {qfun!r} is not IQ"]
    bad = []
    for init in (0, 1):
        bad += _ff_run(name, fets, init)
    return bad


def _ff_run(name, fets, init):
    bad, state = [], None
    def step(clk, d):
        nonlocal state
        state = settle(fets, dict(RAILS, CLK=clk, D=d), state, init=init)
        bad.extend(f"{name}: node {n} fights or oscillates at CLK={clk} D={d}"
                   for n, v in sorted(state.items()) if v not in (0, 1))
        return state.get("Q", "X")
    pattern = [0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0]
    for i, d in enumerate(pattern):
        step(0, d)                 # set up D while the clock is low
        q = step(1, d)             # rising edge
        if q != d:
            bad.append(f"{name}: edge {i} with D={d} gave Q={q}")
        q2 = step(1, 1 - d)        # D changes while CLK is high: Q must hold
        if q2 != d:
            bad.append(f"{name}: Q changed to {q2} while CLK high (edge {i})")
        q3 = step(0, 1 - d)        # falling edge: Q must hold
        if q3 != d:
            bad.append(f"{name}: Q changed to {q3} on falling edge (edge {i})")
    return bad


def check_cell(name, cell):
    if "seq" in cell["liberty"]:
        return check_ff(name, cell)
    return check_comb(name, cell)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "views", "cells.json")
    cells = json.load(open(path))["cells"]
    bad, rows = [], 0
    for name, cell in sorted(cells.items()):
        b = check_cell(name, cell)
        rows += 2 * ((2 ** len(cell_io(cell)[0])) if "seq" not in cell["liberty"] else 33)
        bad += b
    for b in bad:
        print("FAIL", b)
    print(f"views_switch: {len(cells)} cells, {rows} input states, {len(bad)} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
