#!/bin/sh
# run.sh — prove the formal properties of the shared timing unit (and, in
# Tiqora, the rotating register file). Each *_props.svh
# is spliced into a scratch copy of its src/sync/*.sv just before `endmodule`
# (the RTL itself is untouched), then checked with Yosys + yosys-smtbmc + z3:
# a bounded check of 8 clocks from reset, then 4-induction, which
# makes the proof hold for every reachable state. Run from the repository root.
# Exits non-zero on a counterexample or an unproven property.
set -eu
OUT=${FORMAL_OUT:-/tmp/tp_formal}
SRC=${FORMAL_SRC:-src/sync}
DEPTH=${FORMAL_DEPTH:-8}    # bounded check from reset
KIND=${FORMAL_KIND:-4}      # k-induction depth
mkdir -p "$OUT"
n=0
prove() {   # prove <module> <props file> [defines]
    m=$1; p=$2; shift 2; tag="$m${1:+ $*}"
    f=$SRC/$m.sv; [ -f "$f" ] || f=$SRC/../core/$m.sv
    awk -v inc="$(cat "$p")" -v end="endmodule : $m" '$0 ~ "^"end { print inc } { print }' "$f" > "$OUT/$m.sv"
    grep -q 'f_past_ok' "$OUT/$m.sv" || { echo "FAIL  could not splice $p into $m"; exit 1; }
    yosys -q -l "$OUT/$m.yosys.log" -p "read_verilog -formal -sv $* $SRC/../tp_pkg.sv $OUT/$m.sv; prep -top $m; async2sync; dffunmap; write_smt2 -wires $OUT/$m.smt2" >/dev/null 2>&1 \
      || { tail -5 "$OUT/$m.yosys.log"; echo "FAIL  $tag: Yosys"; exit 1; }
    yosys-smtbmc -s z3 -t "$DEPTH" "$OUT/$m.smt2" > "$OUT/$m.bmc.log" 2>&1 \
      || { grep -E 'Assert failed|failed' "$OUT/$m.bmc.log" | head -5; echo "FAIL  $tag: counterexample within $DEPTH clocks"; exit 1; }
    yosys-smtbmc -s z3 -i -t "$KIND" "$OUT/$m.smt2" > "$OUT/$m.ind.log" 2>&1 \
      || { grep -E 'Assert failed|failed' "$OUT/$m.ind.log" | head -5; echo "FAIL  $tag: induction did not close"; exit 1; }
    echo "  ok    $tag: proven (bounded $DEPTH clocks, then $KIND-induction)"
    n=$((n + 1))
}
# the speed rework stores deadline - 1; the properties map it back
DM1=""; grep -q 'deadline_m1' "$SRC/sync_compare.sv" && DM1="-DF_STORES_DM1"
prove sync_timebase syn/formal/timebase_props.svh
prove sync_compare  syn/formal/compare_props.svh $DM1
prove sync_compare  syn/formal/compare_props.svh -DFREE_RUN $DM1
prove sync_event_fifo syn/formal/fifo_props.svh
[ -f "$SRC/../core/tp_nregfile.sv" ] && prove tp_nregfile syn/formal/regfile_props.svh
echo "$n checks, 0 failures"
echo "FORMAL PROOFS PASSED"
