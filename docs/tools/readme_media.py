#!/usr/bin/env python3
"""readme_media.py — the README's short animation, drawn from a recorded tour.

    python3 docs/tools/readme_media.py          write docs/images/explorer/tour.gif and tour.png

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora; which tour,
which signals and where it goes are in docs/site/site.json under "gif".
Every frame is drawn from docs/site/data/traces/<fixture>.json, so the
animation shows the recording, not a drawing of it. tour.png is the last
frame, a still for readers with motion turned off. Uses Pillow and its
built-in font only, so the output depends on nothing installed on the machine.
"""
import json, os, textwrap
from PIL import Image, ImageDraw, ImageFont

# the explorer's dark theme (docs/site/lib/exhibit.css), which reads on GitHub's light and dark pages alike
BG, PANEL, INK, MUTED, LINE = "#0f1214", "#161a1d", "#e8ebe9", "#9aa3a7", "#2c3337"
BIT, BUS, ENUM, CUR, HOST, CHIP, XS = "#6ea8f0", "#3fc49b", "#e68db3", "#ff7d47", "#6ea8f0", "#e3a440", "#5b656a"
W, LABEL, ROW, TOP = 880, 170, 26, 62


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                      # Pillow < 10.1
        return ImageFont.load_default()


def ease(f):
    """Ease in and out: the cursor gathers speed and settles on the caption's cycle."""
    return 4 * f ** 3 if f < 0.5 else 1 - (-2 * f + 2) ** 3 / 2


def value_at(sig, c):
    v = None
    for cc, vv in sig["changes"]:
        if cc > c:
            break
        v = vv
    return v


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


def frame(fx, sigs, lo, hi, cursor, caption, h):
    im = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(im)
    f11, f12, f13, f15 = font(11), font(12), font(13), font(15)
    d.text((16, 12), fx["title"], fill=INK, font=f15)
    tag = "Recorded from RTL simulation"
    tw = d.textlength(tag, font=f11)
    d.rounded_rectangle((W - tw - 34, 10, W - 14, 30), radius=10, outline=BIT, width=1)
    d.text((W - tw - 24, 14), tag, fill=BIT, font=f11)
    d.text((16, 34), f"cycle {cursor}" + ("" if cursor < 0 else f"  ·  {cursor * 20 / 1000:.2f} us at 50 MHz"), fill=MUTED, font=f12)
    span = hi - lo + 1
    x = lambda c: LABEL + (min(max(c, lo), hi + 1) - lo) / span * (W - LABEL - 14)
    rows = list(sigs)
    if fx.get("bytes"):
        rows += ["bytes-host", "bytes-chip"]
    for i, s in enumerate(rows):
        y = TOP + i * ROW
        if isinstance(s, str):
            d.text((16, y + 7), "host -> chip" if s == "bytes-host" else "chip -> host", fill=MUTED, font=f12)
            for b in fx["bytes"]:
                if b["dir"] != s[6:] or b["end"] < lo or b["at"] > hi or b["at"] > cursor:
                    continue
                x0, x1 = x(b["at"]), x(min(b["end"], cursor))
                col = HOST if b["dir"] == "host" else CHIP
                d.rectangle((x0, y + 5, max(x0 + 2, x1), y + ROW - 5), outline=col, fill=PANEL)
                if x1 - x0 > 22:
                    d.text((x0 + 4, y + 7), "%02X" % b["byte"], fill=INK, font=f11)
            continue
        d.text((16, y + 7), s["label"], fill=MUTED, font=f12)
        ch = [c for c in s["changes"] if c[0] <= min(hi, cursor)]
        for k, (c0, v) in enumerate(ch):
            c1 = ch[k + 1][0] if k + 1 < len(ch) else min(hi, cursor) + 1
            if c1 <= lo:
                continue
            x0, x1 = x(max(c0, lo)), x(c1)
            if v is None:
                d.rectangle((x0, y + 6, x1, y + ROW - 6), fill=XS)
            elif s["kind"] == "bit":
                yy = y + 5 if v else y + ROW - 5
                if k and c0 >= lo:
                    d.line((x0, y + 5, x0, y + ROW - 5), fill=BIT, width=2)
                d.line((x0, yy, x1, yy), fill=BIT, width=2)
            else:
                col = ENUM if s["kind"] == "enum" else BUS
                d.polygon([(x0, y + ROW / 2), (x0 + 3, y + 5), (x1 - 3, y + 5), (x1, y + ROW / 2), (x1 - 3, y + ROW - 5), (x0 + 3, y + ROW - 5)], outline=col, fill=PANEL)
                t = fmt(s, v)
                if x1 - x0 > d.textlength(t, font=f11) + 10:
                    d.text((x0 + 6, y + 7), t, fill=INK, font=f11)
    yb = TOP + len(rows) * ROW
    for m in fx.get("marks", []):
        if lo <= m["at"] <= hi:
            d.line((x(m["at"]), TOP - 4, x(m["at"]), yb), fill=LINE, width=1)
            lx = x(m["at"]) + 3
            if lx + d.textlength(m["label"], font=f11) > W - 8:
                lx = x(m["at"]) - 3 - d.textlength(m["label"], font=f11)
            d.text((lx, yb + 2), m["label"], fill=MUTED, font=f11)
    xc = x(cursor) + (x(cursor + 1) - x(cursor)) / 2
    d.line((xc, TOP - 6, xc, yb), fill=CUR, width=2)
    d.rectangle((0, yb + 18, W, h), fill=PANEL)
    for i, ln in enumerate(textwrap.wrap(caption.replace("µ", "u").replace("→", "->").replace("−", "-"), 108)[:3]):
        d.text((16, yb + 28 + 18 * i), ln, fill=INK, font=f13)
    return im


def main():
    site = json.load(open("docs/site/site.json"))
    g = site["gif"]
    fx = json.load(open(f"docs/site/data/traces/{g['fixture']}.json"))
    byid = {s["id"]: s for s in fx["signals"]}
    sigs = [byid[i] for i in g["signals"]]
    lo, hi = g.get("window", fx["cycles"])
    caps = [c for c in fx["captions"] if lo <= c["at"] <= hi]
    h = TOP + (len(sigs) + (2 if fx.get("bytes") else 0)) * ROW + 90
    frames, durs = [], []
    # one sweep from caption to caption: 6 steps of motion, then a hold to read
    for i, c in enumerate(caps):
        nxt = caps[i + 1]["at"] if i + 1 < len(caps) else hi
        start = c["at"]
        for k in range(6):
            cur = round(start + (nxt - start) * ease(k / 6)) if i + 1 < len(caps) else start
            frames.append(frame(fx, sigs, lo, hi, cur, c["text"], h)); durs.append(90)
            if i + 1 == len(caps):
                break
        durs[-1] = 1700 if i + 1 < len(caps) else 3200
    total = sum(durs) / 1000
    if not 8 <= total <= 25:
        raise SystemExit(f"readme_media.py: the animation runs {total:.1f} s; keep it between 8 and 25")
    os.makedirs(os.path.dirname(g["out"]), exist_ok=True)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=32) for f in frames]
    pal[0].save(g["out"], save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=1)
    frame(fx, sigs, lo, hi, caps[-1]["at"], caps[-1]["text"], h).save(g["out"].replace(".gif", ".png"), optimize=True)
    print(f"wrote {g['out']} ({os.path.getsize(g['out']) / 1024:.0f} KB, {len(frames)} frames, {total:.1f} s) and its still")


if __name__ == "__main__":
    main()
