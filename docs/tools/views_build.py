#!/usr/bin/env python3
"""views_build.py — the data behind the "Inside a gate" page (stage B: no PDK needed).

    python3 docs/tools/views_build.py           write docs/site/data/views.json and docs/site/pages/views.html
    python3 docs/tools/views_build.py --check   fail if either is out of date

The page template is put together here from docs/views/page.html (the
words), views.css and views.js, with the numbers and a static fallback
(for readers without JavaScript) filled in from the same data;
docs/tools/build_site.py then turns it into docs/site/views.html.

Reads only files in the repository:
  docs/views/netlist.json   the gate netlist, per module, and the state machines (views_synth.py)
  docs/views/cells.json     every cell's liberty function, transistors and layout (views_synth.py)
  docs/views/isa.json       the RISC-V instruction table, assembled (views_isa.py)
  src/**/*.sv               the RTL, for the source view and every link into it

and writes one JSON file that docs/site/pages/views.html draws. Everything a
reader can click is a "viewing point" with an id, and every id this file
mentions resolves: test/views/check_views.py proves that.

Five views of one design:
  rtl     the SystemVerilog, line by line
  gates   each register's logic cone: the sky130 cells that compute its next
          value, laid out left (inputs) to right (the flip-flops)
  cell    one standard cell as transistors, with a truth table the page
          computes by switch-level simulation (the same rules views_switch.py
          checks against the liberty file)
  layout  the same cell's polygons, layer by layer, each transistor's gate
          marked where layout-versus-schematic found it
  fsm     the state machines Yosys extracted, in RTL encoding and in the
          one-hot flip-flops synthesis turned them into
"""
import collections, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "site", "data", "views.json")
PAGE = os.path.join(ROOT, "docs", "site", "pages", "views.html")
html_esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
MAX_DRAW = 180          # largest cone drawn in full; bigger ones show the gates nearest the flip-flops
FF = "sky130_fd_sc_hd__dfxtp_1"


def load(p):
    return json.load(open(os.path.join(ROOT, p)))


def rtl_files():
    return [l.split()[-1] for l in open(os.path.join(ROOT, "syn", "synth_check.ys")) if l.startswith("read_verilog")]


def short(t):
    return t.replace("sky130_fd_sc_hd__", "")


# ------------------------------------------------------------------ RTL helpers
def module_spans(files):
    """module name -> (file, first line, last line)."""
    spans = {}
    for f in files:
        lines = open(os.path.join(ROOT, f)).read().split("\n")
        cur = None
        for i, ln in enumerate(lines, 1):
            m = re.match(r"\s*module\s+(\w+)", ln)
            if m:
                cur = (m.group(1), i)
            if re.match(r"\s*endmodule\b", ln) and cur:
                spans[cur[0]] = (f, cur[1], i)
                cur = None
    return spans


def strip_comment(ln):
    return ln.split("//", 1)[0]


def assign_lines(lines, lo, hi, name):
    """Lines in [lo, hi] that assign `name` (nonblocking, blocking or continuous)."""
    pat = re.compile(r"(?<![\w.])%s\b(\s*\[[^\]]*\])*\s*(<=|=(?!=))" % re.escape(name))
    cont = re.compile(r"\bassign\s+%s\b" % re.escape(name))
    out = []
    for i in range(lo, hi + 1):
        code = strip_comment(lines[i - 1])
        if cont.search(code) or (pat.search(code) and not re.search(r"\b(if|while|for)\s*\(.*%s\s*<=" % re.escape(name), code)
                                 and not re.search(r"(==|!=|>=|<=)\s*%s\b" % re.escape(name), code.split("<=")[0] if "<=" in code else "")):
            out.append(i)
    return out


def decl_line(net):
    m = re.match(r".*:(\d+)\.", net.get("src", ""))
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ cones
def cell_dirs(cells_lib, ctype):
    if ctype in cells_lib:
        return {p: i["dir"] for p, i in cells_lib[ctype]["liberty"]["pins"].items()}
    return None


def module_graph(m, cells_lib, netlist):
    """bit -> driving (cell, pin); cell -> input bits; submodule cells use their module's port directions."""
    drv, ins = {}, collections.defaultdict(list)
    for cn, c in m["cells"].items():
        dirs = cell_dirs(cells_lib, c["type"])
        if dirs is None:
            sub = netlist["modules"][c["type"]]["ports"]
            dirs = {p: ("output" if sub[p]["dir"] == "output" else "input") for p in sub}
        for p, bits in c["pins"].items():
            for b in bits:
                if isinstance(b, str):
                    continue
                if dirs.get(p) == "output":
                    drv[b] = (cn, p)
                else:
                    ins[cn].append((p, b))
    return drv, ins


def cone(start_bits, m, drv, ins, cells_lib):
    """Combinational cells feeding start_bits, stopping at flip-flops, submodules and ports."""
    seen, stack = set(), [b for b in start_bits if not isinstance(b, str)]
    while stack:
        b = stack.pop()
        d = drv.get(b)
        if d is None:
            continue
        cn = d[0]
        c = m["cells"][cn]
        if cn in seen or c["type"] == FF or c["type"] not in cells_lib:
            continue
        seen.add(cn)
        stack += [bb for _, bb in ins[cn]]
    return seen


def layered(group_cells, m, drv, ins, cells_lib, sinks):
    """Place a cone: column = longest path from the cone's inputs; rows by barycentre.
    Returns nodes [{id, kind, col, row}], edges [[src, dst, pin]] (indices), and how many cells were dropped."""
    members = set(group_cells) | set(sinks)
    # depth = longest path to a sink (sinks at 0), so a too-big cone keeps the
    # gates nearest its flip-flops and drops its far end
    succ = collections.defaultdict(set)
    for cn in members:
        for _, b in ins[cn]:
            d = drv.get(b) if not isinstance(b, str) else None
            if d and d[0] in members and d[0] != cn and d[0] not in sinks:
                succ[d[0]].add(cn)
    depth = {}
    sys.setrecursionlimit(10000)
    def dep(c):
        if c in depth:
            return depth[c]
        depth[c] = 0
        if c not in sinks:
            depth[c] = 1 + max((dep(x) for x in succ[c]), default=-1)
        return depth[c]
    for c in sorted(members):
        dep(c)
    kept = sorted(members, key=lambda c: (depth.get(c, 0), c))
    dropped = 0
    if len(kept) > MAX_DRAW:
        dropped = len(kept) - MAX_DRAW
        kept = kept[:MAX_DRAW]
    keep = set(kept)
    maxd = max((depth.get(c, 0) for c in kept), default=0)
    # inputs of the drawn cells that come from outside the drawing: one terminal per source net
    nodes, index = [], {}
    for cn in kept:
        index[cn] = len(nodes)
        nodes.append({"id": cn, "kind": "cell", "col": maxd - depth.get(cn, 0) + 1})
    edges, terms = [], {}
    bitname = {}
    for nn, n in m["nets"].items():
        for i, b in enumerate(n["bits"]):
            bitname.setdefault(b, nn + (f"[{i}]" if len(n["bits"]) > 1 else ""))
    for cn in kept:
        for p, b in sorted(ins[cn]):
            if cn in sinks and p == "CLK":
                continue
            d = drv.get(b) if not isinstance(b, str) else None
            if d and d[0] in keep and d[0] != cn and d[0] not in sinks:
                edges.append([index[d[0]], index[cn], p])
            else:
                if isinstance(b, str):
                    label = "constant " + b
                elif d and d[0] in m["cells"] and m["cells"][d[0]]["type"] == FF:
                    label = bitname.get(b, d[0] + ".Q")
                else:
                    label = bitname.get(b, f"net {b}")
                key = label
                if key not in terms:
                    terms[key] = len(nodes)
                    nodes.append({"id": "in:" + label, "kind": "in", "col": 0,
                                  "from": d[0] if d else None})
                edges.append([terms[key], index[cn], p])
    # rows: barycentre sweeps, deterministic
    cols = collections.defaultdict(list)
    for i, n in enumerate(nodes):
        cols[n["col"]].append(i)
    for c in cols:
        cols[c].sort(key=lambda i: nodes[i]["id"])
    preds = collections.defaultdict(list)
    succs = collections.defaultdict(list)
    for a, b, _ in edges:
        preds[b].append(a)
        succs[a].append(b)
    pos = {}
    for c in cols:
        for r, i in enumerate(cols[c]):
            pos[i] = r
    ncols = max(cols) + 1 if cols else 0
    for sweep in range(8):
        rng = range(1, ncols) if sweep % 2 == 0 else range(ncols - 2, -1, -1)
        for c in rng:
            nb = preds if sweep % 2 == 0 else succs
            def bary(i):
                ps = [pos[j] for j in nb[i] if j in pos]
                return (sum(ps) / len(ps)) if ps else pos[i]
            cols[c].sort(key=lambda i: (round(bary(i), 6), nodes[i]["id"]))
            for r, i in enumerate(cols[c]):
                pos[i] = r
    for i, n in enumerate(nodes):
        n["row"] = pos[i]
    return nodes, edges, dropped


def build_groups(mname, m, netlist, cells_lib, lines, span):
    drv, ins = module_graph(m, cells_lib, netlist)
    lo, hi = span[1], span[2]
    # register groups: flip-flops by the name of the net on their Q pin (preferring
    # a name the RTL assigns with <=), port groups: logic that drives an output port
    alias = collections.defaultdict(list)
    for nn, n in m["nets"].items():
        for i, b in enumerate(n["bits"]):
            alias[b].append((nn, i))
    def reg_name(qbit):
        names = alias.get(qbit, [])
        assigned = [n for n in names if assign_lines(lines, lo, hi, n[0])]
        pick = sorted(assigned or names, key=lambda x: (len(x[0]), x[0]))
        return pick[0] if pick else (None, 0)
    regs = collections.defaultdict(list)
    for cn, c in m["cells"].items():
        if c["type"] == FF:
            nm, bit = reg_name(c["pins"]["Q"][0])
            regs[nm or ("unnamed_" + cn)].append((bit, cn))
    groups = []
    for name, ffs in sorted(regs.items()):
        ffs.sort()
        sinks = [cn for _, cn in ffs]
        cells = cone([m["cells"][cn]["pins"]["D"][0] for cn in sinks], m, drv, ins, cells_lib)
        groups.append({"name": name, "kind": "register", "sinks": sinks, "cells": cells})
    for pn, p in sorted(m["ports"].items()):
        if p["dir"] != "output":
            continue
        bits = [b for b in p["bits"] if not isinstance(b, str)]
        cells = cone(bits, m, drv, ins, cells_lib)
        if cells:
            # the cells that drive the port bits directly are the drawing's sinks
            sinks = sorted({drv[b][0] for b in bits if b in drv and drv[b][0] in cells})
            groups.append({"name": pn, "kind": "output", "sinks": sinks, "cells": cells - set(sinks)})
    out = []
    for g in groups:
        nodes, edges, dropped = layered(g["cells"], m, drv, ins, cells_lib, g["sinks"])
        net = m["nets"].get(g["name"], {})
        rtl = sorted(set(assign_lines(lines, lo, hi, g["name"])) | ({decl_line(net)} if decl_line(net) else set()))
        out.append({"id": f"{mname}/{g['name']}", "module": mname, "name": g["name"], "kind": g["kind"],
                    "flops": len(g["sinks"]) if g["kind"] == "register" else 0,
                    "size": len(g["cells"]) + (len(g["sinks"])),
                    "dropped": dropped, "rtl": rtl,
                    "nodes": [[n["id"], n["kind"][0], n["col"], n["row"]] + ([n["from"]] if n.get("from") else []) for n in nodes],
                    "edges": edges,
                    "ctypes": [short(m["cells"][n["id"]]["type"]) if n["kind"] == "cell" else None for n in nodes]})
    return out


# ------------------------------------------------------------------ cells
def cell_entry(name, c):
    lib = c["liberty"]
    pins = {p: i["dir"] for p, i in sorted(lib["pins"].items())}
    funcs = {p: i["function"] for p, i in sorted(lib["pins"].items()) if "function" in i}
    fets = [[f["name"], f["type"], f["g"], f["d"], f["s"], f["w"], f["l"], f["at"][0], f["at"][1], f["model"].replace("sky130_fd_pr__", "")]
            for f in c["spice"]["fets"]]
    g = c["gds"]
    return {"area": lib["area"], "pins": pins, "function": funcs, "seq": lib.get("seq"),
            "ports": c["spice"]["ports"], "fets": fets, "bbox": g["bbox"],
            "layers": {k: [[[round(x, 3), round(y, 3)] for x, y in poly] for poly in v] for k, v in sorted(g["layers"].items())},
            "labels": g["labels"]}


# ------------------------------------------------------------------ FSMs
def fsm_entry(mod, f, lines, span, groups_by_id, m):
    lo, hi = span[1], span[2]
    # state names: localparams in the module whose value is an RTL code
    names = {}
    for i in range(lo, hi + 1):
        mm = re.search(r"localparam\s+logic\s*\[\d+:0\]\s*(\w+)\s*=\s*\d+'d(\d+)", lines[i - 1])
        if mm:
            names.setdefault(int(mm.group(2)), (mm.group(1), i))
    bit_of_idx = {st["index"]: len(st["pattern"]) - 1 - st["pattern"].index("1") for st in f["states"]}
    idx_of_bit = {v: k for k, v in bit_of_idx.items()}
    code_of_idx = {idx_of_bit[c["onehot_bit"]]: c["rtl"] for c in f["codes"]}
    reset = next(st["index"] for st in f["states"] if st["reset"])
    # the arm of `case (state)` for each state, and the lines inside it that set the state
    arms, cur = {}, None
    case_lo = next((i for i in range(lo, hi + 1) if re.search(r"case\s*\(\s*%s\s*\)" % f["wire"], lines[i - 1])), None)
    if case_lo:
        depth = 0
        for i in range(case_lo, hi + 1):
            code = strip_comment(lines[i - 1])
            mm = re.match(r"\s*(\w+)\s*:", code)
            if mm and any(mm.group(1) == n for n, _ in names.values()) and depth <= 1:
                cur = mm.group(1)
                arms[cur] = [i, i]
            elif mm and mm.group(1) == "default" and depth <= 1:
                cur = None
            if cur:
                arms[cur][1] = i
            depth += code.count("begin") - len(re.findall(r"\bend\b", code))
            if re.search(r"\bendcase\b", code):
                break
    # assignments to the state outside the case statement: the reset branch
    reset_lines = [i for i in range(lo, (case_lo or hi)) if re.search(r"\b%s\s*<=" % f["wire"], strip_comment(lines[i - 1]))]
    sets = collections.defaultdict(list)
    for st, (a, b) in arms.items():
        for i in range(a, b + 1):
            mm = re.search(r"\b%s\s*<=\s*([^;]+);" % f["wire"], strip_comment(lines[i - 1]))
            if mm:
                sets[st].append((i, mm.group(1).strip()))
    # gate side: the flip-flop that holds each one-hot bit
    flop_of_bit = {}
    for g in groups_by_id.values():
        if g["module"] == mod and g["name"] == f["wire"]:
            for cn in [n[0] for n in g["nodes"] if n[1] == "c" and m["cells"][n[0]]["type"] == FF]:
                flop_of_bit[alias_bit(m, cn, f["wire"])] = cn
    states = []
    for idx in sorted(code_of_idx):
        code = code_of_idx[idx]
        nm, line = names.get(code, (f"S{code}", None))
        arm = arms.get(nm)
        states.append({"index": idx, "code": code, "name": nm, "bits": f["codes"][0]["bits"],
                       "onehot": bit_of_idx[idx], "flop": flop_of_bit.get(bit_of_idx[idx]),
                       "reset": idx == reset, "decl": line, "arm": arm})
    by_name = {s["name"]: s for s in states}
    inputs = [s.lstrip("\\") for s in f["inputs"]]
    edges = collections.OrderedDict()
    for t in f["transitions"]:
        key = (t["from"], t["to"])
        conds = []
        for i, ch in enumerate(reversed(t["when"])):
            if ch != "-":
                conds.append(("" if ch == "1" else "!") + pretty_sig(inputs[i], lines))
        edges.setdefault(key, []).append(" && ".join(conds) or "always")
    out_edges = []
    for (a, b), conds in edges.items():
        fa = next(s for s in states if s["index"] == a)
        fb = next(s for s in states if s["index"] == b)
        rtl = [i for i, rhs in sets.get(fa["name"], []) if re.search(r"\b%s\b" % fb["name"], rhs)]
        if "rst" in conds and fb["reset"]:
            rtl += reset_lines
        out_edges.append({"from": a, "to": b, "when": conds, "rtl": sorted(set(rtl))})
    return {"module": mod, "wire": f["wire"], "encoding": f["encoding"], "states": states,
            "edges": out_edges, "inputs": inputs, "case": case_lo, "reset_lines": reset_lines}


def alias_bit(m, cn, wire):
    q = m["cells"][cn]["pins"]["Q"][0]
    bits = m["nets"].get(wire, {}).get("bits", [])
    return bits.index(q) if q in bits else None


def pretty_sig(s, lines):
    """$eq$src/core/tp_ncore.sv:177$784_Y -> 'line 177: <the expression>'."""
    mm = re.match(r"\$(\w+)\$(src/[\w/.]+):(\d+)\$\d+_Y", s)
    if not mm:
        return s
    op = {"eq": "==", "ne": "!=", "logic_or": "||", "logic_and": "&&", "lt": "<", "le": "<=",
          "gt": ">", "ge": ">=", "reduce_or": "|", "reduce_and": "&", "logic_not": "!"}.get(mm.group(1), mm.group(1))
    return f"[{op} on line {mm.group(3)}]"


# ------------------------------------------------------------------ hierarchy
def hierarchy(netlist, top):
    out = []
    def walk(mod, path, depth):
        m = netlist["modules"][mod]
        n_cells = sum(1 for c in m["cells"].values() if c["type"].startswith("sky130_"))
        out.append({"path": path, "module": mod, "depth": depth, "cells": n_cells})
        for cn, c in sorted(m["cells"].items()):
            if c["type"] in netlist["modules"]:
                walk(c["type"], path + "." + cn, depth + 1)
    walk(top, top, 0)
    return out


def links_between(netlist, mod):
    """Bits shared between sibling submodules inside `mod` (the connection graph)."""
    m = netlist["modules"][mod]
    owner = collections.defaultdict(set)
    for cn, c in m["cells"].items():
        if c["type"] in netlist["modules"]:
            for bits in c["pins"].values():
                for b in bits:
                    if not isinstance(b, str):
                        owner[b].add(cn)
    pairs = collections.Counter()
    for b, os_ in owner.items():
        os_ = sorted(os_)
        for i in range(len(os_)):
            for j in range(i + 1, len(os_)):
                pairs[(os_[i], os_[j])] += 1
    return [[a, b, n] for (a, b), n in sorted(pairs.items())]


def isa_decode_lines(isa, src, f):
    """Each instruction row gets the decoder line(s) that use its opcode constant (tp_pkg::OPC_X)."""
    rows = []
    for r in isa["rows"]:
        hits = [i + 1 for i, ln in enumerate(src[f]) if re.search(r"tp_pkg::%s\b" % r["opc"], strip_comment(ln))]
        rows.append(dict(r, rtl=[f, hits]))
    return dict(isa, rows=rows)


# ------------------------------------------------------------------ main
def build():
    netlist = load("docs/views/netlist.json")
    cells_doc = load("docs/views/cells.json")
    cells_lib = cells_doc["cells"]
    chip = load("docs/views/chip.json")
    isa = load("docs/views/isa.json") if chip.get("isa") else None
    files = rtl_files()
    spans = module_spans(files)
    src = {f: open(os.path.join(ROOT, f)).read().rstrip("\n").split("\n") for f in files}
    if isa:
        isa = isa_decode_lines(isa, src, chip["isa"]["decoder"])
    modules, groups = {}, {}
    for mname, m in sorted(netlist["modules"].items()):
        f, lo, hi = spans[mname]
        gs = build_groups(mname, m, netlist, cells_lib, src[f], spans[mname])
        for g in gs:
            groups[g["id"]] = g
        area = sum(cells_lib[c["type"]]["liberty"]["area"] for c in m["cells"].values() if c["type"] in cells_lib)
        types = collections.Counter(short(c["type"]) for c in m["cells"].values() if c["type"] in cells_lib)
        modules[mname] = {"file": f, "lines": [lo, hi], "cells": sum(types.values()), "area": round(area, 2),
                          "flops": types.get("dfxtp_1", 0), "types": dict(sorted(types.items())),
                          "groups": [g["id"] for g in gs],
                          "links": links_between(netlist, mname)}
    fsms = [fsm_entry(mod, f, src[spans[mod][0]], spans[mod], groups, netlist["modules"][mod])
            for mod, f in sorted(netlist["fsms"].items())]
    used = sorted({short(c["type"]) for m in netlist["modules"].values() for c in m["cells"].values() if c["type"] in cells_lib})
    out = {
        "about": {"synthesis": netlist["tool"], "recipe": netlist["recipe"], "pdk": cells_doc["pdk"],
                  "cells": sum(mm["cells"] for mm in modules.values()),
                  "area": round(sum(mm["area"] for mm in modules.values()), 1),
                  "transistors": sum(len(cells_lib["sky130_fd_sc_hd__" + t]["spice"]["fets"]) * sum(mm["types"].get(t, 0) for mm in modules.values()) for t in used),
                  "max_draw": MAX_DRAW},
        "files": src,
        "modules": modules,
        "hierarchy": hierarchy(netlist, netlist["top"]),
        "groups": groups,
        "celltypes": {short(k): cell_entry(k, v) for k, v in sorted(cells_lib.items())},
        "fsms": fsms,
        "isa": isa,
        "chip": {"top": chip["top"], "start": chip["start"], "links_root": chip["links_root"],
                 "isa_module": chip["isa"]["module"] if chip.get("isa") else None},
    }
    return out


def dump(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":")) + "\n"


# ------------------------------------------------------------------ the page template
def noscript(d):
    """What a reader without JavaScript sees: the modules, the state machines, the ISA lens, as tables."""
    out = ["<div class=vw-static>", "<p>The interactive views need JavaScript. The same data, as tables:</p>",
           "<h3>Modules</h3><table><tr><th>instance</th><th>module</th><th>cells</th><th>area (µm²)</th><th>flip-flops</th></tr>"]
    for n in d["hierarchy"]:
        m = d["modules"][n["module"]]
        out.append(f"<tr><td><code>{html_esc(n['path'])}</code></td><td>{n['module']}</td><td>{m['cells']:,}</td><td>{m['area']:,.2f}</td><td>{m['flops']}</td></tr>")
    out.append("</table>")
    for F in d["fsms"]:
        out.append(f"<h3>State machine {F['module']}.{F['wire']}</h3><table><tr><th>state</th><th>RTL code</th><th>one-hot flip-flop</th><th>goes to</th></tr>")
        name = {st["index"]: st["name"] for st in F["states"]}
        for st in F["states"]:
            to = sorted({name[e["to"]] for e in F["edges"] if e["from"] == st["index"]})
            out.append(f"<tr><td>{st['name']}{' (reset)' if st['reset'] else ''}</td><td>{st['code']}</td><td>{st['onehot']}</td><td>{', '.join(to)}</td></tr>")
        out.append("</table>")
    if d["isa"]:
        out.append("<h3>RISC-V instructions</h3><table><tr><th>instruction</th><th>encoding</th><th>what it does</th></tr>")
        for r in d["isa"]["rows"]:
            out.append(f"<tr><td><code>{html_esc(r['rv'])}</code></td><td><code>{r['rv_hex']}</code></td><td>{html_esc(r['note'])}</td></tr>")
        out.append("</table>")
    out.append("</div>")
    return "\n".join(out)


def page(d):
    src = open(os.path.join(ROOT, "docs", "views", "page.html")).read()
    a = d["about"]
    facts = {"cells": f"{a['cells']:,}", "area": f"{a['area']:,.1f}", "transistors": f"{a['transistors']:,}",
             "celltypes": str(len(d["celltypes"])), "yosys": a["synthesis"].split()[1] if len(a["synthesis"].split()) > 1 else a["synthesis"],
             "noscript": noscript(d)}
    def sub(mm):
        if mm.group(1) not in facts:
            sys.exit(f"views_build: docs/views/page.html: unknown {{{{v:{mm.group(1)}}}}}")
        return facts[mm.group(1)]
    body = re.sub(r"\{\{v:(\w+)\}\}", sub, src)
    css = open(os.path.join(ROOT, "docs", "views", "views.css")).read()
    js = open(os.path.join(ROOT, "docs", "views", "views.js")).read()
    if "</script" in js:
        sys.exit("views_build: views.js must not contain </script")
    head = ("<!-- generated by docs/tools/views_build.py from docs/views/page.html, views.css and views.js; edit those, not this file -->\n")
    # build_site.py keeps the JSON comment first; the generated note goes after it
    first = body.index("-->") + 3
    return body[:first] + "\n" + head + "<style>\n" + css + "</style>" + body[first:] + "<script>\n" + js + "</script>\n"


def main():
    d = build()
    outs = {OUT: dump(d), PAGE: page(d)}
    if "--check" in sys.argv:
        stale = [os.path.relpath(p, ROOT) for p, t in outs.items() if not os.path.exists(p) or open(p).read() != t]
        if stale:
            sys.exit("views_build --check: out of date: " + ", ".join(stale) + "; run python3 docs/tools/views_build.py")
        print("views_build --check: views.json and the page template are up to date")
        return
    for p, t in outs.items():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(t)
        print(f"{os.path.relpath(p, ROOT)}: {len(t) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
