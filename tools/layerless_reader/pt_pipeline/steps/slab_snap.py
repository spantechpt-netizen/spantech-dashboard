"""حد البلاطة على وش الكمرة/الحيطة بالظبط (عشان الـ meshing).

الحد بعد الفاصل والتشطيب ممكن يفضل على 1–10 سم من وش الكمرة الطرفية (شق الفاصل 3 سم في HDB)، والشريحة دي
بتعمل عناصر مشوّهة في شبكة RAM. كل ضلع في الحد موازي لوش كمرة/حيطة (< 1°)، على بعد ≤ 10 سم، وماشي جنبه
≥ 0.5 م، بيتنقل على الوش (نفس `region_snap.snap_edges`).
القبول: مساحة البلاطة ماتتغيرش > 5%، وكل عمود/كمرة كان متغطي ≥ 98% يفضل متغطي. غير كده الحد بيفضل زي ما هو.
بيشتغل قبل `region_snap`، عشان المناطق والفتحات تتلزق على الحد الجديد.
usage: python slab_snap.py TAG...   ({tag}_res_c.json + {tag}_members_c.json)"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon
from shapely.ops import unary_union
from region_snap import ring, edges, snap_edges

TOL = float(os.environ.get("SLAB_SNAP_TOL", "0.10"))

for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    mem = [LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}) for b in M.get("beams", [])] + \
          [LR._wall_poly(w) for w in M.get("walls", [])]
    faces = edges([ring(list(g.exterior.coords)[:-1]) for g in mem if g.geom_type == "Polygon"])
    elems = [Polygon(c["rect"]["corners"]).buffer(0) for c in M.get("cols", [])] + [g for g in mem[:len(M.get("beams", []))]]
    pts = ring(R["slabs"][0]["outline"])
    old = Polygon(pts).buffer(0)
    OPS = unary_union([Polygon(o["poly"]).buffer(0) for o in R.get("openings", [])]) if R.get("openings") else Polygon()

    def covered(A, g):
        """متغطي ≥ 98%، أو الجزء البارز عمقه ≤ 5 سم (عمود أعرض من الكمرة الطرفية بسنتيمترات)."""
        if g.area <= 0: return True
        d = g.difference(A.union(OPS))
        return d.area <= 0.02 * g.area or d.buffer(-0.026).is_empty

    def good(new):
        return new.geom_type == "Polygon" and new.is_valid and abs(new.area - old.area) <= 0.05 * old.area and \
            all(covered(new, g) for g in elems if covered(old, g))
    # 1) ضلع ضلع: كل ضلع بيتنقل على الوش لو الفحص عدّى (مش الكل أو لا شيء)
    moved = 0
    n = len(pts)
    for i in range(n):
        a, b = pts[i % len(pts)], pts[(i + 1) % len(pts)]
        from shapely.geometry import LineString
        e = LineString([a, b])
        near = [f for f in faces if LineString(f).distance(e) <= TOL + 0.01]
        if not near:
            continue
        cand, m = snap_edges(pts, near, TOL)
        if m and good(Polygon(cand).buffer(0)):
            pts = ring(list(Polygon(cand).buffer(0).exterior.coords)[:-1]); moved += m
    # 2) سنّة أو شق عمقه ≤ 5 سم في الحد (عمود بارز 3 سم عن وش الكمرة الطرفية عند الفاصل): الحد بيتعدل على خط واحد
    P0 = Polygon(pts).buffer(0)
    P1 = P0.buffer(-0.05, join_style=2).buffer(0.05, join_style=2).buffer(0.05, join_style=2).buffer(-0.05, join_style=2)
    P1 = max(getattr(P1, "geoms", [P1]), key=lambda q: q.area) if not P1.is_empty else P1
    straightened = False
    if not P1.is_empty and P1.geom_type == "Polygon" and good(P1) and P1.symmetric_difference(P0).area > 1e-4:
        P0 = P1.simplify(0.002); straightened = True
    if not moved and not straightened:
        print(tag, "slab edge already on the member faces"); continue
    R["slabs"][0]["outline"] = [list(q) for q in list(P0.exterior.coords)[:-1]]
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, f"slab edge: {moved} edge move(s) onto beam/wall faces" + (", jogs <= 5 cm straightened" if straightened else "") +
          f", area {old.area:.1f} -> {P0.area:.1f}")
