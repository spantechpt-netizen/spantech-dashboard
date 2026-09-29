"""حد فتحة المنحدر: البلاطة بتتقطع بالحوائط والكمرات (المنحنية كقطع مستقيمة) والأعمدة والخطوط
المستقيمة الطويلة الأفقية/الرأسية (≥ 2.5 م: خط نهاية المنحدر مثلًا). الخلايا اللي ≥ 50% منها جوه
نطاق المنحدر (من الخطوط المايلة) بتتضم (الخط اللي بينهم بيتقفل)، فالحد بيمشي على وش الحيطة
وعلى قطع الكمرة/الحيطة المنحنية ونهاية المنحدر المرسومة - من غير انحرافات.
usage: python ramp_faces.py TAG..."""
import json, sys, math
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union


BASE = 0.0     # اتجاه شبكة المسقط (بيتحسب لكل زون)


def axis(a, b):
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 90
    return any(min(abs(ang - p) % 90, 90 - abs(ang - p) % 90) < 2 for p in (BASE if isinstance(BASE, list) else [BASE]))


for t in sys.argv[1:]:
    R = json.load(open(f"{t}_res_c.json")); M = json.load(open(f"{t}_members_c.json")); g = json.load(open(f"{t}_geo.json"))["segs"]
    old = [Polygon(o["poly"]).buffer(0) for o in R["openings"] if o.get("kind") == "ramp"]
    if not old: continue
    hist = {}
    for a, b in g:
        L = math.dist(a, b)
        if L >= 1.0:
            k = round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 90); hist[k] = hist.get(k, 0) + L
    import collections as _C
    cnt = _C.Counter()
    for c in M["cols"]:
        if not c.get("round"): cnt[round(c["rect"].get("angle_deg", 0)) % 90] += 1
    for w in M["walls"]:
        cnt[round(math.degrees(math.atan2(w["p2"][1] - w["p1"][1], w["p2"][0] - w["p1"][0]))) % 90] += 1
    BASE = [k for k, v in cnt.items() if v >= 3]
    if not BASE:
        mx = max(hist.values()) if hist else 0
        BASE = [k for k, v in hist.items() if v >= 0.35 * mx] or [0.0]
    slab = Polygon(R["slabs"][0]["outline"])
    OLD = unary_union(old)
    # الكمرات اللي أغلبها جوه نطاق المنحدر (حروف بلاطة المنحدر اتقرت كمرات) مش حدود - الحدود كمرات برّاه
    def _cut(b):
        if not b.get("w") or b["p1"] == b["p2"]: return False
        if not str(b.get("label", "")).startswith("unlabelled"): return True     # كمرة متسمية = حد حقيقي للمنحدر
        g_ = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        return g_.intersection(OLD).area < 0.5 * g_.area
    sup = unary_union([LR._wall_poly(w) for w in M["walls"]] + [Polygon(c["rect"]["corners"]) for c in M["cols"]] +
                      [LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}) for b in M["beams"] + M.get("ramp_beams", []) if _cut(b)])
    lines = unary_union([LineString(s) for s in g if math.dist(*s) >= 2.5 and axis(*s) and OLD.buffer(1.0).intersects(LineString(s))])
    OLDB = OLD.buffer(0.3)
    # فتحة صغيرة جوه نطاق المنحدر (مثلث من تقاطع خطوط الدهان اتقرا X) = جزء من المنحدر
    inner = [o for o in R["openings"] if o.get("kind") != "ramp" and Polygon(o["poly"]).buffer(0).intersection(OLDB).area >= 0.3 * Polygon(o["poly"]).buffer(0).area]
    R["openings"] = [o for o in R["openings"] if o not in inner]
    OLD = unary_union([OLD] + [Polygon(o["poly"]).buffer(0) for o in inner])
    others = unary_union([Polygon(o["poly"]) for o in R["openings"] if o.get("kind") != "ramp"])
    cells = slab.difference(sup).difference(lines.buffer(0.01)).difference(others)
    cells = [c for c in getattr(cells, "geoms", [cells]) if c.geom_type == "Polygon" and c.area >= 0.05]
    pick = [c for c in cells if c.intersection(OLD).area >= 0.5 * c.area]
    U = unary_union([c.buffer(0.06, join_style=2) for c in pick]).buffer(-0.06, join_style=2)   # يقفل شق الخطوط (الحيطة ≥ 0.2 مابتتقفلش)
    new = []
    for rp in old:
        parts = [p for p in getattr(U, "geoms", [U]) if p.geom_type == "Polygon" and p.intersection(rp).area >= 0.3 * p.area and p.area >= 5]
        if not parts: new.append(rp); continue
        # كل حتت المنحدر (مش الأكبر بس): الحتت المتجاورة بتتضم (فجوة ≤ 0.5 م = كمرة/خط بينهم)
        q = unary_union([p.buffer(0.25, join_style=2) for p in parts]).buffer(-0.25, join_style=2)
        q = max(getattr(q, "geoms", [q]), key=lambda z: z.area)
        new.append(Polygon(q.exterior).simplify(0.02))
    R["openings"] = [o for o in R["openings"] if o.get("kind") != "ramp"] + \
        [{"poly": list(q.exterior.coords)[:-1], "kind": "ramp", "status": "ok", "src": "cells between walls/beams/lines"} for q in new]
    json.dump(R, open(f"{t}_res_c.json", "w"))
    print(t, "cells", len(pick), "ramps (old -> new m², vertices)", [(round(o.area, 1), round(q.area, 1), len(q.exterior.coords)) for o, q in zip(old, new)])
