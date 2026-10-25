#!/usr/bin/env python3
"""dont_use.py — copy a sky130 liberty file, marking the cells the real flow may not use.

LibreLane (the Tiny Tapeout GDS flow) synthesizes with SYNTH_EXCLUDED_CELL_FILE,
the PDK's libs.tech/openlane/sky130_fd_sc_hd/no_synth.cells: 185 cells, among
them most of the smallest drive strengths (dfxtp_1, nand2_1, mux2i_1, ...).
Synthesis against the full library picks those small cells and reports an
area the flow can never reach; measured on Tiqora v20, 50,880 um^2 with the
full library against 60,750 um^2 with the excluded cells removed, which is
what LibreLane 3.0.14 itself synthesizes (59,797 um^2).

usage: python3 syn/dont_use.py IN.lib OUT.lib [no_synth.cells]
With no cell list it looks next to the library, where every open_pdks
install keeps it. Prints how many cells were marked; exits 2 if it cannot
find the list (3 if it marks nothing), so a caller never reports the optimistic number silently.
"""
import os, re, sys

lib_in, lib_out = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:
    cells_file = sys.argv[3]
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
