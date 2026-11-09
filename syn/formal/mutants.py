"""mutants.py — break the shared timing unit eight ways and check that
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
]
caught = 0
for name, f, a, b in muts:
    d = tempfile.mkdtemp(prefix="fmut_")
    os.makedirs(d + "/src/sync"); shutil.copy(repo + "/src/tp_pkg.sv", d + "/src/")
    for g in os.listdir(repo + "/src/sync"): shutil.copy(f"{repo}/src/sync/{g}", d + "/src/sync/")
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
