"""اختلاف المناسيب في السقف (بدون ليّرات).

- تسميات المنسوب: رقم (+0.30 / -0.8 / EL. -10.50) جنبه كلمة دلالة (TOS / T.O.S /
  T.O.C / SSL / FFL / EL) - نص عادي أو attributes بلوك (حتى المتداخلة).
- لكل تسمية: أصغر منطقة مقفولة (من خطوط الرسمة) حواليها.
  * المنطقة كبيرة (> 40% من البلاطة) أو مفيش = دي البلاطة نفسها -> المنسوب الأساسي.
  * المنطقة صغيرة وقيمتها غير الأساسي -> "منطقة منسوب" SE = (قيمتها - الأساسي) بالمم.
- الناتج في {tag}_res_c.json: main_level_m و level_zones [{poly, level_m, se_mm}].
usage: python levels.py <clean.dxf> TAG...   (wins.json في نفس الفولدر)
"""
import json, math, re, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import ezdxf, slab_extractor as SX
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union, polygonize

KW = re.compile(r"^(T\.?O\.?S\.?|T\.?O\.?C\.?(\s*SLAB)?|SSL|FFL|EL\.?|LEVEL)$", re.I)
NUM = re.compile(r"^(?:EL\.?\s*)?([+\-]?\s*\d+(?:\.\d{1,3})?)\s*M?$", re.I)


def level_labels(doc, win, m=1.0):
    items = []                                   # (text, x, y, source)

    def add(t, x, y):
        if win[0] - m < x < win[2] + m and win[1] - m < y < win[3] + m:
            items.append((t.strip(), x, y))

    for e in SX._explode(list(doc.modelspace())):
        if e.dxftype() in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r:
                add(r[0], r[1][0], r[1][1])

    def walk(es, depth=0):
        for e in es:
            if e.dxftype() != "INSERT":
                continue
            p = e.dxf.insert
            for a in e.attribs:
                add(a.dxf.text, p.x, p.y)
            if depth < 4:
                try:
                    walk(list(e.virtual_entities()), depth + 1)
                except Exception:
                    pass
    walk(list(doc.modelspace().query("INSERT")))
    kws = [(x, y) for t, x, y in items if KW.match(t)]
    nums = []
    for t, x, y in items:
        mm = NUM.match(t.replace(" ", ""))
        if mm and ("." in t or t.strip().startswith(("+", "-"))):
            nums.append((float(mm.group(1).replace(" ", "")), x, y, t))
    out = []
    for v, x, y, t in nums:
        # "EL. -10.50" لوحده كفاية؛ غير كده لازم كلمة دلالة قريبة
        if t.upper().startswith("EL") or any(math.hypot(kx - x, ky - y) <= 1.5 for kx, ky in kws):
            out.append((v, x, y))
    return out


def run(dxf, tags):
    doc = ezdxf.readfile(dxf)
    W = json.load(open("wins.json"))
    for tag in tags:
        R = json.load(open(f"{tag}_res_c.json"))
        g = json.load(open(f"{tag}_geo.json"))["segs"]
        slab = Polygon(R["slabs"][0]["outline"])
        ops = unary_union([Polygon(o["poly"]) for o in R["openings"]]) if R["openings"] else Polygon()
        labs = level_labels(doc, W[tag])
        # خطوط حدود شرايح الصب (pour strips) مش حدود منسوب: بتتشال قبل القفل
        import os
        if os.environ.get("EXCL_POLYS"):
            ex = unary_union([Polygon(p).exterior for p in json.load(open(os.environ["EXCL_POLYS"]))]).buffer(0.05)
            g = [s for s in g if not ex.contains(LineString(s))]
        faces = [f for f in polygonize(unary_union([LineString(s) for s in g] + [slab.exterior])) if f.area > 0.5]
        free, cand = [], []
        # قطع البلاطة بين خطوط الرسمة، بعد قفل فجوات ≤ 0.8 م (خط حد المنسوب ممكن يبقى متقطع)
        import os
        gap = float(os.environ.get("LEVEL_GAP", "0"))
        if gap > 0:
            cut = slab.difference(unary_union([LineString(s) for s in g if LineString(s).length >= 2.0]).buffer(gap / 2, cap_style=2))
            pieces = [Polygon(q.exterior).buffer(gap / 2, join_style=2).intersection(slab) for q in getattr(cut, "geoms", [cut]) if q.area >= 2.0]
        for v, x, y in labs:
            p = Point(x, y)
            if not slab.buffer(0.5).contains(p):
                continue
            if gap > 0:
                fs = [q for q in pieces if q.buffer(0.3).contains(p)]
                f = min(fs, key=lambda q: q.area) if fs else None
                if f is None or f.area > 0.85 * slab.area: free.append((v, x, y))
                else: cand.append((v, f))
                continue
            # أصغر منطقة مقفولة ≥ 2 م² حوالين التسمية (إطار نص صغير مايتحسبش)
            fs = [Polygon(f.exterior) for f in faces if Polygon(f.exterior).area >= 2.0
                  and Polygon(f.exterior).buffer(0.05).contains(p)]
            f = min(fs, key=lambda q: q.area) if fs else None
            if f is None or f.area > 0.4 * slab.area:
                free.append((v, x, y))
            else:
                cand.append((v, f))
        main = None
        if gap > 0 and cand:
            # المنسوب الأساسي = اللي مناطقه أكبر مساحة
            area = {}
            for v in set(v for v, _ in cand): area[v] = unary_union([f for w, f in cand if w == v]).area
            main = max(area, key=area.get)
            covered = unary_union([f for _, f in cand])
            rest = slab.difference(covered)
            R["level_unlabelled_m2"] = round(rest.area, 1)
        # المنسوب الأساسي = اللي بيغطي أكبر مساحة: كل نقطة في البلاطة لأقرب تسمية "حرة"
        if main is None and free:
            x0, y0, x1, y1 = slab.bounds; cnt = {}
            nx = max(int((x1 - x0) / 1.0), 1); ny = max(int((y1 - y0) / 1.0), 1)
            for i in range(nx):
                for j in range(ny):
                    q = (x0 + (i + 0.5) * (x1 - x0) / nx, y0 + (j + 0.5) * (y1 - y0) / ny)
                    if not slab.contains(Point(q)):
                        continue
                    v = min(free, key=lambda t: math.hypot(t[1] - q[0], t[2] - q[1]))[0]
                    cnt[v] = cnt.get(v, 0) + 1
            main = max(cnt, key=cnt.get) if cnt else free[0][0]
        elif main is None and labs:
            main = max(set(v for v, _, _ in labs), key=[v for v, _, _ in labs].count)
        # تسميات حرة بقيمة غير الأساسي ومالهاش منطقة مقفولة = للمراجعة
        R["level_unresolved"] = sorted({v for v, _, _ in free if main is not None and abs(v - main) >= 0.02})
        zones = []
        if main is not None:
            for v, f in cand:
                if abs(v - main) < 0.02 or f.area < 2.0:
                    continue
                z = f.intersection(slab).difference(ops)
                z = max(getattr(z, "geoms", [z]), key=lambda q: q.area) if not z.is_empty else None
                if z is None or z.area < 2.0 or any(z.equals(q["_g"]) for q in zones):
                    continue
                zones.append({"_g": z, "poly": list(z.exterior.coords)[:-1], "level_m": v, "se_mm": round((v - main) * 1000)})
        R["main_level_m"] = main
        R["level_zones"] = [{k: q[k] for k in ("poly", "level_m", "se_mm")} for q in zones]
        json.dump(R, open(f"{tag}_res_c.json", "w"))
        print(tag, "main", main, "zones", [(q["level_m"], q["se_mm"], round(q["_g"].area, 1)) for q in zones], "unresolved", R["level_unresolved"],
              "labels", sorted(set(v for v, _, _ in labs)), "unlabelled m2", R.get("level_unlabelled_m2"))


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2:])
