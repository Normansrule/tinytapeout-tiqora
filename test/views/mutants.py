#!/usr/bin/env python3
"""mutants.py — break each link of the views chain on purpose; the check for that link must fail.

    python3 test/views/mutants.py [--quick]     (after `make -C test views-lockstep`, which leaves the FSM logs)

Every mutant runs in a fresh copy of the repository (no .git), so the
working tree is never touched. A mutant "survives" when the check that
should catch it passes anyway; any survivor fails this script.

  rtl-tx-idle       RTL: the line chip.json names edited (Tiqora: the UART
                    idles low; Serial: transmitted bits inverted)     -> lockstep (gates no longer equal RTL)
  netlist-gate      gate netlist: one gate in the UART's output cone
                    swapped for another with the same pins            -> lockstep (on chip.json's "sends" run, which transmits)
  rtl-stale         RTL: a comment edited, data not rebuilt           -> views_build --check
  spice-gate-net    SPICE: a transistor's gate on the wrong net       -> views_switch, views_lvs
  spice-width       SPICE: a transistor's width changed               -> views_lvs, mini_lvs
  gds-drop-licon    layout: input A's polysilicon contact removed     -> views_lvs (pin-name check)
  gds-drop-poly     layout: one polysilicon gate removed              -> views_lvs, mini_lvs
  liberty-func      liberty: nand2 described as a nor2                -> views_switch
  ff-no-hold        liberty-derived flip-flop behaviour vs transistors:
                    the flip-flop's feedback transistor removed       -> views_switch
  fsm-edge          state diagram: one transition the chip takes deleted -> fsm_check
  fsm-onehot        state diagram: two states' one-hot bits swapped   -> fsm_check
  fsm-coverage**    lockstep suite: the run that alone takes some arrow left
                    out, or else only the first run kept (coverage drops
                    below chip.json fsm_gaps)                         -> fsm_check (gap gate)
  link-rtl-line     page data: a register points at the wrong RTL line -> check_views
  link-state-flop   page data: a state points at another flip-flop    -> check_views
  link-isa-line*    page data: an instruction points at the wrong decode line -> check_views
  isa-opcode*       lens: a row names the wrong opcode constant       -> views_isa --check
  pkg-opcode*       tp_pkg: an opcode constant changed                -> views_isa --check
  page-pmos         page: the browser's simulator turns PMOS on at 1  -> page_test.js (Playwright)

* only on a chip with a processor (chip.json "isa"); Tiqora-Serial has none.
** only on a chip whose chip.json lists "fsm_gaps".
"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
QUICK = "--quick" in sys.argv
CHIP = json.load(open(os.path.join(ROOT, "docs", "views", "chip.json")))
MUT = CHIP["mutants"]


def jload(p):
    return json.load(open(p))


def jsave(p, d, compact=False):
    with open(p, "w") as fh:
        if compact:
            json.dump(d, fh, sort_keys=True, separators=(",", ":"))
        else:
            json.dump(d, fh, indent=1, sort_keys=True)
        fh.write("\n")


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def sub_file(path, old, new):
    s = open(path).read()
    if old not in s:
        raise RuntimeError(f"mutant anchor not found in {path}: {old!r}")
    open(path, "w").write(s.replace(old, new, 1))


# ------------------------------------------------------------------ mutations
def lockstep(cwd, run="quick"):
    """Build the RTL-versus-gates bench in the mutant's copy and run it (chip.json names the run)."""
    rtl = " ".join("../" + l.split()[-1] for l in open(os.path.join(cwd, "syn", "synth_check.ys")) if l.startswith("read_verilog"))
    models = " ".join(CHIP["lockstep"]["models"])
    return (f"cd test && mkdir -p views_mut && {PY} views/netlist_v.py views_mut G_ && "
            f"iverilog -g2012 -o views_mut/ls.vvp -s tb_lockstep {rtl} {models} views_mut/cells.v views_mut/netlist.v views/tb_lockstep.sv && "
            f"sh vv.sh views_mut/ls.vvp {CHIP['lockstep'][run]}")


def m_rtl_tx_idle(c):
    sub_file(os.path.join(c, MUT["rtl_file"]), MUT["rtl_from"], MUT["rtl_to"])
    return [lockstep(c)]


SWAP = {"nand2_1": "nor2_1", "nor2_1": "nand2_1", "a21oi_1": "o21ai_0", "o21ai_0": "a21oi_1", "and2_0": "or2_0", "or2_0": "and2_0"}


def m_netlist_gate(c):
    p = os.path.join(c, "docs/views/netlist.json")
    d = jload(p)
    m = d["modules"][MUT["cone_module"]]
    drv = {}
    for cn, cell in m["cells"].items():
        for pin, bits in cell["pins"].items():
            if pin in ("Y", "X", "Q"):
                for b in bits:
                    drv[b] = cn
    # walk back from the tx port to the nearest swappable gate
    todo, seen = list(m["ports"][MUT["cone_port"]]["bits"]), set()
    while todo:
        b = todo.pop(0)
        cn = drv.get(b)
        if cn is None or cn in seen:
            continue
        seen.add(cn)
        t = m["cells"][cn]["type"].replace("sky130_fd_sc_hd__", "")
        if t in SWAP:
            m["cells"][cn]["type"] = "sky130_fd_sc_hd__" + SWAP[t]
            jsave(p, d)
            # a run long enough to drive that output (chip.json "sends")
            return [lockstep(c, "sends")]
        todo += [bb for pin, bits in m["cells"][cn]["pins"].items() if pin not in ("Y", "X", "Q") for bb in bits]
    raise RuntimeError(f"no swappable gate in the cone of {MUT['cone_module']}.{MUT['cone_port']}")


def m_rtl_stale(c):
    sub_file(os.path.join(c, MUT["rtl_file"]), "module ", "// mutant\nmodule ")
    return [f"{PY} docs/tools/views_build.py --check"]


def cell(c, name):
    p = os.path.join(c, "docs/views/cells.json")
    d = jload(p)
    return p, d, d["cells"]["sky130_fd_sc_hd__" + name]


def m_spice_gate_net(c):
    p, d, k = cell(c, "nand2_1")
    f = next(f for f in k["spice"]["fets"] if f["type"] == "n" and f["g"] == "A")
    f["g"] = "B"
    jsave(p, d)
    return [f"{PY} docs/tools/views_switch.py", f"{PY} docs/tools/views_lvs.py"]


def m_spice_width(c):
    p, d, k = cell(c, "nor2_1")
    k["spice"]["fets"][0]["w"] = round(k["spice"]["fets"][0]["w"] * 2, 3)
    jsave(p, d)
    return [f"{PY} docs/tools/views_lvs.py", f"{PY} test/views/mini_lvs.py"]


def m_gds_drop_licon(c):
    p, d, k = cell(c, "nand2_1")
    # input A's only contact: the licon nearest A's pin label, which joins the li1
    # pin to the polysilicon gate (source and drain contacts come in rows, so
    # dropping one of those is redundant and rightly still passes LVS)
    L = k["gds"]["layers"]
    ax, ay = next((x, y) for lab, lay, x, y in k["gds"]["labels"] if lab == "A")
    def centre(poly):
        return sum(x for x, _ in poly) / len(poly), sum(y for _, y in poly) / len(poly)
    i = min(range(len(L["licon"])), key=lambda i: (centre(L["licon"][i])[0] - ax) ** 2 + (centre(L["licon"][i])[1] - ay) ** 2)
    del L["licon"][i]
    jsave(p, d)
    return [f"{PY} docs/tools/views_lvs.py"]


def m_gds_drop_poly(c):
    p, d, k = cell(c, "nand2_1")
    del k["gds"]["layers"]["poly"][0]
    jsave(p, d)
    return [f"{PY} docs/tools/views_lvs.py", f"{PY} test/views/mini_lvs.py"]


def m_liberty_func(c):
    p, d, k = cell(c, "nand2_1")
    out = next(pn for pn, i in k["liberty"]["pins"].items() if i["dir"] == "output")
    k["liberty"]["pins"][out]["function"] = "(!A&!B)"
    jsave(p, d)
    return [f"{PY} docs/tools/views_switch.py"]


def m_ff_no_hold(c):
    p, d, k = cell(c, "dfxtp_1")
    fets = k["spice"]["fets"]
    # remove every transistor whose gate is the stored node's complement in the slave latch:
    # the first transistor driven by Q's own internal node
    q_driver = next(f for f in fets if f["d"] == "Q" or f["s"] == "Q")
    inner = q_driver["g"]
    victims = [f for f in fets if f["d"] == inner or f["s"] == inner]
    fets.remove(victims[0])
    jsave(p, d)
    return [f"{PY} docs/tools/views_switch.py"]


def fsm_logs(c):
    logs = sorted(os.path.join(c, "test/views_gl", f) for f in os.listdir(os.path.join(c, "test/views_gl")) if f.startswith("fsm_"))
    if not logs:
        raise RuntimeError("no FSM logs: run make -C test views-lockstep first")
    return " ".join(logs)


def m_fsm_edge(c):
    p = os.path.join(c, "docs/views/netlist.json")
    d = jload(p)
    # drop the state change the runs take most often (a self-loop would hide in "staying put")
    taken = {}
    for log in fsm_logs(c).split():
        for line in open(log):
            mod, a, b, _ = line.split()
            if a != b:
                taken[(mod, int(a), int(b))] = taken.get((mod, int(a), int(b)), 0) + 1
    mod, a, b = max(sorted(taken), key=lambda k: taken[k])
    F = d["fsms"][mod]
    idx_of_bit = {len(st["pattern"]) - 1 - st["pattern"].index("1"): st["index"] for st in F["states"]}
    idx_of_code = {c_["rtl"]: idx_of_bit[c_["onehot_bit"]] for c_ in F["codes"]}
    i = next(i for i, t in enumerate(F["transitions"]) if (t["from"], t["to"]) == (idx_of_code[a], idx_of_code[b]))
    del F["transitions"][i]
    jsave(p, d)
    return [f"{PY} test/views/fsm_check.py {fsm_logs(c)}"]


def m_fsm_onehot(c):
    p = os.path.join(c, "docs/views/netlist.json")
    d = jload(p)
    codes = d["fsms"][sorted(d["fsms"])[0]]["codes"]
    codes[0]["onehot_bit"], codes[1]["onehot_bit"] = codes[1]["onehot_bit"], codes[0]["onehot_bit"]
    jsave(p, d)
    # check_views cannot see this one: the data stays self-consistent, only behaviour shows the lie
    return [f"{PY} test/views/fsm_check.py {fsm_logs(c)}"]


def m_fsm_coverage(c):
    # leave out the first run (by name) that is the only one to take some arrow
    sys.path.insert(0, os.path.join(c, "test/views"))
    import fsm_check
    fsms = jload(os.path.join(c, "docs/views/netlist.json"))["fsms"]
    logs = fsm_logs(c).split()

    def took(ls):
        return {m: r[0] for m, r in fsm_check.check(ls, fsms)[2].items()}
    full = took(logs)
    for drop in logs:
        if took([l for l in logs if l != drop]) != full:
            return [f"{PY} test/views/fsm_check.py " + " ".join(l for l in logs if l != drop)]
    # every arrow is taken by two runs or more (Tiqora-Serial): keep the first run only
    if took(logs[:1]) != full:
        return [f"{PY} test/views/fsm_check.py {logs[0]}"]
    raise RuntimeError("the first run alone takes every arrow: no smaller suite to try")


def views_json(c):
    return os.path.join(c, "docs/site/data/views.json")


def m_link_rtl_line(c):
    d = jload(views_json(c))
    g = d["groups"][CHIP["start"]["g"]]
    m = d["modules"][g["module"]]
    src = d["files"][m["file"]]
    base = g["name"].split("[")[0]
    wrong = next(ln for ln in range(m["lines"][0], m["lines"][1] + 1) if base not in src[ln - 1])
    g["rtl"] = [wrong] + g["rtl"][1:]                # a line of the module that does not name the register
    jsave(views_json(c), d, compact=True)
    return [f"{PY} test/views/check_views.py docs/site/data/views.json"]


def m_link_state_flop(c):
    d = jload(views_json(c))
    st = d["fsms"][0]["states"]
    st[0]["flop"], st[1]["flop"] = st[1]["flop"], st[0]["flop"]
    st[1]["flop"] = st[0]["flop"]                    # two states on one flip-flop
    jsave(views_json(c), d, compact=True)
    return [f"{PY} test/views/check_views.py docs/site/data/views.json"]


def m_link_isa_line(c):
    d = jload(views_json(c))
    r = d["isa"]["rows"][0]
    r["rtl"][1] = [r["rtl"][1][0] + 1]
    if d["isa"]["rows"][1]["opc"] in d["files"][r["rtl"][0]][r["rtl"][1][0] - 1]:
        r["rtl"][1] = [r["rtl"][1][0] + 5]
    jsave(views_json(c), d, compact=True)
    return [f"{PY} test/views/check_views.py docs/site/data/views.json"]


def m_isa_opcode(c):
    p = os.path.join(c, "docs/views/isa_lens.json")
    d = jload(p)
    row = next(r for r in d["rows"] if r["opc"] == "OPC_OP")
    row["opc"] = "OPC_OPIMM"
    jsave(p, d)
    return [f"{PY} docs/tools/views_isa.py --check"]


def m_pkg_opcode(c):
    p = os.path.join(c, "src/tp_pkg.sv")
    s = open(p).read()
    m = re.search(r"(localparam logic \[6:0\] OPC_LUI\s*=\s*7'b)([01]+)", s)
    flipped = m.group(2)[:-3] + ("0" if m.group(2)[-3] == "1" else "1") + m.group(2)[-2:]
    open(p, "w").write(s[:m.start(2)] + flipped + s[m.end(2):])
    return [f"{PY} docs/tools/views_isa.py --check"]


def m_page_pmos(c):
    sub_file(os.path.join(c, "docs/views/views.js"),
             'function on(f) { var g = val[f[2]]; return (f[1] === "n" && g === 1) || (f[1] === "p" && g === 0); }',
             'function on(f) { var g = val[f[2]]; return (f[1] === "n" && g === 1) || (f[1] === "p" && g === 1); }')
    return [f"{PY} docs/tools/views_build.py && {PY} docs/tools/build_site.py >/dev/null && node test/views/page_test.js"]


MUTANTS = [
    ("rtl-tx-idle", m_rtl_tx_idle), ("netlist-gate", m_netlist_gate), ("rtl-stale", m_rtl_stale),
    ("spice-gate-net", m_spice_gate_net), ("spice-width", m_spice_width),
    ("gds-drop-licon", m_gds_drop_licon), ("gds-drop-poly", m_gds_drop_poly),
    ("liberty-func", m_liberty_func), ("ff-no-hold", m_ff_no_hold),
    ("fsm-edge", m_fsm_edge), ("fsm-onehot", m_fsm_onehot), ("fsm-coverage", m_fsm_coverage),
    ("link-rtl-line", m_link_rtl_line), ("link-state-flop", m_link_state_flop), ("link-isa-line", m_link_isa_line),
    ("isa-opcode", m_isa_opcode), ("pkg-opcode", m_pkg_opcode), ("page-pmos", m_page_pmos),
]


ISA_ONLY = {"link-isa-line", "isa-opcode", "pkg-opcode"}


def has_playwright():
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    pw = has_playwright()
    caught = survived = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        shutil.copytree(ROOT, base, ignore=shutil.ignore_patterns(".git", "sim_build", "__pycache__", ".zig-cache*"), symlinks=True)
        # sanity: every check passes on the unmutated copy (otherwise "caught" would mean nothing)
        # (the lockstep runs too, so a mutant "caught" by lockstep cannot just mean the bench was already failing)
        base_checks = [f"{PY} docs/tools/views_build.py --check", f"{PY} test/views/check_views.py docs/site/data/views.json"]
        if CHIP.get("isa"):
            base_checks.append(f"{PY} docs/tools/views_isa.py --check")
        base_checks += [lockstep(base, run) for run in ("quick", "sends")]
        base_checks.append(f"{PY} test/views/fsm_check.py {fsm_logs(base)}")   # the FSM mutants need a passing start
        for chk in base_checks:
            rc, out = run(chk, base)
            if rc:
                print("FAIL baseline:", chk, "\n", out[-800:])
                sys.exit(1)
        for name, fn in MUTANTS:
            if only and name not in only:
                continue
            if name in ISA_ONLY and not CHIP.get("isa"):
                print(f"mutant {name:16s} not applicable (no processor on this chip)")
                continue
            if name == "fsm-coverage" and "fsm_gaps" not in CHIP:
                print(f"mutant {name:16s} not applicable (chip.json lists no fsm_gaps)")
                continue
            if name == "page-pmos" and not pw:
                print(f"mutant {name:16s} skipped (no Playwright)")
                skipped += 1
                continue
            if QUICK and name in ("page-pmos",):
                skipped += 1
                continue
            work = os.path.join(tmp, name)
            shutil.copytree(base, work, symlinks=True)
            try:
                cmds = fn(work)
            except Exception as e:  # a mutant that cannot be applied is a failure of this script
                print(f"FAIL mutant {name}: could not apply: {e}")
                survived += 1
                continue
            for cmd in cmds:
                rc, out = run(cmd, work)
                short = cmd.split("&&")[-1].strip().split()[1 if cmd.split("&&")[-1].strip().startswith(PY) else 0]
                if rc:
                    caught += 1
                    why = next((l.strip() for l in out.splitlines() if re.search(r"FAIL|MISMATCH|differ|out of date|mismatch", l)), out.strip().splitlines()[-1] if out.strip() else "")
                    print(f"mutant {name:16s} caught by {os.path.basename(short):18s} {why[:110]}")
                else:
                    survived += 1
                    print(f"FAIL mutant {name} SURVIVED {cmd}")
            shutil.rmtree(work)
    print(f"views mutants: {caught} caught, {survived} survived, {skipped} skipped")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
