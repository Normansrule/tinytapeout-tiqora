"""tracekit.py — turn a testbench's per-clock trace into explorer fixtures.

Shared, unchanged, by tiqora-skywater130 and tinytapeout-tiqora; what to
show, and the words for it, live in each repository's docs/tools/traces.py.

A testbench writes a header line of column names, then one line per clock
(or per clock on which something changed): the cycle number first, then one
value per column, in hex or binary. A cycle may carry a one-letter suffix
naming a phase of the run ("12h"). Unknown values ('x', 'z') read as None.

A fixture is one JSON file: the signals with their change points, captions
anchored to cycles found in the data, the checks the testbench passed, and
the provenance (testbench, sources and their SHA-256, simulator, command)
that --check uses to prove the fixture still matches the RTL.
"""
import hashlib, json, os, re, subprocess

SCHEMA = 1


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def read_trace(path):
    lines = open(path).read().splitlines()
    cols = lines[0].split()
    rows = []
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) != len(cols):
            continue
        m = re.fullmatch(r"(-?\d+)([a-z]?)", parts[0])
        row = {"cycle": int(m.group(1)), "run": m.group(2) or ""}
        for c, v in zip(cols[1:], parts[1:]):
            row[c] = None if re.search(r"[xzXZ]", v) else int(v, 16)
        rows.append(row)
    return rows


def checks_from(log):
    """The testbench's own pass/fail lines: '  ok    text' / '  FAIL  text'."""
    out = []
    for ln in open(log).read().splitlines():
        m = re.match(r"\s+(ok|FAIL)\s+(.*)", ln)
        if m:
            out.append({"ok": m.group(1) == "ok", "text": m.group(2).strip()})
    return out


def first(rows, pred, after=None):
    for r in rows:
        if (after is None or r["cycle"] > after) and pred(r):
            return r["cycle"]
    raise ValueError("anchor not found in trace")


def changes(rows, fn, lo, hi):
    """[[cycle, value], ...] at every change of fn(row) inside [lo, hi]."""
    out, last = [], object()
    for r in rows:
        if r["cycle"] < lo or r["cycle"] > hi:
            continue
        v = fn(r)
        if v != last:
            out.append([r["cycle"], v])
            last = v
    return out


def fixture(seq_id, title, summary, rows, lo, hi, signals, captions, marks, checks, provenance, extra=None):
    sigs = []
    for s in signals:
        d = {k: v for k, v in s.items() if k != "fn"}
        d["changes"] = changes(rows, s["fn"], lo, hi)
        sigs.append(d)
    caps = sorted(captions, key=lambda c: c["at"])
    for c in caps:
        if not lo <= c["at"] <= hi:
            raise ValueError(f"{seq_id}: caption at {c['at']} outside {lo}..{hi}")
    out = {"schema": SCHEMA, "id": seq_id, "title": title, "summary": summary,
           "kind": "recorded", "kind_text": "Recorded from an RTL simulation, not computed in the browser",
           "cycles": [lo, hi], "signals": sigs, "captions": caps, "marks": marks,
           "checks": checks, "provenance": provenance}
    if extra:
        out.update(extra)
    return out


def tool_version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()[0].strip()
    except Exception:
        return "unknown"


def write_all(fixtures, outdir, index_extra=None):
    os.makedirs(outdir, exist_ok=True)
    texts = {}
    for f in fixtures:
        texts[os.path.join(outdir, f["id"] + ".json")] = json.dumps(f, indent=1, sort_keys=True) + "\n"
    index = {"schema": SCHEMA, "fixtures": [{"id": f["id"], "title": f["title"], "file": f["id"] + ".json"} for f in fixtures]}
    if index_extra:
        index.update(index_extra)
    texts[os.path.join(outdir, "index.json")] = json.dumps(index, indent=1, sort_keys=True) + "\n"
    return texts


def compare_or_write(texts, check, stale_ok_keys=("simulator",)):
    """Write the fixtures, or with check=True report every file that differs."""
    bad = []
    for path, text in texts.items():
        if check:
            old = open(path).read() if os.path.exists(path) else ""
            strip = lambda s: re.sub(r'"(%s)": "[^"]*"' % "|".join(stale_ok_keys), r'"\1": ""', s)
            if strip(old) != strip(text):
                bad.append(path)
        else:
            open(path, "w").write(text)
    return bad
