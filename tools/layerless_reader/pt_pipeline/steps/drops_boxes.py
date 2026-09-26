"""Drop panels مرسومة مستطيل مقفول بخط عادي حوالين عمود، من غير نص ومن غير تقطيع
(زي مسقط بدروم رؤية: مستطيلات 3.0×2.5 حوالين كل عمود في بلاطة PT).

المستطيل بيتقري دروب لو:
  - مستطيل (مساحته ≥ 95% من المستطيل المحيط)، أضلاعه 1.0–6.0 م.
  - جوه البلاطة (≥ 90% منه)، ومش فوق فتحة (< 20% منه في فتحة).
  - فيه مركز عمود واحد على الأقل، ومساحته ≥ 3 أضعاف العمود (مش هو العمود نفسه).
  - متكرر: ≥ 4 مستطيلات في الرسمة كلها (كل الزونات) مقاسها في حدود ±20% من المقاس النمطي -
    مستطيل لوحده ممكن يبقى أي حاجة.
السُمك من نص "400mm THK" أو "TH=400" جوه الدروب أو لازق فيه؛ من غير نص السُمك بيفضل فاضي
والبرنامج بياخد سُمك الدروب الافتراضي من صفحة Project - والدروب بيطلع REVIEW.
usage: python drops_boxes.py TAG...   (DXF=m.dxf بالمتر)"""
import collections, json, os, pickle, re, sys
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

RE = re.compile(r"(?:(\d{3,4})\s*mm\.?\s*TH(?:K|ICK)|TH(?:K|ICK)?\s*[=:]\s*(\d{3,4}))", re.I)
_, tx, _ = pickle.load(open("cache.pkl", "rb"))[:3]
doc = ezdxf.readfile(os.environ.get("DXF", "m.dxf"))
rects = []
for e in doc.modelspace().query("LWPOLYLINE POLYLINE"):
    try:
        pts = [tuple(p[:2]) for p in (e.get_points() if e.dxftype() == "LWPOLYLINE" else [v.dxf.location for v in e.vertices])]
    except Exception:
        continue
    closed = e.closed if e.dxftype() == "LWPOLYLINE" else e.is_closed
    if len(pts) >= 3 and (closed or (len(pts) >= 4 and Point(pts[0]).distance(Point(pts[-1])) < 0.01)):
        p = Polygon(pts).buffer(0)
        if p.is_empty or p.geom_type != "Polygon":
            continue
        r = p.minimum_rotated_rectangle
        xs = sorted(Point(r.exterior.coords[i]).distance(Point(r.exterior.coords[i + 1])) for i in range(2))
        if r.area > 0 and p.area >= 0.95 * r.area and 1.0 <= xs[0] and xs[1] <= 6.0:
            rects.append((p, (round(xs[0] / 0.15), round(xs[1] / 0.15))))

import statistics
# المرور الأول: المرشحين في كل الزونات
per = {}
for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    slab = Polygon(R["slabs"][0]["outline"]).buffer(0)
    ops = unary_union([Polygon(o["poly"]).buffer(0) for o in R["openings"]]) if R["openings"] else Polygon()
    cols = [Polygon(c["rect"]["corners"]).buffer(0) for c in M["cols"]]
    have = [Polygon(d["poly"]).buffer(0) for d in R.get("drops", [])]
    cand = []
    for p, key in rects:
        if p.intersection(slab).area < 0.9 * p.area or p.intersection(ops).area > 0.2 * p.area:
            continue
        inside = [c for c in cols if p.contains(c.centroid)]
        if not inside or p.area < 3 * max(c.area for c in inside):
            continue
        if any(p.symmetric_difference(q).area < 0.05 * p.area for q, _ in cand) or \
                any(p.intersection(q).area > 0.5 * p.area for q in have):
            continue
        cand.append((p, key))
    per[tag] = (R, slab, cand)

# التكرار والمقاس النمطي على الرسمة كلها، مش لكل زون: زون فيها دروبين بس من نفس النمط بتاخدهم
allc = [k for _, _, c in per.values() for _, k in c]
ok = set()
if allc:
    m0 = statistics.median(k[0] for k in allc); m1 = statistics.median(k[1] for k in allc)
    ok = {k for k in allc if abs(k[0] - m0) <= 0.2 * m0 and abs(k[1] - m1) <= 0.2 * m1}
    if sum(1 for k in allc if k in ok) < 4:
        ok = set()

for tag, (R, slab, cand) in per.items():
    keep = [(p, k) for p, k in cand if k in ok]
    notes = []
    for t, pt, h in tx:
        m = RE.search(t)
        if m and slab.contains(Point(pt)):
            notes.append((int(m.group(1) or m.group(2)), Point(pt)))
    typ = collections.Counter(v for v, pt in notes if any(p.buffer(0.8).contains(pt) for p, _ in keep)).most_common(1)
    new = []
    for p, k in keep:
        th = [v for v, pt in notes if p.buffer(0.8).contains(pt)]
        d = {"poly": list(p.exterior.coords)[:-1], "thickness_mm": th[0] if th else (typ[0][0] if typ else None), "src": "box"}
        if not th and typ:
            d["typ"] = True
        if d["thickness_mm"] is None:
            d["t_unknown"] = True
        new.append(d)
    R["drops"] = R.get("drops", []) + new
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, "box drops", len(new), "of", len(cand), "candidates; sizes", dict(collections.Counter(k for _, k in cand)),
          "thickness", collections.Counter(d["thickness_mm"] for d in new))
