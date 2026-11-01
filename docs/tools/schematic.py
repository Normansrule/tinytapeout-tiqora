#!/usr/bin/env python3
"""schematic.py — one deadline channel's logic, lit by the RTL's own signals.

    python3 docs/tools/schematic.py              run make -C test tour, write the data and the drawings
    python3 docs/tools/schematic.py --check      no simulation: fail if the data breaks the RTL's
                                                 equations, disagrees with the deadline tour, or any
                                                 drawing is out of date
    python3 docs/tools/schematic.py --check-sim  simulate again and fail if the data differs
    python3 docs/tools/schematic.py --mutants    break copies of the data and confirm --check catches each

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; the words that
differ (where arm_time comes from) are in docs/site/site.json under
"schematic". test/tb_tour.sv writes test/schematic_probe.txt: every value this
drawing shows on a wire is read inside sync_compare by the testbench, on the
falling edge of each clock, after every flip-flop has updated. Two values are
arithmetic on recorded ones and say so: the subtractor's output (now minus
deadline - 1) and the counter's cnt - 1.

Before anything is written, every recorded clock is checked against the RTL's
equations, written again here in Python (an independent model, not a copy of
the simulator's numbers):

    reached  = signed(now - dm1) >= 0
    fire     = armed & reached | pulse_we
    armed'   = arm_we ? 1 : (armed & reached ? 0 : armed)
    dm1'     = arm_we ? arm_time - 1 : dm1
    pcnt'    = fire ? pw : (pcnt != 0 ? pcnt - 1 : 0)
    trig     = pcnt != 0 ;  pin = trig

and against the deadline tour in docs/site/data/traces/deadline.json (same
simulation): the arm, the deadline and the trigger edge must be the same
clocks. Each component carries the line of src/sync/sync_compare.sv it draws,
found by its text, so a changed RTL line fails the check instead of linking
to the wrong place.

Outputs: docs/site/data/schematic.json (the steps, for docs/site/lib/schematic.js),
docs/images/schematic_deadline.svg (the README's animation: it steps through
the recording on its own, and is a still of the trigger edge under reduced
motion). build_site.py inlines the same drawing, at the same still, into the
overview page, so it reads without JavaScript.
"""
import copy, html, json, os, re, subprocess, sys, textwrap

DATA = "docs/site/data/schematic.json"
README_SVG = "docs/images/schematic_deadline.svg"
PROBE = "test/schematic_probe.txt"
FIXTURE = "docs/site/data/traces/deadline.json"
RTL = "src/sync/sync_compare.sv"
COLS = ["cycle", "now", "arm_we", "arm_sel", "arm_time", "arm_m1", "dm1", "reached", "fire",
        "armed", "pcnt", "pw", "pulse_we", "trig", "pin"]
M32 = 0xFFFFFFFF
W, H = 1120, 560
esc = lambda s: html.escape(str(s), quote=True)

# The RTL line each part of the drawing stands for, found by its text.
PARTS = {
    "minus1":  ("arm_time - 1",            "assign arm_time_m1 = arm_time - 32'd1;"),
    "mux_dm1": ("load the deadline",       "deadline_m1[i] <= arm_time_m1;"),
    "dm1":     ("deadline - 1 register",   "(* mem2reg *) logic [31:0]    deadline_m1"),
    "sub":     ("the compare",             "assign reached = ($signed(now - deadline_m1[i]) >= 0);"),
    "and":     ("armed and reached",       "assign fire    = (armed[i] && reached) ||"),
    "or":      ("or a direct pulse",       "(pulse_we && pulse_mask[i]);"),
    "armed":   ("armed flip-flop",         "armed[i]    <= 1'b1;"),
    "clear":   ("disarm when reached",     "end else if (armed[i] && reached) begin"),
    "mux_cnt": ("load the pulse width",    "if (fire)                        pulse_cnt[i] <= pw;"),
    "cnt":     ("pulse counter",           "else if (pulse_cnt[i] != '0)     pulse_cnt[i] <= pulse_cnt[i] - 1'b1;"),
    "nz":      ("trigger output",          "assign trig[i] = (pulse_cnt[i] != '0);"),
    "pw":      ("pulse width, 8 at reset", "if (rst)        pw <= {{(PWW-4){1'b0}}, 4'd8};"),
}


def rtl_lines():
    src = open(RTL).read().splitlines()
    out = {}
    for k, (_, text) in PARTS.items():
        hits = [i + 1 for i, ln in enumerate(src) if text in ln]
        if len(hits) != 1:
            raise ValueError(f"{RTL}: expected one line containing {text!r}, found {len(hits)}")
        out[k] = hits[0]
    return out


# ------------------------------------------------------------------ the data
def read_probe(path):
    lines = open(path).read().split("\n")
    if lines[0].split() != COLS:
        raise ValueError(f"{path}: columns are {lines[0].split()}, expected {COLS}")
    rows = []
    for ln in lines[1:]:
        if ln.strip():
            p = ln.split()
            rows.append({c: (int(p[0]) if c == "cycle" else int(v, 16)) for c, v in zip(COLS, p)})
    return rows


def sgn(v):
    return v - (1 << 32) if v & 0x80000000 else v


def model_errors(rows):
    """Every recorded clock against the RTL's equations, written again here."""
    err = []
    for i, r in enumerate(rows):
        c = r["cycle"]
        if r["reached"] != (1 if sgn((r["now"] - r["dm1"]) & M32) >= 0 else 0):
            err.append(f"cycle {c}: reached is {r['reached']}, but now - dm1 = {sgn((r['now'] - r['dm1']) & M32)}")
        if r["fire"] != ((r["armed"] & r["reached"]) | r["pulse_we"]):
            err.append(f"cycle {c}: fire is {r['fire']}, not armed & reached | pulse_we")
        if r["arm_m1"] != (r["arm_time"] - 1) & M32:
            err.append(f"cycle {c}: arm_time - 1 is {r['arm_m1']}")
        if r["trig"] != (1 if r["pcnt"] else 0):
            err.append(f"cycle {c}: trig is {r['trig']} with the counter at {r['pcnt']}")
        if r["pin"] != r["trig"]:
            err.append(f"cycle {c}: the pin is {r['pin']} and trig is {r['trig']}")
        if i + 1 < len(rows) and rows[i + 1]["cycle"] == c + 1:
            n = rows[i + 1]
            armed = 1 if r["arm_we"] and r["arm_sel"] == 0 else (0 if r["armed"] and r["reached"] else r["armed"])
            dm1 = r["arm_m1"] if r["arm_we"] and r["arm_sel"] == 0 else r["dm1"]
            pcnt = r["pw"] if r["fire"] else (r["pcnt"] - 1 if r["pcnt"] else 0)
            for k, want in (("armed", armed), ("dm1", dm1), ("pcnt", pcnt)):
                if n[k] != want:
                    err.append(f"cycle {c + 1}: {k} is {n[k]}, the RTL's next-state rule gives {want}")
            if n["now"] != (r["now"] + 1) & M32:
                err.append(f"cycle {c + 1}: the timebase did not count by one")
    return err


def changes(fx, sid):
    return next(s for s in fx["signals"] if s["id"] == sid)["changes"]


def fixture_errors(rows, fx):
    """The probe and the deadline tour come from one simulation: same arm, same deadline, same edge."""
    err = []
    arm = [r for r in rows if r["arm_we"] and r["arm_sel"] == 0]
    rise = [r for i, r in enumerate(rows) if r["pin"] and (i == 0 or not rows[i - 1]["pin"])]
    if len(arm) != 1 or len(rise) != 1:
        return [f"expected one arm and one trigger edge, found {len(arm)} and {len(rise)}"]
    dl = changes(fx, "deadline0")[-1]
    if dl != [arm[0]["cycle"] + 1, arm[0]["arm_time"]]:
        err.append(f"the tour's deadline is {dl}, the probe armed {arm[0]['arm_time']} at cycle {arm[0]['cycle']}")
    tr = [c for c, v in changes(fx, "trig0") if v == 1]
    if tr != [rise[0]["cycle"]]:
        err.append(f"the tour's TRIG0 rises at {tr}, the probe's at {rise[0]['cycle']}")
    if rise[0]["now"] != arm[0]["arm_time"]:
        err.append(f"the pin rose at now = {rise[0]['now']}, the deadline was {arm[0]['arm_time']}")
    return err


def pick(rows):
    """The arm and the clock after it, then the four clocks before the edge to the end of the pulse."""
    ia = next(i for i, r in enumerate(rows) if r["arm_we"] and r["arm_sel"] == 0)
    ie = next(i for i, r in enumerate(rows) if r["pin"] and not rows[i - 1]["pin"])
    lo = ie - 5
    if lo <= ia + 1:
        raise ValueError("the deadline is too close to the arm to show both")
    return rows[ia:ia + 2], rows[lo:]


def caption(r, prev, arm, deadline, source):
    d = sgn((r["now"] - r["dm1"]) & M32)
    if r["arm_we"]:
        return (f"Channel 0 is armed for tick {arm['arm_time']:,} by {source}: arm_time carries it and arm_we is high. "
                f"The -1 makes {arm['arm_m1']:,}, and the multiplexer steers it into the deadline register at this clock edge. "
                f"reached is already 1, against the register's reset value, but armed is 0, so the AND gate holds fire low.")
    if prev is not None and prev["arm_we"]:
        return (f"The register holds {r['dm1']:,} and armed is 1. now - (deadline - 1) = {d:,}: negative, "
                f"so reached is 0. From here the same subtraction runs on every clock, and nothing outside the timing unit takes part.")
    if r["fire"] and r["armed"]:
        return (f"now = {r['now']:,} = deadline - 1. The difference is 0, so reached rises, and with armed at 1 "
                f"the AND gate raises fire. Nothing has moved yet: fire is a wire, and the clock edge has not come.")
    if r["armed"]:
        return f"now = {r['now']:,}. now - (deadline - 1) = {d:,}: still negative, reached stays 0 and the pin stays low."
    if r["pin"] and not prev["pin"]:
        return (f"The clock edge. The counter loads pw = {r['pw']} and armed clears. The counter is not zero, so TRIG0 "
                f"on uo_out[0] goes high on this clock, when now = {r['now']:,}: the deadline exactly, 0 ticks late.")
    if r["pin"]:
        return f"The counter counts down to {r['pcnt']}. TRIG0 stays high; reached is still 1, but armed is 0, so fire stays low."
    if prev["pin"]:
        return (f"The counter reaches 0 and TRIG0 falls: a pulse of exactly {deadline['width']} clocks. "
                f"reached stays 1, since the deadline is now in the past, but armed is 0, so nothing fires again.")
    return "Idle: TRIG0 is low and the channel waits to be armed again."


def build(rows, site):
    arm_rows, fire_rows = pick(rows)
    arm = arm_rows[0]
    width = sum(1 for r in rows if r["pin"])
    steps, prev = [], None
    keep = ("cycle", "now", "arm_we", "arm_time", "arm_m1", "dm1", "reached", "fire", "armed", "pcnt", "pw", "pulse_we", "trig", "pin")
    for part, rs in (("arm", arm_rows), ("fire", fire_rows)):
        for r in rs:
            s = {k: r[k] for k in keep}
            s["diff"] = sgn((r["now"] - r["dm1"]) & M32)
            s["cnt_m1"] = r["pcnt"] - 1 if r["pcnt"] else 0
            s["part"] = part
            s["text"] = caption(r, prev, arm, {"width": width}, site.get("schematic", {}).get("arm_source", "a register write"))
            steps.append(s)
            prev = r
    edge = next(i for i, s in enumerate(steps) if s["pin"] and not steps[i - 1]["pin"])
    cfg = site.get("schematic", {})
    return {"schema": 1, "chip": site["chip"], "repo": site["repo"], "ref": site["ref"],
            "rtl": RTL, "lines": rtl_lines(), "parts": {k: v[0] for k, v in PARTS.items()},
            "arm_source": cfg.get("arm_source", "a register write"),
            "gap": fire_rows[0]["cycle"] - arm_rows[-1]["cycle"] - 1,
            "deadline": arm["arm_time"], "width": width, "edge": edge, "steps": steps,
            "provenance": {"command": "make -C test tour  (then python3 docs/tools/schematic.py)",
                           "probe": "test/tb_tour.sv writes test/schematic_probe.txt, read inside sync_compare on each falling clock edge",
                           "computed": "the subtractor's output and cnt - 1 are arithmetic on recorded values; every other value is recorded"}}


# --------------------------------------------------------------- the drawing
# Colours: the explorer's CSS variables when the drawing is inside the site,
# and the dark screen of readme_media.py / motion.py on GitHub.
STYLE = """
.sc{font-family:var(--sans,system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif)}
.sc .bg{fill:var(--sch-bg,#0f1214)}
.sc .box{fill:var(--sch-box,#161a1d);stroke:var(--sch-edge,#3a4247);stroke-width:1.5}
.sc .ff{fill:var(--sch-box,#161a1d);stroke:var(--sch-ink,#e8ebe9);stroke-width:1.5}
.sc .gate{fill:var(--sch-box,#161a1d);stroke:var(--sch-ink,#e8ebe9);stroke-width:1.6}
.sc .t{fill:var(--sch-ink,#e8ebe9);font-size:13px;font-weight:600}
.sc .m{fill:var(--sch-muted,#9aa3a7);font-size:11px}
.sc .k{fill:var(--sch-muted,#9aa3a7);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase}
.sc .v{fill:var(--sch-bus,#3fc49b);font-family:var(--mono,ui-monospace,SFMono-Regular,Consolas,Menlo,monospace);font-size:12.5px}
.sc .vb{fill:var(--sch-ink,#e8ebe9);font-family:var(--mono,ui-monospace,SFMono-Regular,Consolas,Menlo,monospace);font-size:20px;font-weight:600}
.sc .vb.small{font-size:15px}
.sc .w{fill:none;stroke:var(--sch-off,#3a4247);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.sc .w.bus{stroke:var(--sch-bus,#3fc49b);stroke-width:3.4;opacity:.55}
.sc .w.bus.hot{opacity:1}
.sc .w.on{stroke:var(--sch-hi,#ffb000);stroke-width:2.6}
.sc .glow{fill:none;stroke:var(--sch-hi,#ffb000);stroke-width:8;opacity:.18;stroke-linecap:round;stroke-linejoin:round}
.sc .dot{fill:var(--sch-off,#3a4247)}
.sc .dot.on{fill:var(--sch-hi,#ffb000)}
.sc .clk{fill:none;stroke:var(--sch-muted,#9aa3a7);stroke-width:1.3}
.sc .pad{fill:var(--sch-box,#161a1d);stroke:var(--sch-hi,#ffb000);stroke-width:2}
.sc .pad.on{fill:var(--sch-hi,#ffb000)}
.sc .lane{fill:var(--sch-lane,#12161a)}
.sc .rowl{fill:var(--sch-muted,#9aa3a7);font-size:11px}
.sc .cur{fill:var(--sch-cur,#6ea8f0);opacity:.22}
.sc .curl{stroke:var(--sch-cur,#6ea8f0);stroke-width:2}
.sc .cap{fill:var(--sch-ink,#e8ebe9);font-size:13.5px}
.sc .gapt{fill:var(--sch-muted,#9aa3a7);font-size:11px}
"""

# Bit wires: (id, signal, points). A wire is lit when its signal is 1.
BITS = [
    ("arm_we", "arm_we", [(20, 236), (262, 236), (262, 191)]),
    ("arm_we_s", "arm_we", [(190, 236), (190, 330), (222, 330)]),
    ("reached", "reached", [(722, 135), (770, 135), (770, 214), (802, 214)]),
    ("armed", "armed", [(446, 340), (770, 340), (770, 246), (802, 246)]),
    ("clear", "armed_reached", [(864, 230), (884, 230), (884, 392), (204, 392), (204, 350), (222, 350)]),
    ("andout", "armed_reached", [(864, 230), (904, 230), (904, 258), (918, 258)]),
    ("pulse_we", "pulse_we", [(20, 420), (896, 420), (896, 290), (918, 290)]),
    ("fire", "fire", [(978, 274), (998, 274), (998, 440), (820, 440), (820, 459)]),
    ("trig", "trig", [(1032, 492), (1056, 492)]),
]
# Bus wires: (id, signal, points, label at, anchor)
BUSES = [
    ("now", "now", [(206, 76), (566, 76)], (390, 66), "middle"),
    ("arm_time", "arm_time", [(20, 150), (148, 150)], (84, 140), "middle"),
    ("arm_m1", "arm_m1", [(210, 150), (250, 150)], None, None),
    ("muxo", "dm1next", [(274, 166), (306, 166)], None, None),
    ("dm1", "dm1", [(446, 166), (566, 166)], (506, 156), "middle"),
    ("dm1fb", "dm1", [(500, 166), (500, 214), (236, 214), (236, 182), (250, 182)], None, None),
    ("diff", "diff", [(646, 120), (684, 120)], (665, 104), "middle"),
    ("pw", "pw", [(724, 470), (788, 470)], None, None),
    ("cnt_m1", "cnt_m1", [(724, 514), (788, 514)], None, None),
    ("cnto", "pcnt", [(812, 492), (846, 492)], None, None),
    ("cnt", "pcnt", [(946, 492), (972, 492)], None, None),
    ("cntfb", "pcnt", [(958, 492), (958, 540), (606, 540), (606, 514), (636, 514)], None, None),
]


def path(pts):
    return "M" + " L".join(f"{x},{y}" for x, y in pts)


def bit_of(s, sig):
    if sig == "armed_reached":
        return s["armed"] & s["reached"]
    return s[sig]


def fmt(v):
    return f"{v:,}"


def gate_and(x, y, w, h):
    r = h / 2
    return f"<path class=gate d='M{x},{y} H{x + w - r} A{r},{r} 0 0 1 {x + w - r},{y + h} H{x} Z'/>"


def gate_or(x, y, w, h):
    return (f"<path class=gate d='M{x},{y} Q{x + w * .55},{y} {x + w},{y + h / 2} Q{x + w * .55},{y + h} {x},{y + h} "
            f"Q{x + w * .28},{y + h / 2} {x},{y} Z'/>")


def mux(x, y, w, h):
    return f"<path class=gate d='M{x},{y} L{x + w},{y + h * .2} L{x + w},{y + h * .8} L{x},{y + h} Z'/>"


def ff(x, y, w, h, title, sid, lines, data):
    """A register: the clock notch on its lower left, its name and its value."""
    a = (f"<g class=part data-part={sid}><title>{esc(PARTS[sid][0])} · {esc(RTL)} line {lines[sid]}</title>"
         f"<rect class=ff x={x} y={y} width={w} height={h} rx=6/>"
         f"<path class=clk d='M{x},{y + h - 18} L{x + 10},{y + h - 11} L{x},{y + h - 4}'/>"
         f"<text class=k x={x + 12} y={y + 18}>{esc(title)}</text>")
    return a + f"<text class=vb x={x + 12} y={y + h - 14} data-v={data}>0</text></g>"


def drawing(lines, arm_source, still=None, interactive=False):
    """Everything that does not change with the clock; wires drawn as they are at `still`."""
    o = [f"<rect class=bg width={W} height={H} rx=14/>"]
    # inputs, left edge
    o.append(f"<text class=k x=20 y=112>arm_time</text><text class=m x=20 y=125>{esc(arm_source)}</text>")
    o.append("<text class=k x=20 y=228>arm_we</text>")
    o.append("<text class=k x=20 y=412>pulse_we · mask[0]</text>")
    # the timebase
    o.append("<g class=part data-part=now><title>timebase · src/sync/sync_timebase.sv</title>"
             "<rect class=box x=20 y=26 width=186 height=68 rx=8/><text class=k x=34 y=46>timebase · now</text>"
             "<text class=vb x=34 y=80 data-v=now>0</text><text class=m x=196 y=80 text-anchor=end>+1 each clock</text></g>")
    # -1
    o.append(f"<g class=part data-part=minus1><title>arm_time - 1 · {RTL} line {lines['minus1']}</title>"
             "<rect class=box x=148 y=132 width=62 height=36 rx=8/><text class=t x=179 y=155 text-anchor=middle>− 1</text></g>")
    # mux into the deadline register
    o.append(f"<g class=part data-part=mux_dm1><title>{esc(PARTS['mux_dm1'][0])} · {RTL} line {lines['mux_dm1']}</title>"
             + mux(250, 136, 24, 60) + "<text class=m x=256 y=154>1</text><text class=m x=256 y=186>0</text></g>")
    o.append(ff(306, 128, 140, 76, "deadline − 1", "dm1", lines, "dm1"))
    # subtractor
    o.append(f"<g class=part data-part=sub><title>{esc(PARTS['sub'][0])} · {RTL} line {lines['sub']}</title>"
             "<path class=gate d='M566,48 L646,88 L646,152 L566,192 L566,140 L582,120 L566,100 Z'/>"
             "<text class=t x=614 y=127 text-anchor=middle style='font-size:24px;font-weight:400'>−</text>"
             "<text class=m x=572 y=80>now</text><text class=m x=572 y=170>d−1</text></g>")
    # sign bit inverter
    o.append("<g class=part data-part=sub><path class=gate d='M684,108 L712,123 L684,138 Z'/>"
             "<circle class=gate cx=717 cy=123 r=4.5/></g>")
    o.append("<text class=m x=690 y=158>sign ≥ 0</text>")
    o.append("<text class=k x=730 y=128>reached</text>")
    # armed set/clear logic and flop
    o.append(f"<g class=part data-part=clear><title>{esc(PARTS['clear'][0])} · {RTL} line {lines['clear']}</title>"
             "<rect class=box x=222 y=316 width=64 height=48 rx=8/><text class=m x=230 y=334>set</text>"
             "<text class=m x=230 y=354>clear</text></g>")
    o.append("<path class='w bus' d='M286,340 L306,340' style='opacity:.0'/>")
    o.append(f"<g class=part data-part=armed><title>{esc(PARTS['armed'][0])} · {RTL} line {lines['armed']}</title>"
             "<rect class=ff x=306 y=310 width=140 height=60 rx=6/>"
             "<path class=clk d='M306,352 L316,359 L306,366'/><text class=k x=318 y=328>armed</text>"
             "<text class=vb x=318 y=358 data-v=armed>0</text></g>")
    o.append("<path class=w d='M286,340 L306,340'/>")
    # AND, OR
    o.append(f"<g class=part data-part=and><title>{esc(PARTS['and'][0])} · {RTL} line {lines['and']}</title>"
             + gate_and(802, 200, 62, 60) + "<text class=m x=812 y=234>AND</text></g>")
    o.append(f"<g class=part data-part=or><title>{esc(PARTS['or'][0])} · {RTL} line {lines['or']}</title>"
             + gate_or(914, 244, 66, 60) + "<text class=m x=932 y=278>OR</text></g>")
    o.append("<text class=k x=1004 y=268>fire</text>")
    # pulse counter
    o.append(f"<g class=part data-part=pw><title>{esc(PARTS['pw'][0])} · {RTL} line {lines['pw']}</title>"
             "<rect class=box x=636 y=452 width=88 height=36 rx=8/><text class=m x=646 y=474>pw</text>"
             "<text class=v x=714 y=475 text-anchor=end data-v=pw>8</text></g>")
    o.append(f"<g class=part data-part=cnt><title>cnt − 1, stopping at 0 · {RTL} line {lines['cnt']}</title>"
             "<rect class=box x=636 y=496 width=88 height=36 rx=8/><text class=m x=646 y=518>cnt−1</text>"
             "<text class=v x=714 y=519 text-anchor=end data-v=cnt_m1>0</text></g>")
    o.append(f"<g class=part data-part=mux_cnt><title>{esc(PARTS['mux_cnt'][0])} · {RTL} line {lines['mux_cnt']}</title>"
             + mux(788, 456, 24, 72) + "<text class=m x=794 y=474>1</text><text class=m x=794 y=520>0</text></g>")
    o.append(ff(846, 456, 100, 72, "pulse_cnt", "cnt", lines, "pcnt"))
    o.append(f"<g class=part data-part=nz><title>{esc(PARTS['nz'][0])} · {RTL} line {lines['nz']}</title>"
             "<rect class=box x=972 y=474 width=60 height=36 rx=8/><text class=t x=1002 y=497 text-anchor=middle>≠ 0</text></g>")
    # the pad
    o.append("<g class=part data-part=pin><title>the pin: uo_out[0], TRIG0</title>"
             "<rect class=pad x=1056 y=466 width=50 height=52 rx=6 data-b=pin/>"
             "<text class=k x=1081 y=455 text-anchor=middle>TRIG0</text><text class=m x=1081 y=536 text-anchor=middle>uo_out[0]</text></g>")
    # one clock for every register
    o.append("<text class=m x=304 y=294>every register: one clock, rising edge</text>")
    # wires
    s = still
    for wid, sig, pts, lab, anc in BUSES:
        hot = s is not None and wid in ("now", "dm1", "arm_time", "diff", "cnt", "cnto")
        o.append(f"<path class='w bus{' hot' if hot else ''}' data-w={wid} d='{path(pts)}'/>")
    for wid, sig, pts in BITS:
        on = s is not None and bit_of(s, sig)
        o.append(f"<path class='glow' data-g={wid} d='{path(pts)}' style='opacity:{.18 if on else 0}'/>"
                 f"<path class='w{' on' if on else ''}' data-w={wid} data-s='{sig}' pathLength=1 d='{path(pts)}'/>")
    # junction dots
    for x, y, sig in ((190, 236, "arm_we"), (884, 230, "armed_reached"), (500, 166, None), (958, 492, None)):
        on = s is not None and sig and bit_of(s, sig)
        o.append(f"<circle class='dot{' on' if on else ''}' cx={x} cy={y} r=4{f' data-s={sig}' if sig else ''}/>")
    # bus values
    o.append("<text class=v x=84 y=140 text-anchor=middle data-v=arm_time>0</text>")
    o.append("<text class=v x=190 y=124 text-anchor=middle data-v=arm_m1>0</text>")
    o.append("<text class=v x=652 y=100 text-anchor=start data-v=diff>0</text>")
    return "".join(o)


def fill(svg_static, s):
    """Write a step's values into the drawing's value slots (the still, for readers without JavaScript)."""
    vals = {"now": fmt(s["now"]), "dm1": fmt(s["dm1"]), "armed": str(s["armed"]), "pcnt": str(s["pcnt"]),
            "arm_time": fmt(s["arm_time"]) if s["arm_we"] else "", "arm_m1": fmt(s["arm_m1"]) if s["arm_we"] else "",
            "diff": fmt(s["diff"]), "pw": str(s["pw"]), "cnt_m1": str(s["cnt_m1"])}
    big = lambda k: " style='font-size:15px'" if len(vals[k]) > 9 and k in ("now", "dm1") else ""
    svg_static = re.sub(r"data-v=(\w+)>[^<]*<", lambda m: f"data-v={m.group(1)}{big(m.group(1))}>{esc(vals[m.group(1)])}<", svg_static)
    if s["pin"]:
        svg_static = svg_static.replace("class=pad x=1056", "class='pad on' x=1056")
    return svg_static


STRIP = [("arm_we", "arm_we"), ("armed", "armed"), ("reached", "reached"), ("fire", "fire"), ("TRIG0", "pin")]


def strip(d, x0=150, y0=0, w=None):
    """The steps as a small timing diagram: one column per recorded clock, a break where clocks are skipped."""
    steps = d["steps"]
    w = w or (W - x0 - 30)
    n = len(steps)
    gapw = 46
    cw = (w - gapw) / n
    xs, x = [], x0
    for i, s in enumerate(steps):
        if i and steps[i - 1]["part"] != s["part"]:
            x += gapw
        xs.append(x)
        x += cw
    o = []
    rh = 20
    for k, (lab, sig) in enumerate(STRIP):
        y = y0 + 22 + k * rh
        o.append(f"<rect class=lane x={x0 - 4} y={y - 13} width={w + 8} height={rh - 4} rx=3/>")
        o.append(f"<text class=rowl x={x0 - 12} y={y} text-anchor=end>{lab}</text>")
        pts = []
        for i, s in enumerate(steps):
            hi = y - 10 if s[sig] else y
            if i and steps[i - 1]["part"] != s["part"]:
                o.append(f"<path class='w on' d='{path(pts)}'/>")
                pts = []
            pts += [(round(xs[i], 1), hi), (round(xs[i] + cw, 1), hi)]
        o.append(f"<path class='w on' d='{path(pts)}'/>")
    gx = next(xs[i] - gapw for i, s in enumerate(steps) if i and steps[i - 1]["part"] != s["part"])
    o.append(f"<text class=gapt x={gx + gapw / 2:.1f} y={y0 + 22 + 2 * rh - 4} text-anchor=middle>{d['gap']:,}</text>")
    o.append(f"<text class=gapt x={gx + gapw / 2:.1f} y={y0 + 22 + 3 * rh - 8} text-anchor=middle>clocks</text>")
    for i, s in enumerate(steps):
        o.append(f"<text class=gapt x={xs[i] + cw / 2:.1f} y={y0 + 22 + 5 * rh + 2} text-anchor=middle>{f"{s['cycle']:,}" if (i % 3 == 0 or i == d['edge']) and not (i % 3 and abs(i - d['edge']) < 2 and i != d['edge']) else ''}</text>")
    return o, xs, cw, y0 + 22 + 5 * rh + 8


def site_svg(d, still):
    """The drawing for the overview page: the still state written in, ids for schematic.js."""
    s = d["steps"][still]
    body = fill(drawing(d["lines"], d["arm_source"], s, interactive=True), s)
    return xml(f"<svg class=sc viewBox='0 0 {W} {H}' role=img aria-labelledby=sc-title sc-desc xmlns='http://www.w3.org/2000/svg'>"
            f"<title id=sc-title>Deadline channel 0 of sync_compare, drawn as logic</title>"
            f"<desc id=sc-desc>{esc(s['text'])}</desc><style>{STYLE}</style>{body}</svg>")


def strip_svg(d, still):
    o, xs, cw, h = strip(d, x0=70, y0=0, w=W - 100)
    o.append(f"<g class=cursor data-xs='{json.dumps([round(x, 1) for x in xs])}' data-cw='{cw:.2f}'>"
             f"<rect class=cur x={xs[still]:.1f} y=4 width={cw:.1f} height={h - 4}/></g>")
    return xml(f"<svg class='sc strip' viewBox='0 0 {W - 20} {h + 4}' aria-hidden=true xmlns='http://www.w3.org/2000/svg'>"
            f"<style>{STYLE}</style>{''.join(o)}</svg>")


def readme_svg(d):
    """A self-playing SVG for the README: one frame per recorded clock, CSS steps between them."""
    steps, edge = d["steps"], d["edge"]
    n = len(steps)
    T = [3.2 if (i in (0, 1, edge - 1, edge) or s["part"] != steps[i - 1]["part"]) else 1.15 for i, s in enumerate(steps)]
    T[-1] = 3.0
    total = sum(T)
    capy = H + 24
    o, xs, cw, sh = strip(d, x0=150, y0=H + 88, w=W - 190)
    HH = sh + 16
    css = [STYLE, ".fr{opacity:0}", f".fr.still{{opacity:1}}"]
    t0 = 0
    frames = []
    for i, s in enumerate(steps):
        a, b = t0 / total * 100, (t0 + T[i]) / total * 100
        css.append(f"@keyframes f{i}{{0%,{a:.3f}%{{opacity:0}}{a + .001:.3f}%,{b:.3f}%{{opacity:1}}{b + .001:.3f}%,100%{{opacity:0}}}}")
        t0 += T[i]
        g = [f"<g class='fr{' still' if i == edge else ''}' style='--i:{i}'>"]
        for wid, sig, pts in BITS:
            if bit_of(s, sig):
                g.append(f"<path class=glow d='{path(pts)}'/><path class='w on' d='{path(pts)}'/>")
        for x, y, sig in ((190, 236, "arm_we"), (884, 230, "armed_reached")):
            if bit_of(s, sig):
                g.append(f"<circle class='dot on' cx={x} cy={y} r=4/>")
        if s["pin"]:
            g.append("<rect class='pad on' x=1056 y=466 width=50 height=52 rx=6/>")
        vals = [("vb", 34, 80, "start", fmt(s["now"])), ("vb" if s["dm1"] < 10 ** 7 else "vb small", 318, 190, "start", fmt(s["dm1"])),
                ("vb", 318, 358, "start", str(s["armed"])), ("vb", 858, 514, "start", str(s["pcnt"])),
                ("v", 652, 100, "start", fmt(s["diff"])), ("v", 714, 519, "end", str(s["cnt_m1"])), ("v", 714, 475, "end", str(s["pw"]))]
        if s["arm_we"]:
            vals += [("v", 84, 140, "middle", fmt(s["arm_time"])), ("v", 190, 124, "middle", fmt(s["arm_m1"]))]
        for cls, x, y, anc, t in vals:
            g.append(f"<text class='{cls}' x={x} y={y} text-anchor={anc}>{esc(t)}</text>")
        g.append(f"<text class=k x=20 y={capy}>cycle {s['cycle']:,} · now {s['now']:,}</text>")
        for k, ln in enumerate(textwrap.wrap(s["text"], 150)):
            g.append(f"<text class=cap x=20 y={capy + 22 + k * 19}>{esc(ln)}</text>")
        g.append(f"<rect class=cur x={xs[i]:.1f} y={H + 88 + 4} width={cw:.1f} height={sh - H - 92}/>")
        g.append("</g>")
        frames.append("".join(g))
    css.append("@media (prefers-reduced-motion:no-preference){.fr,.fr.still{opacity:0;animation:" +
               f"var(--a) {total:.2f}s infinite}}" + "}")
    # each frame names its own keyframes
    frames = [f.replace(f"style='--i:{i}'", f"style='--a:f{i}'") for i, f in enumerate(frames)]
    static = drawing(d["lines"], d["arm_source"], None)
    static = static.replace(">0</text>", "></text>")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' class=sc viewBox='0 0 {W} {HH}' width={W} height={HH} role=img "
            f"aria-label='Deadline channel 0 drawn as logic, lit clock by clock from the RTL simulation: the deadline is armed, the "
            f"comparator waits, fire rises one clock early, and the trigger pin rises on exactly tick {d['deadline']:,} for {d['width']} clocks'>"
            f"<style>{''.join(css)}</style><rect class=bg width={W} height={HH} rx=14/>{static}"
            f"<text class=m x={W - 20} y={capy} text-anchor=end>recorded: make -C test tour · drawn by docs/tools/schematic.py</text>"
            f"{''.join(o)}{''.join(frames)}</svg>\n")


# ------------------------------------------------------------------- checks
def check_errors(d, fx):
    """The committed data, without a simulator: the equations, the tour, the RTL lines."""
    err = []
    steps = d["steps"]
    rows = [{k: s[k] for k in ("cycle", "now", "arm_we", "arm_time", "arm_m1", "dm1", "reached", "fire", "armed",
                                "pcnt", "pw", "pulse_we", "trig", "pin")} | {"arm_sel": 0} for s in steps]
    err += model_errors(rows)
    for s in steps:
        if s["diff"] != sgn((s["now"] - s["dm1"]) & M32):
            err.append(f"cycle {s['cycle']}: the drawn difference {s['diff']} is not now - dm1")
        if s["cnt_m1"] != (s["pcnt"] - 1 if s["pcnt"] else 0):
            err.append(f"cycle {s['cycle']}: the drawn cnt - 1 is {s['cnt_m1']}")
    arm = [s for s in steps if s["arm_we"]]
    if len(arm) != 1:
        return err + [f"{len(arm)} arming clocks drawn"]
    full = [s for s in steps if s["part"] == "fire"]
    if not full or full[0]["cycle"] - steps[1]["cycle"] - 1 != d["gap"]:
        err.append("the drawn gap between arming and firing is wrong")
    e = d["edge"]
    if not (0 < e < len(steps) and steps[e]["pin"] and not steps[e - 1]["pin"]):
        err.append("edge does not point at the trigger's rising clock")
    else:
        if steps[e]["now"] != d["deadline"] or arm[0]["arm_time"] != d["deadline"]:
            err.append(f"the pin rose at now = {steps[e]['now']}, the deadline is {d['deadline']}")
        if sum(1 for s in steps if s["pin"]) != d["width"] or d["width"] != steps[e]["pw"]:
            err.append("the pulse width does not match pw")
        err += fixture_errors(rows, fx)
    try:
        if d["lines"] != rtl_lines():
            err.append(f"the RTL line numbers are stale against {RTL}")
    except ValueError as x:
        err.append(str(x))
    return err


def xml(svg):
    """Quote every attribute, so the file is XML (GitHub serves it as an image) as well as HTML."""
    return re.sub(r"<[^<>]+>", lambda t: re.sub(r"(\s[\w:-]+)=([^\s'\">/]+)", r'\1="\2"', t.group(0)), svg)


def outputs(d):
    return {DATA: json.dumps(d, indent=1, sort_keys=True) + "\n", README_SVG: xml(readme_svg(d))}


MUTANTS = [
    ("the pin rising one clock late", lambda d: d["steps"][d["edge"]].update(pin=0, trig=0)),
    ("reached that disagrees with the subtraction", lambda d: d["steps"][d["edge"] - 2].update(reached=1)),
    ("fire without armed", lambda d: d["steps"][-1].update(fire=1)),
    ("a deadline register that did not load", lambda d: d["steps"][1].update(dm1=d["steps"][1]["dm1"] + 1)),
    ("a counter that skips a count", lambda d: d["steps"][d["edge"] + 2].update(pcnt=d["steps"][d["edge"] + 2]["pcnt"] - 1)),
    ("a timebase that skips a tick", lambda d: [s.update(now=s["now"] + 1) for s in d["steps"][d["edge"]:]]),
    ("a different deadline than the tour's", lambda d: [d.update(deadline=d["deadline"] + 1)]),
    ("a drawn difference that is not now - dm1", lambda d: d["steps"][3].update(diff=0)),
    ("a stale RTL line", lambda d: d["lines"].update(sub=d["lines"]["sub"] + 1)),
    ("a pulse width that does not match pw", lambda d: d.update(width=d["width"] + 1)),
]


def main():
    args = sys.argv[1:]
    site = json.load(open("docs/site/site.json"))
    fx = json.load(open(FIXTURE))
    if "--check" in args or "--mutants" in args:
        if not os.path.exists(DATA):
            sys.exit(f"schematic: {DATA} is missing; run python3 docs/tools/schematic.py")
        d = json.load(open(DATA))
        if "--mutants" in args:
            caught = 0
            for name, f in MUTANTS:
                m = copy.deepcopy(d)
                f(m)
                if check_errors(m, fx):
                    caught += 1
                    print(f"  caught: {name}")
                else:
                    print(f"  MISSED: {name}")
            print(f"schematic: --check caught {caught} of {len(MUTANTS)} broken copies")
            sys.exit(0 if caught == len(MUTANTS) else 1)
        err = check_errors(d, fx)
        if err:
            sys.exit("schematic: " + "\n  ".join(["the data fails its checks:"] + err))
        stale = [p for p, t in outputs(d).items() if not os.path.exists(p) or open(p).read() != t]
        if stale:
            sys.exit("schematic: out of date, run python3 docs/tools/schematic.py: " + ", ".join(stale))
        print(f"schematic: {len(d['steps'])} recorded clocks of deadline channel 0 obey the RTL's equations; "
              f"the pin rises at tick {d['deadline']:,} as in the deadline tour; {len(d['lines'])} RTL lines current")
        return
    r = subprocess.run(["make", "-s", "-C", "test", "tour"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("schematic: make -C test tour failed:\n" + r.stdout[-3000:] + r.stderr[-2000:])
    rows = read_probe(PROBE)
    err = model_errors(rows) + fixture_errors(rows, fx)
    if err:
        sys.exit("schematic: " + "\n  ".join(["the recording disagrees with the RTL's equations, nothing written:"] + err[:20]))
    d = build(rows, site)
    err = check_errors(d, fx)
    if err:
        sys.exit("schematic: " + "\n  ".join(["the built data fails its own check:"] + err))
    out = outputs(d)
    if "--check-sim" in args:
        if not os.path.exists(DATA) or open(DATA).read() != out[DATA]:
            sys.exit(f"schematic: {DATA} differs from a fresh simulation; run python3 docs/tools/schematic.py")
        print(f"schematic: a fresh simulation gives the same {len(d['steps'])} clocks ({len(rows)} probed)")
        return
    for p, t in out.items():
        open(p, "w").write(t)
        print(f"wrote {p} ({len(t) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
