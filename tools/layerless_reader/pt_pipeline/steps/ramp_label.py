"""منحدر مكتوب عليه RAMP (بدون ليّرات).
- الوشوش المقفولة بخطوط ≥ 2 م؛ البداية الوش اللي فيه النص.
- بيكبر للوشوش المجاورة (ضلع مشترك ≥ 1.5 م) اللي فيها دهان المنحدر: ≥ 3 خطوط قصيرة مايلة
  15-80° عن اتجاه المنحدر (شيفرونات).
- حتتين نفس المنحدر مقسومين بشريحة صب (≤ 1.2 م) بيتضموا.
المنحدر = فتحة (قاعدة المكتب).  usage: python ramp_label.py TAG...  (cache.pkl فيه النصوص)"""
import json, sys, pickle, math, re
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
_, tx, _ = pickle.load(open("cache.pkl", "rb"))
for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
    R["openings"] = [o for o in R["openings"] if o.get("kind") != "ramp"]
    slab = Polygon(R["slabs"][0]["outline"])
    pts = [Point(p) for t, p, h in tx if re.search(r"\bRAMP\b", t, re.I) and slab.contains(Point(p))]
    got = []
    for P in pts:
        loc = [s for s in g if LineString(s).distance(P) < 40]
        faces = [Polygon(f.exterior) for f in polygonize(unary_union([LineString(s) for s in loc if math.dist(*s) >= 3.5])) if f.area >= 1.0]
        seed = [f for f in faces if f.contains(P)]
        if not seed: continue
        # اتجاه المنحدر = اتجاه أطول ضلع في الوش
        f0 = seed[0]; c = list(f0.minimum_rotated_rectangle.exterior.coords)
        e = max(zip(c, c[1:]), key=lambda q: math.dist(*q)); ax = math.degrees(math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0])) % 180
        shorts = [LineString(s) for s in loc if 0.3 <= math.dist(*s) < 3.5 and
                  15 <= min(abs((math.degrees(math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])) % 180) - ax),
                            180 - abs((math.degrees(math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])) % 180) - ax)) <= 80]
        tree = STRtree(shorts)
        painted = lambda f: sum(1 for k in tree.query(f) if f.buffer(-0.05).contains(shorts[int(k)].centroid)) >= 3
        reg = [f0]; grew = True
        while grew:
            grew = False
            U = unary_union(reg)
            for f in faces:
                if any(f.equals(r) for r in reg): continue
                if f.buffer(0.02).intersection(U.boundary).length >= 1.5 and painted(f):
                    reg.append(f); grew = True
        got.append(unary_union(reg)); print("  seed", round(f0.area,1), "ax", round(ax), "shorts", len(shorts), "region", len(reg), round(got[-1].area,1))
    if got:
        U = unary_union([f.buffer(0.65, join_style=2) for f in got]).buffer(-0.65, join_style=2)
        got = [Polygon(u.exterior) for u in getattr(U, "geoms", [U]) if u.area >= 15]
        # منحدر أكبر من ربع البلاطة = النمو فلت (خطوط مايلة في كل حتة) - مرفوض، والمنحدر بيتقري من الخطوط المايلة
        big = [q for q in got if q.area > 0.25 * slab.area]
        if big: print(tag, "RAMP region too large - rejected", [round(q.area) for q in big])
        got = [q for q in got if q.area <= 0.25 * slab.area]
    R["openings"] = [o for o in R["openings"] if not any(q.contains(Polygon(o["poly"]).representative_point()) for q in got)]
    for f in got:
        R["openings"].append({"poly": list(f.simplify(0.02).exterior.coords)[:-1], "kind": "ramp", "status": "ok"})
    json.dump(R, open(f"{tag}_res.json", "w"))
    print(tag, "RAMP labels", len(pts), "ramps", [round(f.area, 1) for f in got])
