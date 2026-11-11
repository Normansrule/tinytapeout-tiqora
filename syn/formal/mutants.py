"""mutants.py — break the shared timing unit (and Tiqora's register file) on purpose and check that
syn/formal/run.sh fails on every one (the proofs are not vacuous).
Usage, from the repository root: python3 syn/formal/mutants.py"""
import subprocess, shutil, os, sys, tempfile
repo = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
muts = [
 ("fire one tick early", "sync_compare.sv", "(now + 32'd1) - deadline[i]", "(now + 32'd2) - deadline[i]"),
 ("fire one tick late", "sync_compare.sv", "(now + 32'd1) - deadline[i]", "(now + 32'd0) - deadline[i]"),
 ("unsigned compare (wrap bug)", "sync_compare.sv", "assign reached = ($signed((now + 32'd1) - deadline[i]) >= 0);", "assign reached = ((now + 32'd1) >= deadline[i]);"),
 ("never disarms", "sync_compare.sv", "armed[i]    <= 1'b0;", "armed[i]    <= 1'b1;"),
 ("pulse one tick short", "sync_compare.sv", "if (fire)                        pulse_cnt[i] <= pw;", "if (fire)                        pulse_cnt[i] <= pw - 1'b1;"),
 ("fires while disarmed", "sync_compare.sv", "assign fire    = (armed[i] && reached) ||", "assign fire    = (reached) ||"),
 ("TADJ swallows the tick", "sync_timebase.sv", "now <= now + adj_in + 32'd1;", "now <= now + adj_in;"),
 ("free run counts by 2", "sync_timebase.sv", "else          step = frac_co ? 32'd2 : 32'd1;", "else          step = frac_co ? 32'd2 : 32'd2;"),
 ("queue drops `lost` silently", "sync_event_fifo.sv", "if ((push && full) || lost) overflow <= 1'b1;", "if (push && full) overflow <= 1'b1;"),
 ("push into a full queue overwrites", "sync_event_fifo.sv", "assign do_push = push && !full;", "assign do_push = push;"),
 ("queue shows the newest, not the oldest", "sync_event_fifo.sv", "assign rdata = mem[rptr];", "assign rdata = mem[wptr];"),
 ("capture skips a synchroniser flop", "sync_capture.sv", "assign stable[c] = sync1[c];", "assign stable[c] = sync0[c];"),
 ("falling edge reported as rising", "sync_capture.sv", "assign evt_rise = rise;", "assign evt_rise = rise | falling;"),
 ("capture ignores the channel enable", "sync_capture.sv", "assign evt      = en & (", "assign evt      = ("),
 ("both-edges mode misses falling edges", "sync_capture.sv", "(both ? (rise | falling)", "(both ? (rise)"),
 ("glitch filter one sample short", "sync_capture.sv", "else if (&shift)            stable[c] <= 1'b1;", "else if (&shift[FILTW-1:0]) stable[c] <= 1'b1;"),
 ("register write ignores the address", "../core/tp_nregfile.sv", "(we && wa == i[3:0]) ? wd : r[i][3:0]", "(we) ? wd : r[i][3:0]"),
 ("register write lands one nibble off", "../core/tp_nregfile.sv", "r[i] <= {(we && wa == i[3:0]) ? wd : r[i][3:0], r[i][31:4]};", "r[i] <= {r[i][3:0], (we && wa == i[3:0]) ? wd : r[i][31:28], r[i][27:4]};"),
 ("x0 reads non-zero", "../core/tp_nregfile.sv", "qa = 4'd0;", "qa = r[1][3:0];"),
]
muts = [m for m in muts if os.path.exists(f"{repo}/src/sync/{m[1]}")]   # Serial has no register file
caught = 0
for name, f, a, b in muts:
    d = tempfile.mkdtemp(prefix="fmut_")
    os.makedirs(d + "/src/sync"); shutil.copy(repo + "/src/tp_pkg.sv", d + "/src/")
    for g in os.listdir(repo + "/src/sync"): shutil.copy(f"{repo}/src/sync/{g}", d + "/src/sync/")
    if os.path.isdir(repo + "/src/core"): shutil.copytree(repo + "/src/core", d + "/src/core")
    p = f"{d}/src/sync/{f}"; s = open(p).read()
    if s.count(a) != 1: print("PATTERN NOT FOUND", name); continue
    open(p, "w").write(s.replace(a, b))
    r = subprocess.run(["sh", "syn/formal/run.sh"], cwd=repo, env={**os.environ, "FORMAL_SRC": d + "/src/sync", "FORMAL_OUT": d + "/out"}, capture_output=True, text=True)
    fail = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    if r.returncode != 0: caught += 1; print(f"  caught  {name}: {fail[0] if fail else r.stdout[-200:]}")
    else: print(f"  MISSED  {name}")
    shutil.rmtree(d)
print(f"formal mutants: {caught} of {len(muts)} caught")
print(f"{len(muts)} checks, {len(muts) - caught} failures")
sys.exit(0 if caught == len(muts) else 1)
