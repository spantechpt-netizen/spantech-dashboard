"""الكمرة المتقطّعة عند الأعمدة بتتلم كمرة واحدة.

قراءة الوشوش بتقطع الكمرة عند كل عمود/حيطة، فكمرة واحدة طويلة (زي PT-(550x600) على حد البدروم)
بتطلع 29 حتة، منهم حتت 0.2-0.5 م - والحتة القصيرة بتعمل عنصر مشوّه في شبكة RAM.
حتتين بيتلموا لو:
  - نفس العلامة ونفس العرض والعمق ونفس INV/المنسوب،
  - على استقامة واحدة (الزاوية < 0.3° والإزاحة الجانبية ≤ 2 سم)،
  - والفجوة بينهم ≤ 1.2 م ومتغطية بعمود أو حيطة (أو الحتتين متلامسين/متداخلين)،
  - والكمرة الملمومة كلها جوه البلاطة أو فتحاتها (≤ 1% برّه - فحص الزونات بيسمح بـ 2%).
الكمرة الملمومة بتاخد الأطراف الحقيقية للحتتين اللي على الأطراف.
الكمرة بعرضين (TAPER) مابتتلمش: العرض مختلف. الكمرات من غير تسمية (B?) مابتتلمش.
usage: python beam_merge.py TAG..."""
import json, math, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union


def key(b):
    return (b.get("mark"), round(b["w"], 3), round(b["d"], 3) if b.get("d") else None,
            bool(b.get("inverted")), b.get("se_mm"), bool(b.get("review")))


for tag in sys.argv[1:]:
    M = json.load(open(f"{tag}_members_c.json")); R = json.load(open(f"{tag}_res_c.json"))
    # الكمرة الملمومة لازم تفضل جوه البلاطة (أو فتحاتها) زي كل حتة فيها: الفجوة ممكن تعدّي على ركن برّه
    AREA = unary_union([Polygon(R["slabs"][0]["outline"]).buffer(0)] +
                       [Polygon(o["poly"]).buffer(0) for o in R["openings"]])
    sup = unary_union([Polygon(c["rect"]["corners"]).buffer(0.02) for c in M["cols"]] +
                      [LR._wall_poly(w).buffer(0.02) for w in M["walls"]])
    beams = M["beams"]
    n0 = len(beams)
    changed = True
    while changed:
        changed = False
        for i in range(len(beams)):
            a = beams[i]
            if a.get("mark") in (None, "B?") or a.get("review"):
                continue
            ua = (a["p2"][0] - a["p1"][0], a["p2"][1] - a["p1"][1]); La = math.hypot(*ua)
            if La < 1e-6:
                continue
            ua = (ua[0] / La, ua[1] / La)
            for j in range(i + 1, len(beams)):
                b = beams[j]
                if key(a) != key(b):
                    continue
                ub = (b["p2"][0] - b["p1"][0], b["p2"][1] - b["p1"][1]); Lb = math.hypot(*ub)
                if Lb < 1e-6 or abs(ua[0] * ub[1] - ua[1] * ub[0]) / Lb > math.sin(math.radians(0.3)):
                    continue
                # الإزاحة الجانبية لطرفين b عن خط a
                off = max(abs((q[0] - a["p1"][0]) * ua[1] - (q[1] - a["p1"][1]) * ua[0]) for q in (b["p1"], b["p2"]))
                if off > 0.02:
                    continue
                ta = sorted((0.0, La)); tb = sorted(((q[0] - a["p1"][0]) * ua[0] + (q[1] - a["p1"][1]) * ua[1]) for q in (b["p1"], b["p2"]))
                gap = max(tb[0] - ta[1], ta[0] - tb[1])
                if gap > 1.2:
                    continue
                if gap > 0.02:
                    lo, hi = (ta[1], tb[0]) if tb[0] > ta[1] else (tb[1], ta[0])
                    g = LineString([(a["p1"][0] + ua[0] * lo, a["p1"][1] + ua[1] * lo),
                                    (a["p1"][0] + ua[0] * hi, a["p1"][1] + ua[1] * hi)])
                    if g.difference(sup).length > 0.05:
                        continue
                # الأطراف الحقيقية للحتتين اللي على الأطراف (مش إسقاط على خط الأولى: الإسقاط بيزحّل كمرة الحرف)
                ends = [tuple(q) for q in (a["p1"], a["p2"], b["p1"], b["p2"])]
                proj = lambda q: (q[0] - a["p1"][0]) * ua[0] + (q[1] - a["p1"][1]) * ua[1]
                q1 = min(ends, key=proj); q2 = max(ends, key=proj)
                mp = LR._wall_poly({"p1": q1, "p2": q2, "t": a["w"]})
                if mp.difference(AREA).area > 0.01 * mp.area:
                    continue
                a["p1"], a["p2"] = q1, q2
                a["merged"] = a.get("merged", 1) + b.get("merged", 1)
                del beams[j]
                changed = True
                break
            if changed:
                break
    json.dump(M, open(f"{tag}_members_c.json", "w"))
    print(f"{tag}: beams {n0} -> {len(beams)} (collinear pieces of the same beam joined)")
