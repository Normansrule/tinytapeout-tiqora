#!/usr/bin/env python3
"""check_views.py — every viewing point on the "Inside a gate" page resolves, and means what it says.

    python3 test/views/check_views.py [views.json]

The page links RTL lines, registers, gates, transistors, layout positions,
states, transitions and instructions to each other by id. This checks every
one of those references against the data and against the source files:

  modules     each has its file and line span; its span starts with `module <name>`;
              its cell, flip-flop and area totals add up from its cells
  groups      every RTL line it lights names the register (or is its declaration);
              every node is a real cell of the module, of a type the page has;
              every edge joins two nodes; every input terminal that names a
              source flip-flop names a flip-flop of the same module
  cells       every transistor has a layout position inside the cell and a
              gate, drain and source; every pin the liberty file names exists
  fsms        every state's declaration line declares it with its code; its case
              arm starts with its name; its one-hot flip-flop is a flip-flop in
              the state register's group; every transition's RTL line assigns its
              target state; the reset state is the one the reset line loads
  isa         every row's decode line uses its opcode constant
  links       every connection joins two submodule instances of that module
  determinism views_build.py gives byte-identical output twice in a row
"""
import collections, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "docs", "tools"))


def check(d):
    err = []
    E = err.append
    files = d["files"]
    hier_paths = {n["path"]: n["module"] for n in d["hierarchy"]}
    ch = d["chip"]
    if ch["start"]["m"] not in d["modules"] or ch["start"]["g"] not in d["groups"]:
        E(f"chip: start {ch['start']} is not a module and group of the page")
    if ch["links_root"] not in d["modules"] or not d["modules"][ch["links_root"]]["links"]:
        E(f"chip: links_root {ch['links_root']} has no connections to draw")
    if bool(ch["isa_module"]) != bool(d["isa"]) or (ch["isa_module"] and ch["isa_module"] not in d["modules"]):
        E(f"chip: instruction module {ch['isa_module']} and instruction data disagree")
    if ch["top"] != d["hierarchy"][0]["module"]:
        E(f"chip: top {ch['top']} is not the hierarchy's root")
    for n in d["hierarchy"]:
        if n["module"] not in d["modules"]:
            E(f"hierarchy {n['path']}: module {n['module']} has no data")
    for mname, m in d["modules"].items():
        if m["file"] not in files:
            E(f"{mname}: file {m['file']} not in the page")
            continue
        lo, hi = m["lines"]
        if not re.match(r"\s*module\s+%s\b" % mname, files[m["file"]][lo - 1]):
            E(f"{mname}: line {lo} of {m['file']} does not start the module")
        if sum(m["types"].values()) != m["cells"]:
            E(f"{mname}: cell types add to {sum(m['types'].values())}, not {m['cells']}")
        area = sum(d["celltypes"][t]["area"] * n for t, n in m["types"].items())
        if abs(area - m["area"]) > 0.01:
            E(f"{mname}: area from cell types {area:.2f}, stored {m['area']}")
        if m["types"].get("dfxtp_1", 0) != m["flops"]:
            E(f"{mname}: flip-flop count differs from its dfxtp_1 cells")
        # links: both ends are instances inside this module
        for a, b, n in m["links"]:
            for x in (a, b):
                if not any(p.endswith("." + x) and hier_paths[p] != mname for p in hier_paths):
                    E(f"{mname}: link end {x} is not a submodule instance")
            if n <= 0:
                E(f"{mname}: link {a}-{b} has {n} wires")
        for gid in m["groups"]:
            if gid not in d["groups"]:
                E(f"{mname}: group {gid} missing")
    ff_of_module = collections.defaultdict(set)
    for gid, g in d["groups"].items():
        for n, ct in zip(g["nodes"], g["ctypes"]):
            if n[1] == "c" and ct == "dfxtp_1":
                ff_of_module[g["module"]].add(n[0])
    for gid, g in d["groups"].items():
        m = d["modules"][g["module"]]
        src = files[m["file"]]
        lo, hi = m["lines"]
        base = re.sub(r"\[\d+\]$", "", g["name"])
        for ln in g["rtl"]:
            if not lo <= ln <= hi:
                E(f"{gid}: RTL line {ln} outside {g['module']} ({lo}-{hi})")
            elif not re.search(r"\b%s\b" % re.escape(base), src[ln - 1]):
                E(f"{gid}: RTL line {ln} does not mention {base}: {src[ln - 1].strip()}")
        if len(g["ctypes"]) != len(g["nodes"]):
            E(f"{gid}: {len(g['ctypes'])} cell types for {len(g['nodes'])} nodes")
        ids = set()
        for n, ct in zip(g["nodes"], g["ctypes"]):
            if n[1] == "c":
                if ct not in d["celltypes"]:
                    E(f"{gid}: node {n[0]} has type {ct}, which the page has no data for")
                if not n[0].endswith("_" + ct):
                    E(f"{gid}: node {n[0]} is named for another type than {ct}")
                if n[0] in ids:
                    E(f"{gid}: node {n[0]} twice")
                ids.add(n[0])
            elif n[1] == "i":
                if ct is not None:
                    E(f"{gid}: input terminal {n[0]} has a cell type")
                if len(n) > 4 and n[4] not in ff_of_module[g["module"]] and not n[4].endswith("dfxtp_1"):
                    pass  # driven by a non-register cell outside the drawing: plain terminal
                if len(n) > 4 and n[4].endswith("_dfxtp_1") and n[4] not in ff_of_module[g["module"]]:
                    E(f"{gid}: input {n[0]} names flip-flop {n[4]}, which no group of {g['module']} draws")
            else:
                E(f"{gid}: node kind {n[1]}")
        nn = len(g["nodes"])
        for a, b, pin in g["edges"]:
            if not (0 <= a < nn and 0 <= b < nn) or g["nodes"][b][1] != "c":
                E(f"{gid}: edge {a}->{b} does not join two nodes into a gate")
            elif pin not in d["celltypes"][g["ctypes"][b]]["pins"]:
                E(f"{gid}: edge into {g['nodes'][b][0]} on pin {pin}, which {g['ctypes'][b]} lacks")
        if g["kind"] == "register" and sum(1 for ct in g["ctypes"] if ct == "dfxtp_1") != g["flops"]:
            E(f"{gid}: draws a different number of flip-flops than it holds")
        # every drawn gate has each input pin wired, unless the cone was cut
        if not g["dropped"]:
            into = collections.defaultdict(set)
            for a, b, pin in g["edges"]:
                into[b].add(pin)
            for i, (n, ct) in enumerate(zip(g["nodes"], g["ctypes"])):
                if n[1] != "c":
                    continue
                need = {p for p, dr in d["celltypes"][ct]["pins"].items() if dr == "input"} - {"CLK"}
                if need - into[i]:
                    E(f"{gid}: {n[0]} input(s) {sorted(need - into[i])} not drawn")
    for ct, T in d["celltypes"].items():
        x0, y0, x1, y1 = T["bbox"]
        nets = set()
        for f in T["fets"]:
            name, typ, g_, dr, s_, w, l, x, y = f[:9]
            nets |= {g_, dr, s_}
            if typ not in ("p", "n") or w <= 0 or l <= 0:
                E(f"{ct} {name}: type {typ}, W {w}, L {l}")
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                E(f"{ct} {name}: layout position ({x}, {y}) outside the cell")
        for p in T["pins"]:
            if p not in nets:
                E(f"{ct}: liberty pin {p} touches no transistor")
        for o, fn in T["function"].items():
            if T["pins"].get(o) != "output":
                E(f"{ct}: function for non-output {o}")
        labels = {l[0] for l in T["labels"]}
        for p in T["pins"]:
            if p not in labels:
                E(f"{ct}: pin {p} has no label in the layout")
    for F in d["fsms"]:
        m = d["modules"][F["module"]]
        src = files[m["file"]]
        gid = F["module"] + "/" + F["wire"]
        if gid not in d["groups"]:
            E(f"fsm {F['module']}: no group for its state register {gid}")
            continue
        g = d["groups"][gid]
        flops = {n[0] for n, ct in zip(g["nodes"], g["ctypes"]) if ct == "dfxtp_1"}
        names = {}
        seen_flops = set()
        for st in F["states"]:
            names[st["index"]] = st["name"]
            dl = src[st["decl"] - 1]
            if not re.search(r"\b%s\s*=\s*\d+'d%d\b" % (st["name"], st["code"]), dl):
                E(f"fsm {F['module']}.{st['name']}: line {st['decl']} does not declare it as {st['code']}: {dl.strip()}")
            if st["arm"] and not re.match(r"\s*%s\s*:" % st["name"], src[st["arm"][0] - 1]):
                E(f"fsm {F['module']}.{st['name']}: case arm line {st['arm'][0]} does not start with it")
            if st["flop"] not in flops:
                E(f"fsm {F['module']}.{st['name']}: flip-flop {st['flop']} is not in {gid}")
            if st["flop"] in seen_flops:
                E(f"fsm {F['module']}.{st['name']}: flip-flop {st['flop']} shared by two states")
            seen_flops.add(st["flop"])
        if len(seen_flops) != len(flops):
            E(f"fsm {F['module']}: {len(flops)} flip-flops in the state register, {len(seen_flops)} states (one-hot means equal)")
        resets = [st for st in F["states"] if st["reset"]]
        if len(resets) != 1:
            E(f"fsm {F['module']}: {len(resets)} reset states")
        else:
            if not any(re.search(r"\b%s\s*<=\s*%s\b" % (F["wire"], resets[0]["name"]), src[ln - 1]) for ln in F["reset_lines"]):
                E(f"fsm {F['module']}: reset lines {F['reset_lines']} do not load {resets[0]['name']}")
        pairs = set()
        for e in F["edges"]:
            if e["from"] not in names or e["to"] not in names:
                E(f"fsm {F['module']}: edge {e['from']}->{e['to']} to an unknown state")
                continue
            if (e["from"], e["to"]) in pairs:
                E(f"fsm {F['module']}: edge {e['from']}->{e['to']} twice")
            pairs.add((e["from"], e["to"]))
            if not e["when"]:
                E(f"fsm {F['module']}: edge {names[e['from']]}->{names[e['to']]} has no condition")
            for ln in e["rtl"]:
                if not re.search(r"\b%s\s*<=[^;]*\b%s\b" % (F["wire"], names[e["to"]]), src[ln - 1]):
                    E(f"fsm {F['module']}: edge to {names[e['to']]} points at line {ln}, which does not load it: {src[ln - 1].strip()}")
    if d["isa"]:
        for r in d["isa"]["rows"]:
            f, lines = r["rtl"]
            if not lines:
                E(f"isa {r['rv']}: no decode line for {r['opc']}")
            for ln in lines:
                if r["opc"] not in files[f][ln - 1]:
                    E(f"isa {r['rv']}: line {ln} does not use {r['opc']}")
            if len(r["rv_hex"]) != 8:
                E(f"isa {r['rv']}: encoding {r['rv_hex']} is not one 32-bit word")
    return err


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "site", "data", "views.json")
    d = json.load(open(path))
    err = check(d)
    if len(sys.argv) == 1:
        import views_build
        a, b = views_build.dump(views_build.build()), views_build.dump(views_build.build())
        if a != b:
            err.append("views_build.py is not deterministic: two runs differ")
        if a != open(path).read():
            err.append("docs/site/data/views.json is not what views_build.py writes now")
    for e in err[:40]:
        print("FAIL", e)
    refs = (sum(len(g["rtl"]) + len(g["nodes"]) + len(g["edges"]) for g in d["groups"].values())
            + sum(len(T["fets"]) for T in d["celltypes"].values())
            + sum(len(F["states"]) + len(F["edges"]) for F in d["fsms"]) + len(d["isa"]["rows"] if d["isa"] else []))
    print(f"check_views: {len(d['modules'])} modules, {len(d['groups'])} groups, {len(d['celltypes'])} cell types, "
          f"{len(d['fsms'])} state machines, {refs:,} references checked, {len(err)} errors")
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
