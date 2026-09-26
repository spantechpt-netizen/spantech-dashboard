"""سُمك البلاطة من ملاحظات "slab thick. 30 cm" / "200 MM THICK" / "t=250".
كل ملاحظة -> أصغر منطقة مقفولة حواليها: كبيرة (>40% من البلاطة) = السُمك العام،
صغيرة وسُمكها مختلف = منطقة سُمك (thick_zones) تتصدّر "ZONE t=..".
usage: python thick.py <dxf> TAG...   (wins.json)"""
import json, re, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import ezdxf, slab_extractor as SX
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union, polygonize
RE = re.compile(r"(?:slab\s*)?thick(?:ness)?\.?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\s*(cm|mm)?|(\d{2,4})\s*mm\s*thick|\bt\s*=\s*(\d{2,4})", re.I)


def mm(m):
    if m.group(1):
        v = float(m.group(1)); u = (m.group(2) or "").lower()
        return int(round(v * 10 if u == "cm" or v < 100 else v))
    return int(m.group(3) or m.group(4))


doc = ezdxf.readfile(sys.argv[1]); W = json.load(open("wins.json"))
ENT = list(SX._explode(list(doc.modelspace())))
for tag in sys.argv[2:]:
    w = W[tag]; R = json.load(open(f"{tag}_res_c.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
    slab = Polygon(R["slabs"][0]["outline"])
    notes = []
    for e in ENT:
        if e.dxftype() in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r and slab.buffer(0.5).contains(Point(r[1])):
                m = RE.search(r[0])
                if m: notes.append((mm(m), Point(r[1]), r[0].strip()))
    # الباكية = البلاطة ناقص الكمرات والحوائط والأعمدة (مش أي خط - إطار ملاحظة أو خزان جوه الباكية مايتحسبش)
    import layerless_reader as LR
    M = json.load(open(f"{tag}_members_c.json"))
    def ext(p1, p2, e=1.0):     # الكمرة ممدودة متر من كل طرف: تقفل فتحة صغيرة عند طرفها
        import math
        L = math.dist(p1, p2) or 1; u = ((p2[0]-p1[0])/L, (p2[1]-p1[1])/L)
        return (p1[0]-u[0]*e, p1[1]-u[1]*e), (p2[0]+u[0]*e, p2[1]+u[1]*e)
    sup = [LR._rect_pts(*ext(b["p1"], b["p2"]), b["w"]) for b in M["beams"]] + [LR._rect_pts(x["p1"], x["p2"], x["t"]) for x in M["walls"]] + \
          [c["rect"]["corners"] for c in M["cols"]]
    cut = slab.difference(unary_union([Polygon(q).buffer(0.02) for q in sup]))
    faces = [Polygon(f.exterior) for f in getattr(cut, "geoms", [cut]) if f.area >= 2.0]
    # حدود الباكية: أول كمرة أو حائط طويل (≥ 4 م) أو حد البلاطة في كل اتجاه من الملاحظة
    frame = [LineString([b["p1"], b["p2"]]).buffer(b["w"] / 2) for b in M["beams"]] + \
            [LineString([x["p1"], x["p2"]]).buffer(x["t"] / 2) for x in M["walls"] if LineString([x["p1"], x["p2"]]).length >= 4.0] + \
            [slab.exterior]
    frame = unary_union(frame)

    def box(p, R_=60):
        lim = []
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ray = LineString([(p.x, p.y), (p.x + dx * R_, p.y + dy * R_)])
            h = ray.intersection(frame)
            lim.append(p.distance(h) if not h.is_empty else R_)
        return Polygon([(p.x - lim[0], p.y - lim[2]), (p.x + lim[1], p.y - lim[2]), (p.x + lim[1], p.y + lim[3]), (p.x - lim[0], p.y + lim[3])]).buffer(0.25, join_style=2)

    main, zones = [], []
    for v, p, t in notes:
        fs = [f for f in faces if f.buffer(0.05).contains(p)]
        f = min(fs, key=lambda q: q.area) if fs else None
        if f is not None and f.area <= 0.4 * slab.area:
            q = f.intersection(box(p))
            f = max(getattr(q, "geoms", [q]), key=lambda k: k.area) if not q.is_empty else f
        (main if f is None or f.area > 0.4 * slab.area else zones).append((v, f, t))
    st = max(set(v for v, _, _ in main), key=[v for v, _, _ in main].count) if main else (zones[0][0] if zones else None)
    if st is not None: R["slab_thickness_mm"] = st
    _tz = [{"poly": list(f.intersection(slab).exterior.coords)[:-1], "thickness_mm": v, "note": t}
                        for v, f, t in zones if v != st]
    if _tz or not R.get("thick_zones"): R["thick_zones"] = _tz        # مايمسحش مناطق لقاها بلوك السُمك
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, "slab t", st, "zones", [(z["thickness_mm"], round(Polygon(z["poly"]).area, 1), z["note"]) for z in R["thick_zones"]])
