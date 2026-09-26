"""شرايح الصب (pour strips) من غير ليّرات: شريط متهاشر طويل (عرضه 0.5-2.5 م، طوله ≥ 5 أضعاف عرضه)
ومكتوب جنبه/عليه "POUR STRIP". أي هاتش تاني بنفس النمط وبنفس العرض = شريحة كمان (الملاحظة
بتتكتب مرة واحدة على شريحة من كذا شريحة). الناتج pourstrips.json (حلقات بالمتر).
usage: python pourstrips.py   (hatch.pkl: الهاتشات، cache.pkl: النصوص)"""
import json, pickle, re, sys
from shapely.geometry import Polygon, Point
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import slab_extractor as SX
_, H = pickle.load(open("hatch.pkl", "rb")); _, tx, _ = pickle.load(open("cache.pkl", "rb"))
notes = [Point(p) for t, p, h in tx if re.search(r"POUR\s*STRIP", t, re.I)]
found = {}
for pat, rings in H.items():
    polys = []
    for r in rings:
        if len(r) < 3: continue
        g = Polygon(r).buffer(0)
        # هاتش حلقته اتلغت أو اتقسمت (مساحة صفر أو حتتين) - كل حتة لوحدها، والفاضي بيتشال
        polys += [q for q in getattr(g, "geoms", [g]) if q.geom_type == "Polygon" and q.length > 0]
    strip = []
    for p in polys:
        # شريط ممكن يبقى مكسور (بيلف): العرض ≈ 2×المساحة/المحيط، والطول ≈ المحيط/2
        S = 2 * p.area / p.length; L = p.length / 2
        if 0.5 <= S <= 2.5 and L >= 5 * S: strip.append((p, S))
    labelled = [(p, S) for p, S in strip if any(p.distance(n) <= 1.5 for n in notes)]
    if not labelled: continue
    widths = [S for _, S in labelled]
    found[pat] = [p for p, S in strip if any(abs(S - w) <= 0.1 for w in widths)]
out = [list(p.exterior.coords) for ps in found.values() for p in ps]
json.dump(out, open("pourstrips.json", "w"))
print("POUR STRIP notes", len(notes), "patterns", {k: len(v) for k, v in found.items()}, "strips", len(out),
      "widths", sorted({round(2 * Polygon(r).area / Polygon(r).length, 2) for r in out}))
