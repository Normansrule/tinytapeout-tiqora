#!/usr/bin/env python3
"""check_site.py — prove the explorer site still tells the truth about the RTL.

    python3 docs/tools/check_site.py          (part of make docs)

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. Fast: it
re-runs no simulation (docs/tools/traces.py --check does that). It fails when

  - a shared file differs from docs/shared_explorer.sha256, the list both
    repositories carry, so the two sites cannot drift apart;
  - the atlas or a tour fixture was made from sources that have changed since;
  - the in-browser models (docs/site/lib/model.js, run here under Node)
    disagree with any operation the RTL recorded;
  - the atlas pinout differs from info.yaml;
  - a built page is stale, loads anything from the network, or links to a
    file, tour or block that does not exist.
"""
import glob, hashlib, json, os, re, subprocess, sys

errors = []
fail = errors.append
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

# ---------------------------------------------------------------- shared files
for ln in open("docs/shared_explorer.sha256").read().splitlines():
    h, path = ln.split(None, 1)
    if not os.path.exists(path):
        fail(f"shared file missing: {path}")
    elif sha(path) != h:
        fail(f"{path} differs from docs/shared_explorer.sha256: change it in both repositories and update the list")

# ---------------------------------------------------------------- staleness
atlas = json.load(open("docs/site/data/atlas.json"))
for f, h in atlas["provenance"]["sources"].items():
    if not os.path.exists(f) or sha(f) != h:
        fail(f"atlas.json was built from an older {f}: run python3 docs/tools/atlas.py")
idx = json.load(open("docs/site/data/traces/index.json"))
fixtures = [json.load(open("docs/site/data/traces/" + f["file"])) for f in idx["fixtures"]]
for fx in fixtures:
    for f, h in fx["provenance"]["sources"].items():
        if not os.path.exists(f) or sha(f) != h:
            fail(f"tour '{fx['id']}' was recorded from an older {f}: run python3 docs/tools/traces.py")
    caps = [c["at"] for c in fx["captions"]]
    if not caps:
        fail(f"tour '{fx['id']}' has no captions for its summary")
    if fx["kind"] != "recorded":
        fail(f"tour '{fx['id']}' is not labelled recorded")
    for c in fx["captions"]:
        for b in c.get("blocks", []):
            if b not in {x["module"] for x in atlas["blocks"]}:
                fail(f"tour '{fx['id']}' caption names {b}, which is not a block in the atlas")

# ---------------------------------------------------------------- models vs recordings
js = r"""
const M = require(process.argv[1]);
const fx = JSON.parse(require("fs").readFileSync(0, "utf8"));
const bad = [];
let n = 0;
for (const f of fx) {
  for (const r of ((f.model || {}).recorded || [])) {
    n++;
    const m = M.nibbleOp(r.a, r.b, r.op);
    if (m.result !== r.result) bad.push(`${r.op} ${r.a} ${r.b}: model ${m.result}, RTL ${r.result}`);
    r.phases.forEach((p, i) => ["a_n", "bx_n", "cin", "sum_n", "cout"].forEach(k => {
      if (m.phases[i][k] !== p[k]) bad.push(`${r.op} ${r.a} ${r.b} phase ${i} ${k}: model ${m.phases[i][k]}, RTL ${p[k]}`);
    }));
  }
  if (f.id === "overview" && f.commands) {
    for (const c of f.commands) {
      n++;
      const m = M.hostPort(c.bytes);
      if (!c.got.length) { if (!m.waiting) bad.push(`${c.cmd}: the RTL stayed silent, the model is not waiting`); continue; }
      const got = m.commands[0];
      if (!got) { bad.push(`${c.cmd}: the model saw no command`); continue; }
      if (Array.isArray(got.reply) && JSON.stringify(got.reply) !== JSON.stringify(c.got)) bad.push(`${c.cmd}: model ${got.reply}, RTL ${c.got}`);
      if (got.reply === "4 bytes" && c.got.length !== 4) bad.push(`${c.cmd}: RTL answered ${c.got.length} bytes`);
    }
  }
}
console.log(JSON.stringify({ n, bad }));
"""
try:
    r = subprocess.run(["node", "-e", js, os.path.abspath("docs/site/lib/model.js")], input=json.dumps(fixtures), capture_output=True, text=True)
    res = json.loads(r.stdout or "{}")
    if r.returncode or "n" not in res:
        fail("model.js under node: " + (r.stderr.strip()[-400:] or "no output"))
    else:
        errors.extend("model.js disagrees with the RTL: " + b for b in res["bad"])
        models = res["n"]
except FileNotFoundError:
    print("check_site: node not found, skipping the model check (install Node.js to run it)")
    models = 0

# ---------------------------------------------------------------- pinout
yaml_pins = {}
for k, v in re.findall(r'^\s+(u[io]o?\[\d\]|uio\[\d\]):\s*"(.*)"', open("info.yaml").read(), re.M):
    yaml_pins[k] = v
if yaml_pins != atlas["pins"]:
    fail("atlas.json pins differ from info.yaml: run python3 docs/tools/atlas.py")

# ---------------------------------------------------------------- built pages
r = subprocess.run([sys.executable, "docs/tools/build_site.py", "--check"], capture_output=True, text=True)
if r.returncode:
    fail(r.stdout.strip() or r.stderr.strip())
site = json.load(open("docs/site/site.json"))
# The atlas links every block to its source on GitHub at site["ref"], with the line
# number read from this checkout. Both must agree: the line must declare the module
# here, and the ref must be the branch this checkout is merged into, not an old tag
# whose files have moved on.
if site.get("ref", "main") != "main":
    fail(f"site.json ref is {site['ref']!r}, but the atlas's line numbers come from this checkout; "
         "its source links must point at main")
for b in atlas["blocks"]:
    try:
        line = open(b["file"]).read().split("\n")[b["line"] - 1]
    except (OSError, IndexError):
        line = ""
    if not re.match(rf"\s*module\s+{re.escape(b['module'])}\b", line):
        fail(f"atlas: {b['module']} is not declared at {b['file']}:{b['line']}")
ids = {f["id"] for f in fixtures}
paths = {b["path"] for b in atlas["blocks"]}
pages = 0
for p in site["pages"]:
    path = f"docs/site/{p['id']}.html"
    if not os.path.exists(path):
        continue
    pages += 1
    text = open(path).read()
    for m in re.finditer(r'<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)=["\']?(https?:)?//', text):
        fail(f"{path} loads something from the network: {m.group(0)[:80]}")
    if re.search(r"\bfetch\(|XMLHttpRequest", text):
        fail(f"{path} fetches data at run time; pages must be self-contained")
    for href in re.findall(r'href=["\']?([^"\' >]+)', text):
        if href.startswith(("http://", "https://", "mailto:", "data:", "blob:")) or href == "#main":
            continue
        target, _, frag = href.partition("#")
        if target and not os.path.exists(os.path.join("docs/site", target)):
            fail(f"{path} links to {target}, which does not exist")
        m = re.match(r"seq=([\w-]+)", frag)
        if m and m.group(1) not in ids:
            fail(f"{path} links to tour '{m.group(1)}', which does not exist")
        m = re.match(r"block=([^&]+)", frag)
        if m and m.group(1).replace("%2F", "/") not in paths:
            fail(f"{path} links to block '{m.group(1)}', which does not exist")

if errors:
    for e in errors:
        print("  FAIL  " + e)
    sys.exit(f"check_site: {len(errors)} problem(s)")
print(f"site: {pages} pages, {len(fixtures)} tours, {len(atlas['blocks'])} blocks; {models} recorded operations agree with model.js; pinout matches info.yaml; shared files identical")
