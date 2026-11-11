#!/usr/bin/env python3
"""cards.py — the README's feature cards, drawn from the repository's own data.

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. Each repository lists
its cards in docs/cards.json; this script draws one SVG per card into
docs/images/cards/. A card is a title, a small picture and two short lines.

Nothing on a card is invented:
  * every number in a card's lines must sit inside one of its "cite" strings, and
    every cite string must appear, word for word, in README.md, where it carries
    its measurement, version and command;
  * the pictures are drawn from recorded or measured files: the deadline from
    docs/site/data/schematic.json (recorded inside sync_compare by tb_tour.sv), the
    register from docs/site/data/adder.json, the serial bytes from
    docs/site/data/traces/host-protocol.json, the die from the area cited on the
    card, the bars from docs/progress.json.

The SVGs follow the reader's light or dark setting (a prefers-color-scheme rule
inside each file, which GitHub honours for images), and their one-time entrance
animation is skipped under prefers-reduced-motion. The output is deterministic:
the same data gives the same bytes.

It also writes the README's "A deadline, step by step" table, between its
<!-- steps:begin --> and <!-- steps:end --> markers, from the same recording: the
clocks named in docs/cards.json "steps", each with the caption the recording
carries (docs/site/data/schematic.json, written by docs/tools/schematic.py).

  python3 docs/tools/cards.py            write docs/images/cards/*.svg and the README table
  python3 docs/tools/cards.py --check    the files match the data, and the cites hold
  python3 docs/tools/cards.py --mutants  prove --check catches broken numbers and pictures
"""
import json
import pathlib
import re
import sys
from html import escape

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/images/cards"
W, H = 460, 270
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

STYLE = (
    "svg{--bg:#ffffff;--edge:#d0d7de;--ink:#1f2328;--ink2:#59636e;--dim:#d8dee4;--box:#f6f8fa;"
    "--hi:#bf6a00;--ok:#1a7f37;--acc:#0969da}"
    "@media (prefers-color-scheme:dark){svg{--bg:#0d1117;--edge:#3d444d;--ink:#e6edf3;--ink2:#9198a1;"
    "--dim:#30363d;--box:#151b23;--hi:#ffb000;--ok:#3fb950;--acc:#4493f8}}"
    f".bg{{fill:var(--bg);stroke:var(--edge)}}.t{{font:700 22px {FONT};fill:var(--ink);letter-spacing:-.3px}}"
    f".e{{font:600 13px {FONT};fill:var(--hi)}}.l{{font:400 13.5px {FONT};fill:var(--ink2)}}"
    f".m{{font:500 12px {MONO};fill:var(--ink2)}}.mb{{font:700 17px {MONO};fill:var(--ink)}}"
    ".box{fill:var(--box);stroke:var(--edge)}.dim{stroke:var(--dim);fill:none}.hi{stroke:var(--hi);fill:none}"
    ".hif{fill:var(--hi)}.okf{fill:var(--ok)}.dimf{fill:var(--dim)}.acc{stroke:var(--acc);fill:none}"
    ".pill{fill:none;stroke:var(--hi)}"
    "@media (prefers-reduced-motion:no-preference){"
    ".draw{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.1s cubic-bezier(.23,1,.32,1) .25s forwards}"
    "@keyframes draw{to{stroke-dashoffset:0}}"
    ".rise{opacity:0;animation:rise .55s cubic-bezier(.23,1,.32,1) forwards;animation-delay:calc(var(--d,0)*90ms + 200ms)}"
    "@keyframes rise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}"
    ".grow{transform-box:fill-box;transform-origin:left;transform:scaleX(0);"
    "animation:grow .9s cubic-bezier(.23,1,.32,1) forwards;animation-delay:calc(var(--d,0)*110ms + 250ms)}"
    "@keyframes grow{to{transform:none}}}"
)


def load(p):
    return json.loads((ROOT / p).read_text())


# ---------------------------------------------------------------- pictures (each returns SVG and its own checks)

def pic_wave(card):
    """The recorded deadline: TRIG0 low, then high from the armed tick, as tb_tour.sv read it inside sync_compare."""
    d = load("docs/site/data/schematic.json")
    steps = d["steps"]
    rise = next(k for k, s in enumerate(steps) if s["pin"])
    errs = []
    if steps[rise]["now"] != d["deadline"]:
        errs.append(f"the recorded pin rises at now {steps[rise]['now']}, not at the deadline {d['deadline']}")
    x0, x1, y_lo, y_hi = 40, 420, 158, 112
    n = len(steps)
    xs = [x0 + (x1 - x0) * k / (n - 1) for k in range(n)]
    pts, prev = [], None
    for k, s in enumerate(steps):
        y = y_hi if s["pin"] else y_lo
        if prev is not None and y != prev:
            pts.append((xs[k], prev))
        pts.append((xs[k], y))
        prev = y
    path = "M" + " L".join(f"{x:.1f},{y}" for x, y in pts)
    xr = xs[rise]
    o = [f"<line class=dim x1={x0} y1={y_lo + 14} x2={x1} y2={y_lo + 14} stroke-width=1/>",
         f"<text class=m x={x0} y={y_lo - 30}>TRIG0</text>",
         f"<path class='hi draw' pathLength=1 stroke-width=3 stroke-linejoin=round d='{path}'/>",
         f"<line class=acc x1={xr:.1f} y1={y_hi - 14} x2={xr:.1f} y2={y_lo + 20} stroke-width=1.5 stroke-dasharray='3 3'/>",
         f"<text class=m x={xr + 6:.1f} y={y_hi - 4}>tick {d['deadline']:,}</text>"]
    return "".join(o), errs


def pic_ring(card):
    """The nibble-serial register: rd after the recorded add, one 4-bit nibble per clock."""
    d = load("docs/site/data/adder.json")
    s = max((s for s in d["steps"] if "add" in s.get("asm", "")), key=lambda s: s["cycle"])
    nib = [str(s[f"r{k}"]) for k in range(7, -1, -1)]
    errs = []
    if any(not re.fullmatch(r"[0-9a-f]", v) for v in nib):
        errs.append("the recorded register holds a value that is not a nibble")
    o = [f"<text class=m x=40 y=100>{escape(s['rd'].split(' ')[0])} after {escape(s['asm'])}</text>",
         "<text class=m x=40 y=174>nibble 7</text><text class=m x=420 y=174 text-anchor=end>nibble 0</text>"]
    for k, v in enumerate(nib):
        x = 40 + k * 48
        o.append(f"<g class=rise style='--d:{7 - k}'><rect class=box x={x} y=110 width=40 height=46 rx=8/>"
                 f"<text class=mb x={x + 20} y={140} text-anchor=middle>{v}</text></g>")
    o.append("<path class='hi draw' pathLength=1 stroke-width=2 d='M392,182 C392,196 88,196 88,182'/>")
    return "".join(o), errs


def pic_die(card):
    """The die as the tiles it buys, filled to the measured share of standard-cell area."""
    tiles = card["tiles"]                       # [columns, rows]
    share = card["share"]                       # the cited percentage
    cols, rows = tiles
    tw, th = 64, 38
    w, h = cols * tw, rows * th
    x0, y0 = 40, 92
    o = [f"<rect class=box x={x0} y={y0} width={w} height={h} rx=6/>",
         (f"<rect class='hif grow' style='opacity:.22' x={x0 + 1} y={y0 + 1} width={(w - 2) * share / 100:.1f} height={h - 2} rx=5/>"
          if cols >= rows else   # a portrait die fills from the bottom
          f"<rect class=hif style='opacity:.22' x={x0 + 1} y={y0 + 1 + (h - 2) * (1 - share / 100):.1f} width={w - 2} "
          f"height={(h - 2) * share / 100:.1f} rx=5/>")]
    for c in range(1, cols):
        o.append(f"<line class=dim x1={x0 + c * tw} y1={y0} x2={x0 + c * tw} y2={y0 + h} stroke-dasharray='3 3'/>")
    for r in range(1, rows):
        o.append(f"<line class=dim x1={x0} y1={y0 + r * th} x2={x0 + w} y2={y0 + r * th} stroke-dasharray='3 3'/>")
    bx = x0 + w + 36
    bw = W - 40 - bx
    o.append(f"<text class=m x={bx} y={y0 + 10}>standard cells</text>")
    o.append(f"<rect class=dimf x={bx} y={y0 + 22} width={bw} height=16 rx=8/>")
    o.append(f"<rect class='hif grow' x={bx} y={y0 + 22} width={bw * share / 100:.1f} height=16 rx=8/>")
    o.append(f"<text class=mb x={bx} y={y0 + 66}>{share}%</text><text class=m x={bx + 50} y={y0 + 66}>of the die</text>")
    o.append(f"<text class=m x={x0} y={y0 + h + 18}>{cols} × {rows} tiles</text>")
    return "".join(o), []


def pic_bytes(card):
    """The recorded serial session: each host command, byte by byte, and the chip's reply."""
    d = load("docs/site/data/traces/host-protocol.json")
    errs = []
    rows = [c for c in d["commands"] if c["cmd"] in card["commands"]]
    if len(rows) != len(card["commands"]):
        errs.append("a command named on the card is missing from the recording")
    o, y = [], 102
    for k, c in enumerate(rows):
        if c.get("got") != c.get("reply"):
            errs.append(f"{c['cmd']}: the recorded reply differs from the expected one")
        o.append(f"<text class=m x=40 y={y}>{escape(c['cmd'])}</text>")
        x = 40
        for j, b in enumerate(c["bytes"]):
            o.append(f"<g class=rise style='--d:{k * 6 + j}'><rect class=box x={x} y={y + 8} width=34 height=28 rx=6/>"
                     f"<text class=m x={x + 17} y={y + 27} text-anchor=middle>{b:02X}</text></g>")
            x += 38
        o.append(f"<text class=m x={x + 6} y={y + 27}>→</text>")
        x += 24
        for j, b in enumerate(c["got"]):
            o.append(f"<g class=rise style='--d:{k * 6 + 6 + j}'><rect class='box' x={x} y={y + 8} width=34 height=28 rx=6 "
                     f"style='stroke:var(--hi)'/><text class=m x={x + 17} y={y + 27} text-anchor=middle>{b:02X}</text></g>")
            x += 38
        y += 52
    return "".join(o), errs


def pic_bars(card):
    """docs/progress.json: each milestone's steps done of steps, measured results only."""
    p = load("docs/progress.json")
    ms = p["milestones"]
    o, y = [], 88
    bw = 110
    for k, m in enumerate(ms):
        done = sum(s["state"] == "done" for s in m["steps"])
        n = len(m["steps"])
        o.append(f"<text class=m x=40 y={y + 10}>{escape(m['name'])}</text>")
        o.append(f"<rect class=dimf x=290 y={y} width={bw} height=11 rx=5.5/>")
        if done:
            o.append(f"<rect class='okf grow' style='--d:{k}' x=290 y={y} width={bw * done / n:.1f} height=11 rx=5.5/>")
        o.append(f"<text class=m x={290 + bw + 8} y={y + 10}>{done}/{n}</text>")
        y += 17
    return "".join(o), []


PICS = {"wave": pic_wave, "ring": pic_ring, "die": pic_die, "bytes": pic_bytes, "bars": pic_bars}


# ---------------------------------------------------------------- cards

NUM = re.compile(r"(?<![A-Za-z0-9])(?:\d[\d,.]*\d|\d)(?![A-Za-z])")


def cite_errors(card, readme):
    """Every number on the card sits inside a cite, and every cite is in README.md word for word."""
    errs = []
    for c in card.get("cite", []):
        if c not in readme:
            errs.append(f"{card['id']}: cite not in README.md: {c!r}")
    for line in [card["title"]] + card["lines"]:
        rest = line
        for c in card.get("cite", []):
            rest = rest.replace(c, " ")
        for n in NUM.findall(rest):
            errs.append(f"{card['id']}: {n!r} in {line!r} is not inside a cite")
    if card["visual"] == "die" and f"{card['share']}%" not in " ".join(card["cite"]):
        errs.append(f"{card['id']}: the drawn share {card['share']}% is not a cited number")
    return errs


def xml(svg):
    """Quote every attribute, so the file is XML (GitHub serves it as an image), as schematic.py does."""
    return re.sub(r"<[^<>]+>", lambda t: re.sub(r"(\s[\w:-]+)=([^\s'\">/]+)", r'\1="\2"', t.group(0)), svg)


def render(card):
    body, errs = PICS[card["visual"]](card)
    lines = "".join(f"<text class=l x=40 y={222 + 20 * k}>{escape(t)}</text>" for k, t in enumerate(card["lines"]))
    alt = f"{card['title']}: " + " ".join(card["lines"])
    ev = card["evidence"]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' viewBox='0 0 {W} {H}' role='img'"
           f" aria-label='{escape(alt, quote=True)}'><title>{escape(alt)}</title><style>{STYLE}</style>"
           f"<rect class=bg x=.5 y=.5 width={W - 1} height={H - 1} rx=16/>"
           f"<text class=e x=40 y=42>{escape(card['eyebrow'])}</text>"
           f"<rect class=pill x={W - 40 - 8 * len(ev) - 18} y=27 width={8 * len(ev) + 18} height=22 rx=11/>"
           f"<text class=e x={W - 40 - 9} y=42 text-anchor=end style='font-size:11.5px'>{escape(ev)}</text>"
           f"<text class=t x=40 y=72>{escape(card['title'])}</text>{body}{lines}</svg>\n")
    return xml(svg), errs


BEGIN = "<!-- steps:begin (generated by docs/tools/cards.py from docs/site/data/schematic.json; do not edit) -->"
END = "<!-- steps:end -->"


def steps_table(cfg):
    """The README table: each named clock of the recorded deadline, with the recording's own caption."""
    d = load("docs/site/data/schematic.json")
    rows = ["| Step | Tick | What the recording shows |", "|---|---:|---|"]
    for st in cfg["steps"]:
        s = d["steps"][st["at"]]
        rows.append(f"| **{st['name']}** | {s['now']:,} | {s['text'].replace('|', '/')} |")
    return BEGIN + "\n\n" + "\n".join(rows) + "\n\n" + END


def with_steps(readme, cfg):
    if "steps" not in cfg:
        return readme
    a, b = readme.find(BEGIN.split(" (")[0]), readme.find(END)
    if a < 0 or b < 0:
        raise SystemExit("cards.py: README.md has no <!-- steps:begin --> ... <!-- steps:end --> block")
    return readme[:a] + steps_table(cfg) + readme[b + len(END):]


def build():
    cfg = load("docs/cards.json")
    readme = (ROOT / "README.md").read_text()
    out, errs = {ROOT / "README.md": with_steps(readme, cfg)}, []
    for card in cfg["cards"]:
        svg, e = render(card)
        errs += [f"{card['id']}: {x}" for x in e] + cite_errors(card, readme)
        out[OUT / f"{card['id']}.svg"] = svg
    return out, errs


def check():
    out, errs = build()
    for p, svg in out.items():
        if not p.exists() or p.read_text() != svg:
            errs.append(f"{p.relative_to(ROOT)} is stale: run python3 docs/tools/cards.py")
    return errs


def mutants():
    """Break each card's numbers, cites and recorded pictures one at a time; --check must catch every one."""
    cfg = load("docs/cards.json")
    readme = (ROOT / "README.md").read_text()
    caught = total = 0
    base = [e for c in cfg["cards"] for e in cite_errors(c, readme)]
    if base:
        print("cards: the cards fail --check before any mutation:", *base, sep="\n  ")
        return False

    def bump(t):
        m = NUM.search(t)
        if not m:
            return None
        n = m.group(0)
        k = max(i for i, ch in enumerate(n) if ch.isdigit())
        return t[:m.start() + k] + str((int(n[k]) + 1) % 10) + t[m.start() + k + 1:]

    for card in cfg["cards"]:
        for field in ("lines", "cite"):
            for i, t in enumerate(card.get(field, [])):
                b = bump(t)
                if b is None:
                    continue
                total += 1
                bad = json.loads(json.dumps(card))
                bad[field][i] = b
                if cite_errors(bad, readme):
                    caught += 1
                else:
                    print(f"  missed: {card['id']} {field}[{i}] -> {b!r}")
    # the recorded pictures: a deadline that misses its tick, a reply that differs
    import unittest.mock as um
    sch = load("docs/site/data/schematic.json")
    sch["deadline"] += 1
    real = load
    for vis, fake, path in (("wave", sch, "docs/site/data/schematic.json"),):
        if any(c["visual"] == vis for c in cfg["cards"]):
            total += 1
            with um.patch(__name__ + ".load", lambda p, f=fake, q=path: f if p == q else real(p)):
                if pic_wave(next(c for c in cfg["cards"] if c["visual"] == vis))[1]:
                    caught += 1
    if any(c["visual"] == "bytes" for c in cfg["cards"]):
        hp = load("docs/site/data/traces/host-protocol.json")
        card = next(c for c in cfg["cards"] if c["visual"] == "bytes")
        tgt = next(c for c in hp["commands"] if c["cmd"] in card["commands"])
        tgt["got"] = [(tgt["got"][0] + 1) & 255] + tgt["got"][1:]
        total += 1
        with um.patch(__name__ + ".load", lambda p: hp if p.endswith("host-protocol.json") else real(p)):
            if pic_bytes(card)[1]:
                caught += 1
    if "steps" in cfg:
        good = with_steps(readme, cfg)
        k = good.find("| **", good.find(BEGIN))
        bad = good[:k] + good[k:].replace(" |", " 1 |", 1)
        total += 1
        if with_steps(bad, cfg) != bad:
            caught += 1
    print(f"cards: --check caught {caught} of {total} broken copies")
    return caught == total and total > 0


def main():
    if "--mutants" in sys.argv:
        sys.exit(0 if mutants() else 1)
    if "--check" in sys.argv:
        errs = check()
        for e in errs:
            print("  FAIL ", e)
        cfg = load("docs/cards.json")
        print(f"cards: {len(cfg['cards'])} cards and the steps table, " + ("ok" if not errs else f"{len(errs)} problem(s)"))
        sys.exit(1 if errs else 0)
    out, errs = build()
    if errs:
        for e in errs:
            print("  FAIL ", e)
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    for p, svg in out.items():
        p.write_text(svg)
    print(f"cards: wrote {len(out) - 1} cards to {OUT.relative_to(ROOT)} and the README's steps table")


if __name__ == "__main__":
    main()
