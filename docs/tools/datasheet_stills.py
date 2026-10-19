#!/usr/bin/env python3
"""datasheet_stills.py — still images for the PDF datasheet.

The Tiny Tapeout datasheet is built with typst 0.13, which reads PNG, JPEG,
GIF and SVG but not WebP. This picks three frames of docs/images/zoom.webp
(the whole tile, one block, single cells) and writes them side by side.

    python3 docs/tools/datasheet_stills.py    ->  docs/images/zoom_steps.png

Run it after zoom_animation.py.
"""
from PIL import Image

anim = Image.open("docs/images/zoom.webp")
n = anim.n_frames
# The WebP encoder merges zoom_animation.py's repeated hold frames, so the
# stored frames are the zoom itself: first, middle and last.
picks = [0, n // 2, n - 1]
frames = []
for i in picks:
    anim.seek(i)
    frames.append(anim.convert("RGB"))
w, h = frames[0].size
gap = 8
strip = Image.new("RGB", (3 * w + 2 * gap, h), (255, 255, 255))
for k, f in enumerate(frames):
    strip.paste(f, (k * (w + gap), 0))
strip = strip.resize((strip.width // 2, strip.height // 2), Image.LANCZOS)
strip.save("docs/images/zoom_steps.png", optimize=True)
print(f"docs/images/zoom_steps.png: frames {picks} of {n}, {strip.width}x{strip.height}")
