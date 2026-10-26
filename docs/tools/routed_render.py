#!/usr/bin/env python3
"""routed_render.py — the README's pictures of the real routed layout.

    python3 docs/tools/routed_render.py      write docs/images/routed.jpg, routed_clock.gif, routed_clock.png

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. It draws
docs/site/data/routed.json (docs/tools/routed_map.py) the way the site's
layout.js does, so the README shows what the site shows:

    routed.jpg         the whole die: cells, the power grid, every routed wire,
                       each metal layer tinted with its own thin-film gradient
                       and the layers added together, with a soft glow
    routed_clock.gif   a clock edge leaving the clk pin and running down the
                       clock tree net by net, in the order of each net's depth,
                       until the flip-flops it reaches flash
    routed_clock.png   the last frame, the whole tree lit, for readers with
                       motion turned off

Only the colours are chosen; every rectangle and line is the run's geometry.
Pillow only, no randomness: the same routed.json and Pillow give the same
bytes. Like site_shots.py its pictures are not compared by make docs, because
a different Pillow may compress them differently; rerun it after
routed_map.py.
"""
import base64, json, struct, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC = "docs/site/data/routed.json"
OUT = "docs/images"
SCREEN = (5, 7, 10)
# per layer: the two ends of its thin-film gradient (as in layout.js)
FILM = {"li1": ("#3b4bff", "#7a3bff"), "met1": ("#6b5bff", "#00d0ff"), "met2": ("#00e0c0", "#3c8cff"),
        "met3": ("#ffc04d", "#ff5fa2"), "met4": ("#ff4f8b", "#b06bff"), "met5": ("#ffffff", "#aaaaaa")}
CLASS_FILL = [(70, 210, 150, 66), (140, 160, 200, 33), (110, 130, 255, 51), (255, 176, 0, 158), (120, 130, 160, 13)]
METAL_ALPHA, BLOOM_ALPHA, DIM = .62, .4, .32
SS = 2                                   # supersampling, for clean thin wires


def u16(s):
    raw = base64.b64decode(s)
    return struct.unpack(f"<{len(raw) // 2}H", raw)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def film(size, a, b):
    """A gradient from bottom-left to top-right: a, b at the middle, a again (layout.js's createLinearGradient)."""
    W, H = size
    gx = Image.linear_gradient("L").rotate(90).transpose(Image.FLIP_LEFT_RIGHT).resize(size)   # 0 at left, 255 at right
    gy = Image.linear_gradient("L").resize(size).transpose(Image.FLIP_TOP_BOTTOM)              # 0 at bottom, 255 at top
    t = Image.blend(gx, gy, H * H / (W * W + H * H))
    a, b = rgb(a), rgb(b)
    lut = lambda ch: [round(a[ch] + (b[ch] - a[ch]) * (1 - abs(2 * i / 255 - 1))) for i in range(256)]
    return Image.merge("RGB", [t.point(lut(ch)) for ch in range(3)])


def scale(img, f):
    return img.point(lambda v: round(v * f))


def draw_die(R, W):
    """The die at W pixels wide, as layout.js's render(): (picture, metal layer alone)."""
    DW, DH = R["die"]
    s = W / DW
    H = round(DH * s)
    big = (W * SS, H * SS)
    S = s * SS
    Y = lambda y: big[1] - y * S
    base = Image.new("RGBA", big, SCREEN + (255,))
    cells = Image.new("RGBA", big, (0, 0, 0, 0))
    d = ImageDraw.Draw(cells)
    row = R["row"] - min(R["row"] * .3, .8 / s)
    for k, enc in enumerate(R["cells"]):
        a = u16(enc)
        layer = Image.new("RGBA", big, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        for i in range(0, len(a), 3):
            x, y, w = a[i], a[i + 1], a[i + 2]
            dl.rectangle([x * S, Y(y + row), (x + w) * S - 1, Y(y) - 1], fill=CLASS_FILL[k])
        cells = Image.alpha_composite(cells, layer)
    base = Image.alpha_composite(base, cells)
    pw = Image.new("RGBA", big, (0, 0, 0, 0))
    d = ImageDraw.Draw(pw)
    p = u16(R["power"])
    for i in range(0, len(p), 6):
        w = p[i + 5] / 2
        d.rectangle([(p[i + 1] - w) * S, Y(p[i + 4] + w), (p[i + 3] + w) * S, Y(p[i + 2] - w)], fill=(200, 210, 230, 26))
    base = Image.alpha_composite(base, pw).convert("RGB")
    metal = Image.new("RGB", big, (0, 0, 0))
    for li, L in enumerate(R["layers"]):
        a = u16(R["wires"][li])
        if not a:
            continue
        mask = Image.new("L", big, 0)
        d = ImageDraw.Draw(mask)
        h = max(R["width_nm"][li] / R["unit_nm"], .6 / s) / 2
        for i in range(0, len(a), 4):
            d.rectangle([(a[i] - h) * S, Y(a[i + 3] + h), (a[i + 2] + h) * S, Y(a[i + 1] - h)], fill=255)
        tint = film(big, *FILM.get(L, ("#ffffff", "#ffffff")))
        metal = ImageChops.add(metal, scale(ImageChops.multiply(tint, mask.convert("RGB")), METAL_ALPHA))
    bloom = scale(metal.filter(ImageFilter.GaussianBlur(max(2, 6 * s * 10) * SS)), BLOOM_ALPHA)
    out = ImageChops.add(ImageChops.add(base, bloom), metal)
    return out.resize((W, H), Image.LANCZOS), s


def clock_frame(R, base, s, t, whole=False):
    """The clock tree over a dimmed die at time t (0..1.25), as layout.js's drawClock()."""
    W, H = base.size
    img = scale(base, DIM)
    clock = [(c["depth"], u16(c["segs"]), u16(c["flops"])) for c in R["clock"]]
    D = max(c[0] for c in clock) + 1
    front = D + 1 if whole else t * (D + 1.2)
    glow = Image.new("RGB", (W, H)); core = Image.new("RGB", (W, H))
    dg, dc = ImageDraw.Draw(glow), ImageDraw.Draw(core)
    for depth, segs, _ in clock:
        lit = min(1, front - depth)
        if lit <= 0:
            continue
        fade = 1 if whole else max(.35, 1 - (front - depth - 1) * .45)
        col = (255, 190 + 40 * (depth % 2), 90)
        for i in range(0, len(segs), 5):
            xy = [segs[i + 1] * s, H - segs[i + 2] * s, segs[i + 3] * s, H - segs[i + 4] * s]
            dg.line(xy, fill=tuple(round(v * .35 * fade) for v in col), width=5)
            dc.line(xy, fill=tuple(round(v * .95 * fade) for v in col), width=2)
    img = ImageChops.add(ImageChops.add(img, glow.filter(ImageFilter.GaussianBlur(2))), core)
    flash = .9 if whole else max(0, min(1, front - D)) * max(0, 1.6 - (front - D))
    if flash > .02:
        f = Image.new("RGB", (W, H)); df = ImageDraw.Draw(f)
        c = tuple(round(v * min(1, flash)) for v in (150, 255, 200))
        for _, _, fl in clock:
            for i in range(0, len(fl), 2):
                x, y = fl[i] * s, H - fl[i + 1] * s
                df.rectangle([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=c)
        img = ImageChops.add(img, ImageChops.add(f.filter(ImageFilter.GaussianBlur(2)), f))
    return img


def main():
    R = json.load(open(SRC))
    if not R["clock"]:
        sys.exit("routed_render.py: routed.json has no clock tree")
    wide = R["die"][0] >= R["die"][1]
    still, _ = draw_die(R, 1200 if wide else 800)
    still.save(f"{OUT}/routed.jpg", quality=82, optimize=True, progressive=True)
    small, s = draw_die(R, 760 if wide else 480)
    whole = clock_frame(R, small, s, 0, whole=True)
    whole.save(f"{OUT}/routed_clock.png", optimize=True)
    # one palette for every frame, so only the pixels the edge changes differ between frames
    sheet = Image.new("RGB", (small.width * 2, small.height)); sheet.paste(scale(small, DIM), (0, 0)); sheet.paste(whole, (small.width, 0))
    pal = sheet.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [clock_frame(R, small, s, i / 24).quantize(palette=pal, dither=Image.Dither.NONE) for i in range(0, 31)]
    durs = [700] + [70] * 29 + [1600]
    frames[0].save(f"{OUT}/routed_clock.gif", save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True, disposal=1)
    print(f"routed_render.py: wrote {OUT}/routed.jpg, routed_clock.gif, routed_clock.png ({R['design']})")


if __name__ == "__main__":
    main()
