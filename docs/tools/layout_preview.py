#!/usr/bin/env python3
"""layout_preview.py — draw Tiqora-Serial's real standard cells in its 1x2 tile.

What this is: every cell Yosys maps the design onto (about 5,000 instances of
real sky130_fd_sc_hd cells, the same library the fab uses), each drawn with
its real GDS geometry, placed in standard-cell rows inside the 161.00 x
225.76 um outline of a Tiny Tapeout 1x2 tile. Cells are grouped by the block
they belong to, and the leftover space is filled with filler and decap cells
the way a finished layout is.

What this is NOT: the fabricated layout. There is no routing (the metal2+
wires that connect the cells), and the placement is a simple block-by-block
row packer, not OpenROAD's. The real layout comes out of the `gds` GitHub
Actions job, which runs the full LibreLane flow and publishes a 3D viewer.

Usage (from the repo root):
    pip install klayout
    python3 docs/tools/layout_preview.py <sky130_fd_sc_hd dir>
where the directory contains lib/*tt_025C_1v80.lib, lef/sky130_fd_sc_hd.lef
and gds/sky130_fd_sc_hd.gds (any volare/ciel install has it under
<pdk>/sky130A/libs.ref/sky130_fd_sc_hd).

Outputs: docs/images/layout.png, docs/images/layout_blocks.png,
         docs/images/layout_zoom.png, docs/area.json
"""
import json, os, re, shutil, subprocess, sys, collections, math
import klayout.db as db
import klayout.lay as lay

TOP = "tt_um_normansrule_tiqora_serial"
TILE_W, TILE_H = 161.00, 225.76            # Tiny Tapeout 1x2 (tt_block_1x2_pg.def)
SITE_W, ROW_H = 0.46, 2.72                 # sky130 unithd site
MARGIN_X, MARGIN_Y = 6 * SITE_W, ROW_H     # LEFT/RIGHT_MARGIN_MULT 6, TOP/BOTTOM 1

BLOCKS = [   # (module name, label, colour) — first match in the path wins
    ("tp_uart_rx",      "UART receiver",                  "#c77dff"),
    ("tp_uart_tx",      "UART transmitter",               "#9d4edd"),
    ("tp_host_uart",    "Command interpreter",            "#8a5cff"),
    ("sync_compare",    "Deadline comparators",           "#ff5d73"),
    ("sync_timebase",   "Timebase + rate trim",           "#ffd23f"),
    ("sync_event_fifo", "Event queue",                    "#3ddc97"),
    ("sync_capture",    "Capture channels",               "#2ec4b6"),
    ("sync_unit",       "Timing unit control",            "#e76f51"),
]
GLUE = ("Glue", "#6c757d")


def base_name(m):
    # "$paramod\\tp_ncore\\RESET_PC=..." and "$paramod$<hash>\\sync_unit" both
    # carry the module name as the second backslash-separated field
    parts = m.split("\\")
    return parts[1] if m.startswith("$paramod") and len(parts) > 1 else parts[-1]


def synth(libdir):
    os.makedirs("syn/_w", exist_ok=True)
    lib = next(f for f in os.listdir(f"{libdir}/lib") if f.endswith("tt_025C_1v80.lib"))
    shutil.copy(f"{libdir}/lib/{lib}", "syn/_w/hd.lib")
    reads = [l for l in open("syn/synth_check.ys") if l.startswith("read_verilog")]
    ys = reads + [f"hierarchy -check -top {TOP}\n", f"synth -top {TOP}\n",
                  "dfflibmap -liberty syn/_w/hd.lib\n", "abc -liberty syn/_w/hd.lib\n",
                  "opt_clean\n", "write_json syn/_w/net.json\n"]
    open("syn/_w/p.ys", "w").writelines(ys)
    subprocess.run(["yowasp-yosys", "-q", "-s", "syn/_w/p.ys"], check=True)
    return json.load(open("syn/_w/net.json"))


def expand(net):
    """Flatten the hierarchy into (block_label, colour, cell_type) triples."""
    mods = net["modules"]
    out = []
    def walk(mod, path):
        for inst in mods[mod]["cells"].values():
            t = inst["type"]
            if t in mods:
                walk(t, path + [base_name(t)])
            elif t.startswith("sky130_fd_sc_hd__"):
                label, col = GLUE
                for key, lab, c in BLOCKS:
                    if key in path:
                        label, col = lab, c
                        break
                out.append((label, col, t))
    walk(TOP, [TOP])
    return out


def lef_sizes(lef):
    sizes, cur = {}, None
    for line in open(lef):
        m = re.match(r"\s*MACRO\s+(\S+)", line)
        if m: cur = m.group(1)
        m = re.match(r"\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", line)
        if m and cur: sizes[cur] = (float(m.group(1)), float(m.group(2)))
    return sizes


def treemap(items, x, y, w, h):
    """Slice-and-dice: split the rectangle among items proportionally."""
    if not items: return {}
    if len(items) == 1: return {items[0][0]: (x, y, w, h)}
    total = sum(a for _, a in items)
    half, acc = total / 2, 0
    for i, (_, a) in enumerate(items):
        acc += a
        if acc >= half: break
    left, right = items[:i + 1], items[i + 1:]
    fl = sum(a for _, a in left) / total
    if w >= h:
        return {**treemap(left, x, y, w * fl, h), **treemap(right, x + w * fl, y, w * (1 - fl), h)}
    return {**treemap(left, x, y, w, h * fl), **treemap(right, x, y + h * fl, w, h * (1 - fl))}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    libdir = sys.argv[1]
    net = synth(libdir)
    cells = expand(net)
    sizes = lef_sizes(f"{libdir}/lef/sky130_fd_sc_hd.lef")

    by_block = collections.defaultdict(list)
    colour = {}
    for label, col, t in cells:
        by_block[label].append(t); colour[label] = col
    area = {b: sum(sizes[t][0] * sizes[t][1] for t in ts) for b, ts in by_block.items()}
    total = sum(area.values())

    # core area snapped to whole rows and sites
    cx0, cy0 = MARGIN_X, MARGIN_Y
    nrows = int((TILE_H - 2 * MARGIN_Y) / ROW_H)
    cw = math.floor((TILE_W - 2 * MARGIN_X) / SITE_W) * SITE_W
    ch = nrows * ROW_H
    util = total / (cw * ch)

    order = sorted(area.items(), key=lambda kv: -kv[1])
    regions = treemap(order, cx0, cy0, cw, ch)

    placements, fills = [], []           # (cell, x, y, flipped)
    FILL = [("sky130_fd_sc_hd__decap_8", 8), ("sky130_fd_sc_hd__decap_4", 4),
            ("sky130_fd_sc_hd__fill_2", 2), ("sky130_fd_sc_hd__fill_1", 1)]
    for label, (rx, ry, rw, rh) in regions.items():
        r0 = math.ceil((ry - cy0) / ROW_H - 1e-6)
        r1 = math.floor((ry + rh - cy0) / ROW_H + 1e-6)
        s0 = math.ceil((rx - cx0) / SITE_W - 1e-6)
        s1 = math.floor((rx + rw - cx0) / SITE_W + 1e-6)
        rows = list(range(r0, r1))
        todo = sorted(by_block[label], key=lambda t: -sizes[t][0])
        n_sites_row = s1 - s0
        # spread cells so the block's density matches the design's overall
        per_row = collections.defaultdict(list)
        widths = [round(sizes[t][0] / SITE_W) for t in todo]
        cap = sum(widths)
        per_row_target = max(1, cap / max(1, len(rows)))
        ri, fill_sites = 0, 0
        for t, wsites in zip(todo, widths):
            if fill_sites + wsites > n_sites_row or fill_sites > per_row_target * 1.02:
                ri = min(ri + 1, len(rows) - 1); fill_sites = 0
            per_row[rows[ri]].append((t, wsites)); fill_sites += wsites
        for r in rows:
            items = per_row.get(r, [])
            used = sum(w for _, w in items)
            gap = (n_sites_row - used) / (len(items) + 1) if items else n_sites_row
            pos, acc = s0, 0.0
            flipped = (r % 2 == 1)
            y = cy0 + r * ROW_H
            def fill_span(a, b):
                p = a
                while p < b:
                    for name, w in FILL:
                        if p + w <= b:
                            fills.append((name, cx0 + p * SITE_W, y, flipped)); p += w; break
            for t, wsites in items:
                acc += gap
                start = s0 + int(round(acc)) + (pos - s0)
                start = max(start, pos)
                fill_span(pos, start)
                placements.append((t, cx0 + start * SITE_W, y, flipped))
                pos = start + wsites
                acc = 0.0
            fill_span(pos, s1)

    # ---- build the layout from the real cell GDS ----
    ly = db.Layout()
    ly.read(f"{libdir}/gds/sky130_fd_sc_hd.gds")
    ly.dbu = ly.dbu
    top = ly.create_cell("TIQORA_SERIAL_PREVIEW")
    idx = {c.name: c.cell_index() for c in ly.each_cell()}
    for t, x, y, flip in placements + fills:
        if t not in idx: continue
        if flip:
            tr = db.DTrans(db.DTrans.M0, db.DVector(x, y + ROW_H))
        else:
            tr = db.DTrans(db.DVector(x, y))
        top.insert(db.DCellInstArray(idx[t], tr))
    outline = ly.layer(235, 4)
    top.shapes(outline).insert(db.DBox(0, 0, TILE_W, TILE_H))
    os.makedirs("docs/images", exist_ok=True)
    opt = db.SaveLayoutOptions(); opt.add_cell(top.cell_index())
    ly.write("syn/_w/preview.gds", opt)

    # ---- render ----
    LAYERS = [  # (source, fill, frame, dither)  sky130 layer numbers
        ("64/20", 0x10141c, 0x10141c, 0),   # nwell
        ("65/20", 0x2a9d5c, 0x2a9d5c, 0),   # diffusion
        ("66/20", 0xd6453d, 0xd6453d, 0),   # poly
        ("67/20", 0x4f8cff, 0x4f8cff, 5),   # local interconnect
        ("67/44", 0xe9ecef, 0xe9ecef, 0),   # mcon
        ("68/20", 0xb08cff, 0xb08cff, 9),   # metal 1 (rails)
        ("235/4", 0xffd23f, 0xffd23f, 1),   # tile outline
    ]
    def render(path, box, w, h):
        lv = lay.LayoutView()
        lv.set_config("background-color", "#0b0e14")
        lv.set_config("grid-visible", "false")
        lv.set_config("text-visible", "false")
        lv.load_layout("syn/_w/preview.gds", False)
        lv.clear_layers()
        for src, fc, frc, dith in LAYERS:
            lp = lay.LayerPropertiesNode()
            lp.source = src + "@1"
            lp.fill_color, lp.frame_color = fc, frc
            lp.dither_pattern = dith
            lp.width = 0
            lv.insert_layer(lv.end_layers(), lp)
        lv.max_hier()
        lv.zoom_box(box)
        lv.save_image(path, w, h)

    render("docs/images/layout.png", db.DBox(-4, -4, TILE_W + 4, TILE_H + 4), 2400, 1640)
    rf = regions.get("Event queue") or max(regions.values(), key=lambda r: r[2] * r[3])
    if rf:
        zx, zy = rf[0] + rf[2] * 0.2, rf[1] + rf[3] * 0.3
        render("docs/images/layout_zoom.png", db.DBox(zx, zy, zx + 24, zy + 14), 1600, 933)

    # ---- block overlay ----
    try:
        from PIL import Image, ImageDraw, ImageFont
        im = Image.open("docs/images/layout.png").convert("RGBA")
        W, H = im.size
        sx, sy = W / (TILE_W + 8), H / (TILE_H + 8)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        except OSError:
            font = ImageFont.load_default()
        for label, (rx, ry, rw, rh) in regions.items():
            c = colour[label].lstrip("#")
            rgb = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
            x0, x1 = (rx + 4) * sx, (rx + rw + 4) * sx
            y0, y1 = H - (ry + rh + 4) * sy, H - (ry + 4) * sy
            d.rectangle([x0, y0, x1, y1], fill=rgb + (70,), outline=rgb + (255,), width=4)
            txt = f"{label}\n{area[label]:,.0f} um\u00b2"
            d.multiline_text((x0 + 10, y0 + 8), txt, fill=(255, 255, 255, 255), font=font,
                             stroke_width=3, stroke_fill=(0, 0, 0, 255))
        Image.alpha_composite(im, ov).convert("RGB").save("docs/images/layout_blocks.png")
    except ImportError:
        print("PIL not installed: skipping the labelled overlay")

    json.dump({"tile": "1x2", "tile_um": [TILE_W, TILE_H],
               "total_cell_area_um2": round(total, 1),
               "utilization_of_core_area": round(util, 4),
               "instances": len(placements), "fill_instances": len(fills),
               "blocks": {b: round(a, 1) for b, a in sorted(area.items(), key=lambda kv: -kv[1])},
               "regions_um": {b: [round(v, 2) for v in r] for b, r in regions.items()}},
              open("docs/area.json", "w"), indent=2)
    print(f"{len(placements)} cells ({total:,.0f} um^2, {100*util:.1f}% of the core area), "
          f"{len(fills)} fill/decap cells")
    for b, a in sorted(area.items(), key=lambda kv: -kv[1]):
        print(f"  {b:<32}{a:>9,.0f} um^2")


if __name__ == "__main__":
    main()
