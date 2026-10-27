#!/usr/bin/env bash
# area_sky130.sh — REAL sky130 standard-cell area for this design.
#
# Maps the design onto the actual sky130_fd_sc_hd cell library from your
# PDK install, minus the cells the Tiny Tapeout flow excludes from
# synthesis, and reports total cell area against every Tiny Tapeout tile
# size. This replaces estimates with a measurement. It is still not place
# and route — routing, tap cells and antenna diodes come on top, which is
# why the tile columns are shown at 60% and 70% utilisation — but it is
# the number that decides which tile to order.
#
# usage:  bash syn/area_sky130.sh [path/to/sky130_fd_sc_hd__tt_025C_1v80.lib]
#
# With no argument it looks in the usual PDK locations.
set -euo pipefail

LIB="${1:-}"
if [ -z "$LIB" ]; then
    for c in \
        "$HOME/pdk/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" \
        "$HOME/ttsetup/pdk/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" \
        "$HOME/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" \
        "$HOME/.ciel/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" \
        "${PDK_ROOT:-/nonexistent}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
    do
        if [ -f "$c" ]; then LIB="$c"; break; fi
    done
    # Still nothing? Go looking. PDK installs land in all sorts of places
    # (volare and ciel bury them under a version hash), so search rather
    # than make the user hunt.
    if [ -z "$LIB" ]; then
        echo "searching for a sky130 library under $HOME ..." >&2
        LIB=$(find "$HOME" -name 'sky130_fd_sc_hd__tt_025C_1v80.lib' \
                   -path '*sky130A*' 2>/dev/null | head -1)
        [ -n "$LIB" ] && echo "found: $LIB" >&2
    fi
fi
if [ -z "$LIB" ] || [ ! -f "$LIB" ]; then
    echo "error: no sky130 liberty file found." >&2
    echo "pass one explicitly:  bash syn/area_sky130.sh /path/to/sky130_fd_sc_hd__tt_025C_1v80.lib" >&2
    echo "find yours with:      find ~ -name 'sky130_fd_sc_hd__tt_025C_1v80.lib' 2>/dev/null" >&2
    exit 1
fi

# Any Yosys will do: the RTL refers to package symbols as tp_pkg::NAME
# rather than using file-scope `import`, which older builds reject. Prefer
# a locally installed oss-cad-suite build if there is one, since it tends
# to be newer than the distribution package.
YOSYS=""
for y in "${YOSYS_BIN:-}" "$HOME/oss-cad-suite/bin/yosys" yosys yowasp-yosys; do
    if [ -n "$y" ] && command -v "$y" >/dev/null 2>&1; then YOSYS="$y"; break; fi
done
if [ -z "$YOSYS" ]; then
    echo "error: no yosys found. Install it, or source ~/oss-cad-suite/environment" >&2
    exit 1
fi

# reuse the source list and top module from the existing synth script
TOP=$(grep -oP 'hierarchy -check -top \K\S+' syn/synth_check.ys)
READS=$(grep '^read_verilog' syn/synth_check.ys)

# yowasp runs sandboxed to the working directory, so stage the library here,
# with the cells LibreLane may not use marked dont_use (see syn/dont_use.py).
# NO_SYNTH=path/to/no_synth.cells overrides where the list is looked for.
python3 syn/dont_use.py "$LIB" syn/.lib.tmp ${NO_SYNTH:+"$NO_SYNTH"}
trap 'rm -f syn/.lib.tmp syn/.area.ys syn/.area.txt syn/.area.log' EXIT

cat > syn/.area.ys <<YS
$READS
hierarchy -check -top $TOP
synth -top $TOP -flatten
dfflibmap -liberty syn/.lib.tmp
abc -liberty syn/.lib.tmp
opt_clean
tee -o syn/.area.txt stat -liberty syn/.lib.tmp
YS

echo "library: $LIB"
echo "top:     $TOP"
echo "yosys:   $YOSYS ($("$YOSYS" -V | grep -oP 'Yosys \S+'))"
echo "running synthesis against the real cell library..."
if ! "$YOSYS" -q -l syn/.area.log -s syn/.area.ys >/dev/null 2>&1; then
    echo "synthesis failed:" >&2
    grep -iE "error" syn/.area.log | head -5 >&2
    exit 1
fi

# Parse defensively. Under `set -euo pipefail` a grep that matches nothing
# inside $( ) ends the script silently, and the stat format has changed
# between Yosys releases, so every lookup tolerates a miss.
AREA=$(grep -oP "Chip area for (top )?module .*?: \K[0-9.]+" syn/.area.txt | tail -1 || true)
CELLS=$(grep -oP "^\s*\K[0-9]+(?=\s+cells\s*$)" syn/.area.txt | tail -1 || true)
[ -z "$CELLS" ] && CELLS=$(grep -oP "Number of cells:\s+\K[0-9]+" syn/.area.txt | tail -1 || true)
FLOPS=$(grep -E "sky130_fd_sc_hd__(dfxtp|dfrtp|dfrbp|dfstp|dfsbp|dfbbp|edfxtp|sdf)" syn/.area.txt \
        | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+$/) { s += $i; break }} END {print s+0}' || true)
# (the count is the first whole number on each line: Yosys 0.33 prints the cell
#  name first, newer versions print the count first)

if [ -z "$AREA" ]; then
    echo "error: could not find the chip area in the Yosys report:" >&2
    tail -20 syn/.area.txt >&2
    exit 1
fi

python3 - "$AREA" "${CELLS:-}" "${FLOPS:-}" <<'PY'
import sys
area  = float(sys.argv[1])
cells = sys.argv[2] or "?"
flops = sys.argv[3] or "?"
tiles = {"1x1":(161.00,111.52), "1x2":(161.00,225.76), "2x2":(334.88,225.76),
         "3x2":(508.76,225.76), "4x2":(682.64,225.76), "8x2":(1378.16,225.76)}
print(f"\ncells {cells}   flip-flops {flops}   cell area {area:,.0f} um^2\n")
print(f"{'tile':<6}{'tile um^2':>11}{'@60% util':>11}{'@70% util':>11}   verdict")
print("-"*56)
for n,(w,h) in tiles.items():
    t=w*h; u60=100*area/(t*0.6); u70=100*area/(t*0.7)
    v = "fits" if u60 <= 100 else ("tight" if u70 <= 100 else "does not fit")
    print(f"{n:<6}{t:>11,.0f}{u60:>10.0f}%{u70:>10.0f}%   {v}")
print("\n'fits' = under 60% utilisation, where Tiny Tapeout designs route")
print("reliably. 'tight' = only under 70%, which may or may not route.")
print("Place and route is the final word; this is the number to plan with.")
PY
