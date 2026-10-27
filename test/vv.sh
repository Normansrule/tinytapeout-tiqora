#!/bin/sh
# vv.sh — run a self-checking iverilog testbench and turn its verdict into an
# exit status. vvp itself exits 0 after $finish even when checks failed, so
# `make sim` used to finish "successfully" with FAIL lines in its output.
# This passes the output through unchanged and fails unless vvp succeeded,
# no line reports a failure, and the bench printed its "... PASSED" line.
#
# usage: sh vv.sh tb_name.vvp [plusargs...]
log=$(mktemp) || exit 1
vvp "$@" > "$log" 2>&1; status=$?
cat "$log"
if [ $status -ne 0 ]; then
    echo "*** $1: vvp exited with status $status"; rm -f "$log"; exit 1
fi
if grep -qE '^ *FAIL( |$)|FAILED' "$log"; then
    echo "*** $1: a check failed (see FAIL above)"; rm -f "$log"; exit 1
fi
if ! grep -qE 'PASSED *$' "$log"; then
    echo "*** $1: no PASSED line; the bench did not finish"; rm -f "$log"; exit 1
fi
rm -f "$log"
