"""الكور (مصاعد + سلالم + اللوبي اللي بينهم) = فتحة واحدة (قاعدة المكتب).

من غير ليّرات: الحوائط = هاتشات الركائز (أي نمط غير المستبعد). الأماكن المقفولة بالحوائط
(بعد قفل فتحات الأبواب ≤ 1.2 م) هي "جيوب". الجيب اللي فيه فتحة مصعد/سلم/شفت (من res)
بيبقى جزء من الكور؛ الجيوب المتجاورة (بينها حائط داخلي) بتتضم لفتحة واحدة. حوائط الكور
الخارجية بتفضل ركائز على حرف الفتحة، والداخلية (جوه الفتحة) بتتشال.
usage: python core.py TAG...   (env HATCH_PKL = hatch rings {pattern:[rings]}, EXCL="GOST_WOOD ANSI31")
"""
import json, sys, os, pickle
from shapely.geometry import Polygon
from shapely.ops import unary_union

EXCL = set(os.environ.get("EXCL", "").split())
_, H = pickle.load(open(os.environ.get("HATCH_PKL", "hatch.pkl"), "rb"))


SUF = os.environ.get("RES_SUFFIX", "")


def run(tag):
    R = json.load(open(f"{tag}_res{SUF}.json"))
    slab = Polygon(R["slabs"][0]["outline"])
    walls = unary_union([Polygon(r).buffer(0) for p, rs in H.items() if p not in EXCL for r in rs
                         if len(r) >= 3 and slab.buffer(1).contains(Polygon(r).representative_point())])
    closed = walls.buffer(0.6, join_style=2).buffer(-0.6, join_style=2)
    holes = []
    for g in getattr(closed, "geoms", [closed]):
        for ring in g.interiors:
            h = Polygon(ring)
            if 1.0 <= h.area <= 200: holes.append(h)
    ops = [(Polygon(o["poly"]).buffer(0), o) for o in R["openings"]]
    seeds = [h for h in holes if any(h.buffer(0.1).contains(op.representative_point()) and op.area >= 1.0 and o["kind"] in ("stair", "X", "lift", "lift?", "X*")
                                     for op, o in ops)]
    # مصعد/سلم مش مقفول بالحوائط (باب المصعد مفتوح على اللوبي): الفتحة نفسها لو محاطة بحوائط
    # على ≥ 50% من محيطها
    wb = walls.buffer(0.6)
    for op, o in ops:
        if o["kind"] in ("stair", "X", "lift", "lift?", "X*") and op.area >= 2.0 and \
                op.exterior.intersection(wb).length >= 0.5 * op.exterior.length:
            seeds.append(op)
    # بير مصعد من غير X: جيب محاط بحوائط على ≥ 70% من محيطه (U بباب مفتوح لحد 2 م)، 2-12 م²
    wide = walls.buffer(1.0, join_style=2).buffer(-1.0, join_style=2)
    for g in getattr(wide, "geoms", [wide]):
        for ring in g.interiors:
            h = Polygon(ring)
            if 2.0 <= h.area <= 12.0 and h.exterior.intersection(walls.buffer(0.08)).length >= 0.7 * h.exterior.length \
                    and max(h.minimum_rotated_rectangle.exterior.length / 4 * 0, 0) == 0:
                L_, S_ = sorted([h.minimum_rotated_rectangle.exterior.length / 4] * 2)
                seeds.append(h.buffer(0))
    if not seeds:
        R["cores"] = []; json.dump(R, open(f"{tag}_res{SUF}.json", "w")); print(tag, "no cores"); return
    # الجيوب المتجاورة (حائط داخلي ≤ 0.8 م بينهم) -> كور واحد، مع الحائط الداخلي
    cores = unary_union([h.buffer(0.45, join_style=2) for h in seeds]).buffer(-0.45, join_style=2)
    cores = [c for c in getattr(cores, "geoms", [cores]) if c.area >= 1.0]
    # السلم (أو شفت) اللي لازق في الكور (≤ 1.5 م) = جزء منه: فتحة واحدة
    grown = True; merged = set()
    while grown:
        grown = False
        for op, o in ops:
            if id(o) in merged: continue
            if o["kind"] not in ("stair", "X", "lift", "lift?", "X*") or op.area < 1.0: continue
            for i_, c in enumerate(cores):
                dd = c.distance(op)
                if 0 < dd <= 1.5 or (c.intersects(op) and not c.buffer(0.05).contains(op)):
                    r_ = max(0.55, dd / 2 + 0.1)
                    m_ = unary_union([c, op]).buffer(r_, join_style=2).buffer(-r_, join_style=2)
                    cores[i_] = unary_union([max(getattr(m_, "geoms", [m_]), key=lambda z: z.area), op]); grown = True
                    merged.add(id(o)); break
    keep = []
    for op, o in ops:
        if any(c.buffer(0.05).contains(op.representative_point()) for c in cores): continue    # جوه الكور
        keep.append(o)
    # بعد الضم: شيل الشرايح الرفيعة (≤ 25 سم)
    cores = [max(getattr(c.buffer(-0.12, join_style=2).buffer(0.12, join_style=2), "geoms", [c.buffer(-0.12, join_style=2).buffer(0.12, join_style=2)]), key=lambda z: z.area) if not c.buffer(-0.12, join_style=2).is_empty else c for c in cores]
    new = [{"poly": list(Polygon(c.exterior).simplify(0.02).exterior.coords)[:-1], "kind": "core", "status": "ok"} for c in cores]
    R["openings"] = keep + new
    R["cores"] = [n["poly"] for n in new]
    json.dump(R, open(f"{tag}_res{SUF}.json", "w"))
    print(tag, "cores", len(new), [round(Polygon(n["poly"]).area, 1) for n in new], "openings now", len(R["openings"]))


for t in sys.argv[1:]: run(t)
