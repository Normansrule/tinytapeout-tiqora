#!/usr/bin/env python3
"""fsm_check.py — the state diagrams on the page against what the chip actually did.

Reads the per-clock log tb_lockstep.sv writes (+FSMLOG=), with lines
    <module> <rtl state before> <rtl state after> <gate one-hot flip-flops>
and the state machines in docs/views/netlist.json (as Yosys extracted them).

Checks, every clock:
  1. encoding: exactly one gate flip-flop is hot, and it is the one synthesis
     assigned to the RTL state (the one-hot column on the page);
  2. every RTL step (including staying put) is an edge of the drawn diagram.
Then prints how many of the diagram's edges the run took (coverage), so a
run that never leaves reset cannot pass quietly: each machine must visit at
least MIN_STATES states.

If docs/views/chip.json has "fsm_gaps" ({module: {"a->b": reason}}), the
run's untaken edges must be exactly the listed ones: an untaken edge with no
reason fails (coverage went down, or a new arrow appeared), and so does a
listed edge the run took (the reason is stale). The gate is only meaningful
on the whole suite's logs (`make -C test views-lockstep`); --no-gaps skips it,
for runs of a single program.

    python3 test/views/fsm_check.py [--no-gaps] LOG [LOG ...]
"""
import collections, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN_STATES = 4


def diagram(fsm):
    """(from rtl code, to rtl code) edges and index<->code maps."""
    idx_of_bit = {}
    for st in fsm["states"]:
        idx_of_bit[len(st["pattern"]) - 1 - st["pattern"].index("1")] = st["index"]
    code_of_idx = {idx_of_bit[c["onehot_bit"]]: c["rtl"] for c in fsm["codes"]}
    edges = {(code_of_idx[t["from"]], code_of_idx[t["to"]]) for t in fsm["transitions"]}
    bit_of_code = {c["rtl"]: c["onehot_bit"] for c in fsm["codes"]}
    return edges, bit_of_code


def check(logs, fsms, gaps=None):
    seen = collections.defaultdict(collections.Counter)
    errors, clocks = [], 0
    dia = {m: diagram(f) for m, f in fsms.items()}
    for path in logs:
        for n, line in enumerate(open(path), 1):
            mod, a, b, onehot = line.split()
            a, b = int(a), int(b)
            if mod not in dia:
                errors.append(f"{path}:{n}: no diagram for {mod}")
                continue
            edges, bit_of_code = dia[mod]
            hot = [len(onehot) - 1 - i for i, ch in enumerate(onehot) if ch == "1"]
            if hot != [bit_of_code.get(b)]:
                errors.append(f"{path}:{n}: {mod} RTL state {b} but gate flip-flops {onehot}")
            if (a, b) not in edges:
                errors.append(f"{path}:{n}: {mod} step {a} -> {b} is not in the diagram")
            seen[mod][(a, b)] += 1
            clocks += 1
    report = {}
    for mod, (edges, _) in dia.items():
        took = set(seen[mod]) & edges
        states = {b for _, b in seen[mod]}
        report[mod] = (len(took), len(edges), len(states), sorted(edges - took))
        if len(states) < MIN_STATES:
            errors.append(f"{mod}: the run only visited {len(states)} states")
        if gaps is not None:
            listed = {tuple(int(x) for x in k.split("->")) for k in gaps.get(mod, {})}
            for a, b in sorted(edges - took - listed):
                errors.append(f"{mod}: edge {a}->{b} not taken and not in chip.json fsm_gaps")
            for a, b in sorted(listed & took):
                errors.append(f"{mod}: edge {a}->{b} is in chip.json fsm_gaps but was taken")
            for a, b in sorted(listed - edges):
                errors.append(f"{mod}: chip.json fsm_gaps lists {a}->{b}, which is not a diagram edge")
    return errors, clocks, report


def main():
    logs = [a for a in sys.argv[1:] if a != "--no-gaps"]
    if not logs:
        sys.exit(__doc__)
    fsms = json.load(open(os.path.join(ROOT, "docs", "views", "netlist.json")))["fsms"]
    gaps = None
    if "--no-gaps" not in sys.argv:
        gaps = json.load(open(os.path.join(ROOT, "docs", "views", "chip.json"))).get("fsm_gaps")
    errors, clocks, report = check(logs, fsms, gaps)
    for e in errors[:20]:
        print("FAIL", e)
    for mod, (took, total, states, missed) in sorted(report.items()):
        print(f"fsm_check {mod}: {took}/{total} diagram edges taken, {states} states visited")
        if missed:
            print(f"fsm_check {mod}: not taken (RTL codes from -> to): " + ", ".join(f"{a}->{b}" for a, b in missed))
    print(f"fsm_check: {clocks} clock-steps checked, {len(errors)} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
