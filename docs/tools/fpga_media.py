#!/usr/bin/env python3
"""fpga_media.py — "Basys 3, simulated": the board animation, drawn from a recording.

    make -C fpga/basys3 record           re-run the board simulation, write docs/fpga/basys3_demo.rec
    python3 docs/tools/fpga_media.py     write docs/images/explorer/fpga.gif and fpga.png

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; what the LEDs and
buttons mean, and how the terminal reads, are in docs/site/site.json under "fpga".

Every frame is drawn from docs/fpga/basys3_demo.rec, which fpga/basys3/rec_basys3.sv
writes while fpga/basys3/tb_basys3.sv runs the whole board design in Icarus Verilog:
the LEDs, the 7-segment digits, the buttons the bench presses and every byte on
the USB serial pins. Time runs linearly, compressed. An LED that switches faster
than one frame is drawn at the brightness of the time it was on, the way it
looks to an eye, but never dimmer than a faint glow if it was on at all: a
pulse of a few clocks would otherwise vanish. Nothing has run on a real board,
and every frame says so.

fpga.png is the last frame, a still for readers with motion turned off. Uses Pillow
and its built-in font only, so the output depends on nothing installed on the machine.
"""
import json, os, sys, textwrap
from PIL import Image, ImageDraw, ImageFont

REC = "docs/fpga/basys3_demo.rec"
OUT = "docs/images/explorer"
W, H = 880, 560
FRAMES, MS = 120, 110                       # about 13 s, then the last frame holds
# the explorer's dark screen (docs/site/lib/exhibit.css)
BG, PANEL, INK, DIM, LINE = "#0b0d0c", "#111413", "#e5e8e3", "#8e968f", "#2a302d"
AMBER, PROBE, GREEN = "#ffb000", "#9ad8f7", "#5fd0a6"
PCB, PCB_EDGE, SILK = "#0f281d", "#1f4a37", "#a9cdb9"
LED_ON, LED_OFF = (74, 222, 128), (34, 52, 41)
SEG_ON, SEG_OFF = (255, 77, 61), (52, 24, 21)
SEGS = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc",
        8: "abcdefg", 9: "abcdfg", 10: "abcefg", 11: "cdefg", 12: "adef", 13: "bcdeg", 14: "adefg", 15: "aefg"}


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                      # Pillow < 10.1
        return ImageFont.load_default()


def load():
    """The recording as {kind: [(cycle, value)]}; bytes as [(cycle, dir, byte)]."""
    ch, uart, end = {}, [], 0
    for line in open(REC):
        if line.startswith("#"):
            continue
        c, k, v = line.split()
        c = int(c)
        end = max(end, c)
        if k in ("tx", "rx"):
            uart.append((c, k, int(v, 16)))
        else:
            # an undriven bit (x or z) reads as off; a value with no driven bit at all is unknown
            known = v.lower().strip("xz")
            base = 2 if k == "led" else 16          # the recorder writes the LEDs in binary
            ch.setdefault(k, []).append((c, int("".join("0" if q in "xXzZ" else q for q in v), base) if known else None))
    uart.sort()
    return ch, uart, end


def at(changes, c):
    v = None
    for cc, vv in changes:
        if cc > c:
            break
        v = vv
    return v


def duty(changes, bit, c0, c1):
    """The fraction of cycles c0..c1 in which bit was 1."""
    on, v, t = 0, None, c0
    for cc, vv in changes:
        if cc <= c0:
            v = vv
            continue
        if cc >= c1:
            break
        if v is not None and (v >> bit) & 1:
            on += cc - t
        v, t = vv, cc
    if v is not None and (v >> bit) & 1:
        on += c1 - t
    return on / max(1, c1 - c0)


def mix(a, b, f):
    return tuple(round(x + (y - x) * f) for x, y in zip(a, b))


def digit(d, x, y, v, dot):
    """One 7-segment digit, 26 x 44, top left at x, y."""
    lit = SEGS.get(v, "") if v is not None else "g"
    seg = {"a": (4, 0, 22, 4), "g": (4, 20, 22, 24), "d": (4, 40, 22, 44),
           "f": (0, 3, 4, 21), "b": (22, 3, 26, 21), "e": (0, 23, 4, 41), "c": (22, 23, 26, 41)}
    for s, (x0, y0, x1, y1) in seg.items():
        d.rounded_rectangle((x + x0, y + y0, x + x1, y + y1), radius=1, fill=SEG_ON if s in lit else SEG_OFF)
    d.ellipse((x + 29, y + 40, x + 33, y + 44), fill=SEG_ON if dot else SEG_OFF)


def frame(cfg, ch, uart, end, c0, c1, marks):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f10, f11, f12, f13, f15 = font(10), font(11), font(12), font(13), font(15)
    # header
    d.text((16, 12), cfg["title"], fill=INK, font=f15)
    tag = "Simulated board, not a real one"
    tw = d.textlength(tag, font=f11)
    d.rounded_rectangle((W - tw - 34, 10, W - 14, 30), radius=4, outline=AMBER, width=1)
    d.text((W - tw - 24, 14), tag, fill=AMBER, font=f11)
    d.text((16, 34), f"cycle {c1:,}  ·  {c1 * 20 / 1000:,.1f} us at 50 MHz", fill=DIM, font=f12)

    # the board
    bx0, by0, bx1, by1 = 16, 60, 560, 424
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=14, fill=PCB, outline=PCB_EDGE, width=2)
    for hx, hy in ((bx0 + 14, by0 + 14), (bx1 - 14, by0 + 14), (bx0 + 14, by1 - 14), (bx1 - 14, by1 - 14)):
        d.ellipse((hx - 5, hy - 5, hx + 5, hy + 5), fill=BG, outline=PCB_EDGE)
    d.text((bx0 + 30, by0 + 12), "BASYS 3", fill=SILK, font=f13)
    d.text((bx0 + 30, by0 + 28), "Artix-7 FPGA board", fill=SILK, font=f10)
    # Pmod port JA: two rows of six pins, and what this build does with it
    for r in range(2):
        for i in range(6):
            d.rectangle((bx0 + 30 + i * 11, by0 + 52 + r * 11, bx0 + 37 + i * 11, by0 + 59 + r * 11), fill="#c9a227")
    d.text((bx0 + 30, by0 + 76), "Pmod JA", fill=SILK, font=f10)
    for i, line in enumerate(textwrap.wrap(cfg.get("pmod", ""), 20)[:2]):
        d.text((bx0 + 30, by0 + 88 + i * 12), line, fill=SILK, font=f10)
    # the 100 MHz oscillator the design divides to 50 MHz
    d.rectangle((bx0 + 30, 236, bx0 + 56, 252), fill="#c9cdc8", outline="#7d858c")
    d.text((bx0 + 30, 256), "100 MHz clock,", fill=SILK, font=f10)
    d.text((bx0 + 30, 268), "halved to 50", fill=SILK, font=f10)
    # USB-UART: the PC's serial port, with a tick when a byte passes
    busy = any(c0 - 400 <= c < c1 for c, _, _ in uart)
    d.rectangle((bx0 - 6, 180, bx0 + 20, 214), fill="#3a3f43", outline="#5b6268")
    d.text((bx0 + 26, 184), "USB", fill=SILK, font=f10)
    d.text((bx0 + 26, 196), "serial", fill=SILK, font=f10)
    d.ellipse((bx0 + 64, 192, bx0 + 72, 200), fill=PROBE if busy else LED_OFF)
    # the FPGA, with Tiqora in it
    fx0, fy0 = 196, 136
    d.rectangle((fx0 - 6, fy0 - 6, fx0 + 136, fy0 + 136), outline=PCB_EDGE)
    for i in range(14):              # pins on all four sides
        o = 4 + i * 9
        for x0, y0, x1, y1 in ((fx0 + o, fy0 - 6, fx0 + o + 3, fy0), (fx0 + o, fy0 + 130, fx0 + o + 3, fy0 + 136),
                               (fx0 - 6, fy0 + o, fx0, fy0 + o + 3), (fx0 + 130, fy0 + o, fx0 + 136, fy0 + o + 3)):
            d.rectangle((x0, y0, x1, y1), fill="#7d858c")
    d.rectangle((fx0, fy0, fx0 + 130, fy0 + 130), fill="#16191b", outline="#3a3f43")
    d.text((fx0 + 12, fy0 + 14), "XC7A35T", fill=INK, font=f12)
    d.text((fx0 + 12, fy0 + 34), cfg["chip"], fill=AMBER, font=f12)
    for i, line in enumerate(textwrap.wrap(cfg["inside"], 18)[:4]):
        d.text((fx0 + 12, fy0 + 56 + i * 15), line, fill=DIM, font=f10)
    # 7-segment display: uo_out on the left two digits, ui_in on the right two
    out_v, in_v = at(ch.get("out", []), c1), at(ch.get("in", []), c1)
    sx, sy = 372, 92
    d.rectangle((sx - 10, sy - 10, sx + 4 * 38 + 4, sy + 56), fill="#070707", outline="#3a3f43")
    nib = lambda v, k: None if v is None else (v >> (4 * k)) & 15
    for i, v in enumerate((nib(out_v, 1), nib(out_v, 0), nib(in_v, 1), nib(in_v, 0))):
        digit(d, sx + i * 38, sy, v, i == 1)
    d.text((sx, sy + 62), "uo_out", fill=SILK, font=f10)
    d.text((sx + 78, sy + 62), "ui_in", fill=SILK, font=f10)
    # buttons: the bench presses them; a pressed one lights up
    btn_any = {k: duty(ch.get("btn", []), b, c0, c1) > 0 for k, b in (("C", 0), ("L", 1), ("R", 2), ("U", 3))}
    cx, cy = 436, 252
    for k, (dx, dy) in {"U": (0, -40), "L": (-48, 0), "C": (0, 0), "R": (48, 0), "D": (0, 40)}.items():
        x, y = cx + dx, cy + dy
        on = btn_any.get(k, False)
        d.rectangle((x - 15, y - 15, x + 15, y + 15), fill="#2b2f31", outline="#4a5156")
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=PROBE if on else "#5b6268")
        lab = cfg["buttons"].get(k, "") if k != "C" else ""
        if lab:          # each label sits on the outside of its button
            tw = d.textlength(lab, font=f10)
            tx, ty = {"U": (x - tw / 2, y - 30), "D": (x + 20, y - 6), "L": (x - 20 - tw, y - 6), "R": (x + 20, y - 6)}[k]
            d.text((tx, ty), lab, fill=PROBE if on else SILK, font=f10)
    if cfg["buttons"].get("C"):
        d.text((cx - 112, cy + 28), "centre: " + cfg["buttons"]["C"], fill=SILK, font=f10)
    # 16 LEDs, LD0 on the right as on the board, lit by the share of the frame they were on
    leds = ch.get("led", [])
    ly, step, lx0 = 346, 31, 520
    for i in range(16):
        x = lx0 - i * step
        f = duty(leds, i, c0, c1)
        if 0 < f < 0.35:     # on for a moment: a few clocks would be invisible to an eye, so show it dimly
            f = 0.35
        col = mix(LED_OFF, LED_ON, f)
        if f > 0.05:
            glow = mix(PCB_rgb, LED_ON, 0.35 * f)
            d.ellipse((x - 9, ly - 8, x + 19, ly + 14), fill=glow)
        d.rectangle((x, ly, x + 10, ly + 6), fill=col)
        d.text((x - 2, ly + 10), f"LD{i}", fill=SILK, font=f10)
        lab = cfg["leds"][i]
        if lab:
            tw = d.textlength(lab, font=f10)
            d.text((x + 5 - tw / 2, ly - 22 - (i % 2) * 12), lab, fill=INK if f > 0.05 else SILK, font=f10)
    # 16 switches, all down in this run
    for i in range(16):
        x = lx0 - i * step
        d.rectangle((x - 1, 384, x + 11, 408), fill="#2b2f31", outline="#4a5156")
        d.rectangle((x + 1, 396, x + 9, 406), fill="#c9cdc8")

    # the PC's terminal
    tx0, ty0, tx1, ty1 = 572, 60, W - 16, 424
    d.rectangle((tx0, ty0, tx1, ty1), fill="#070908", outline=LINE)
    d.text((tx0 + 10, ty0 + 8), cfg["terminal_title"], fill=DIM, font=f11)
    d.line((tx0, ty0 + 26, tx1, ty0 + 26), fill=LINE)
    lines = terminal(cfg, [u for u in uart if u[0] < c1])
    typed = [b for c, k, b in uart if k == "rx" and c < c1]
    if cfg["terminal"] == "text" and typed:   # a terminal does not echo keys: the chip's reply shows them
        d.text((tx0 + 10, ty1 - 20), "keys the PC sent: " + "".join(chr(b) if 32 <= b < 127 else "." for b in typed), fill=PROBE, font=f11)
    cols = 40
    rows = []
    for text, who in lines:
        for part in (textwrap.wrap(text, cols, drop_whitespace=False) or [""]):
            rows.append((part, who))
    rows = rows[-21:]
    for i, (text, who) in enumerate(rows):
        d.text((tx0 + 10, ty0 + 34 + i * 16), text, fill={"chip": INK, "host": PROBE, "note": DIM}[who], font=f12)
    if (c1 // 2000) % 2 == 0 or c1 >= end:
        cy_ = ty0 + 34 + max(0, len(rows) - 1) * 16
        last = rows[-1][0] if rows else ""
        d.rectangle((tx0 + 12 + d.textlength(last, font=f12), cy_ + 1, tx0 + 19 + d.textlength(last, font=f12), cy_ + 13), fill=GREEN)

    # the whole run as a strip: LED 0 in amber, the bench's actions marked, the cursor in probe blue
    sx0, sx1, sy0 = 150, W - 16, 448
    d.text((16, sy0 + 2), f"LD0 ({cfg['leds'][0]}), whole run", fill=DIM, font=f11)
    X = lambda c: sx0 + c / end * (sx1 - sx0)
    highs, v, t = [], 0, 0
    for c, val in leds:
        nv = (val or 0) & 1
        if nv and not v:
            t = c
        if v and not nv:
            highs.append((t, c))
        v = nv
    if v:
        highs.append((t, end))
    x = sx0
    for a, b in highs:       # a pulse of a few clocks still gets 3 pixels, so it can be seen
        xa, xb = X(a), max(X(b), X(a) + 3)
        d.line((x, sy0 + 14, xa, sy0 + 14, xa, sy0 + 2, xb, sy0 + 2, xb, sy0 + 14), fill=AMBER, width=2, joint="curve")
        x = xb
    d.line((x, sy0 + 14, sx1, sy0 + 14), fill=AMBER, width=2)
    for c, lab in marks:
        x = X(c)
        d.line((x, sy0 + 20, x, sy0 + 30), fill=PROBE, width=2)
        d.text((x + 3, sy0 + 22), lab, fill=PROBE, font=f10)
    d.line((X(c1), sy0 - 4, X(c1), sy0 + 36), fill=PROBE, width=2)
    # what this is
    for i, line in enumerate(textwrap.wrap(cfg["note"], 132)[:3]):
        d.text((16, 494 + i * 15), line, fill=DIM, font=f11)
    return im


PCB_rgb = tuple(int(PCB[i:i + 2], 16) for i in (1, 3, 5))


def terminal(cfg, bytes_):
    """The PC's view: text as it prints, or bytes in hex grouped by direction."""
    out = []
    if cfg["terminal"] == "text":
        cur, who = "", "chip"
        for _, k, b in bytes_:
            if k == "rx":
                continue
            if b == 10:
                out.append((cur, who)); cur = ""
            elif 32 <= b < 127:
                cur += chr(b)
        out.append((cur, who))
        return out
    run, who = [], None
    for _, k, b in bytes_:
        w = "chip" if k == "tx" else "host"
        if w != who and run:
            out.append(((cfg["host_prefix"] if who == "host" else cfg["chip_prefix"]) + " ".join(run), who)); run = []
        who = w
        run.append("%02X" % b)
    if run:
        out.append(((cfg["host_prefix"] if who == "host" else cfg["chip_prefix"]) + " ".join(run), who))
    return out or [("", "note")]


def main():
    cfg = json.load(open("docs/site/site.json"))["fpga"]
    ch, uart, end = load()
    # the bench's actions, marked on the strip
    marks, prev = [], 0
    for c, v in ch.get("btn", []):
        v = v or 0
        for k, b in (("C", 0), ("L", 1), ("R", 2), ("U", 3)):
            if (v >> b) & 1 and not (prev >> b) & 1:
                marks.append((c, "BTN" + k))
        prev = v
    if not marks or cfg["terminal"] == "text":
        marks += [(c, "typed") for c, k, _ in uart if k == "rx"]
    rgb = [frame(cfg, ch, uart, end, round(end * i / FRAMES), round(end * (i + 1) / FRAMES), marks) for i in range(FRAMES)]
    # one palette for every frame, taken from the last (it has every colour lit), so unchanged pixels stay
    # identical between frames and the GIF stores only what moved
    pal = rgb[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in rgb]
    os.makedirs(OUT, exist_ok=True)
    frames[0].save(f"{OUT}/fpga.gif", save_all=True, append_images=frames[1:], loop=0,
                   duration=[MS] * (FRAMES - 1) + [3000], optimize=True)
    rgb[-1].save(f"{OUT}/fpga.png", optimize=True)
    print(f"wrote {OUT}/fpga.gif ({os.path.getsize(f'{OUT}/fpga.gif') / 1024:.0f} KB, {FRAMES} frames, "
          f"{(FRAMES - 1) * MS / 1000 + 3:.1f} s) and its still, from {end:,} recorded cycles")


if __name__ == "__main__":
    main()
