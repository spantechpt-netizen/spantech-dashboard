"""سلالم مرسوم عليها تسليحها (بلاطة البوست تنشن نفسها مالهاش نصوص تسليح): عنقود ≥ 6 نصوص
تسليح (Ø../M ، T..@) في دايرة 2.5 م = سلم. المنطقة = أصغر وش مقفول (خطوط ≥ 2 م) حوالين مركز
العنقود مساحته 8-60 م². السلم فتحة (قاعدة المكتب) - وبعدين core.py بيضمه للكور اللي جنبه.
usage: python stairs_rebar.py TAG   (cache.pkl)"""
import json, sys, pickle, re, math
from shapely.geometry import LineString, Polygon, Point, MultiPoint
from shapely.ops import unary_union, polygonize
tag = sys.argv[1]
R = json.load(open(f"{tag}_res.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
slab = Polygon(R["slabs"][0]["outline"])
_, tx, _ = pickle.load(open("cache.pkl", "rb"))
RB = re.compile(r"%%C\s*\d+\s*/\s*M|\bT\s*\d+\s*@|\d+\s*T\s*\d+\s*/\s*m", re.I)
pts = [Point(p) for t, p, h in tx if RB.search(t) and slab.contains(Point(p))]
U = unary_union([p.buffer(2.5) for p in pts]) if pts else Polygon()
n = 0
for cl in getattr(U, "geoms", [U]):
    inside = [p for p in pts if cl.contains(p)]
    if len(inside) < 6: continue
    c = MultiPoint(inside).centroid
    loc = [LineString(s) for s in g if math.dist(*s) >= 2.0 and LineString(s).distance(c) < 12]
    fs = [Polygon(f.exterior) for f in polygonize(unary_union(loc)) if 8 <= f.area <= 60 and Polygon(f.exterior).buffer(0.3).contains(c)]
    if not fs: continue
    f = min(fs, key=lambda q: q.area)
    R["openings"] = [o for o in R["openings"] if not f.buffer(0.1).contains(Polygon(o["poly"]).representative_point())]
    R["openings"].append({"poly": list(f.exterior.coords)[:-1], "kind": "stair", "status": "ok", "src": "rebar-annotated"})
    n += 1
json.dump(R, open(f"{tag}_res.json", "w"))
print(tag, "stairs from rebar notes", n)
