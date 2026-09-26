# -*- coding: utf-8 -*-
"""
مسقط إنشائي صناعي للاختبار (مم، كل حاجة على ليّر 0 عشان الأسماء ماتفرقش):
شبكة 3×2 بحور 6 م بفقاعات محاور، أعمدة 400×400 معبّاة، كمرات 300 على كل
المحاور بتسمية B1(300X700)، فتحة X 2×2 في بحر، عنوان، وملاحظة سُمك.
الحقيقة المعروفة بترجع مع الملف.

    python make_struct_sample.py out.dxf
"""
import sys

import ezdxf

BAY = 6000.0
NX, NY = 4, 3                 # محاور A-D و 1-3
COL = 400.0
BW = 300.0


def build(path, origin=(0.0, 0.0)):
    ox, oy = origin
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    xs = [ox + i * BAY for i in range(NX)]
    ys = [oy + j * BAY for j in range(NY)]

    def rect(x0, y0, x1, y1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)

    # محاور + فقاعات
    for i, x in enumerate(xs):
        msp.add_line((x, ys[0] - 3000), (x, ys[-1] + 3000), dxfattribs={"linetype": "CENTER"})
        for yb in (ys[0] - 3500, ys[-1] + 3500):
            msp.add_circle((x, yb), 500)
            msp.add_text("ABCD"[i], dxfattribs={"height": 400, "insert": (x - 130, yb - 200)})
    for j, y in enumerate(ys):
        msp.add_line((xs[0] - 3000, y), (xs[-1] + 3000, y), dxfattribs={"linetype": "CENTER"})
        for xb in (xs[0] - 3500, xs[-1] + 3500):
            msp.add_circle((xb, y), 500)
            msp.add_text(str(j + 1), dxfattribs={"height": 400, "insert": (xb - 100, y - 200)})

    # أعمدة معبّاة
    h = COL / 2
    for x in xs:
        for y in ys:
            rect(x - h, y - h, x + h, y + h)
            hat = msp.add_hatch()
            hat.paths.add_polyline_path([(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)], is_closed=True)

    # كمرات: وشّين بين وشوش الأعمدة، والكمرات الطرفية وشها الخارجي = حد البلاطة
    b = BW / 2
    beams = 0
    for y in ys:
        for x0, x1 in zip(xs, xs[1:]):
            msp.add_line((x0 + h, y - b), (x1 - h, y - b)); msp.add_line((x0 + h, y + b), (x1 - h, y + b))
            msp.add_text("B1(300X700)", dxfattribs={"height": 200, "insert": ((x0 + x1) / 2 - 700, y + b + 80)})
            beams += 1
    for x in xs:
        for y0, y1 in zip(ys, ys[1:]):
            msp.add_line((x - b, y0 + h), (x - b, y1 - h)); msp.add_line((x + b, y0 + h), (x + b, y1 - h))
            msp.add_text("B1(300X700)", dxfattribs={"height": 200, "rotation": 90,
                                                   "insert": (x - b - 80, (y0 + y1) / 2 - 700)})
            beams += 1

    # حد البلاطة على الوش الخارجي للكمرات الطرفية (وأوسع شوية عند الأعمدة)
    e = max(h, b)
    rect(xs[0] - e, ys[0] - e, xs[-1] + e, ys[-1] + e)

    # فتحة X 2×2 في نص البحر A-B / 1-2
    cx, cy = (xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2
    rect(cx - 1000, cy - 1000, cx + 1000, cy + 1000)
    msp.add_line((cx - 1000, cy - 1000), (cx + 1000, cy + 1000))
    msp.add_line((cx - 1000, cy + 1000), (cx + 1000, cy - 1000))

    # عنوان وسُمك
    msp.add_text("TYPICAL FLOOR SLAB PLAN", dxfattribs={"height": 500, "insert": (xs[0], ys[0] - 6000)})
    msp.add_text("SLAB THICKNESS t=250 mm", dxfattribs={"height": 250, "insert": (xs[1] + 1000, ys[1] + 2500)})

    doc.saveas(path)
    #  17 بحر، بس الكمرة على كل محور متصلة فوق الأعمدة (نفس العلامة والمقاس) = 7 كمرات
    return {"columns": NX * NY, "beams": NX + NY, "spans": beams, "openings": 1,
            "area": (xs[-1] - xs[0] + 2 * e) * (ys[-1] - ys[0] + 2 * e) / 1e6 - 4.0,
            "thickness": 250}


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "struct_sample.dxf"))


def build_flat(path, drop_note=True):
    """
    بلاطة مسطحة (flat slab) من غير كمرات: شبكة 4×3 أعمدة 500×500، دروب مرسوم مستطيل
    عادي 2.4×2.4 حوالين كل عمود (من غير تقطيع)، وملاحظة سُمك واحدة "400mm THK" لو drop_note،
    وعمود زيادة 400×400 مكتوب جنبه "Planted Column".
    """
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    xs = [i * BAY for i in range(NX)]
    ys = [j * BAY for j in range(NY)]

    def rect(x0, y0, x1, y1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)

    for i, x in enumerate(xs):
        msp.add_line((x, ys[0] - 3000), (x, ys[-1] + 3000), dxfattribs={"linetype": "CENTER"})
        for yb in (ys[0] - 3500, ys[-1] + 3500):
            msp.add_circle((x, yb), 500)
            msp.add_text("ABCD"[i], dxfattribs={"height": 400, "insert": (x - 130, yb - 200)})
    for j, y in enumerate(ys):
        msp.add_line((xs[0] - 3000, y), (xs[-1] + 3000, y), dxfattribs={"linetype": "CENTER"})
        for xb in (xs[0] - 3500, xs[-1] + 3500):
            msp.add_circle((xb, y), 500)
            msp.add_text(str(j + 1), dxfattribs={"height": 400, "insert": (xb - 100, y - 200)})

    def col(x, y, h):
        rect(x - h, y - h, x + h, y + h)
        hat = msp.add_hatch()
        hat.paths.add_polyline_path([(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)], is_closed=True)

    for x in xs:
        for y in ys:
            col(x, y, 250)
            rect(x - 1200, y - 1200, x + 1200, y + 1200)            # الدروب: مستطيل عادي
    if drop_note:
        msp.add_text("400mm THK.", dxfattribs={"height": 150, "insert": (xs[1] - 1000, ys[1] + 700)})
    px, py = (xs[1] + xs[2]) / 2, (ys[0] + ys[1]) / 2
    col(px, py, 200)
    msp.add_text("Planted Column", dxfattribs={"height": 200, "insert": (px + 500, py + 100)})
    rect(xs[0] - 1500, ys[0] - 1500, xs[-1] + 1500, ys[-1] + 1500)
    msp.add_text("TYPICAL FLOOR SLAB PLAN", dxfattribs={"height": 500, "insert": (xs[0], ys[0] - 6000)})
    msp.add_text("SLAB THICKNESS t=250 mm", dxfattribs={"height": 250, "insert": (xs[1] + 1500, ys[1] - 2500)})
    doc.saveas(path)
    return {"columns": NX * NY, "planted": 1, "drops": NX * NY, "drop_t": 400 if drop_note else None}


def build_sections(path, frame=True):
    """
    رسمة مقسومة أقسام بعناوين كبيرة (زي HDB): تحت كل قسم عنوان "FRAMING PLANS" / "LOADING PLANS"
    ارتفاعه أضعاف أي كتابة تانية، وفي قسم البلاطات صفين (دورين)، كل صف فيه مبنيين منفصلين
    (بينهم 12 م). من غير عناوين مساقط، فالتجميع العادي مابيلاقيش شيتات.
    الحقيقة: 4 زونات (دورين × مبنيين)، كل زون 3×3 أعمدة 400×400.
    """
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    def rect(x0, y0, x1, y1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)

    def building(ox, oy):
        for i in range(3):
            for j in range(3):
                x, y = ox + i * BAY, oy + j * BAY
                h = COL / 2
                rect(x - h, y - h, x + h, y + h)
                hat = msp.add_hatch()
                hat.paths.add_polyline_path([(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)], is_closed=True)
                msp.add_text("C1", dxfattribs={"height": 200, "insert": (x + 300, y + 300)})
        rect(ox - 1000, oy - 1000, ox + 2 * BAY + 1000, oy + 2 * BAY + 1000)
        msp.add_text("SLAB THICKNESS t=250 mm", dxfattribs={"height": 200, "insert": (ox + 1500, oy + 2500)})

    W = 2 * BAY + 2000                     # عرض المبنى 14 م
    for row in range(2):
        oy = row * 40000.0
        for k in range(2):
            building(k * (W + 12000.0), oy)
        # قسم الأحمال (نفس المباني من غير سُمك) بعيد 150 م
        for k in range(2):
            ox = 150000.0 + k * (W + 12000.0)
            for i in range(3):
                for j in range(3):
                    x, y = ox + i * BAY, oy + j * BAY
                    rect(x - 200, y - 200, x + 200, y + 200)
    if frame:
        # الدور الأول: خطوط محاور بتوصل المبنيين وبتقفل الفراغ اللي بينهم (زي أرضي HDB) - لازم يتقسم زي التاني
        msp.add_line((2 * BAY + 1000, 0), (W + 12000 - 1000, 0))
        msp.add_line((2 * BAY + 1000, 2 * BAY), (W + 12000 - 1000, 2 * BAY))
    msp.add_text("FRAMING PLANS", dxfattribs={"height": 6000, "insert": (-5000, -20000)})
    msp.add_text("LOADING PLANS", dxfattribs={"height": 6000, "insert": (145000, -20000)})
    doc.saveas(path)
    return {"zones": 4, "columns": 9}
