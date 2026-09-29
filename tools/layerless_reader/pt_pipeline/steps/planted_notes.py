"""ملاحظة "Planted Column" مكتوبة جنب عمود = العمود ده مزروع (واقف على البلاطة/الكمرة، مش ركيزة تحتها).

الملاحظة بتخص العمود اللي بتشاور عليه، مش النمط كله: بياخد أقرب عمود في حدود 2.5 م، ولو فيه
مقاس مكتوب جنب الملاحظة ("C- 400*400" أو "(400x400)") بيفضّل العمود اللي مقاسه كده (±50 مم).
كل عمود بياخد ملاحظة واحدة بس. الأعمدة اللي من غير ملاحظة وبنفس مقاس المزروعة بالظبط
بتتسجّل REVIEW (ممكن تكون مزروعة ومحدش كتب جنبها) - مابتتغيّرش من غير دليل.
usage: python planted_notes.py TAG..."""
import json, math, pickle, re, sys
from shapely.geometry import Point, Polygon

_, tx, _ = pickle.load(open("cache.pkl", "rb"))[:3]
PL = re.compile(r"\bPLANTED\b|مزروع", re.I)
SZ = re.compile(r"(\d{3,4})\s*[*xX×]\s*(\d{3,4})")
notes = [Point(p) for t, p, h in tx if PL.search(t) and not re.search(r"\bNOT\b", t, re.I)]
sizes = [(Point(p), sorted((int(m.group(1)) / 1000, int(m.group(2)) / 1000))) for t, p, h in tx for m in [SZ.search(t)] if m]

for tag in sys.argv[1:]:
    R = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    slab = Polygon(R["slabs"][0]["outline"]).buffer(1.0)
    cols = M["cols"]
    taken, marked = set(), 0
    for q in notes:
        if not slab.contains(q):
            continue
        want = [s for p, s in sizes if p.distance(q) <= 0.8]
        best = None
        for i, c in enumerate(cols):
            if i in taken:
                continue
            d = Point(c["rect"]["center"]).distance(q)
            if d > 2.5:
                continue
            fit = not want or any(abs(sorted((c["b"], c["d"]))[0] - w[0]) <= 0.05 and
                                  abs(sorted((c["b"], c["d"]))[1] - w[1]) <= 0.05 for w in want)
            key = (0 if fit else 1, d)
            if best is None or key < best[0]:
                best = (key, i)
        if best is not None:
            i = best[1]; taken.add(i)
            if cols[i]["type"] != "planted":
                cols[i]["type"] = "planted"; cols[i]["planted_note"] = True; marked += 1
    # نفس مقاس المزروعة ومن غير ملاحظة: مراجعة، مش تغيير
    psz = {tuple(round(v, 2) for v in sorted((cols[i]["b"], cols[i]["d"]))) for i in taken}
    rev = [c for i, c in enumerate(cols) if i not in taken and c["type"] != "planted"
           and tuple(round(v, 2) for v in sorted((c["b"], c["d"]))) in psz]
    if rev:
        R.setdefault("review", []).append(
            ["planted?", f"{len(rev)} column(s) have the exact size of the columns noted 'Planted' but no note "
                         f"- kept as supports below the slab; check them"])
        for c in rev:
            c["review_planted"] = True
    json.dump(M, open(f"{tag}_members_c.json", "w")); json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(f"{tag}: {len(notes)} 'planted' notes -> {marked} column(s) set planted; {len(rev)} same-size without a note (REVIEW)")
