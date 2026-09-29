"""مسقط الأحمال (LOADING PLANS) -> أحمال كل منطقة على الزون (SIDL وLL بالظبط زي الرسمة).

الرسمة فيها قسم بعنوان LOADING، وفي كل صف (دور) جدول:
    Load Pattern | SIDL (FC, Ceiling, Walls ...) | LL | Usage
كل صف في الجدول فيه عينة هاتش (نمط)، والمسقط جنبه مهاشر بنفس الأنماط.

الطريقة:
  1) الجدول: عناوين SIDL/SDL و LL و Usage و Pattern (نصوص). الصفوف = الأرقام تحت العناوين متجمعة بالـ y.
     SIDL = مجموع كل الأرقام اللي تحت عنوان SIDL ("-" = صفر)؛ LL = الرقم تحت LL؛ الاستخدام = النص تحت Usage؛
     النمط = الهاتش اللي في عمود Pattern على نفس الـ y (اسم النمط + اللون).
  2) مسقط الأحمال ↔ مسقط البلاطات: الإزاحة التقريبية = فرق مكان عنوانين القسمين، والدقيقة من مطابقة
     الأعمدة المهاشرة (أكتر إزاحة بتطابق أعمدة، ولازم ≥ 50% منها تتطابق).
  3) كل هاتش بنمط من الجدول في مسقط الأحمال -> مضلع (even-odd للحلقات) -> بيتزاح على الزون -> بيتقص على
     البلاطة ناقص الفتحات. الأصغر الأول والأكبر بيتقص منه (مافيش حملين على نفس الحتة).
  4) الجزء من البلاطة اللي مافيش عليه حمل من المسقط = REVIEW (بياخد الأحمال الافتراضية في البرنامج).
الناتج: R["load_areas"] = [{poly, sdl, ll, usage, pattern}] في {tag}_res_c.json.
usage: python loads_plan.py TAG...   (DXF=m.dxf)
"""
import collections, json, math, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import ezdxf, slab_extractor as SX, layerless_reader as LR
from ezdxf import bbox
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

NUM = re.compile(r"^\s*[+-]?\d+(?:\.\d+)?\s*$")
DASH = re.compile(r"^\s*[-–—]\s*$")
H_SDL = re.compile(r"\bS\.?I?\.?D\.?L\b|SUPER\s*IMPOSED", re.I)
H_LL = re.compile(r"^\s*L\.?\s*L\.?\b|\bLIVE\s*LOAD", re.I)
H_USE = re.compile(r"\bUSAGE\b|\bUSE\b|\bOCCUPANCY\b", re.I)
H_PAT = re.compile(r"PATTERN|HATCH|LEGEND", re.I)


def headers(texts):
    big = [t for t in texts if t[3] > 5 * sorted(q[3] for q in texts)[len(texts) // 2]]
    load = [t for t in big if re.search(r"\bLOADING\b", t[0], re.I) and len(t[0]) < 40]
    fram = [t for t in big if re.search(r"FRAM|SLAB PLAN|CEILING", t[0], re.I) and len(t[0]) < 40]
    return load, fram


def tables(texts, hatches):
    """كل جدول أحمال: [{"y", "sdl", "ll", "usage", "pattern"}] + مكانه."""
    out = []
    for sd in [t for t in texts if H_SDL.search(t[0])]:
        ll = min([t for t in texts if H_LL.search(t[0]) and abs(t[2] - sd[2]) < 3 and 0 < t[1] - sd[1] < 25],
                 key=lambda t: t[1] - sd[1], default=None)
        if ll is None:
            continue
        use = min([t for t in texts if H_USE.search(t[0]) and abs(t[2] - sd[2]) < 3 and 0 < t[1] - ll[1] < 25],
                  key=lambda t: t[1] - ll[1], default=None)
        pat = min([t for t in texts if H_PAT.search(t[0]) and abs(t[2] - sd[2]) < 3 and -25 < t[1] - sd[1] < 0],
                  key=lambda t: sd[1] - t[1], default=None)
        # حدود الأعمدة: SIDL من نص المسافة بين Pattern و SIDL لحد نص المسافة بين SIDL و LL (عرض SIDL ممكن يبقى أعمدة فرعية)
        x_pat = pat[1] if pat else sd[1] - 6
        x0 = (x_pat + sd[1]) / 2 if pat else sd[1] - 4
        x1 = ll[1] - 1.0
        x2 = (ll[1] + (use[1] if use else ll[1] + 6)) / 2
        body = [t for t in texts if t[2] < sd[2] - 1.0 and t[2] > sd[2] - 60 and x0 - 8 < t[1] < (use[1] + 10 if use else x2 + 8)]
        rows = []
        for t in sorted(body, key=lambda q: -q[2]):
            if rows and abs(rows[-1][0] - t[2]) < 1.0:
                rows[-1][1].append(t)
            else:
                rows.append([t[2], [t]])
        got = []
        for y, items in rows:
            nums = [t for t in items if NUM.match(t[0]) or DASH.match(t[0])]
            sdl_v = [float(t[0]) if NUM.match(t[0]) else 0.0 for t in nums if x0 <= t[1] < x1]
            ll_v = [float(t[0]) for t in nums if NUM.match(t[0]) and x1 <= t[1] < x2]
            words = [t for t in items if not (NUM.match(t[0]) or DASH.match(t[0])) and t[1] >= x2 - 2]
            if not ll_v or not sdl_v:
                continue
            # الهاتش في عمود Pattern على نفس الصف
            cand = [h for h in hatches if abs(h["y"] - y) < 1.8 and h["x"] < x0 + 1 and h["x"] > x_pat - 8]
            h = min(cand, key=lambda h: abs(h["y"] - y), default=None)
            got.append({"y": y, "sdl": round(sum(sdl_v), 3), "ll": ll_v[0],
                        "usage": " ".join(t[0].strip() for t in words) or "?",
                        "pattern": (h["name"], h["color"]) if h else None})
        if got:
            out.append({"x": sd[1], "y": sd[2], "rows": got})
    return out


def no_holes(g):
    """RAM بياخد حد خارجي بس: المضلع اللي فيه خرم بيتقسم لقطع من غير خرم."""
    if not g.interiors:
        return [g]
    from shapely.ops import split
    from shapely.geometry import LineString
    cx = g.interiors[0].centroid.x; y0, y1 = g.bounds[1] - 1, g.bounds[3] + 1
    out = []
    for q in split(g, LineString([(cx, y0), (cx, y1)])).geoms:
        if q.geom_type == "Polygon" and q.area > 1e-6:
            out += no_holes(q)
    return out


def hatch_polys(e):
    """مضلع الهاتش (even-odd بين الحلقات)."""
    rings = [r for r in LR.hatch_rings(e, 0.01) if len(r) >= 3]
    g = Polygon()
    for r in rings:
        p = Polygon(r).buffer(0)
        if not p.is_empty:
            g = g.symmetric_difference(p)
    return g


def main(tags, dxf):
    doc = ezdxf.readfile(dxf)
    ents = list(SX._explode(list(doc.modelspace())))
    texts = []
    for e in ents:
        if e.dxftype() in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r and r[0].strip():
                texts.append((r[0].strip(), r[1][0], r[1][1], r[2]))
    if not texts:
        print("no texts"); return
    load_h, fram_h = headers(texts)
    if not load_h:
        print("no LOADING section - loads come from the program's defaults"); return
    hatches = []
    cols = []
    for e in ents:
        if e.dxftype() != "HATCH":
            continue
        try:
            b = bbox.extents([e], fast=True)
        except Exception:
            continue
        if not b.has_data:
            continue
        hatches.append({"e": e, "name": e.dxf.pattern_name, "color": e.dxf.color, "x": b.center.x, "y": b.center.y,
                        "w": b.size.x, "h": b.size.y})
        if 0.15 <= min(b.size.x, b.size.y) and max(b.size.x, b.size.y) <= 2.5:
            cols.append((b.center.x, b.center.y))
    T = tables(texts, hatches)
    if not T:
        print("LOADING section found but no load table (SIDL / LL / Usage) - loads come from the defaults"); return
    dx0 = (fram_h[0][1] - load_h[0][1]) if fram_h else None
    # المرحلة 1: إزاحة كل زون من أعمدتها
    info = {}
    for tag in tags:
        R = json.load(open(f"{tag}_res_c.json"))
        R["review"] = [r for r in R.get("review", []) if r[0] != "loads"]      # إعادة التشغيل مابتكررش الملاحظات
        R.pop("load_areas", None)
        slab = Polygon(R["slabs"][0]["outline"]).buffer(0)
        x0, y0, x1, y1 = slab.bounds
        if dx0 is None:
            continue
        # الجدول بتاع الصف ده: نفس شريط الـ y، في قسم الأحمال
        cands = [t for t in T if y0 - 60 < t["y"] < y1 + 60 and abs(t["x"] - (x0 - dx0)) < 400]
        if not cands:
            print(tag, "no load table in this row"); continue
        tab = min(cands, key=lambda t: abs(t["y"] - (y0 + y1) / 2))
        F = [(x, y) for x, y in cols if slab.buffer(1).contains(Point(x, y))]
        L = [(x, y) for x, y in cols if x0 - dx0 - 20 < x < x1 - dx0 + 20 and y0 - 20 < y < y1 + 20]
        votes = collections.Counter()
        for lx, ly in L:
            for fx, fy in F:
                d = (round(fx - lx, 1), round(fy - ly, 1))
                if abs(d[0] - dx0) < 30 and abs(d[1]) < 30:
                    votes[d] += 1

        # كل إزاحة مرشحة بتتقيّم بعدد أعمدة البلاطة اللي ليها عمود في مسقط الأحمال على ≤ 25 سم (مش بالتقريب لـ 10 سم)
        def score(d, F=F, L=L):
            return sum(1 for fx, fy in F if any(abs(fx - lx - d[0]) <= 0.25 and abs(fy - ly - d[1]) <= 0.25 for lx, ly in L))
        best = max((d for d, _ in votes.most_common(8)), key=score) if votes else None
        n = score(best) if best else 0
        # مسقط الأحمال ممكن مايبينش كل الهاتشات الصغيرة (دروبات/علامات): النسبة من الأقل عددًا، وبحد أدنى 6 أعمدة
        strong = best is not None and n >= max(6, 0.4 * min(len(F), len(L)))
        info[tag] = dict(R=R, slab=slab, tab=tab, F=F, L=L, best=best, n=n, strong=strong, score=score, votes=votes)
    # المرحلة 2: إجماع الدور - كل مساقط الأحمال في نفس الدور مزاحة بنفس القيمة. الزون اللي مطابقتها ضعيفة
    # (أو محتارة بين إزاحتين، زي السطح: (400، 0) و(400، 24)) بتاخد إزاحة الدور لو أعمدتها بتأكدها
    cons = {}
    for tag, I in info.items():
        if I["strong"]:
            cons.setdefault(id(I["tab"]), collections.Counter())[(round(I["best"][0]), round(I["best"][1]))] += 1
    for tag, I in info.items():
        R, slab, tab, F, L = I["R"], I["slab"], I["tab"], I["F"], I["L"]
        ops = unary_union([Polygon(o["poly"]).buffer(0) for o in R.get("openings", [])]) if R.get("openings") else Polygon()
        x0, y0, x1, y1 = slab.bounds
        c = cons.get(id(tab))
        best, n = I["best"], I["n"]
        if c:
            cx, cy = c.most_common(1)[0][0]
            near = [d for d, _ in I["votes"].most_common(40) if abs(d[0] - cx) <= 0.3 and abs(d[1] - cy) <= 0.3]
            cb = max(near, key=I["score"]) if near else None
            cn = I["score"](cb) if cb else 0
            if cb and (not I["strong"] or (round(best[0]), round(best[1])) != (cx, cy)) and cn >= max(4, 0.25 * min(len(F), len(L))):
                best, n = cb, cn
            elif not I["strong"]:
                best = None
        elif not I["strong"]:
            best = None
        if best is None:
            print(tag, "alignment too weak", I["n"], len(F), len(L), I["votes"].most_common(3))
            R.setdefault("review", []).append(["loads", f"loading plan found but could not be aligned with this slab ({I['n']} of {len(F)} columns) - default loads used"])
            json.dump(R, open(f"{tag}_res_c.json", "w")); continue
        dx, dy = best
        pats = {r["pattern"]: r for r in tab["rows"] if r["pattern"]}
        areas = []
        for h in hatches:
            key = (h["name"], h["color"])
            if key not in pats and (h["name"], None) not in pats:
                key = next((k for k in pats if k[0] == h["name"]), None)
                if key is None:
                    continue
            if abs(h["y"] - tab["y"]) < 1.8 and abs(h["x"] - tab["x"]) < 30:
                continue                                       # عينة الجدول نفسها
            if not (x0 - dx - 5 < h["x"] < x1 - dx + 5 and y0 - dy - 5 < h["y"] < y1 - dy + 5):
                continue
            g = hatch_polys(h["e"])
            if g.is_empty:
                continue
            from shapely.affinity import translate
            g = translate(g, dx, dy).intersection(slab).difference(ops)
            if g.area < 0.5:
                continue
            r = pats[key]
            areas.append((g, r))
        # الأصغر الأول: المحل جوه الـ OUTER AREA بياخد حمله هو
        areas.sort(key=lambda q: q[0].area)
        taken = Polygon(); out = []
        for g, r in areas:
            g = g.difference(taken)
            for p0 in getattr(g, "geoms", [g]):
                if p0.geom_type != "Polygon" or p0.area < 0.5:
                    continue
                for p in no_holes(p0):
                    if p.area >= 0.5:
                        out.append({"poly": [list(c) for c in list(p.exterior.coords)[:-1]],
                                    "sdl": r["sdl"], "ll": r["ll"], "usage": r["usage"], "pattern": r["pattern"][0]})
            taken = taken.union(g)
        R["load_areas"] = out
        free = slab.difference(ops).difference(taken).area
        if out and free > 0.05 * slab.area:
            R.setdefault("review", []).append(["loads", f"{free:.0f} m² of the slab has no load from the loading plan - the program's default SDL/LL is used there"])
        json.dump(R, open(f"{tag}_res_c.json", "w"))
        by = collections.defaultdict(float)
        for a in out:
            by[(a["usage"], a["sdl"], a["ll"])] += Polygon(a["poly"]).area
        print(tag, f"shift ({dx:.1f}, {dy:.1f}) from {n} columns", {f"{k[0]} SDL {k[1]:g} LL {k[2]:g}": round(v) for k, v in by.items()},
              f"uncovered {free:.0f} m²")


if __name__ == "__main__":
    main(sys.argv[1:], os.environ.get("DXF", "m.dxf"))
