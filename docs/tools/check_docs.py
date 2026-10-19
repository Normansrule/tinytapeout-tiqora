#!/usr/bin/env python3
"""check_docs.py — do the docs still describe the repository that exists?

For every Markdown file in the repository it checks that
  * every local link and image points at a file or folder that exists
  * every `make <target>` mentioned is a target in one of the Makefiles
  * every `python3 <script>.py` mentioned is a file in the repository
and that docs/info.md will build into Tiny Tapeout's PDF datasheet (typst 0.13):
  * every image is a local PNG, JPEG, GIF or SVG file (no web images, no WebP)
  * no link to a heading anchor (#name); the datasheet's headings have no anchors
Docs drift silently as a project changes; this makes drift a test failure.
    python3 docs/tools/check_docs.py        (from the repository root)
"""
import os, re, sys
ROOT = os.getcwd()
SKIP = {".git", "tt", "node_modules", "sim_build", "riscv-arch-test", "__pycache__"}
mds, makefiles, files = [], [], set()
for d, dirs, fs in os.walk(ROOT):
    dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".zig-cache")]
    for f in fs:
        p = os.path.join(d, f)
        files.add(os.path.relpath(p, ROOT))
        if f.endswith(".md"): mds.append(p)
        if f == "Makefile": makefiles.append(p)
targets = {"sim", "results.xml", "clean"}                   # cocotb's own targets
for mk in makefiles:
    for m in re.finditer(r"^([A-Za-z0-9_.\-]+(?:\s+[A-Za-z0-9_.\-]+)*)\s*:(?!=)", open(mk).read(), re.M):
        targets.update(m.group(1).split())
basenames = {os.path.basename(f) for f in files}
problems = 0
for md in sorted(mds):
    text = open(md).read()
    rel = os.path.relpath(md, ROOT)
    def bad(msg):
        global problems; problems += 1; print(f"  {rel}: {msg}")
    for m in re.finditer(r"\]\(([^)\s]+)\)", text):
        link = m.group(1).split("#")[0]
        if not link or re.match(r"[a-z]+:", link):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(md), link))):
            bad(f"broken link or image: {link}")
    # commands only count inside code: fenced blocks and `inline code`, never prose
    snippets = re.findall(r"```.*?```", text, re.S) + re.findall(r"`([^`\n]+)`", text)
    makes = [m for snip in snippets   # each snippet on its own: a match never spans two
             for m in re.finditer(r"\bmake\s+((?:-[sC]\s+\S+\s+|-s\s+|[A-Z_]+=\S+\s+)*)([a-z][a-z0-9_.\-]*)", snip)]
    for m in makes:
        t = m.group(2)
        if t not in targets:
            bad(f"`make {t}`: no such target in any Makefile")
    for m in [m for snip in snippets for m in re.finditer(r"python3?\s+(?:-m\s+\S+\s+)?([\w./-]+\.py)\b", snip)]:
        if m.group(1).startswith("tt/"):          # Tiny Tapeout's tools, cloned by the docs' own instructions
            continue
        if os.path.basename(m.group(1)) not in basenames:
            bad(f"script not found: {m.group(1)}")
    if rel == os.path.join("docs", "info.md"):
        for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]*\bsrc=\"([^\"]+)\"", text):
            img = m.group(1) or m.group(2)
            if re.match(r"[a-z]+:", img):
                bad(f"datasheet image must be a local file, not {img}")
            elif not re.search(r"\.(png|jpe?g|gif|svg)$", img, re.I):
                bad(f"datasheet image must be PNG, JPEG, GIF or SVG for typst: {img}")
        for m in re.finditer(r"\]\((#[^)\s]*)\)", text):
            bad(f"datasheet link to a heading anchor fails the PDF build: {m.group(1)}")
print(f"{len(mds)} Markdown files checked: " + ("all links, images, make targets and scripts exist"
                                                if not problems else f"{problems} problems"))
sys.exit(1 if problems else 0)
