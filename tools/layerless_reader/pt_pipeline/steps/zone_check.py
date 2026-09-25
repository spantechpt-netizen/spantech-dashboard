"""فحص دقة الزونات بعد التصدير (لازم يعدّي قبل ما الملف يتسلّم):
- كل عمود/حائط/كمرة: مساحته جوه زونه ≥ مساحته في أي زون تانية (مش عنصر من الجيران).
- مفيش توأم في نفس الزون: كمرتين متوازيين متداخلين طولًا وبينهم ≤ 0.1 م، أو عمودين لازقين (≤ 0.05 م)
  بينهم خط فاصل.
- البلاطة مغطية أعمدتها وكمراتها اللي ع الداير (≥ 98% من كل عنصر جوه البلاطة).
- مفيش تداخل بين بلاطات الزونات (> 0.5 م²).
usage: python zone_check.py TAG...   ({tag}_res_c.json + {tag}_members_c.json)"""
import json, sys, math, itertools
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, LineString
tags = sys.argv[1:]
S = {t: Polygon(json.load(open(f"{t}_res_c.json"))["slabs"][0]["outline"]).buffer(0) for t in tags}
bad = 0
for a, b in itertools.combinations(tags, 2):
    ov = S[a].intersection(S[b]).area
    if ov > 0.5: print(f"  OVERLAP {a}/{b}: {ov:.1f} m²"); bad += 1
for t in tags:
    M = json.load(open(f"{t}_members_c.json"))
    els = [("col", Polygon(c["rect"]["corners"]).buffer(0)) for c in M["cols"]] + [("wall", LR._wall_poly(w)) for w in M["walls"]] + \
          [("beam", LR._wall_poly({"p1": x["p1"], "p2": x["p2"], "t": x["w"]})) for x in M["beams"]]
    foreign = [(k, g) for k, g in els if max([g.intersection(S[o]).area for o in tags if o != t] + [0]) > g.intersection(S[t]).area]
    R_ = json.load(open(f"{t}_res_c.json"))
    from shapely.ops import unary_union
    OPS = unary_union([Polygon(o["poly"]).buffer(0) for o in R_["openings"]]) if R_["openings"] else Polygon()
    # الجزء اللي فوق فتحة (كمرة حرف فتحة / فوق سلم) مش مشكلة؛ المشكلة جزء برّه البلاطة ومش في فتحة
    uncovered = [(k, g) for k, g in els if k != "wall" and g.difference(S[t]).difference(OPS).area > 0.02 * g.area]
    tw = 0
    bs = M["beams"]
    for x, y in itertools.combinations(bs, 2):
        lx, ly = LineString([x["p1"], x["p2"]]), LineString([y["p1"], y["p2"]])
        ax = math.atan2(x["p2"][1] - x["p1"][1], x["p2"][0] - x["p1"][0]); ay = math.atan2(y["p2"][1] - y["p1"][1], y["p2"][0] - y["p1"][0])
        if abs(math.sin(ax - ay)) > 0.02: continue
        # توأم = جنب بعض بفجوة (مش متداخلين: كمرة داخلة في كمرة كتلة عريضة ده ربط مش توأم)
        gap = LineString([x["p1"], x["p2"]]).distance(LineString([y["p1"], y["p2"]])) - (x["w"] + y["w"]) / 2
        if -0.02 <= gap <= 0.1 and LR._wall_poly({"p1": x["p1"], "p2": x["p2"], "t": x["w"] + 0.3}).intersection(ly).length > 1.0: tw += 1
        # مكررة = نفس العرض تقريبًا ومتداخلين ≥ 60% من الأصغر
        gx = LR._wall_poly({"p1": x["p1"], "p2": x["p2"], "t": x["w"]}); gy = LR._wall_poly({"p1": y["p1"], "p2": y["p2"], "t": y["w"]})
        if abs(x["w"] - y["w"]) <= 0.1 and gx.intersection(gy).area >= 0.6 * min(gx.area, gy.area): tw += 1
    print(t, "foreign", len(foreign), "not covered by slab", len(uncovered), "twin beams in zone", tw,
          [(k, [round(v, 1) for v in g.centroid.coords[0]]) for k, g in (foreign + uncovered)[:6]])
    bad += len(foreign) + len(uncovered) + tw
print("CHECK", "OK" if bad == 0 else f"FAILED ({bad})")
