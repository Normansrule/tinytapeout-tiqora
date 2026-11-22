#!/usr/bin/env python3
"""audit_mutants.py — break the RTL on purpose and show the audit checks fail.

Each mutant is one textual edit to one source file. The script copies the
repository to a scratch directory, applies the edit, runs the make target
that should catch it, and counts the mutant as caught only if that target
exits non-zero. The original tree is never touched.

    python3 audit_mutants.py            # run every mutant
    python3 audit_mutants.py -k late    # only mutants whose name contains "late"

A mutant whose edit no longer applies (the source changed) is a failure too,
so the list cannot rot silently.
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# (name, file, old text, new text, make target in test/)
MUTANTS = [
    ("late: unsigned deadline compare (no 2^31 window)",
     "src/sync/sync_compare.sv",
     "assign reached = ($signed((now + 32'd1) - deadline[i]) >= 0);",
     "assign reached = ((now + 32'd1) >= deadline[i]);",
     "proto"),
    ("late: fire only on an exact match (a passed deadline never fires)",
     "src/sync/sync_compare.sv",
     "assign reached = ($signed((now + 32'd1) - deadline[i]) >= 0);",
     "assign reached = ((now + 32'd1) == deadline[i]);",
     "proto"),
    ("coherence: bytes 2-4 of a read reply re-sampled one byte later",
     "src/uart/tp_host_uart.sv",
     "payload <= {8'd0, payload[31:8]};",
     "payload <= (count == 3'd4) ? {8'd0, reg_rdata[31:8]} : {8'd0, payload[31:8]};",
     "proto"),
    ("coherence: a read reply touches the register port a second time",
     "src/uart/tp_host_uart.sv",
     "assign reg_req   = (state == H_DO);",
     "assign reg_req   = (state == H_DO) || (state == H_SEND && tx_go && count == 3'd4);",
     "proto"),
    ("syncdiff: trigger pulse one tick short",
     "src/sync/sync_compare.sv",
     "if (fire)                        pulse_cnt[i] <= pw;",
     "if (fire)                        pulse_cnt[i] <= pw - 1'b1;",
     "syncdiff"),
    ("syncdiff: TIME read returns the timebase one tick late",
     "src/sync/sync_unit.sv",
     "tp_pkg::SR_TIME:  reg_rdata = now;",
     "tp_pkg::SR_TIME:  reg_rdata = now + 32'd1;",
     "syncdiff"),
]


def run(sel=None):
    caught = total = 0
    for name, path, old, new, target in MUTANTS:
        if sel and sel not in name:
            continue
        total += 1
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "r")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "*.vvp", "*.vcd", "runs"))
            f = os.path.join(dst, path)
            src = open(f).read()
            if src.count(old) != 1:
                print(f"  FAIL  {name}: the edit does not apply to {path} ({src.count(old)} matches)")
                continue
            open(f, "w").write(src.replace(old, new))
            r = subprocess.run(["make", "-C", os.path.join(dst, "test"), target],
                               capture_output=True, text=True, errors="replace")
            ok = r.returncode != 0
            caught += ok
            out = (r.stdout + r.stderr).splitlines()
            fl = [l.strip() for l in out if l.strip().startswith("FAIL")]
            why = "\n          ".join(fl[:4]) if fl else (out[-1].strip() if out else "")
            print(f"  {'caught' if ok else 'FAIL  missed'}: {name} (make {target})")
            if ok:
                print(f"          {why}")
    print(f"\naudit mutants: {caught} of {total} caught")
    print("AUDIT MUTANTS PASSED" if caught == total and total else "AUDIT MUTANTS FAILED")
    return caught == total and total > 0


if __name__ == "__main__":
    sel = sys.argv[2] if sys.argv[1:2] == ["-k"] else None
    sys.exit(0 if run(sel) else 1)
