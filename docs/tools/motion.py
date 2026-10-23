#!/usr/bin/env python3
"""motion.py — every recorded tour, as an animation that plays in the README.

    python3 docs/tools/motion.py           write docs/images/motion/<tour>.svg
    python3 docs/tools/motion.py --check   fail if any of them is out of date

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; which tours,
which signals and which window are in docs/site/site.json under "motion".
Every edge is drawn from docs/site/data/traces/<tour>.json, the recording
`make -C test tour` made, so an animation shows the recording, not a drawing
of it. The output is plain SVG text: deterministic, diffable, and played by
GitHub inline.

Motion is opt-in. With no CSS animation, or with prefers-reduced-motion set,
each file is a still: the whole window drawn, the tour's summary as its
caption and no cursor. Only under prefers-reduced-motion: no-preference does
a cursor sweep the window from caption to caption, revealing the recording
as it goes.
"""
import html, json, os, sys, textwrap

# the explorer's dark theme, as in readme_media.py, which reads on GitHub's light and dark pages alike
BG, PANEL, INK, MUTED, LINE = "#0f1214", "#161a1d", "#e8ebe9", "#9aa3a7", "#2c3337"
BIT, BUS, ENUM, CUR, HOST, CHIP, XS = "#6ea8f0", "#3fc49b", "#e68db3", "#ff7d47", "#6ea8f0", "#e3a440", "#5b656a"
W, LABEL, ROW, TOP, PAD = 880, 150, 24, 66, 14
MOVE, HOLD, LAST = 0.7, 2.6, 4.0          # seconds: sweep to a caption, read it, read the last one
SANS = "font-family='system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif'"
MONO = "font-family='ui-monospace,SFMono-Regular,Consolas,Menlo,monospace'"
esc = lambda s: html.escape(str(s), quote=True)
n2 = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")


def fmt(sig, v):
    if v is None:
        return "x"
    if sig["kind"] == "enum":
        return sig["enum"][v] if v < len(sig["enum"]) else str(v)
    if sig["kind"] == "text":
        return str(v)
    if sig["width"] > 4:
        return "0x%0*X" % ((sig["width"] + 3) // 4, v)
    return "%X" % v


def segments(sig, lo, hi):
    """(start, end, value) runs inside [lo, hi], end exclusive."""
    ch = sig["changes"]
    out = []
    for k, (c0, v) in enumerate(ch):
        c1 = ch[k + 1][0] if k + 1 < len(ch) else hi + 1
        a, b = max(c0, lo), min(c1, hi + 1)
        if b > a:
            out.append((a, b, v))
    return out


def wave(fx, sigs, lo, hi):
    """The whole window, drawn once: the still, and what the curtain uncovers."""
    span = hi - lo + 1
    x = lambda c: LABEL + (min(max(c, lo), hi + 1) - lo) / span * (W - LABEL - PAD)
    rows = list(sigs) + (["host", "chip"] if fx.get("bytes") else [])
    p = []
    for i, s in enumerate(rows):
        y = TOP + i * ROW
        p.append(f"<line x1='{LABEL}' y1='{y + ROW}' x2='{W - PAD}' y2='{y + ROW}' stroke='{LINE}' stroke-width='.5'/>")
        if isinstance(s, str):
            p.append(f"<text x='16' y='{y + 16}' fill='{MUTED}' font-size='12'>{'host → chip' if s == 'host' else 'chip → host'}</text>")
            col = HOST if s == "host" else CHIP
            for b in fx["bytes"]:
                if b["dir"] != s or b["end"] < lo or b["at"] > hi:
                    continue
                x0, x1 = x(b["at"]), x(b["end"])
                p.append(f"<rect x='{n2(x0)}' y='{y + 4}' width='{n2(max(2, x1 - x0))}' height='{ROW - 8}' rx='3' fill='{PANEL}' stroke='{col}'/>")
                if x1 - x0 > 22:
                    p.append(f"<text x='{n2(x0 + 4)}' y='{y + 16}' fill='{INK}' font-size='11' {MONO}>{b['byte']:02X}</text>")
            continue
        p.append(f"<text x='16' y='{y + 16}' fill='{MUTED}' font-size='12'>{esc(s['label'])}</text>")
        segs = segments(s, lo, hi)
        if s["kind"] == "bit":
            # one path for the whole row; changes closer than a pixel merge into one stroke
            d, last = [], None
            for a, b, v in segs:
                yy = y + 5 if v else y + ROW - 5
                if v is None:
                    p.append(f"<rect x='{n2(x(a))}' y='{y + 6}' width='{n2(max(.5, x(b) - x(a)))}' height='{ROW - 12}' fill='{XS}'/>")
                    last = None
                    continue
                d.append(f"{'L' if last is not None else 'M'}{n2(x(a))} {yy}H{n2(x(b))}")
                last = yy
            if d:
                p.append(f"<path d='{''.join(d)}' fill='none' stroke='{BIT}' stroke-width='2'/>")
            continue
        col = ENUM if s["kind"] == "enum" else BUS
        busy = None                         # a run of values too short to draw one by one
        for a, b, v in segs + [(hi + 1, hi + 1, None)]:
            x0, x1 = x(a), x(b)
            if b > a and x1 - x0 < 4:
                busy = (busy[0] if busy else x0, x1, busy[2] if busy else v, v, (busy[4] if busy else 0) + 1)
                continue
            if busy:
                bx0, bx1, v0, v1, k = busy
                p.append(f"<rect x='{n2(bx0)}' y='{y + 5}' width='{n2(max(.5, bx1 - bx0))}' height='{ROW - 10}' fill='{col}' opacity='.35'/>")
                t = f"{fmt(s, v0)} … {fmt(s, v1)}  ({k} values)"
                if bx1 - bx0 - 10 > len(t) * 6.6:
                    p.append(f"<text x='{n2(bx0 + 6)}' y='{y + 16}' fill='{INK}' font-size='11' {MONO}>{esc(t)}</text>")
                busy = None
            if b <= a:
                continue
            if v is None:
                p.append(f"<rect x='{n2(x0)}' y='{y + 6}' width='{n2(x1 - x0)}' height='{ROW - 12}' fill='{XS}'/>")
                continue
            m = y + ROW / 2
            p.append(f"<path d='M{n2(x0)} {m}L{n2(x0 + 3)} {y + 5}H{n2(x1 - 3)}L{n2(x1)} {m}L{n2(x1 - 3)} {y + ROW - 5}H{n2(x0 + 3)}Z' fill='{PANEL}' stroke='{col}'/>")
            t = fmt(s, v)
            room = int((x1 - x0 - 10) / 6.6)
            if room >= min(len(t), 3):
                t = t if len(t) <= room else t[:room - 1] + "…"
                p.append(f"<text x='{n2(x0 + 6)}' y='{y + 16}' fill='{INK}' font-size='11' {MONO}>{esc(t)}</text>")
    yb = TOP + len(rows) * ROW
    for m in fx.get("marks", []):
        if lo <= m["at"] <= hi:
            xm = x(m["at"])
            anchor = "end" if xm > W - 120 else "start"
            p.append(f"<line x1='{n2(xm)}' y1='{TOP - 4}' x2='{n2(xm)}' y2='{yb}' stroke='{MUTED}' stroke-dasharray='3 3'/>"
                     f"<text x='{n2(xm + (-3 if anchor == 'end' else 3))}' y='{yb + 13}' text-anchor='{anchor}' fill='{MUTED}' font-size='11'>{esc(m['label'])}</text>")
    return "".join(p), x, yb


def caption(text, y0, cls):
    lines = textwrap.wrap(text, 118)[:3]
    if len(textwrap.wrap(text, 118)) > 3:
        lines[-1] = lines[-1][:115] + "…"
    ts = "".join(f"<tspan x='16' dy='{0 if i == 0 else 18}'>{esc(ln)}</tspan>" for i, ln in enumerate(lines))
    hide = "" if cls.endswith("sum") else " visibility='hidden'"
    return f"<text class='{cls}'{hide} x='16' y='{y0}' fill='{INK}' font-size='13'>{ts}</text>"


def reel(fx, cfg, clock_ns):
    byid = {s["id"]: s for s in fx["signals"]}
    missing = [i for i in cfg["signals"] if i not in byid]
    if missing:
        sys.exit(f"motion.py: tour '{fx['id']}' has no signal {missing}")
    sigs = [byid[i] for i in cfg["signals"]]
    lo, hi = cfg.get("window", fx["cycles"])
    caps = [c for c in fx["captions"] if lo <= c["at"] <= hi]
    if not caps:
        sys.exit(f"motion.py: tour '{fx['id']}' has no caption inside {lo}..{hi}")
    body, x, yb = wave(fx, sigs, lo, hi)
    H = yb + 30 + 3 * 18 + 22
    # the timeline: sweep to caption i and hold it; after the last one, sweep on to the
    # end of the window, hold the whole recording, and start again
    t, stops = 0.0, []
    for c in caps:
        stops.append((t, t + MOVE, c))
        t += MOVE + HOLD
    tail = (t, t + 2 * MOVE)
    total = t + 2 * MOVE + LAST
    pc = lambda s: f"{100 * s / total:.2f}%"
    xcur = lambda c: min(x(c + 1) + 3, W - PAD)     # just past the captioned cycle, so its edge is uncovered
    full = W - PAD - LABEL
    # the curtain hides what is to the right of the cursor; the cursor rides its left edge
    kf, prev = [], 0.0
    for a, b, d in [(a, b, xcur(c["at"]) - LABEL) for a, b, c in stops] + [(*tail, full)]:
        kf.append(f"{pc(a)}{{transform:translateX({prev:.1f}px);animation-timing-function:ease-in-out}}")
        kf.append(f"{pc(b)}{{transform:translateX({d:.1f}px)}}")
        prev = d
    kf.append(f"99.6%{{transform:translateX({prev:.1f}px)}}100%{{transform:translateX(0)}}")
    # every class, keyframe and id carries the tour's name, so pages can inline several reels side by side
    P = "m-" + fx["id"]
    css = [f"@keyframes {P}-sweep{{{''.join(kf)}}}",
           "@media (prefers-reduced-motion:no-preference){",
           f".{P}-sum{{visibility:hidden}}.{P}-cap,.{P}-cur,.{P}-curtain{{visibility:visible}}.{P}-cap{{opacity:0}}",
           f".{P}-curtain,.{P}-cur{{animation:{P}-sweep {total:.2f}s infinite}}"]
    for i, (a, b, c) in enumerate(stops):
        end = stops[i + 1][1] if i + 1 < len(stops) else total
        css.append(f"@keyframes {P}-c{i}{{0%,{pc(b)}{{opacity:0}}{pc(b + .15)},{pc(max(b + .2, end - .05))}{{opacity:1}}{pc(end)},100%{{opacity:0}}}}"
                   f".{P}-c{i}{{animation:{P}-c{i} {total:.2f}s infinite}}")
    css.append("}")
    span_ns = (hi - lo + 1) * clock_ns
    when = f"{span_ns / 1000:,.2f} µs" if span_ns < 1e6 else f"{span_ns / 1e6:,.2f} ms"
    head = (f"<text x='16' y='26' fill='{INK}' font-size='16' font-weight='700'>{esc(fx['title'])}</text>"
            f"<text x='16' y='46' fill='{MUTED}' font-size='12'>cycles {lo} to {hi} · {when} at {1000 / clock_ns:g} MHz</text>")
    tag = "Recorded from RTL simulation"
    tw = len(tag) * 6.2 + 20
    head += (f"<rect x='{n2(W - PAD - tw)}' y='12' width='{n2(tw)}' height='20' rx='10' fill='none' stroke='{BIT}'/>"
             f"<text x='{n2(W - PAD - tw / 2)}' y='26' text-anchor='middle' fill='{BIT}' font-size='11'>{tag}</text>")
    # hidden unless motion is wanted, so a still (or a viewer without CSS) shows the whole window
    curtain = f"<rect class='{P}-curtain' visibility='hidden' x='{LABEL}' y='{TOP - 6}' width='{full + PAD + 2}' height='{yb - TOP + 22}' fill='{BG}'/>"
    cur = f"<line class='{P}-cur' visibility='hidden' x1='{LABEL}' y1='{TOP - 6}' x2='{LABEL}' y2='{yb}' stroke='{CUR}' stroke-width='2'/>"
    yc = yb + 30 + 14
    caps_svg = caption(fx["summary"], yc, f"{P}-sum") + "".join(caption(c["text"], yc, f"{P}-cap {P}-c{i}") for i, (_, _, c) in enumerate(stops))
    desc = f"{fx['summary']} {fx['kind_text']}. Made by docs/tools/motion.py from docs/site/data/traces/{fx['id']}.json."
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='{W}' height='{H}' role='img' aria-labelledby='{P}-t {P}-d' {SANS}>"
            f"<title id='{P}-t'>{esc(fx['title'])}</title><desc id='{P}-d'>{esc(desc)}</desc>"
            f"<style>{''.join(css)}</style>"
            f"<rect width='{W}' height='{H}' rx='12' fill='{BG}'/>{head}{body}"
            f"{curtain}{cur}"
            f"<rect x='0' y='{yb + 22}' width='{W}' height='{H - yb - 22}' rx='12' fill='{PANEL}'/><rect x='0' y='{yb + 22}' width='{W}' height='12' fill='{PANEL}'/>"
            f"{caps_svg}</svg>\n"), total


def main():
    check = "--check" in sys.argv
    site = json.load(open("docs/site/site.json"))
    m = site.get("motion")
    if not m:
        sys.exit("motion.py: docs/site/site.json has no \"motion\" section")
    out, stale, lines = {}, [], []
    for cfg in m["reels"]:
        fx = json.load(open(f"docs/site/data/traces/{cfg['fixture']}.json"))
        if fx.get("kind") != "recorded":
            sys.exit(f"motion.py: tour '{fx['id']}' is not a recording")
        svg, total = reel(fx, cfg, site["clock_ns"])
        path = f"{m['out']}/{fx['id']}.svg"
        out[path] = svg
        lines.append(f"{path} ({len(svg) / 1024:.0f} KB, {total:.1f} s loop)")
    for path, text in out.items():
        if check:
            if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
                stale.append(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(text)
    extra = sorted(f"{m['out']}/{f}" for f in os.listdir(m["out"]) if f.endswith(".svg") and f"{m['out']}/{f}" not in out) if os.path.isdir(m["out"]) else []
    if check:
        if stale or extra:
            print("motion: out of date, run python3 docs/tools/motion.py: " + ", ".join(stale + [f"{e} (no reel)" for e in extra]))
            sys.exit(1)
        print(f"motion: {len(out)} animations up to date")
    else:
        for e in extra:
            os.remove(e)
            print(f"removed {e}: no reel in site.json")
        print("wrote " + "; ".join(lines))


if __name__ == "__main__":
    main()
