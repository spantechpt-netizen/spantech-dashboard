"""فراغات معلّمة بـ X كبير (فناء/ذبل/فاصل بين بلوكين): قطرين طوال بيتقاطعوا عند نصهم.
الفراغ = الشكل الرباعي بين أطراف القطرين. البلاطة = الحد الخارجي ناقص الفراغات، وكل حتة
منفصلة = بلاطة لوحدها. أي مساحة متهاشرة مكتوب عليها STEEL / BRIDGE = مش خرسانة -> فراغ برضه.
usage: python xvoids.py TAG   ({tag}_res.json + {tag}_geo.json + hatch.pkl + cache.pkl)"""
import json, math, sys, pickle, re
from shapely.geometry import LineString, Polygon, Point, MultiPoint
from shapely.ops import unary_union
tag = sys.argv[1]
R = json.load(open(f"{tag}_res.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
_, tx, hs = pickle.load(open("cache.pkl", "rb"))
L = [s for s in g if math.dist(*s) >= 3.0]
voids = []
for i, a in enumerate(L):
    la = LineString(a)
    for b in L[i + 1:]:
        lb = LineString(b)
        x = la.intersection(lb)
        if x.is_empty or x.geom_type != "Point": continue
        ta = la.project(x) / la.length; tb = lb.project(x) / lb.length
        if not (0.35 <= ta <= 0.65 and 0.35 <= tb <= 0.65): continue
        ang = abs(math.degrees(math.atan2(a[1][1] - a[0][1], a[1][0] - a[0][0])) - math.degrees(math.atan2(b[1][1] - b[0][1], b[1][0] - b[0][0]))) % 180
        if min(ang, 180 - ang) < 8: continue
        q = MultiPoint([a[0], a[1], b[0], b[1]]).convex_hull
        if q.area < 6.0 or abs(la.length - lb.length) > 0.15 * max(la.length, lb.length): continue
        voids.append(q)
# مساحة متهاشرة عليها STEEL/BRIDGE
steel = [Point(p) for t, p, h in tx if re.search(r"STEEL|BRIDGE", t, re.I)]
for r, pat in hs:
    if len(r) < 3: continue
    p = Polygon(r).buffer(0)
    if p.area >= 6 and any(p.buffer(0.5).contains(s) for s in steel): voids.append(p)
V = unary_union(voids)
slab0 = Polygon(R["slabs"][0]["outline"])
env = unary_union([slab0, V]).buffer(0.3, join_style=2).buffer(-0.3, join_style=2)
rest = env.difference(V.buffer(0.02)).buffer(-0.4, join_style=2).buffer(0.4, join_style=2)   # شيل شرايح رفيعة على حرف الفراغ
parts = sorted([p for p in getattr(rest, "geoms", [rest]) if p.area >= 20], key=lambda p: (-p.area))
print("x voids", len(voids), "void area", round(V.area), "slab parts", [round(p.area) for p in parts])
json.dump({"voids": [list(Polygon(v.exterior).exterior.coords) for v in getattr(V, "geoms", [V])],
           "parts": [list(p.exterior.coords) for p in parts]}, open(f"{tag}_xvoids.json", "w"))
