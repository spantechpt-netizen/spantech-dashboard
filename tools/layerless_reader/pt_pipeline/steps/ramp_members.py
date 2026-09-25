"""كمرات المنحدر: المنحدر فتحة، فأي كمرة واقعة ≥ 70% جوه فتحة المنحدر (أو تسمية كمرة مالقتش
وشوش وواقعة جوه المنحدر) بتتنقل لـ ramp_beams وماتتحسبش ناقصة. بيشتغل بعد ramp_faces لأن
حد المنحدر النهائي بيتعرف هناك (members.py بيشتغل قبل ما المنحدر يتكشف من الخطوط المايلة).
usage: python ramp_members.py TAG..."""
import json, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

for t in sys.argv[1:]:
    R = json.load(open(f"{t}_res_c.json")); M = json.load(open(f"{t}_members_c.json"))
    rp = [Polygon(o["poly"]).buffer(0.3) for o in R["openings"] if o.get("kind") == "ramp"]
    if not rp: continue
    U = unary_union(rp); rb = M.setdefault("ramp_beams", []); moved = 0
    keep = []
    for b in M["beams"]:
        bp = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        if not b.get("review") and bp.area > 0 and bp.intersection(U).area >= 0.7 * bp.area: rb.append(b); moved += 1
        else: keep.append(b)
    M["beams"] = keep
    pts = M.get("miss_pts", []); miss = M.get("miss", [])
    if len(pts) == len(miss):
        k2, m2 = [], []
        for p, m in zip(pts, miss):
            if U.contains(Point(p[4], p[5])):
                rb.append({"label": p[0], "mark": p[1], "w": p[2], "d": p[3], "p1": p[4:6], "p2": p[4:6], "label_only": True}); moved += 1
            else: k2.append(p); m2.append(m)
        M["miss_pts"], M["miss"] = k2, m2
    json.dump(M, open(f"{t}_members_c.json", "w"))
    print(f"{t}: {moved} beams/labels inside ramp -> ramp_beams")
