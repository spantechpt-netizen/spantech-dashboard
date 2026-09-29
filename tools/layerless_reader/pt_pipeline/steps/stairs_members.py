"""سلم عليه تسليحه (≥ 6 نصوص تسليح في دايرة 2.5 م) ومالقاش وش مقفول بالخطوط: المنطقة = الخلية
اللي فيها مركز العنقود بعد ما البلاطة تتقطع بالكمرات والحوائط والأعمدة (من {tag}_members_c)،
لو مساحتها 6-60 م². السلم فتحة.  usage: python stairs_members.py TAG...  (cache.pkl)"""
import json, sys, pickle, re
from shapely.geometry import Polygon, Point, MultiPoint
from shapely.ops import unary_union
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
_, tx, _ = pickle.load(open("cache.pkl", "rb"))
RB = re.compile(r"%%C\s*\d+\s*/\s*M|\bT\s*\d+\s*@|\d+\s*T\s*\d+\s*/\s*m", re.I)
for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    slab = Polygon(R["slabs"][0]["outline"])
    ops = [Polygon(o["poly"]).buffer(0) for o in R["openings"]]
    pts = [Point(p) for t, p, h in tx if RB.search(t) and slab.contains(Point(p))]
    U = unary_union([p.buffer(2.5) for p in pts]) if pts else Polygon()
    sup = unary_union([LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}) for b in M["beams"]] +
                      [LR._wall_poly(w) for w in M["walls"]] + [Polygon(c["rect"]["corners"]) for c in M["cols"]])
    cells = slab.difference(sup.buffer(0.02))
    cells = [c for c in getattr(cells, "geoms", [cells])]
    n = 0
    for cl in getattr(U, "geoms", [U]):
        inside = [p for p in pts if cl.contains(p)]
        if len(inside) < 6: continue
        c = MultiPoint(inside).centroid
        fs = [q for q in cells if q.buffer(0.3).contains(c) and 6 <= q.area <= 60]
        if not fs:
            # الخلية مفتوحة (ضلع رابع = حرف البلاطة بفجوة): المستطيل بين أقرب كمرة/حائط/حرف في الـ 4 اتجاهات
            import math as _m
            from shapely.geometry import LineString as _LS
            obst = sup.union(slab.exterior.buffer(0.001))
            # اتجاه السلم = اتجاه أطول كمرة قريبة (عشان المستطيل يبقى على محاور الكمرات)
            near = sorted(M["beams"], key=lambda b: _LS([b["p1"], b["p2"]]).distance(c))[:4]
            a0 = _m.atan2(near[0]["p2"][1] - near[0]["p1"][1], near[0]["p2"][0] - near[0]["p1"][0]) if near else 0.0
            u = (_m.cos(a0), _m.sin(a0)); v = (-u[1], u[0]); lim = []
            for d in (u, (-u[0], -u[1]), v, (-v[0], -v[1])):
                ray = _LS([(c.x, c.y), (c.x + d[0] * 8, c.y + d[1] * 8)]); h = ray.intersection(obst)
                lim.append(Point(c).distance(h) if not h.is_empty else None)
            if None in lim: continue
            P = lambda s_, t_: (c.x + u[0] * s_ + v[0] * t_, c.y + u[1] * s_ + v[1] * t_)
            q = Polygon([P(-lim[1], -lim[3]), P(lim[0], -lim[3]), P(lim[0], lim[2]), P(-lim[1], lim[2])]).intersection(slab)
            if not (6 <= q.area <= 60): continue
            fs = [q]
        # فتحة السلم = الخلية كلها بين الكمرات/الحوائط اللي حواليه (على وشوشهم الداخلية)،
        # وبتحل محل أي فتحة سلم/جزء اتعرف قبل كده جوه نفس الخلية
        f = min(fs, key=lambda q: q.area)
        # شرايح رفيعة (≤ 25 سم) لازقة في الخلية على الحرف مش جزء من السلم
        f2 = f.buffer(-0.12, join_style=2).buffer(0.12, join_style=2)
        f = max(getattr(f2, "geoms", [f2]), key=lambda z: z.area) if not f2.is_empty else f
        R["openings"] = [o for o in R["openings"] if not (o.get("kind") in ("stair", "X", "X*", "core") and
                         Polygon(o["poly"]).buffer(0).intersection(f).area >= 0.5 * Polygon(o["poly"]).buffer(0).area)]
        R["openings"].append({"poly": list(Polygon(f.exterior).exterior.coords)[:-1], "kind": "stair", "status": "ok", "src": "stair cell between beams/walls"})
        n += 1
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, "extra stairs", n)
