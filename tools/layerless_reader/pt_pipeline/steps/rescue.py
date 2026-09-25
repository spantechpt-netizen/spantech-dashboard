"""طرف كمرة سايب ومفيش قدامه عنصر معروف: غالبًا واقف على كمرة مرسومة بخطين
ومتسمّاش (أو اسمها ما اتربطش). بندوّر على زوج خطوط متوازية بيقطع امتداد الكمرة
قريب، ونعمل منه كمرة: بمقاس label مش متربط لو العرض مطابق، وإلا "للمراجعة"."""
import json, math, re, sys, copy
from shapely.geometry import LineString, Point
from connect import connect, unit, lateral, proj, angle_between

LBL = re.compile(r"^(\w+?)\((\d+)\*(\d+)\)")

def _pairs(segs, P, u, R=4.0, back=1.0):
    ray = LineString([(P[0]-u[0]*back, P[1]-u[1]*back), (P[0]+u[0]*R, P[1]+u[1]*R)])
    near = [(tuple(a), tuple(b)) for a, b in segs
            if math.dist(a, b) >= 2.0 and LineString([a, b]).distance(ray) <= 2.6]
    out = []
    for i in range(len(near)):
        a1, b1 = near[i]; u1 = unit(a1, b1)
        if angle_between(u, u1) < 20: continue          # لازم يقطع الكمرة مش يمشي جنبها
        for j in range(i+1, len(near)):
            a2, b2 = near[j]
            if angle_between(u1, unit(a2, b2)) > 1.5: continue
            s = lateral(a2, a1, b1)
            if not 0.15 <= s <= 2.6: continue
            # التداخل على طول الخطين
            t = sorted([0, math.dist(a1, b1)])
            ta = [(q[0]-a1[0])*u1[0]+(q[1]-a1[1])*u1[1] for q in (a2, b2)]
            lo, hi = max(t[0], min(ta)), min(t[1], max(ta))
            if hi - lo < 0.7*min(math.dist(a1, b1), math.dist(a2, b2)): continue
            n = (-u1[1], u1[0]); sg = 1 if (a2[0]-a1[0])*n[0]+(a2[1]-a1[1])*n[1] > 0 else -1
            c1 = (a1[0]+u1[0]*lo+sg*n[0]*s/2, a1[1]+u1[1]*lo+sg*n[1]*s/2)
            c2 = (a1[0]+u1[0]*hi+sg*n[0]*s/2, a1[1]+u1[1]*hi+sg*n[1]*s/2)
            # مفيش خط تالت موازي بين الاتنين (يبقوا وشين لنفس العنصر)
            mid = LineString([c1, c2])
            if any(angle_between(u1, unit(a, b)) <= 1.5 and (a, b) not in (near[i], near[j])
                   and LineString([a, b]).distance(mid) < s/2 - 0.02 for a, b in near): continue
            X = ray.intersection(LineString([(c1[0]-u1[0]*(s/2+0.3), c1[1]-u1[1]*(s/2+0.3)),
                                            (c2[0]+u1[0]*(s/2+0.3), c2[1]+u1[1]*(s/2+0.3))]))
            if X.is_empty or X.geom_type != "Point": continue
            tt = (X.x-P[0])*u[0]+(X.y-P[1])*u[1]
            out.append((tt if tt > 0 else -1.5*tt, s, c1, c2))
    return sorted(out)

def rescue(M, R, segs):
    Mc, _, log = connect(copy.deepcopy(M), copy.deepcopy(R))
    free = [tuple(p) for p in log["free_beam_ends"]]
    miss = []
    for m in M.get("miss", []):
        g = LBL.match(m)
        if g: miss.append({"text": m.split(" @")[0], "mark": g.group(1), "w": int(g.group(2))/100, "d": int(g.group(3))/100})
    existing = [LineString([b["p1"], b["p2"]]) for b in M["beams"]] + \
               [LineString([w["p1"], w["p2"]]) for w in M["walls"]]
    nid = max([b.get("id", 0) for b in M["beams"]] + [0]) + 1
    added = []
    for P in free:
        # الكمرة صاحبة الطرف ده (بعد الربط) واتجاهها
        b = min(Mc["beams"], key=lambda x: min(math.dist(x["p1"], P), math.dist(x["p2"], P)))
        o = b["p2"] if math.dist(b["p1"], P) < math.dist(b["p2"], P) else b["p1"]
        u = unit(o, P)
        for _, s, c1, c2 in _pairs(segs, P, u):
            cl = LineString([c1, c2])
            if any(e.distance(cl.interpolate(0.5, normalized=True)) < s/2 for e in existing): continue
            if any(LineString([a["p1"], a["p2"]]).distance(cl) < 0.05 for a in added): break
            lab = min((m for m in miss if abs(m["w"]-s) <= max(0.05, 0.15*m["w"])), key=lambda m: abs(m["w"]-s), default=None)
            L = cl.length
            if lab and L >= 2*s:
                nb = {"mark": lab["mark"], "label": lab["text"]+" (from two drawn lines)", "w": lab["w"], "d": lab["d"]}
                miss.remove(lab); M["miss"] = [m for m in M["miss"] if not m.startswith(lab["text"])]
            elif True:          # من غير تسمية: مابنخمّنش كمرات
                continue                                   # عريض من غير label = غالبًا مش كمرة
            else:
                sim = [x["d"] for x in M["beams"] if abs(x["w"]-s) < 0.05 and abs(math.dist(x["p1"], x["p2"])-L) <= 0.3*L]
                d = sorted(sim)[len(sim)//2] if sim else math.ceil(L/10/0.05)*0.05
                nb = {"mark": "B?", "label": "unlabelled (two drawn lines)", "w": round(s, 3), "d": d, "review": True}
            nb.update({"p1": c1, "p2": c2, "id": nid, "rescued": True}); nid += 1
            M["beams"].append(nb); added.append(nb); existing.append(cl)
            break
    return M, added

if __name__ == "__main__":
    for tag in sys.argv[1:]:
        M = json.load(open(f"{tag}_members.json")); R = json.load(open(f"{tag}_res.json"))
        segs = json.load(open(f"{tag}_geo.json"))["segs"]
        M, added = rescue(M, R, segs)
        for a in added: print(tag, "rescued", a["label"], "w=%.2f d=%.2f L=%.2f" % (a["w"], a["d"], math.dist(a["p1"], a["p2"])))
        json.dump(M, open(f"{tag}_members_r.json", "w"))
