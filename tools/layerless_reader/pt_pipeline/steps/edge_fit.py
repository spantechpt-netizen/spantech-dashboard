"""حد البلاطة على الكمرات والأعمدة اللي ع الداير (عشان الـ meshing):
1) كل عنصر لازم يبقى من الزون نفسها: لو واقع في زون تانية أكتر من دي (توأم الفاصل) بيتشال؛
   عمود ع الداير نصه برّه البلاطة بيفضل والبلاطة بتتمد تغطيه.
2) كمرة طرفية (وش منها على بعد ≤ 0.35 م من حد البلاطة): الحد بيبقى على وشها الخارجي بالظبط -
   البلاطة بتتمد تغطيها، واللي زايد برّه الوش الخارجي (شريحة لحد 0.35 م) بيتشال.
3) عمود على الحد: البلاطة بتغطيه كله.
usage: python edge_fit.py TAG...   ({tag}_res_c.json + {tag}_members_c.json)"""
import json, sys, math
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.prepared import prep
TOL = 0.35
ALL = {t: Polygon(json.load(open(f"{t}_res_c.json"))["slabs"][0]["outline"]).buffer(0) for t in sys.argv[1:]}
MALL = {t: json.load(open(f"{t}_members_c.json")) for t in sys.argv[1:]}
# فهارس مكانية: شيت فيه 100+ زون و20 ألف كمرة (HDB) - من غيرها كل عنصر كان بيتقارن بكل الزونات وكل الكمرات
_ZT = list(ALL); _ZG = [ALL[k] for k in _ZT]; _ZTREE = STRtree(_ZG)
_BL = [(k, o, LineString([o["p1"], o["p2"]])) for k, MM in MALL.items() for o in MM["beams"]]
_BTREE = STRtree([l for _, _, l in _BL]) if _BL else None
for t in sys.argv[1:]:
    R = json.load(open(f"{t}_res_c.json")); M = json.load(open(f"{t}_members_c.json"))
    slab = ALL[t]
    OPS = unary_union([Polygon(o["poly"]).buffer(0) for o in R["openings"]]) if R["openings"] else Polygon()

    def own(g, t=t, slab=slab):
        """العنصر بتاع الزون دي إلا لو واقع في زون تانية أكتر منها (توأم الفاصل)."""
        if g.area <= 0: return False
        mine = g.intersection(slab).area
        other = max([_ZG[i].intersection(g).area for i in _ZTREE.query(g) if _ZT[i] != t] + [0])
        return mine > 0.01 * g.area and mine >= other
    n0 = (len(M["cols"]), len(M["walls"]), len(M["beams"]))
    M["cols"] = [c for c in M["cols"] if own(Polygon(c["rect"]["corners"]).buffer(0))]
    M["walls"] = [w for w in M["walls"] if own(LR._wall_poly(w))]
    def own_beam(b):
        g = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        if not own(g): return False
        # تسمية الكمرة واقعة جوه زون تانية = دي كمرة الجار (توأم الفاصل) حتى لو التسمية لقت وشين عندنا
        at = b.get("label_at")
        if at and any(_ZG[i].buffer(-0.02).contains(Point(at)) for i in _ZTREE.query(Point(at)) if _ZT[i] != t) and not slab.buffer(0.02).contains(Point(at)):
            # إلا لو الجار عنده توأمها (نفس التسمية، موازية، جنبها ≤ 1 م): التسمية بتتكتب مرة للتوأمين
            _lb = LineString([b["p1"], b["p2"]])
            near = [_BL[i] for i in _BTREE.query(_lb.buffer(1.0))] if _BTREE is not None else []
            twin = any(o.get("label") == b.get("label") and LineString([o["p1"], o["p2"]]).distance(_lb) <= 1.0
                       and abs(math.sin(math.atan2(o["p2"][1] - o["p1"][1], o["p2"][0] - o["p1"][0]) - math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0]))) < 0.05
                       and LineString([o["p1"], o["p2"]]).distance(_lb) > 0.05
                       for k, o, _ in near if k != t)
            if not twin: return False
        # كمرة برّه البلاطة (فوق فراغ الواجهة) أو جوه فتحة/فراغ: مش كمرة البلاطة
        if g.intersection(slab).area < 0.5 * g.area: return False
        return g.intersection(OPS).area < 0.5 * g.area
    _ok = [own_beam(b) for b in M["beams"]]
    dropped_out = [b for b, k in zip(M["beams"], _ok) if not k]
    M["beams"] = [b for b, k in zip(M["beams"], _ok) if k]
    # كمرتين على نفس الخط متداخلين (تسميتين لنفس الكمرة): الأقصر المتغطية ≥ 80% بتتشال
    keep = []
    # المتسمية الأول (الكمرة المتسمية بتكسب اللي من غير تسمية)، وبعدين الأطول
    for b in sorted(M["beams"], key=lambda b: (1 if str(b.get("label", "")).startswith("unlabelled") else 0, -math.dist(b["p1"], b["p2"]))):
        g = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        unl = str(b.get("label", "")).startswith("unlabelled")
        # كمرة من غير تسمية بتتشال لو متداخلة مع متسمية بأي جزء محسوس (≥ 30% منها)
        if any(g.intersection(LR._wall_poly({"p1": k["p1"], "p2": k["p2"], "t": k["w"]})).area >= (0.3 * g.area if unl else 0.8 * min(g.area, k["w"] * math.dist(k["p1"], k["p2"]))) for k in keep): continue
        # على نفس الخط (المحور نفسه) ومتداخلة ≥ 80% من طولها في كمرة أطول بتسمية تانية (عرض مختلف فالمساحة
        # مابتمسكهاش): تسميتين على نفس الكمرة المرسومة (CA2(200X700) + B4(300X900) في HDB). الأطول بتفضل،
        # والتانية بتطلع REVIEW - الرسمة مابتقولش القطاع بيتغير فين.
        lb = LineString([b["p1"], b["p2"]]); Lb = lb.length
        host = next((k for k in keep if Lb > 0 and abs(math.sin(math.atan2(k["p2"][1] - k["p1"][1], k["p2"][0] - k["p1"][0])
                                                       - math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0]))) < 0.02
                     and LineString([k["p1"], k["p2"]]).distance(lb) <= max(k["w"], b["w"]) / 2
                     and LineString([k["p1"], k["p2"]]).buffer(max(k["w"], b["w"]) / 2, cap_style=2).intersection(lb).length >= 0.8 * Lb), None)
        # حتة قصيرة جنب كمرة أطول موازية وبين الوشّين ≤ 10 سم وطولها كله تقريبًا جنبها (توأم): حتة من الكمرة التانية
        # اتقرت لوحدها (CA2 0.7 م لازقة في B4 جنب سلم HDB) - الأطول بتفضل والتانية REVIEW
        twin = None
        # (حتة قصيرة بس ≤ 1.5 م: كمرتين طوال جنب بعض بإزاحة = خط كمرة مزاح بيتظبط بعدين، مش توأم يتشال - رؤية B3/B4)
        if host is None and 0 < Lb <= 1.5:
            for k in keep:
                if abs(math.sin(math.atan2(k["p2"][1] - k["p1"][1], k["p2"][0] - k["p1"][0])
                                - math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0]))) >= 0.02:
                    continue
                lk = LineString([k["p1"], k["p2"]])
                gap = lk.distance(lb) - (k["w"] + b["w"]) / 2
                if -0.02 <= gap <= 0.1 and lk.buffer((k["w"] + b["w"]) / 2 + 0.12, cap_style=2).intersection(lb).length >= 0.8 * Lb:
                    twin = k; break
        if twin is not None:
            R.setdefault("review", []).append(["beam label", f"{b.get('label')} ({Lb:.1f} m) lies against {twin.get('label')} with no gap near "
                                               f"({b['p1'][0]:.1f}, {b['p1'][1]:.1f}) - kept {twin.get('label')}; check the drawing there"])
            continue
        if host is not None:
            if host.get("label") != b.get("label"):
                R.setdefault("review", []).append(["beam label", f"{b.get('label')} and {host.get('label')} are on the same beam line near "
                                                   f"({b['p1'][0]:.1f}, {b['p1'][1]:.1f}) - kept {host.get('label')} over the whole length; check where the section changes"])
            continue
        keep.append(b)
    M["beams"] = keep
    M.setdefault("dropped_beams", []).extend({**b, "why": "belongs to the neighbouring zone / outside this slab / inside a void"} for b in dropped_out)
    removed = (n0[0] - len(M["cols"]), n0[1] - len(M["walls"]), n0[2] - len(M["beams"]))
    bnd = slab.exterior
    add, cut = [], []
    n_edge = 0
    for b in M["beams"]:
        p1, p2, w = b["p1"], b["p2"], b["w"]
        L = math.dist(p1, p2)
        if L < 0.3: continue
        u = ((p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L); n = (-u[1], u[0])
        faces = []
        for s in (1, -1):
            f = LineString([(p1[0] + s * n[0] * w / 2, p1[1] + s * n[1] * w / 2), (p2[0] + s * n[0] * w / 2, p2[1] + s * n[1] * w / 2)])
            faces.append((s, f))
        # الوش الخارجي = اللي جنبه برّه البلاطة (نقطة شوية برّاه مش جوه)
        best = None
        for s, f in faces:
            m = f.interpolate(0.5, normalized=True)
            probe = Point(m.x + s * n[0] * (TOL + 0.05), m.y + s * n[1] * (TOL + 0.05))
            d = bnd.distance(m)
            if d <= TOL and not slab.contains(probe) and (best is None or d < best[0]): best = (d, s, f)
        if best is None: continue
        _, s, f = best
        n_edge += 1
        add.append(LR._wall_poly({"p1": p1, "p2": p2, "t": w}))
        (a0, a1) = f.coords
        beyond = Polygon([a0, a1, (a1[0] + s * n[0] * TOL, a1[1] + s * n[1] * TOL), (a0[0] + s * n[0] * TOL, a0[1] + s * n[1] * TOL)])
        cut.append(beyond)
    # كمرة طالعة شوية بجنبها برّه الحد (مش كمرة طرفية بالمعنى ده، بس لازم تبقى متغطية)
    for b in M["beams"]:
        g = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        f = g.intersection(slab).area / g.area if g.area else 1
        if 0.85 <= f < 0.999: add.append(g.difference(OPS) if not OPS.is_empty else g)      # الجزء اللي فوق فتحة يفضل فتحة
    # كل أعمدة الزون متغطية بالبلاطة (حتى اللي قص الكمرة الطرفية كان هياكل جزء منها)
    for c in M["cols"]:
        add.append(Polygon(c["rect"]["corners"]).buffer(0))
    new = unary_union([slab] + add)
    # القص برّه الوش الخارجي مايمسّش أي كمرة أو عمود من الزون (شريحة كمرة طرفية ممكن تعدّي على كمرة تانية)
    keep_ = unary_union(add + [LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}) for b in M["beams"]
                               if LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}).intersection(slab).area >= 0.85 * max(b["w"] * math.dist(b["p1"], b["p2"]), 1e-9)])
    if cut: new = new.difference(unary_union(cut).difference(keep_.buffer(0.001)))
    new = max(getattr(new, "geoms", [new]), key=lambda q: q.area)
    # فراغ اتقفل بكمرات حرفه (فراغ واجهة بقى جوه): بيفضل فتحة، مش بلاطة
    for h in new.interiors:
        hp = Polygon(h)
        if hp.area >= 0.5 and not any(Polygon(o["poly"]).buffer(0.05).contains(hp) for o in R["openings"]):
            R["openings"].append({"poly": list(hp.simplify(0.005).exterior.coords)[:-1], "kind": "X", "status": "ok", "src": "void enclosed by edge beams"})
    new = Polygon(new.exterior).simplify(0.005)
    R["slabs"][0]["outline"] = list(new.exterior.coords)[:-1]
    # طرف كمرة فايت الفاصل/حد البلاطة (اتمدت لآكس عمود التوأم في الزون التانية): يتقص عند الحد
    AREA = unary_union([new] + [Polygon(o["poly"]).buffer(0) for o in R["openings"]])
    _A2 = prep(AREA.buffer(0.002)); _Ain = {}; _Ap = prep(AREA)
    for b in M["beams"]:
        ax_ = LineString([b["p1"], b["p2"]]); w2 = b["w"] / 2
        for key in ("p1", "p2"):
            P = Point(b[key])
            if w2 not in _Ain: _Ain[w2] = prep(AREA.buffer(-w2 + 0.001))
            if _Ain[w2].contains(P) or _Ap.contains(LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})): continue
            other = b["p2"] if key == "p1" else b["p1"]
            L = math.dist(b[key], other); u = ((b[key][0] - other[0]) / L, (b[key][1] - other[1]) / L)
            # أبعد نقطة على المحور الشريط كله (بعرضه) لسه جوه البلاطة
            lo, hi = 0.0, L
            for _ in range(30):
                mid = (lo + hi) / 2
                q = (other[0] + u[0] * mid, other[1] + u[1] * mid)
                if _A2.contains(LR._wall_poly({"p1": other, "p2": q, "t": b["w"]})): lo = mid
                else: hi = mid
            if lo > 0.3 and L - lo > 0.005: b[key] = [other[0] + u[0] * lo, other[1] + u[1] * lo]
    json.dump(R, open(f"{t}_res_c.json", "w")); json.dump(M, open(f"{t}_members_c.json", "w"))
    print(t, "removed (cols, walls, beams) of other zones", removed, "edge beams fitted", n_edge, "area", round(slab.area, 1), "->", round(new.area, 1))
