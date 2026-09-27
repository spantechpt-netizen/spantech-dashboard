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
    # الكمرة الملمومة لازم تبقى خط واحد مستقيم: الحتت مزاحة عن بعض بمليمترات (≤ 2 سم)، والأطراف
    # الحقيقية بتطلّع كمرة مايلة (3 سم على 69 م في بدروم رؤية) - ووشها المايل بيخلي حد البلاطة
    # والدروب ومنطقة المنسوب اللي بتتلزق عليه يتعرّجوا بمليمترات. لو الميل عن المحور < 0.5°
    # الكمرة بتتعدل على المحور، والإحداثي الثابت = متوسط الحتت بالطول.
    # وكمان أي كمرة (مش ملمومة) مايلة < 1.5° وإزاحتها الكلية ≤ 10 سم: طرف اتشد على آكس عمود والتاني لأ
    # (HDB الأرضي: B4 من -473.45 لـ -473.40 على 3.3 م جنب الكور - وشها المايل مابيتلزقش عليه حد منطقة المنسوب)
    n_str = 0
    for b in beams:
        (x1, y1), (x2, y2) = b["p1"], b["p2"]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        ang = math.degrees(math.atan2(abs(dy), abs(dx)))
        merged = b.get("merged", 1) >= 2
        lim = 0.5 if merged else 1.5
        if 0 < ang < lim and (merged or abs(dy) <= 0.10):
            yc = (y1 + y2) / 2; b["p1"], b["p2"] = [x1, yc], [x2, yc]; n_str += 1
        elif 0 < 90 - ang < lim and (merged or abs(dx) <= 0.10):
            xc = (x1 + x2) / 2; b["p1"], b["p2"] = [xc, y1], [xc, y2]; n_str += 1
    # كمرتين على نفس الخط بعرضين (B4 200 + B10 300): وش من ناحية لازم يبقى على خط واحد. لو الفرق بين وشّين
    # على نفس الناحية ≤ 3 سم (دقة رسم) الكمرة الأضيق بتتزق عليه - غير كده حد المنطقة/الفتحة اللي جنبهم يا
    # يبقى على وش ويسيب شريحة 2.5 سم جنب التاني، يا يتعرّج (HDB الأرضي جنب الأكوار: 27 حد)
    n_flush = 0
    moved_ = set()
    for i, a in enumerate(beams):
        for j in range(i + 1, len(beams)):
            b = beams[j]
            if i in moved_ and j in moved_:
                continue
            (ax1, ay1), (ax2, ay2) = a["p1"], a["p2"]
            La = math.hypot(ax2 - ax1, ay2 - ay1)
            if La < 1e-6:
                continue
            u = ((ax2 - ax1) / La, (ay2 - ay1) / La); nrm = (-u[1], u[0])
            (bx1, by1), (bx2, by2) = b["p1"], b["p2"]
            Lb = math.hypot(bx2 - bx1, by2 - by1)
            if Lb < 1e-6 or abs(u[0] * (by2 - by1) / Lb - u[1] * (bx2 - bx1) / Lb) > 0.01:
                continue
            d = ((bx1 - ax1) * nrm[0] + (by1 - ay1) * nrm[1] + (bx2 - ax1) * nrm[0] + (by2 - ay1) * nrm[1]) / 2
            if abs(d) > (a["w"] + b["w"]) / 2:
                continue
            ta = sorted([0.0, La]); tb = sorted([(bx1 - ax1) * u[0] + (by1 - ay1) * u[1], (bx2 - ax1) * u[0] + (by2 - ay1) * u[1]])
            if min(ta[1], tb[1]) - max(ta[0], tb[0]) < -1.0:        # مش على نفس الخط ورا بعض (فجوة > 1 م)
                continue
            best = None
            for sgn in (1, -1):
                dl = (d + sgn * b["w"] / 2) - sgn * a["w"] / 2
                if 0.002 < abs(dl) <= 0.03 and (best is None or abs(dl) < abs(best)):
                    best = dl
            if best is None:
                continue
            # الأضيق بيتحرك (ولو نفس العرض: الأقصر)
            if (b["w"], Lb) <= (a["w"], La) and j not in moved_:
                mv, k, sh = b, j, -best
            elif i not in moved_:
                mv, k, sh = a, i, best
            else:
                continue
            mv["p1"] = [mv["p1"][0] + nrm[0] * sh, mv["p1"][1] + nrm[1] * sh]
            mv["p2"] = [mv["p2"][0] + nrm[0] * sh, mv["p2"][1] + nrm[1] * sh]
            moved_.add(k); n_flush += 1
    # ونفس الكلام كمرة جنب حيطة على نفس الخط (وش الحيطة ثابت، الكمرة بتتزق ≤ 3 سم) - HDB: حيطة الكور على 70.40
    # ووش B4 على 70.375، وحد منطقة المنسوب مابيعرفش يبقى على الاتنين
    for k, b in enumerate(beams):
        if k in moved_:
            continue
        (bx1, by1), (bx2, by2) = b["p1"], b["p2"]
        Lb = math.hypot(bx2 - bx1, by2 - by1)
        if Lb < 1e-6:
            continue
        u = ((bx2 - bx1) / Lb, (by2 - by1) / Lb); nrm = (-u[1], u[0])
        best = None
        for w in M.get("walls", []):
            (wx1, wy1), (wx2, wy2) = w["p1"], w["p2"]
            Lw = math.hypot(wx2 - wx1, wy2 - wy1)
            if Lw < 0.3 or abs(u[0] * (wy2 - wy1) / Lw - u[1] * (wx2 - wx1) / Lw) > 0.01:
                continue
            d = ((wx1 - bx1) * nrm[0] + (wy1 - by1) * nrm[1] + (wx2 - bx1) * nrm[0] + (wy2 - by1) * nrm[1]) / 2
            if abs(d) > (b["w"] + w["t"]) / 2 + 0.03:
                continue
            tw = sorted([(wx1 - bx1) * u[0] + (wy1 - by1) * u[1], (wx2 - bx1) * u[0] + (wy2 - by1) * u[1]])
            if min(Lb, tw[1]) - max(0.0, tw[0]) < -1.0:
                continue
            for sgn in (1, -1):
                for wf in (d + w["t"] / 2, d - w["t"] / 2):        # أي وش في الحيطة قريب من وش الكمرة
                    dl = wf - sgn * b["w"] / 2
                    if 0.002 < abs(dl) <= 0.03 and (best is None or abs(dl) < abs(best)):
                        best = dl
        if best is not None:
            b["p1"] = [bx1 + nrm[0] * best, by1 + nrm[1] * best]; b["p2"] = [bx2 + nrm[0] * best, by2 + nrm[1] * best]
            moved_.add(k); n_flush += 1
    json.dump(M, open(f"{tag}_members_c.json", "w"))
    print(f"{tag}: beams {n0} -> {len(beams)} (collinear pieces of the same beam joined), {n_str} straightened onto the grid axis, "
          f"{n_flush} made flush with the beam next to them on the same line")
