#!/usr/bin/env python3
"""views_synth.py — the real artifacts behind the linked SoC views (stage A: needs the PDK).

    python3 docs/tools/views_synth.py <sky130_fd_sc_hd dir>     write docs/views/{netlist,cells}.json
    python3 docs/tools/views_synth.py <sky130_fd_sc_hd dir> --check   rebuild in memory, compare, exit 1 on drift

What it runs, and nothing else:

  1. Yosys (same recipe as `make area`: syn/dont_use.py on the typical-corner
     liberty, then synth, dfflibmap, abc) on the RTL list in syn/synth_check.ys.
     Unlike `make area` it keeps the module hierarchy, so every gate stays
     inside the module that wrote it. Area is therefore a little different
     from the flattened number in the README; views.html says so.
  2. The sky130_fd_sc_hd liberty file, for every cell the netlist uses: pin
     directions, the Boolean function of each output, flip-flop behaviour, area.
  3. The sky130_fd_sc_hd SPICE netlist, for the same cells: every transistor
     (type, drain, gate, source, body, W, L).
  4. The sky130_fd_sc_hd GDS, for the same cells: the polygons of the
     layers a transistor is made of, and the pin labels; then a
     layout-versus-schematic run (views_lvs.py) that pairs every SPICE
     transistor with its gate in the layout.
  5. The state machines Yosys found and re-encoded, from its own log.

Everything is written sorted and rounded, so the same RTL and PDK give the
same bytes. Stage B (views_build.py) needs only these two files, Python and
the RTL, so CI can rebuild and check the page without a PDK.
"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_NET = os.path.join(ROOT, "docs", "views", "netlist.json")
OUT_CELLS = os.path.join(ROOT, "docs", "views", "cells.json")
CHIP = json.load(open(os.path.join(ROOT, "docs", "views", "chip.json")))
TOP = CHIP["top"]

# (gds layer, datatype) -> name, bottom to top. 64/20 n-well, 65/20 diffusion,
# 65/44 tap, 66/20 poly, 66/44 licon, 67/20 li1, 67/44 mcon, 68/20 met1,
# 93/44 nsdm (n+ implant), 94/20 psdm (p+ implant). Labels: 67/5 li1, 68/5 met1.
GDS_LAYERS = [((64, 20), "nwell"), ((93, 44), "nsdm"), ((94, 20), "psdm"), ((65, 20), "diff"),
              ((65, 44), "tap"), ((66, 20), "poly"), ((66, 44), "licon"), ((67, 20), "li1"),
              ((67, 44), "mcon"), ((68, 20), "met1")]
GDS_LABELS = [((67, 5), "li1"), ((68, 5), "met1"), ((67, 16), "li1"), ((68, 16), "met1")]


# --------------------------------------------------------------- liberty
def _blocks(text, kind):
    """Yield (name, body) for every `kind ("name") { ... }` at any depth."""
    for m in re.finditer(r'\b%s\s*\(([^)]*)\)\s*\{' % kind, text):
        depth, i = 1, m.end()
        while depth:
            c = text[i]
            depth += (c == "{") - (c == "}")
            i += 1
        yield m.group(1).strip().strip('"'), text[m.end():i - 1]


def parse_liberty(path, wanted):
    text = open(path).read()
    out = {}
    for name, body in _blocks(text, "cell"):
        if name not in wanted:
            continue
        cell = {"area": float(re.search(r"\barea\s*:\s*([\d.]+)", body).group(1)), "pins": {}}
        for kind in ("ff", "latch"):
            for _, fb in _blocks(body, kind):
                seq = {"kind": kind}
                for k in ("next_state", "clocked_on", "clear", "preset", "enable", "data_in"):
                    m = re.search(r'\b%s\s*:\s*"([^"]*)"' % k, fb)
                    if m:
                        seq[k] = m.group(1)
                cell["seq"] = seq
        for pn, pb in _blocks(body, "pin"):
            d = re.search(r"\bdirection\s*:\s*\"?(\w+)", pb)
            f = re.search(r'\bfunction\s*:\s*"([^"]*)"', pb)
            pin = {"dir": d.group(1) if d else "input"}
            if f:
                pin["function"] = f.group(1)
            cell["pins"][pn] = pin
        out[name] = cell
    missing = sorted(set(wanted) - set(out))
    if missing:
        sys.exit(f"views_synth: liberty has no entry for {missing}")
    return out


# --------------------------------------------------------------- spice
def _num(s):
    """sky130 cell netlists are written by magic for a 1e-6 `scale` option:
    w=420000u means 420000e-6 * 1e-6 m = 0.42 um. Return microns."""
    s = s.lower()
    if s.endswith("u"):
        return round(float(s[:-1]) / 1e6, 4)
    return round(float(s) * 1e6, 4)


def parse_spice(path, wanted):
    lines, out, cur = [], {}, None
    for raw in open(path):
        raw = raw.rstrip("\n")
        if raw.startswith("+") and lines:
            lines[-1] += " " + raw[1:]
        else:
            lines.append(raw)
    for ln in lines:
        t = ln.split()
        if not t or t[0].startswith("*"):
            continue
        if t[0].lower() == ".subckt":
            cur = t[1] if t[1] in wanted else None
            if cur:
                out[cur] = {"ports": t[2:], "fets": []}
        elif t[0].lower() == ".ends":
            cur = None
        elif cur and t[0][0].upper() == "X":
            # Xname D G S B model w=.. l=..
            params = dict(p.lower().split("=", 1) for p in t if "=" in p)
            model = [p for p in t[1:] if "=" not in p][4]
            kind = "p" if "pfet" in model else "n" if "nfet" in model else None
            if kind is None:
                continue
            d, g, s, b = t[1:5]
            out[cur]["fets"].append({"name": t[0], "type": kind, "d": d, "g": g, "s": s, "b": b,
                                     "w": _num(params["w"]), "l": _num(params["l"]), "model": model})
    missing = sorted(set(wanted) - set(out))
    if missing:
        sys.exit(f"views_synth: spice has no subckt for {missing}")
    return out


# --------------------------------------------------------------- gds
def parse_gds(path, wanted):
    import klayout.db as db
    lay = db.Layout()
    lay.read(path)
    dbu = lay.dbu
    out = {}
    for name in sorted(wanted):
        cell = lay.cell(name)
        if cell is None:
            sys.exit(f"views_synth: gds has no cell {name}")
        bb = cell.dbbox()
        rec = {"bbox": [round(bb.left, 3), round(bb.bottom, 3), round(bb.right, 3), round(bb.top, 3)],
               "layers": {}, "labels": []}
        for (ln, dt), lname in GDS_LAYERS:
            li = lay.find_layer(ln, dt)
            if li is None:
                continue
            reg = db.Region(cell.begin_shapes_rec(li)).merged()
            polys = []
            for poly in reg.each():
                pts = [(round(p.x * dbu, 3), round(p.y * dbu, 3)) for p in poly.each_point_hull()]
                if poly.holes():
                    # holes are rare in std cells; keep the hull and say so in the data
                    rec.setdefault("holes", []).append(lname)
                polys.append(pts)
            polys.sort()
            if polys:
                rec["layers"][lname] = polys
        for (ln, dt), lname in GDS_LABELS:
            li = lay.find_layer(ln, dt)
            if li is None:
                continue
            it = cell.begin_shapes_rec(li)
            while not it.at_end():
                sh = it.shape()
                if sh.is_text():
                    t = sh.text.transformed(it.trans())
                    rec["labels"].append([t.string, lname, round(t.x * dbu, 3), round(t.y * dbu, 3)])
                it.next()
        rec["labels"] = sorted(set(map(tuple, rec["labels"])))
        rec["labels"] = [list(x) for x in rec["labels"]]
        out[name] = rec
    return out


# --------------------------------------------------------------- yosys
def yosys_netlist(lib):
    reads = [l for l in open(os.path.join(ROOT, "syn", "synth_check.ys")) if l.startswith("read_verilog")]
    with tempfile.TemporaryDirectory() as tmp:
        dlib = os.path.join(tmp, "dont_use.lib")
        subprocess.run([sys.executable, "syn/dont_use.py", lib, dlib], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        js = os.path.join(tmp, "net.json")
        script = "".join(reads) + f"""
hierarchy -check -top {TOP}
synth -top {TOP}
dfflibmap -liberty {dlib}
abc -liberty {dlib}
opt_clean -purge
write_json {js}
"""
        ys = os.path.join(tmp, "v.ys")
        open(ys, "w").write(script)
        log = os.path.join(tmp, "v.log")
        r = subprocess.run(["yosys", "-q", "-l", log, "-s", ys], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            sys.exit("views_synth: yosys failed\n" + r.stderr[-3000:])
        ver = subprocess.run(["yosys", "-V"], capture_output=True, text=True).stdout.strip()
        return json.load(open(js)), ver, parse_fsms(open(log).read())


def parse_fsms(log):
    """The state machines Yosys found, read from its own FSM_RECODE and FSM_INFO output.

    For each module: the RTL code of every state and the one-hot flip-flop bit
    synthesis gave it, the reset state, the FSM's input and output signals,
    and the transition table (from state, input cube, to state)."""
    fsms, cur, section, lines = {}, None, None, log.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"Recoding FSM `\$fsm\$\\?(\w+)\$\d+' from module `\\?(.+)' using `(\w+)' encoding:", ln)
        if m:
            f = fsms.setdefault(module_label(m.group(2)), {})
            f["wire"] = m.group(1)
            enc = re.search(r"to `([\w-]+)`", lines[i + 1])
            f["encoding"] = enc.group(1) if enc else m.group(3)
            f["codes"] = []
            i += 2
            while i < len(lines) and re.match(r"\s+[01]+ -> [-01]+$", lines[i]):
                code, oh = lines[i].split(" -> ")
                code, oh = code.strip(), oh.strip()
                f["codes"].append({"rtl": int(code, 2), "bits": len(code), "onehot_bit": len(oh) - 1 - oh.index("1")})
                i += 1
            continue
        m = re.match(r"FSM `\$fsm\$\\?\w+\$\d+' from module `\\?(.+)':$", ln)
        if m:
            cur = fsms.setdefault(module_label(m.group(1)), {})
            cur.update({"inputs": [], "outputs": [], "states": [], "transitions": []})
            section = None
        elif cur is not None:
            t = ln.strip()
            if t.startswith("Input signals:"):
                section = "inputs"
            elif t.startswith("Output signals:"):
                section = "outputs"
            elif t.startswith("State encoding:"):
                section = "states"
            elif t.startswith("Transition Table"):
                section = "transitions"
            elif re.match(r"-{20,}$", t) and cur.get("transitions"):
                cur, section = None, None
            elif section in ("inputs", "outputs"):
                mm = re.match(r"(\d+): (.+)$", t)
                if mm:
                    cur[section].append(mm.group(2).strip())
            elif section == "states":
                mm = re.match(r"(\d+):\s+\d+'([-01]+)(\s+<RESET STATE>)?$", t)
                if mm:
                    cur["states"].append({"index": int(mm.group(1)), "pattern": mm.group(2), "reset": bool(mm.group(3))})
            elif section == "transitions":
                mm = re.match(r"\d+:\s+(\d+) \d+'([-01]+)\s+->\s+(\d+) \d+'([-01]+)$", t)
                if mm:
                    cur["transitions"].append({"from": int(mm.group(1)), "when": mm.group(2),
                                               "to": int(mm.group(3)), "out": mm.group(4)})
        i += 1
    return dict(sorted(fsms.items()))


def module_label(name):
    """$paramod$hash\\sync_compare -> sync_compare; $paramod\\tp_ncore\\RESET_PC=.. -> tp_ncore."""
    if name.startswith("$paramod"):
        return name.split("\\")[1]
    return name


def compact(yj):
    """Keep what the views use: per module, ports, named nets, and cells with their pins."""
    mods = {}
    for raw, m in yj["modules"].items():
        if m.get("attributes", {}).get("blackbox"):
            continue
        name = module_label(raw)
        nets = {}
        for nn, n in m["netnames"].items():
            if nn.startswith("$") or n.get("hide_name"):
                continue
            nets[nn] = {"bits": n["bits"]}
            if "src" in n.get("attributes", {}):
                nets[nn]["src"] = n["attributes"]["src"]
        cells = {}
        for cn, c in m["cells"].items():
            rec = {"type": module_label(c["type"]), "pins": {p: b for p, b in sorted(c["connections"].items())}}
            if "src" in c.get("attributes", {}):
                rec["src"] = c["attributes"]["src"]
            cells[cn] = rec
        # Stable cell names: abc names carry run-specific counters; renumber by
        # type and first output bit so two runs of the same netlist give the same ids.
        ports = {pn: {"dir": p["direction"], "bits": p["bits"]} for pn, p in sorted(m["ports"].items())}
        mods[name] = {"ports": ports, "nets": dict(sorted(nets.items())), "cells": cells}
    return mods


def stable_names(mods, lib):
    for m in mods.values():
        renamed = {}
        def key(item):
            cn, c = item
            outs = []
            info = lib.get(c["type"])
            for p, bits in c["pins"].items():
                if info is None or info["pins"].get(p, {}).get("dir") == "output":
                    outs += [b for b in bits if not isinstance(b, str)]
            return (c["type"], min(outs) if outs else 0, cn if not cn.startswith("$") else "")
        n = 0
        for cn, c in sorted(m["cells"].items(), key=key):
            if cn.startswith("$"):
                short = c["type"].replace("sky130_fd_sc_hd__", "")
                nm = f"g{n}_{short}"
                n += 1
            else:
                nm = cn.lstrip("\\")
            renamed[nm] = c
        m["cells"] = dict(sorted(renamed.items()))
    return mods


def build(pdk):
    lib = os.path.join(pdk, "lib", "sky130_fd_sc_hd__tt_025C_1v80.lib")
    yj, ver, fsms = yosys_netlist(lib)
    mods = compact(yj)
    used = sorted({c["type"] for m in mods.values() for c in m["cells"].values() if c["type"].startswith("sky130_")})
    libinfo = parse_liberty(lib, set(used))
    mods = stable_names(mods, libinfo)
    spice = parse_spice(os.path.join(pdk, "spice", "sky130_fd_sc_hd.spice"), set(used))
    gds = parse_gds(os.path.join(pdk, "gds", "sky130_fd_sc_hd.gds"), set(used))
    net = {"tool": ver, "recipe": "syn/dont_use.py + synth (hierarchy kept) + dfflibmap + abc, typical corner liberty",
           "top": TOP, "modules": dict(sorted(mods.items())), "fsms": fsms}
    cells = {"pdk": "sky130A sky130_fd_sc_hd (open_pdks 1.0.471)", "cells": {
        c: {"liberty": libinfo[c], "spice": spice[c], "gds": gds[c]} for c in used}}
    # layout versus schematic on every cell; each transistor learns where its gate is
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import views_lvs
    for name, c in cells["cells"].items():
        ok, where = views_lvs.lvs(name, c)
        if not ok:
            sys.exit(f"views_synth: {name}: layout and SPICE netlist do not match (views_lvs)")
        for f in c["spice"]["fets"]:
            f["at"] = where[f["name"]]
    return net, cells


def dump(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":")) + "\n"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    net, cells = build(args[0])
    if "--check" in sys.argv:
        bad = [p for p, o in ((OUT_NET, net), (OUT_CELLS, cells))
               if not os.path.exists(p) or open(p).read() != dump(o)]
        if bad:
            sys.exit("views_synth --check: out of date: " + ", ".join(os.path.relpath(p, ROOT) for p in bad))
        print("views_synth --check: netlist.json and cells.json match the RTL and PDK")
        return
    os.makedirs(os.path.dirname(OUT_NET), exist_ok=True)
    open(OUT_NET, "w").write(dump(net))
    open(OUT_CELLS, "w").write(dump(cells))
    n = sum(len(m["cells"]) for m in net["modules"].values())
    print(f"docs/views/netlist.json: {len(net['modules'])} modules, {n} cells; "
          f"docs/views/cells.json: {len(cells['cells'])} cell types")


if __name__ == "__main__":
    main()
