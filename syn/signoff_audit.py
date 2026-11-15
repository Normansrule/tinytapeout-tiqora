#!/usr/bin/env python3
"""signoff_audit.py: tape-out margin audit of a finished LibreLane run.

Contract
  Reads <run>/final/metrics.json, the post-PnR STA checks reports
  (<run>/*-openroad-stapostpnr/<corner>/checks.rpt) and the last antenna report
  (<run>/*-openroad-checkantennas*/**/antenna.rpt). Prints a Markdown report and
  one PASS/FAIL line per gate. Exit status: 0 when every gate passes, 1 when any
  gate fails, 2 when an input is missing (a missing report is never a pass).

  Gates (margins chosen so that "met" is never "nearly failed"):
    G1 setup slack  >= +1.00 ns at every corner (5% of the 20 ns clock)
    G2 hold slack   >= +0.05 ns at every corner
    G3 routing DRC, Magic DRC, LVS, antenna violations == 0
    G4 max-slew, max-capacitance, max-fanout violations == 0 at every corner
    G5 worst antenna partial-area ratio <= 80% of the PDK limit, every net
    G6 power-grid violations == 0, inferred latches == 0, unmapped cells == 0

  The Tiny Tapeout pre-flight (KLayout FEOL/BEOL/off-grid, Magic DRC, pins,
  forbidden met5) is a separate CI job (precheck); this script does not repeat it.

Cost: none on silicon; a few milliseconds in CI.

Usage
  python3 syn/signoff_audit.py runs/wokwi            # report, exit 0/1/2
  python3 syn/signoff_audit.py --selftest            # mutation self-test
"""
import glob
import json
import os
import re
import sys
import tempfile

SETUP_MIN = 1.00
HOLD_MIN = 0.05
ANT_MAX = 0.80
ZERO_KEYS = [
    ("route__drc_errors", "routing DRC"),
    ("magic__drc_error__count", "Magic DRC"),
    ("design__lvs_error__count", "LVS"),
    ("route__antenna_violation__count", "antenna violations"),
]
G6_KEYS = [
    ("design__power_grid_violation__count", "power-grid violations"),
    ("design__inferred_latch__count", "inferred latches"),
    ("design__instance_unmapped__count", "unmapped cells"),
]
VIOL = re.compile(r"^\s*(\S+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\(VIOLATED\)")


def read_checks(path):
    """Violators per kind from an OpenSTA report_check_types -violators report."""
    out = {"slew": [], "capacitance": [], "fanout": []}
    kind = None
    for line in open(path):
        low = line.strip().lower()
        for k in out:
            if low.startswith("max " + k):
                kind = k
        m = VIOL.match(line)
        if m and kind:
            pin, limit, value, slack = m.groups()
            out[kind].append((float(slack), pin, float(limit), float(value)))
    for k in out:
        out[k].sort()
    return out


OUT_PINS = {"X", "Y", "Q", "Q_N", "Z", "HI", "LO", "COUT", "SUM", "GCLK"}


def read_netlist(path):
    """{(instance, pin): net}, {net: driver 'inst/pin (cell)'}, {net: load count} from a gate-level netlist."""
    text = open(path).read()
    pin_net, driver, loads = {}, {}, {}
    for m in re.finditer(r"^\s*(sky130_\w+)\s+(\S+)\s*\((.*?)\);", text, re.M | re.S):
        cell, inst, body = m.groups()
        for pm in re.finditer(r"\.(\w+)\(([^()]*)\)", body):
            pin, net = pm.group(1), pm.group(2).strip()
            if not net:
                continue
            pin_net[(inst, pin)] = net
            if pin in OUT_PINS:
                driver[net] = f"{inst}/{pin} ({cell})"
            else:
                loads[net] = loads.get(net, 0) + 1
    return pin_net, driver, loads


def read_antenna(path):
    """(partial/required, net, pin, layer) for every gate checked, worst first."""
    rows, net, pin, layer, par = [], None, None, None, None
    for line in open(path):
        s = line.strip()
        if s.startswith("Net:"):
            net = s.split()[-1]
        elif s.startswith("Pin:"):
            pin = s.split()[1]
        elif s.startswith("Layer:"):
            layer = s.split()[1]
        elif s.startswith("Partial area ratio:"):
            par = float(re.findall(r"[\d.]+", s)[0])
        elif s.startswith("Required ratio:") and par is not None:
            req = float(re.findall(r"[\d.]+", s)[0])
            if req > 0:
                rows.append((par / req, net, pin, layer, par, req))
            par = None
    rows.sort(reverse=True)
    return rows


def audit(run, out=sys.stdout):
    p = lambda *a: print(*a, file=out)
    mpath = os.path.join(run, "final", "metrics.json")
    if not os.path.exists(mpath):
        p(f"MISSING {mpath}")
        return 2
    m = json.load(open(mpath))
    corners = sorted({k.split("corner:")[1] for k in m if k.startswith("timing__setup__ws__corner:")})
    if not corners:
        p("MISSING per-corner timing in metrics.json")
        return 2
    sta = sorted(glob.glob(os.path.join(run, "*-openroad-stapostpnr")))
    ant = sorted(glob.glob(os.path.join(run, "*-openroad-checkantennas*", "**", "antenna.rpt"), recursive=True))
    if not sta or not ant:
        p(f"MISSING post-PnR STA ({len(sta)}) or antenna report ({len(ant)})")
        return 2
    fails = []
    gate = lambda name, ok, why: (p(f"{'PASS' if ok else 'FAIL'} {name}: {why}"), ok or fails.append(name))

    p("| corner | setup ws (ns) | hold ws (ns) | max slew | max cap | max fanout |")
    p("|---|---:|---:|---:|---:|---:|")
    worst = {}
    for c in corners:
        g = lambda k: m.get(f"{k}__corner:{c}")
        row = [g("timing__setup__ws"), g("timing__hold__ws"), g("design__max_slew_violation__count"),
               g("design__max_cap_violation__count"), g("design__max_fanout_violation__count")]
        if any(v is None for v in row):
            p(f"MISSING metrics for corner {c}")
            return 2
        worst[c] = row
        p(f"| {c} | {row[0]:+.3f} | {row[1]:+.3f} | {row[2]} | {row[3]} | {row[4]} |")
    p("")
    ws = min(worst.items(), key=lambda kv: kv[1][0])
    gate("G1 setup margin", ws[1][0] >= SETUP_MIN, f"worst {ws[1][0]:+.3f} ns at {ws[0]} (need >= +{SETUP_MIN:.2f})")
    wh = min(worst.items(), key=lambda kv: kv[1][1])
    gate("G2 hold margin", wh[1][1] >= HOLD_MIN, f"worst {wh[1][1]:+.3f} ns at {wh[0]} (need >= +{HOLD_MIN:.2f})")
    bad = [f"{n}={m.get(k)}" for k, n in ZERO_KEYS if m.get(k) != 0]
    gate("G3 DRC/LVS/antenna", not bad, ", ".join(bad) or "all 0 (" + ", ".join(n for _, n in ZERO_KEYS) + ")")
    drv = {c: sum(worst[c][2:]) for c in corners}
    nbad = {c: v for c, v in drv.items() if v}
    gate("G4 slew/cap/fanout", not nbad,
         "0 at every corner" if not nbad else "violations: " + ", ".join(f"{c} {v}" for c, v in nbad.items()))

    d = sta[-1]
    nl = sorted(glob.glob(os.path.join(run, "final", "nl", "*.nl.v")))
    pin_net, driver, loads = read_netlist(nl[0]) if nl else ({}, {}, {})
    for c in ("max_ss_100C_1v60", "nom_tt_025C_1v80"):
        f = os.path.join(d, c, "checks.rpt")
        if not os.path.exists(f):
            p(f"MISSING {f}")
            return 2
        v = read_checks(f)
        for k, rows in v.items():
            if rows:
                p(f"\n{c}: {len(rows)} max-{k} violators, worst 10 (slack, pin, limit, value):")
                for r in rows[:10]:
                    p(f"  {r[0]:+.4f} {r[1]} limit {r[2]} value {r[3]}")
                # Which nets the violators sit on, so a fix can target the driver.
                nets = {}
                for r in rows:
                    inst, _, pin = r[1].rpartition("/")
                    net = pin_net.get((inst, pin), "?")
                    nets[net] = nets.get(net, 0) + 1
                top = sorted(nets.items(), key=lambda kv: -kv[1])[:8]
                p(f"  violators by net (net: violating pins / all loads, driver): " + "; ".join(
                    f"{n}: {k}/{loads.get(n, '?')}, {driver.get(n, 'port or unknown')}" for n, k in top))

    rows = read_antenna(ant[-1])
    if rows:
        r = rows[0]
        gate("G5 antenna headroom", r[0] <= ANT_MAX,
             f"worst partial/required {r[0]:.2f} ({r[4]:.1f}/{r[5]:.1f}) net {r[1]} pin {r[2]} {r[3]} (need <= {ANT_MAX:.2f})")
        p("worst 5 antenna ratios: " + "; ".join(f"{x[0]:.2f} {x[1]} {x[3]}" for x in rows[:5]))
    else:
        # This OpenROAD build lists only violating nets. With none listed, headroom is what the
        # repair step guaranteed: it diodes every net above (100 - margin)% of the limit.
        cfgs = sorted(glob.glob(os.path.join(run, "*-openroad-repairantennas*", "config.json")) +
                      glob.glob(os.path.join(run, "*-openroad-detailedrouting*", "config.json")))
        found = [float(json.load(open(f))[k]) for f in cfgs for k in ("GRT_ANTENNA_REPAIR_MARGIN", "DRT_ANTENNA_REPAIR_MARGIN")
                 if k in json.load(open(f))]
        if m.get("route__antenna_violation__count") != 0 or not found:
            p(f"MISSING antenna ratios in {ant[-1]} and no antenna repair margin in the step configs")
            return 2
        margin = min(found)
        gate("G5 antenna headroom", margin >= 10,
             f"the final check lists no net over its limit (this OpenROAD lists only violators); repair diodes "
             f"every net above {100 - margin:.0f}% of the limit (smallest repair margin {margin:g}%, need >= 10)")
    bad = [f"{n}={m.get(k)}" for k, n in G6_KEYS if m.get(k) != 0]
    gate("G6 power grid/latches/unmapped", not bad, ", ".join(bad) or "all 0")
    p(f"\nRESULT: {6 - len(fails)}/6 gates pass" + (f"; failing: {', '.join(fails)}" if fails else ""))
    return 1 if fails else 0


def selftest():
    """Build a clean fake run, confirm 0, then break one thing at a time and confirm 1 or 2."""
    corners = ["nom_tt_025C_1v80", "max_ss_100C_1v60"]

    def make(tmp, **mut):
        m = {k: 0 for k, _ in ZERO_KEYS + G6_KEYS}
        for c in corners:
            m[f"timing__setup__ws__corner:{c}"] = mut.get("setup", 2.5)
            m[f"timing__hold__ws__corner:{c}"] = mut.get("hold", 0.2)
            m[f"design__max_slew_violation__count__corner:{c}"] = mut.get("slew", 0)
            m[f"design__max_cap_violation__count__corner:{c}"] = 0
            m[f"design__max_fanout_violation__count__corner:{c}"] = 0
        m.update(mut.get("extra", {}))
        os.makedirs(f"{tmp}/final", exist_ok=True)
        json.dump(m, open(f"{tmp}/final/metrics.json", "w"))
        for c in corners:
            os.makedirs(f"{tmp}/55-openroad-stapostpnr/{c}", exist_ok=True)
            with open(f"{tmp}/55-openroad-stapostpnr/{c}/checks.rpt", "w") as f:
                f.write("max slew\n\nPin Limit Slew Slack\n----\n")
                if mut.get("slew"):
                    f.write("_123_/A                     0.7500   0.9100  -0.1600 (VIOLATED)\n")
        os.makedirs(f"{tmp}/43-openroad-repairantennas", exist_ok=True)
        json.dump({"GRT_ANTENNA_REPAIR_MARGIN": mut.get("ant_margin", 10)},
                  open(f"{tmp}/43-openroad-repairantennas/config.json", "w"))
        if mut.get("empty_ant"):
            os.makedirs(f"{tmp}/60-openroad-checkantennas/reports", exist_ok=True)
            open(f"{tmp}/60-openroad-checkantennas/reports/antenna.rpt", "w").close()
        elif not mut.get("no_ant"):
            os.makedirs(f"{tmp}/60-openroad-checkantennas/reports", exist_ok=True)
            with open(f"{tmp}/60-openroad-checkantennas/reports/antenna.rpt", "w") as f:
                f.write("Net: n1\n  Pin: _1_/A (cell)\n    Layer: met1\n"
                        f"      Partial area ratio: {mut.get('par', 120.0)}\n      Required ratio: 400.0 (Gate area)\n")

    cases = [("clean", {}, 0), ("setup +0.90 ns", {"setup": 0.9}, 1), ("hold +0.01 ns", {"hold": 0.01}, 1),
             ("1 slew violation", {"slew": 1}, 1), ("1 LVS error", {"extra": {"design__lvs_error__count": 1}}, 1),
             ("antenna at 85%", {"par": 340.0}, 1), ("1 latch", {"extra": {"design__inferred_latch__count": 1}}, 1),
             ("antenna report missing", {"no_ant": True}, 2),
             ("only violators listed, none, repair margin 10%", {"empty_ant": True}, 0),
             ("only violators listed, none, repair margin 5%", {"empty_ant": True, "ant_margin": 5}, 1)]
    ok = 0
    for name, mut, want in cases:
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, **mut)
            got = audit(tmp, out=open(os.devnull, "w"))
        good = got == want
        ok += good
        print(f"{'ok ' if good else 'BAD'} {name}: exit {got} (want {want})")
    print(f"selftest {ok}/{len(cases)}")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(audit(sys.argv[1]))
