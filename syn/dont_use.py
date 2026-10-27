#!/usr/bin/env python3
"""dont_use.py — copy a sky130 liberty file, marking the cells the real flow may not use.

LibreLane (the Tiny Tapeout GDS flow) synthesizes with SYNTH_EXCLUDED_CELL_FILE.
This design sets it to src/synth_exclude.cells; the PDK default is
libs.tech/openlane/sky130_fd_sc_hd/no_synth.cells (185 cells, among them most
of the smallest drive strengths). Synthesis against the full library can pick
cells the flow never will and report an area the flow cannot reach, so every
area and timing estimate here goes through this script.

usage: python3 syn/dont_use.py IN.lib OUT.lib [cells-file]
Without a cells file it uses src/synth_exclude.cells when the current
directory has one (the repository root), and otherwise the PDK default next
to the library. Prints how many cells were marked; exits 2 if it cannot find
a list (3 if it marks nothing), so a caller never reports the optimistic
number silently.
"""
import os, re, sys

lib_in, lib_out = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:
    cells_file = sys.argv[3]
elif os.path.isfile(os.path.join("src", "synth_exclude.cells")):
    cells_file = os.path.join("src", "synth_exclude.cells")
else:
    # <pdk>/sky130A/libs.ref/sky130_fd_sc_hd/lib/X.lib -> <pdk>/sky130A/libs.tech/openlane/...
    ref = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(lib_in))))
    cells_file = os.path.join(os.path.dirname(ref), "libs.tech", "openlane",
                              "sky130_fd_sc_hd", "no_synth.cells")
if not os.path.isfile(cells_file):
    print(f"dont_use.py: no cell exclusion list at {cells_file}; pass it as the third argument",
          file=sys.stderr)
    sys.exit(2)

excluded = {l.strip() for l in open(cells_file) if l.strip() and not l.lstrip().startswith("#")}
text = open(lib_in).read()
marked = 0
def mark(m):
    global marked
    if m.group(2) not in excluded:
        return m.group(0)
    marked += 1
    return m.group(0) + "\n        dont_use : true;"
text = re.sub(r'(cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{)', mark, text)
open(lib_out, "w").write(text)
print(f"{marked} cells marked dont_use from {cells_file}")
if marked == 0:
    # a list that matches nothing means the library or the list is not sky130_fd_sc_hd
    print("dont_use.py: no cell in the library is on the list", file=sys.stderr)
    sys.exit(3)
