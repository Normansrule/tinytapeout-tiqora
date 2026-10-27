#!/usr/bin/env python3
"""atlas.py — the chip atlas: every block that really exists, read from the RTL.

    python3 docs/tools/atlas.py                 write docs/site/data/atlas.json
    python3 docs/tools/atlas.py --area LIB      also re-measure per-block cell area
                                                (sky130_fd_sc_hd liberty) into
                                                docs/atlas/area_blocks.json
    python3 docs/tools/atlas.py --check         fail if atlas.json is out of date,
                                                a block has no notes, a note names a
                                                port that does not exist, a test
                                                target is missing, or a recorded
                                                measurement came from other sources

What is generated and what is written by hand, kept apart on purpose:

  generated  from Yosys elaborating the exact files info.yaml submits (and, where
             src/accel exists, the TIQORA_MODES build): the instance tree, every
             port with its direction and width, the nets that join neighbouring
             blocks, flip-flop bits, and which build each block is in.
  by hand    docs/atlas/notes.json: what each block is for, an example, its
             stages, handshake, latency, reset, error and stall behaviour, and the
             tests that check it. --check refuses notes that name a port, block or
             make target the RTL or Makefiles do not have.

The script is identical in tiqora-skywater130 and tinytapeout-tiqora; everything
chip-specific comes from info.yaml and docs/atlas/notes.json, so one chip can
never silently inherit the other's facts.
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.getcwd()
OUT = "docs/site/data/atlas.json"
NOTES = "docs/atlas/notes.json"
AREA = "docs/atlas/area_blocks.json"


def info_yaml():
    """The few fields of info.yaml this needs, without a YAML dependency."""
    text = open("info.yaml").read()
    top = re.search(r'^\s*top_module:\s*"([^"]+)"', text, re.M).group(1)
    tiles = re.search(r'^\s*tiles:\s*"([^"]+)"', text, re.M).group(1)
    block = re.search(r"source_files:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)", text).group(1)
    files = re.findall(r'-\s*"([^"]+)"', block)
    pins = dict(re.findall(r'^\s*((?:ui|uo|uio)\[\d\]):\s*"([^"]*)"', text, re.M))
    return top, tiles, ["src/" + f for f in files], pins


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def yosys_bin():
    for y in (os.environ.get("YOSYS_BIN"), os.path.expanduser("~/oss-cad-suite/bin/yosys"), "yosys"):
        if y and shutil.which(y):
            return y
    sys.exit("atlas.py: no yosys found (set YOSYS_BIN, or install yosys)")


def yosys_version(y):
    return re.search(r"Yosys \S+", subprocess.run([y, "-V"], capture_output=True, text=True).stdout).group(0)


def elaborate(y, top, files, defines=()):
    """Yosys's elaborated view of the design: modules, ports, cells, nets."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "h.json")
        d = " ".join("-D" + x for x in defines)
        reads = "; ".join(f"read_verilog -sv {d} {f}" for f in files)
        cmd = f"{reads}; hierarchy -check -top {top}; proc; opt_clean; write_json {out}"
        r = subprocess.run([y, "-q", "-p", cmd], capture_output=True, text=True)
        if r.returncode:
            sys.exit("atlas.py: yosys failed:\n" + r.stderr[-2000:])
        return json.load(open(out))["modules"]


def base_name(mod_name, mod):
    h = mod.get("attributes", {}).get("hdlname")
    if h:
        return h.lstrip("\\")
    m = re.match(r"\$paramod\\([^\\]+)\\", mod_name)
    return m.group(1) if m else mod_name


def ff_bits(mod):
    n = 0
    for c in mod["cells"].values():
        if re.match(r"\$_?(s?dff|adff|dffe|sdffe|sdffce|aldff|dffsr)", c["type"]):
            n += int(c["parameters"].get("WIDTH", "1"), 2) if "WIDTH" in c["parameters"] else 1
        elif c["type"] == "$mem_v2":
            n += int(c["parameters"]["WIDTH"], 2) * int(c["parameters"]["SIZE"], 2)
    return n


# ------------------------------------------------------------ parameters
def balanced(text, i):
    """text[i] is '(': return what is inside the matching ')', comments removed."""
    t = re.sub(r"//[^\n]*", "", text[i:])
    depth = 0
    for j, ch in enumerate(t):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            return t[1:j]
    return ""


def param_defaults(src_text, module):
    m = re.search(r"\bmodule\s+" + module + r"\s*#\s*\(", src_text)
    if not m:
        return {}
    out = {}
    for p in re.finditer(r"parameter\s+(?:[\w:]+\s+)?(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*([^,\n]+)", balanced(src_text, m.end() - 1)):
        out[p.group(1)] = p.group(2).strip()
    return out


def param_overrides(src_text, child_type, inst):
    for m in re.finditer(r"\b" + child_type + r"\s*#\s*\(", src_text):
        inside = balanced(src_text, m.end() - 1)
        rest = re.sub(r"//[^\n]*", "", src_text[m.end() - 1:])
        after = rest[len(inside) + 2:].lstrip()
        if re.match(re.escape(inst) + r"\s*\(", after):
            return {k: v.strip() for k, v in re.findall(r"\.(\w+)\s*\(([^()]*)\)", inside)}
    return {}


def resolve(value, scope):
    v = value.strip()
    if v in scope:
        return scope[v]
    m = re.fullmatch(r"(\d+)?'([bhd])([0-9a-fA-F_]+)", v)
    if m:
        n = int(m.group(3).replace("_", ""), {"b": 2, "h": 16, "d": 10}[m.group(2)])
        return f"0x{n:x}" if m.group(2) == "h" or n > 0xFFFF else str(n)
    return v


# ------------------------------------------------------------ the tree
def build(top, files, defines=()):
    y = yosys_bin()
    mods = elaborate(y, top, files, defines)
    texts = {f: open(f).read() for f in files}

    def text_of(mod):
        src = mod.get("attributes", {}).get("src", "")
        f = src.split(":")[0]
        return texts.get(f, ""), f, src

    blocks, nets = [], []

    def walk(mod_name, path, scope):
        mod = mods[mod_name]
        name = base_name(mod_name, mod)
        text, f, src = text_of(mod)
        line = int(re.search(r":(\d+)\.", src).group(1)) if ":" in src else 1
        ports = [{"name": p, "dir": v["direction"], "width": len(v["bits"])} for p, v in mod["ports"].items()]
        children = [(c, v) for c, v in mod["cells"].items() if v["type"] in mods]
        blocks.append({"path": path, "module": name, "file": f, "line": line,
                       "params": scope, "ports": ports, "ff_bits": ff_bits(mod),
                       "children": [path + "/" + c for c, _ in sorted(children)]})
        # nets joining this block's children (and its own ports)
        bit_ends = {}
        for c, v in children:
            cm = mods[v["type"]]
            for p, bits in v["connections"].items():
                d = cm["ports"][p]["direction"]
                for b in bits:
                    if not isinstance(b, str):          # "0"/"1"/"x" are constants, not nets
                        bit_ends.setdefault(b, []).append((path + "/" + c, p, d))
        for p, v in mod["ports"].items():
            for b in v["bits"]:
                if not isinstance(b, str):
                    bit_ends.setdefault(b, []).append((path, p, {"input": "output", "output": "input"}.get(v["direction"], "inout")))
        best = {}
        for n, v in sorted(mod["netnames"].items()):
            if v.get("hide_name") or n.startswith("$"):
                continue
            ends = {}
            for b in v["bits"]:
                for e in bit_ends.get(b, []):
                    ends[e] = ends.get(e, 0) + 1
            inner = [e for e in ends if e[0] != path]
            if not inner or len(ends) < 2:
                continue
            key = tuple(sorted(ends))
            # several names can cover the same wires (aliases, slices): keep the
            # tightest one, and never a name like _unused
            rank = ("unused" in n, len(v["bits"]) - max(ends.values()), len(n), n)
            if key not in best or rank < best[key][0]:
                best[key] = (rank, n, v, ends)
        for key, (_, n, v, ends) in sorted(best.items(), key=lambda kv: kv[1][1]):
            consts = sum(1 for b in v["bits"] if isinstance(b, str))
            nets.append({"in": path, "net": n, "width": len(v["bits"]), "const_bits": consts,
                         "drivers": sorted([{"block": e[0], "port": e[1], "bits": k} for e, k in ends.items() if e[2] == "output"], key=lambda x: (x["block"], x["port"])),
                         "loads": sorted([{"block": e[0], "port": e[1], "bits": k} for e, k in ends.items() if e[2] != "output"], key=lambda x: (x["block"], x["port"]))})
        # tied-off child inputs (constants), e.g. an unused port
        for c, v in children:
            cm = mods[v["type"]]
            for p, bits in v["connections"].items():
                if bits and all(isinstance(b, str) for b in bits) and cm["ports"][p]["direction"] == "input":
                    nets.append({"in": path, "net": "constant " + "".join(reversed(bits)), "width": len(bits),
                                 "const_bits": len(bits), "drivers": [],
                                 "loads": [{"block": path + "/" + c, "port": p, "bits": len(bits)}]})
        for c, v in sorted(children):
            cm = mods[v["type"]]
            ctext, _, _ = text_of(cm)
            cname = base_name(v["type"], cm)
            defaults = param_defaults(ctext, cname)
            over = param_overrides(text, cname, c.split(".")[-1])
            child_scope = {k: resolve(over.get(k, dv), scope) for k, dv in defaults.items()}
            walk(v["type"], path + "/" + c, child_scope)

    topname = next(n for n in mods if base_name(n, mods[n]) == top)
    walk(topname, top, {})
    return blocks, nets, yosys_version(y)


# ------------------------------------------------------------ per-block area
def measure_area(lib, top, files, defines=()):
    y = yosys_bin()
    with tempfile.TemporaryDirectory() as tmp:
        # mark the cells LibreLane may not use, as syn/area_sky130.sh does
        r = subprocess.run([sys.executable, os.path.join(ROOT, "syn", "dont_use.py"), lib,
                            os.path.join(tmp, "c.lib")], capture_output=True, text=True)
        if r.returncode:
            sys.exit("atlas.py: " + r.stderr.strip())
        d = " ".join("-D" + x for x in defines)
        reads = "\n".join(f"read_verilog -sv {d} {os.path.abspath(f)}" for f in files)
        ys = os.path.join(tmp, "a.ys")
        open(ys, "w").write(f"""{reads}
hierarchy -check -top {top}
synth -top {top}
dfflibmap -liberty c.lib
abc -liberty c.lib
opt_clean
tee -o stat.txt stat -liberty c.lib
""")
        r = subprocess.run([y, "-q", "-s", ys], cwd=tmp, capture_output=True, text=True)
        if r.returncode:
            sys.exit("atlas.py: area synthesis failed:\n" + r.stderr[-2000:])
        stat = open(os.path.join(tmp, "stat.txt")).read()
    per = {}
    for m in re.finditer(r"^=== (.+?) ===\n(.*?)Chip area for module .*?: ([0-9.]+)", stat, re.S | re.M):
        if m.group(1) == "design hierarchy":
            continue
        base = re.sub(r"^\$paramod(\$[0-9a-f]+)?\\", "", m.group(1).lstrip("\\")).split("\\")[0]
        per[base] = round(per.get(base, 0) + float(m.group(3)), 1)
    total = re.findall(r"Chip area for top module '[^']+': ([0-9.]+)", stat)
    return per, (float(total[-1]) if total else None)


# ------------------------------------------------------------ notes
def make_targets():
    t = set()
    for d, _, fs in os.walk(ROOT):
        if "/." in d or "node_modules" in d:
            continue
        for f in fs:
            if f == "Makefile":
                for m in re.finditer(r"^([A-Za-z0-9_.\-]+(?:\s+[A-Za-z0-9_.\-]+)*)\s*:(?!=)", open(os.path.join(d, f)).read(), re.M):
                    t.update(m.group(1).split())
    return t


def assemble():
    top, tiles, files, pins = info_yaml()
    blocks, nets, yv = build(top, files)
    builds = {"tile": {b["path"] for b in blocks}}
    extra = []
    if os.path.isdir("src/accel"):
        accel = sorted("src/accel/" + f for f in os.listdir("src/accel") if f.endswith(".sv"))
        mfiles = [files[0]] + accel + files[1:]
        mblocks, mnets, _ = build(top, mfiles, defines=("TIQORA_MODES",))
        builds["modes"] = {b["path"] for b in mblocks}
        for b in mblocks:
            if b["path"] not in builds["tile"]:
                b["only_in"] = "modes"
                extra.append(b)
        for n in mnets:
            if any(e["block"] in {b["path"] for b in extra} for e in n["drivers"] + n["loads"]):
                n["only_in"] = "modes"
                nets.append(n)
        mparent = {b["path"]: b for b in mblocks}
        for b in blocks:
            if b["path"] in mparent and mparent[b["path"]]["children"] != b["children"]:
                b["children_modes"] = mparent[b["path"]]["children"]
        files_all = files + accel
    else:
        files_all = files
    blocks += extra
    for b in blocks:
        b["builds"] = [k for k, v in builds.items() if b["path"] in v]
    notes = json.load(open(NOTES))
    area = json.load(open(AREA)) if os.path.exists(AREA) else None
    sources = {f: sha(f) for f in files_all}
    data = {
        "generated_by": "docs/tools/atlas.py from info.yaml, the RTL and docs/atlas/notes.json; do not edit",
        "chip": notes["chip"], "top": top, "tiles": tiles,
        "provenance": {"tool": yv, "command": "python3 docs/tools/atlas.py", "sources": sources},
        "builds": notes.get("builds", {}),
        "categories": notes["categories"],
        "pins": pins,
        "blocks": [], "nets": nets,
        "cross_cutting": notes.get("cross_cutting", []),
        "area": area,
    }
    for b in blocks:
        n = notes["blocks"].get(b["module"], {})
        data["blocks"].append({**b, **{k: v for k, v in n.items() if k != "port_notes"},
                               "port_notes": n.get("port_notes", {})})
    return data, notes, blocks, files_all, top


def problems(data, notes, blocks, files_all):
    bad = []
    mods = {b["module"] for b in blocks}
    targets = make_targets()
    for b in blocks:
        n = notes["blocks"].get(b["module"])
        if not n:
            bad.append(f"{b['module']} ({b['path']}): no entry in {NOTES}")
            continue
        for k in ("title", "category", "summary", "example", "tests"):
            if not n.get(k):
                bad.append(f"{b['module']}: notes need '{k}'")
        if n.get("category") not in notes["categories"]:
            bad.append(f"{b['module']}: category '{n.get('category')}' is not one of {list(notes['categories'])}")
        ports = {p["name"]: p["width"] for p in b["ports"]}
        for p, txt in n.get("port_notes", {}).items():
            if p not in ports:
                bad.append(f"{b['module']}: port_notes names '{p}', which the RTL does not have")
            m = re.match(r"\[(\d+)\]", txt)
            if m and int(m.group(1)) != ports.get(p):
                bad.append(f"{b['module']}.{p}: notes say {m.group(1)} bits, the RTL has {ports.get(p)}")
        for t in n.get("tests", []):
            tgt = t.split()[-1]
            if tgt not in targets:
                bad.append(f"{b['module']}: test 'make {t}' is not a target in any Makefile")
    for m in notes["blocks"]:
        if m not in mods:
            bad.append(f"{NOTES}: '{m}' is not a module in this design")
    area = data.get("area")
    if area:
        want = {f: sha(f) for f in area["sources"]}
        if want != area["sources"] or set(area["sources"]) != set(files_all):
            bad.append(f"{AREA} was measured from different sources: re-run with --area LIB")
    return bad


def main():
    if "--area" in sys.argv:
        lib = sys.argv[sys.argv.index("--area") + 1]
        top, tiles, files, _ = info_yaml()
        per, total = measure_area(lib, top, files)
        rec = {"label": "measured", "what": "sky130_fd_sc_hd cell area per module, hierarchical synthesis before placement "
               "(the flattened netlist the flow builds is smaller: synthesis optimizes across boundaries)",
               "library": os.path.basename(lib), "tool": yosys_version(yosys_bin()),
               "command": "python3 docs/tools/atlas.py --area <sky130_fd_sc_hd__tt_025C_1v80.lib>",
               "total_hierarchical_um2": total, "modules_um2": per, "sources": {f: sha(f) for f in files}}
        if os.path.isdir("src/accel"):
            accel = sorted("src/accel/" + f for f in os.listdir("src/accel") if f.endswith(".sv"))
            mper, mtotal = measure_area(lib, top, [files[0]] + accel + files[1:], defines=("TIQORA_MODES",))
            rec["modes"] = {"define": "TIQORA_MODES", "total_hierarchical_um2": mtotal, "modules_um2": mper}
            rec["sources"].update({f: sha(f) for f in accel})
        os.makedirs(os.path.dirname(AREA), exist_ok=True)
        json.dump(rec, open(AREA, "w"), indent=1, sort_keys=True)
        open(AREA, "a").write("\n")
        print(f"wrote {AREA}: {total} um^2 hierarchical, {len(per)} modules")
    data, notes, blocks, files_all, top = assemble()
    bad = problems(data, notes, blocks, files_all)
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        old = open(OUT).read() if os.path.exists(OUT) else ""
        strip = lambda s: re.sub(r'"tool": "Yosys [^"]*"', '"tool": ""', s)
        if strip(old) != strip(text):
            bad.append(f"{OUT} is out of date: run python3 docs/tools/atlas.py")
        for b in bad:
            print("  " + b)
        print(f"atlas: {len(blocks)} blocks, {len(data['nets'])} nets, " +
              ("notes, ports, tests and measurements consistent with the RTL" if not bad else f"{len(bad)} problems"))
        sys.exit(1 if bad else 0)
    for b in bad:
        print("  warning: " + b)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write(text)
    print(f"wrote {OUT}: {len(blocks)} blocks, {len(data['nets'])} nets")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
