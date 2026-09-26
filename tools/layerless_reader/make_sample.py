# -*- coding: utf-8 -*-
"""
رسمة معمارية تجريبية بأسماء ليّرات **مضلِّلة عن قصد** (الأعمدة على A-FURN،
المحاور على WALLS، الحوائط على COLUMNS...) - لو القارئ اعتمد على الأسماء
هيفشل. الحقيقة المعروفة بترجع مع الملف عشان الاختبار يقارن بيها.

    python make_sample.py sample_arch.dxf
"""

import math
import sys

import ezdxf

MM = 1000.0
BAY = 6.0          # م
NX, NY = 4, 4      # محاور A-D و 1-4
COL_B, COL_D = 0.30, 0.60
EXT_T, PART_T, CORE_T = 0.25, 0.12, 0.25


def P(x, y):
    return (x * MM, y * MM)


def build(path, insunits=0):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = insunits
    for name in ("A-FURN", "WALLS", "COLUMNS", "Layer1", "SLAB", "TXT", "misc", "OPENING"):
        doc.layers.add(name)
    msp = doc.modelspace()
    truth = {"columns": [], "rc_walls": 0, "openings": 0}

    xs = [i * BAY for i in range(NX)]
    ys = [j * BAY for j in range(NY)]

    # ---- المحاور: على ليّر اسمه WALLS، بخط CENTER وفقاعات ----
    for i, x in enumerate(xs):
        msp.add_line(P(x, -2.0), P(x, ys[-1] + 2.0),
                     dxfattribs={"layer": "WALLS", "linetype": "CENTER"})
        msp.add_circle(P(x, ys[-1] + 2.5), 0.5 * MM, dxfattribs={"layer": "WALLS"})
        msp.add_text("ABCD"[i], height=0.4 * MM,
                     dxfattribs={"layer": "TXT", "insert": P(x - 0.12, ys[-1] + 2.35)})
    for j, y in enumerate(ys):
        msp.add_line(P(-2.0, y), P(xs[-1] + 2.0, y),
                     dxfattribs={"layer": "WALLS", "linetype": "CENTER"})
        msp.add_circle(P(-2.5, y), 0.5 * MM, dxfattribs={"layer": "WALLS"})
        msp.add_text(str(j + 1), height=0.4 * MM,
                     dxfattribs={"layer": "TXT", "insert": P(-2.62, y - 0.15)})

    # ---- الأعمدة: على A-FURN، outline + hatch SOLID ----
    for x in xs:
        for y in ys:
            pts = [P(x - COL_B / 2, y - COL_D / 2), P(x + COL_B / 2, y - COL_D / 2),
                   P(x + COL_B / 2, y + COL_D / 2), P(x - COL_B / 2, y + COL_D / 2)]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-FURN"})
            h = msp.add_hatch(color=8, dxfattribs={"layer": "Layer1"})
            h.paths.add_polyline_path(pts, is_closed=True)
            truth["columns"].append((x, y))

    # ---- الحوائط الخارجية (مباني 250) بين الأعمدة، على COLUMNS ----
    def wall_x(y0, xa, xb, t, layer="COLUMNS"):
        msp.add_line(P(xa, y0 - t / 2), P(xb, y0 - t / 2), dxfattribs={"layer": layer})
        msp.add_line(P(xa, y0 + t / 2), P(xb, y0 + t / 2), dxfattribs={"layer": layer})

    def wall_y(x0, ya, yb, t, layer="COLUMNS"):
        msp.add_line(P(x0 - t / 2, ya), P(x0 - t / 2, yb), dxfattribs={"layer": layer})
        msp.add_line(P(x0 + t / 2, ya), P(x0 + t / 2, yb), dxfattribs={"layer": layer})

    for k in range(NX - 1):
        xa, xb = xs[k] + COL_B / 2, xs[k + 1] - COL_B / 2
        wall_x(ys[0], xa, xb, EXT_T)
        wall_x(ys[-1], xa, xb, EXT_T)
    for k in range(NY - 1):
        ya, yb = ys[k] + COL_D / 2, ys[k + 1] - COL_D / 2
        wall_y(xs[0], ya, yb, EXT_T)
        wall_y(xs[-1], ya, yb, EXT_T)

    # ---- قواطيع 120 جوه (مع فتحة باب) على SLAB ----
    wall_x(3.0, 0.2, 2.2, PART_T, "SLAB")
    wall_x(3.0, 3.1, 5.8, PART_T, "SLAB")
    wall_y(15.0, 12.3, 17.7, PART_T, "SLAB")

    # ---- الكور: أسانسير (X) + حوائط خرسانة 250 معبّاه SOLID زي الأعمدة ----
    cx0, cy0, cw, ch = 7.5, 7.5, 2.2, 2.2
    outer = [(cx0, cy0), (cx0 + cw, cy0), (cx0 + cw, cy0 + ch), (cx0, cy0 + ch)]
    t = CORE_T
    inner = [(cx0 + t, cy0 + t), (cx0 + cw - t, cy0 + t), (cx0 + cw - t, cy0 + ch - t),
             (cx0 + t, cy0 + ch - t)]
    msp.add_lwpolyline([P(*q) for q in outer], close=True, dxfattribs={"layer": "misc"})
    msp.add_lwpolyline([P(*q) for q in inner], close=True, dxfattribs={"layer": "misc"})
    for (a, b, c, d) in (
            ((cx0, cy0), (cx0 + cw, cy0), (cx0 + cw, cy0 + t), (cx0, cy0 + t)),
            ((cx0, cy0 + ch - t), (cx0 + cw, cy0 + ch - t), (cx0 + cw, cy0 + ch), (cx0, cy0 + ch)),
            ((cx0, cy0 + t), (cx0 + t, cy0 + t), (cx0 + t, cy0 + ch - t), (cx0, cy0 + ch - t)),
            ((cx0 + cw - t, cy0 + t), (cx0 + cw, cy0 + t), (cx0 + cw, cy0 + ch - t),
             (cx0 + cw - t, cy0 + ch - t))):
        h = msp.add_hatch(color=8, dxfattribs={"layer": "Layer1"})
        h.paths.add_polyline_path([P(*a), P(*b), P(*c), P(*d)], is_closed=True)
    truth["rc_walls"] = 4
    # X الأسانسير
    msp.add_line(P(*inner[0]), P(*inner[2]), dxfattribs={"layer": "A-FURN"})
    msp.add_line(P(*inner[1]), P(*inner[3]), dxfattribs={"layer": "A-FURN"})
    truth["openings"] += 1

    # ---- سلم: قلبتين 10 درجات ----
    sx, sy = 13.0, 7.0
    for k in range(10):
        msp.add_line(P(sx, sy + k * 0.3), P(sx + 1.2, sy + k * 0.3),
                     dxfattribs={"layer": "COLUMNS"})
        msp.add_line(P(sx + 1.4, sy + k * 0.3), P(sx + 2.6, sy + k * 0.3),
                     dxfattribs={"layer": "COLUMNS"})
    truth["openings"] += 1

    # ---- بلوكات: باب، ترابيزة بكراسي، سرير، كومودينو (مربع فاضي 400!) ----
    door = doc.blocks.new("DR90")
    door.add_arc((0, 0), 0.9 * MM, 0, 90)
    door.add_line((0, 0), (0, 0.9 * MM))
    table = doc.blocks.new("TBL")
    table.add_lwpolyline([(0, 0), (1200, 0), (1200, 800), (0, 800)], close=True)
    for cx in (200, 700):
        table.add_lwpolyline([(cx, -450), (cx + 400, -450), (cx + 400, -50), (cx, -50)],
                             close=True)
        table.add_lwpolyline([(cx, 850), (cx + 400, 850), (cx + 400, 1250), (cx, 1250)],
                             close=True)
    bed = doc.blocks.new("BED")
    bed.add_lwpolyline([(0, 0), (1600, 0), (1600, 2000), (0, 2000)], close=True)
    bed.add_lwpolyline([(100, 1600), (700, 1600), (700, 1900), (100, 1900)], close=True)
    bed.add_lwpolyline([(900, 1600), (1500, 1600), (1500, 1900), (900, 1900)], close=True)
    bed.add_lwpolyline([(-500, 1500), (-100, 1500), (-100, 1900), (-500, 1900)], close=True)

    for (x, y, rot) in ((1.0, 3.0, 0), (3.3, 3.0, 0), (15.0, 13.0, 90), (4.0, 0.0, 180)):
        msp.add_blockref("DR90", P(x, y), dxfattribs={"layer": "OPENING", "rotation": rot})
    msp.add_blockref("TBL", P(1.5, 7.5), dxfattribs={"layer": "COLUMNS"})
    msp.add_blockref("TBL", P(13.5, 1.5), dxfattribs={"layer": "COLUMNS"})
    msp.add_blockref("BED", P(2.0, 13.0), dxfattribs={"layer": "A-FURN"})
    msp.add_blockref("BED", P(8.0, 13.0), dxfattribs={"layer": "A-FURN"})

    # ---- نصوص وأبعاد ----
    for (x, y, s) in ((1.5, 1.5, "LIVING"), (8.0, 14.5, "BEDROOM"), (13.5, 4.0, "KITCHEN")):
        msp.add_text(s, height=0.25 * MM, dxfattribs={"layer": "TXT", "insert": P(x, y)})
    dim = msp.add_linear_dim(base=P(0, -1.2), p1=P(0, 0), p2=P(6, 0),
                             dxfattribs={"layer": "COLUMNS"})
    dim.render()

    doc.saveas(path)
    truth["boundary_area"] = (xs[-1] + EXT_T) * (ys[-1] + EXT_T)
    return truth


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample_arch.dxf"
    print(build(out))
