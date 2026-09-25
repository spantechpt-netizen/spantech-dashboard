"""Drop panels مرسومة بخط متقطع حوالين عمود + نص "400mm THK." (و"(TYP)" = نفس السُمك لكل
الدروبات المتشابهة). الدروب = شكل مقفول (1-80 م²) فيه عمود. السُمك من النص اللي جواه أو لازق فيه؛
من غير نص -> السُمك النمطي (الأكتر تكرارًا) ومتعلّم typ.
usage: python drops_dashed.py TAG...  (hatch.pkl: الأشكال المتقطعة، cache.pkl: النصوص)"""
import json, sys, re, pickle, collections
from shapely.geometry import Polygon, Point
lone, _ = pickle.load(open("hatch.pkl", "rb")); _, tx, _ = pickle.load(open("cache.pkl", "rb"))
RE = re.compile(r"(\d{3,4})\s*mm\.?\s*TH(?:K|ICK)", re.I)
for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    slab = Polygon(R["slabs"][0]["outline"])
    cols = [Polygon(c["rect"]["corners"]) for c in M["cols"]] + [Polygon(__import__("layerless_reader")._wall_poly(w)) if False else None for w in []]
    notes = [(int(m.group(1)), Point(p)) for t, p, h in tx for m in [RE.search(t)] if m and slab.contains(Point(p))]
    cand = []
    for r in lone:
        p = Polygon(r).buffer(0)
        if not (1.0 <= p.area <= 80) or not slab.buffer(0.2).contains(p.representative_point()): continue
        if not any(p.contains(c.centroid) for c in cols): continue
        if any(p.equals(q) or p.symmetric_difference(q).area < 0.05 * p.area for q, _ in cand): continue
        th = [v for v, pt in notes if p.buffer(0.8).contains(pt)]
        cand.append((p, th[0] if th else None))
    typ = collections.Counter(v for _, v in cand if v).most_common(1)
    typ = typ[0][0] if typ else None
    new = [{"poly": list(p.exterior.coords)[:-1], "thickness_mm": v or typ, **({} if v else {"typ": True})} for p, v in cand if (v or typ)]
    old = [d for d in R.get("drops", []) if not any(Polygon(d["poly"]).buffer(0).intersection(Polygon(n["poly"])).area > 0.5 * Polygon(d["poly"]).buffer(0).area for n in new)]
    R["drops"] = old + new
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, "drops", len(R["drops"]), "with own note", sum(1 for _, v in cand if v), "typ", typ,
          collections.Counter(d["thickness_mm"] for d in R["drops"]))
