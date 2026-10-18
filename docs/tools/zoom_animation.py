#!/usr/bin/env python3
"""zoom_animation.py — an animated zoom from the whole Tiqora tile down to
single transistors, rendered frame by frame with KLayout from the real
sky130 cell geometry. Run layout_preview.py first (it writes the GDS and the
block positions this uses).

    python3 docs/tools/zoom_animation.py      ->  docs/images/zoom.webp
"""
import json, math, os
import klayout.db as db
import klayout.lay as lay
from PIL import Image, ImageDraw, ImageFont

W, H = 640, 427
area = json.load(open("docs/area.json"))
TILE_W, TILE_H = area["tile_um"]
regs = area["regions_um"]
TARGET = next((k for k in ("Register file (15 x 32 bits)", "Event queue") if k in regs),
              max(regs, key=lambda k: regs[k][2] * regs[k][3]))
rx, ry, rw, rh = regs[TARGET]
TARGET_LABEL = TARGET.split(" (")[0].lower()
cx, cy = rx + rw * 0.22, ry + rh * 0.34          # a spot inside the register file
LAYERS = [("64/20", 0x10141c, 0), ("65/20", 0x2a9d5c, 0), ("66/20", 0xd6453d, 0),
          ("67/20", 0x4f8cff, 5), ("67/44", 0xe9ecef, 0), ("68/20", 0xb08cff, 9), ("235/4", 0xffd23f, 1)]

lv = lay.LayoutView()
lv.set_config("background-color", "#0b0e14")
lv.set_config("grid-visible", "false")
lv.load_layout("syn/_w/preview.gds", False)
lv.clear_layers()
for src, col, dith in LAYERS:
    lp = lay.LayerPropertiesNode(); lp.source = src + "@1"
    lp.fill_color = lp.frame_color = col; lp.dither_pattern = dith; lp.width = 0
    lv.insert_layer(lv.end_layers(), lp)
lv.max_hier()

try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 17)
    small = ImageFont.truetype("DejaVuSans.ttf", 13)
except OSError:
    font = small = ImageFont.load_default()

def frame(width_um, t):
    """Render a window `width_um` wide, centred between the tile and the target."""
    h_um = width_um * H / W
    # the centre glides from the middle of the tile to the target as we zoom
    mx = TILE_W / 2 + (cx - TILE_W / 2) * t
    my = TILE_H / 2 + (cy - TILE_H / 2) * t
    lv.zoom_box(db.DBox(mx - width_um / 2, my - h_um / 2, mx + width_um / 2, my + h_um / 2))
    lv.save_image("/tmp/_zf.png", W, H)
    im = Image.open("/tmp/_zf.png").convert("RGB")
    d = ImageDraw.Draw(im)
    # scale bar: pick a round length about a fifth of the view
    target = width_um / 5
    bar = min((1, 2, 5, 10, 20, 50, 100), key=lambda v: abs(math.log(v / target))) if target >= 1 else 0.5
    px = bar / width_um * W
    d.rectangle([24, H - 38, 24 + px, H - 32], fill=(255, 255, 255))
    d.text((24, H - 62), f"{bar:g} µm", fill=(255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0))
    label = (f"this project's {area['tile']} tiles: {TILE_W:.0f} × {TILE_H:.0f} µm, ~{area['instances']:,} logic cells"
             if width_um > 0.45 * TILE_W else
             f"the {TARGET_LABEL}: rows of real cells" if width_um > 40 else
             "single cells: each one a few transistors")
    d.text((24, 20), label, fill=(255, 255, 255), font=font, stroke_width=3, stroke_fill=(0, 0, 0))
    d.text((W - 24, H - 30), "real sky130 cell geometry · KLayout", fill=(200, 200, 200),
           font=small, anchor="rd", stroke_width=2, stroke_fill=(0, 0, 0))
    return im

w0, w1, N = max(TILE_W, TILE_H * W / H) * 1.03, 22.0, 26   # fit the whole tile, landscape or portrait
frames = []
for i in range(N):
    t = i / (N - 1)
    e = t * t * (3 - 2 * t)                              # ease in and out
    frames.append(frame(w0 * (w1 / w0) ** e, e))
frames = [frames[0]] * 6 + frames + [frames[-1]] * 14   # hold, zoom in, hold, restart
os.makedirs("docs/images", exist_ok=True)
frames[0].save("docs/images/zoom.webp", save_all=True, append_images=frames[1:],
               duration=110, loop=0, quality=55, method=6)
print(f"docs/images/zoom.webp: {len(frames)} frames, {os.path.getsize('docs/images/zoom.webp') / 1e6:.1f} MB")
