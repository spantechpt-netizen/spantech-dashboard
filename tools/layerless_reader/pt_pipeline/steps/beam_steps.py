"""كمرة بعرضين (تسمية "(350/200x700)"): كمرتين ورا بعض في الطول، كل واحدة بعرضها ومحورها المرسوم.
الطريقة (من الرسمة مش من المطابقة العامة): من نقطة التسمية واتجاهها بنمشي على طول الكمرة كل 5 سم:
عند كل محطة لازم يبقى فيه وشين موازيين المسافة بينهم ≈ العرض الأول أو التاني، وواحد منهم على الأقل
هو نفس وش المحطة اللي قبلها (الوش المشترك). بنقف لما الوشوش تخلص (عمود/حائط/نهاية)، والطرف
بيتمد لآكس العمود/الحائط لو قريب (≤ 0.8 م). أي كمرة تانية بنفس التسمية اتطابقت غلط بتتشال.
usage: python beam_steps.py TAG...   ({tag}_members_c.json + {tag}_geo.json)"""
import json, sys, math, re
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union
TAP = re.compile(r"\(\s*(\d{2,4})\s*/\s*(\d{2,4})\s*[xX×*]")
STEP = 0.05


def run(t):
    M = json.load(open(f"{t}_members_c.json")); g = json.load(open(f"{t}_geo.json"))["segs"]
    sup = [Polygon(c["rect"]["corners"]).buffer(0) for c in M["cols"]] + [LR._wall_poly(w) for w in M["walls"]]
    groups = {}
    for b in M["beams"]:
        m = TAP.search(b.get("label", ""))
        if m and b.get("label_at") and b.get("label_rot") is not None:
            groups.setdefault((b["label"], round(b["label_at"][0], 2), round(b["label_at"][1], 2)), []).append(b)
    for tl in M.get("tapered_labels", []):              # تسميات بعرضين اتسابت من المطابقة العادية
        groups.setdefault((tl["label"], round(tl["label_at"][0], 2), round(tl["label_at"][1], 2)), []).append(
            {**tl, "p1": tl["label_at"], "p2": tl["label_at"], "_placeholder": True})
    failed = []
    new, gone, n = [], set(), 0
    for (lab, lx, ly), bs in groups.items():
        m = TAP.search(lab); wA, wB = int(m.group(1)) / 1000, int(m.group(2)) / 1000
        rot = math.radians(bs[0]["label_rot"]); u = (math.cos(rot), math.sin(rot)); nn = (-u[1], u[0])
        P0 = (lx, ly)
        # الوشوش الموازية القريبة: (t0, t1, offset) بالنسبة لنقطة التسمية
        faces = []
        for a, c in g:
            la = math.dist(a, c)
            if la < 0.2 or abs((c[0] - a[0]) / la * nn[0] + (c[1] - a[1]) / la * nn[1]) > 0.02: continue
            off = (a[0] - P0[0]) * nn[0] + (a[1] - P0[1]) * nn[1]
            if abs(off) > 2.0: continue
            ta = (a[0] - P0[0]) * u[0] + (a[1] - P0[1]) * u[1]; tc = (c[0] - P0[0]) * u[0] + (c[1] - P0[1]) * u[1]
            faces.append((min(ta, tc), max(ta, tc), off))

        def pairs(k):
            offs = sorted({round(o, 3) for t0, t1, o in faces if t0 - 0.01 <= k <= t1 + 0.01})
            out = []
            for i in range(len(offs)):
                for j in range(i + 1, len(offs)):
                    sp = offs[j] - offs[i]
                    for w in (wA, wB):
                        if abs(sp - w) <= 0.03: out.append((w, offs[i], offs[j]))
            return out
        # البداية: أقرب زوج لنقطة التسمية (في حدود 1 م)
        start = [p for p in pairs(0.0) if min(abs(p[1]), abs(p[2])) <= 1.0]
        if not start: failed.append(lab); continue
        cur = min(start, key=lambda p: abs((p[1] + p[2]) / 2))
        track = {0.0: cur}
        for sgn in (1, -1):
            prev = cur; k = 0.0
            while True:
                k += sgn * STEP
                cand = [p for p in pairs(k) if abs(p[1] - prev[1]) < 0.01 or abs(p[2] - prev[2]) < 0.01]
                if not cand: break
                # وصلنا ركيزة (عمود/حائط): الكمرة بتقف هنا (وشوش العمود مش كمرة)
                cp = (P0[0] + u[0] * k + nn[0] * (prev[1] + prev[2]) / 2, P0[1] + u[1] * k + nn[1] * (prev[1] + prev[2]) / 2)
                if any(s_.contains(Point(cp)) for s_ in sup): break
                prev = min(cand, key=lambda p: (0 if p[0] == prev[0] else 1, abs(p[1] - prev[1]) + abs(p[2] - prev[2])))
                track[round(k, 3)] = prev
                if abs(k) > 30: break
        ks = sorted(track)
        segs = []
        for k in ks:
            w, o1, o2 = track[k]
            if segs and segs[-1][1] == w and abs(segs[-1][4] - (o1 + o2) / 2) < 0.01: segs[-1][2] = k
            else: segs.append([k, w, k, None, (o1 + o2) / 2])
        segs = [s for s in segs if s[2] - s[0] >= 0.3]
        if not segs: continue
        bounds = [segs[0][0]] + [(segs[i][2] + segs[i + 1][0]) / 2 for i in range(len(segs) - 1)] + [segs[-1][2]]
        pts = lambda k, o: (P0[0] + u[0] * k + nn[0] * o, P0[1] + u[1] * k + nn[1] * o)
        made = []
        for i, (k0, w, k1, _, o) in enumerate(segs):
            a, c = pts(bounds[i], o), pts(bounds[i + 1], o)
            nb_ = {**bs[0], "p1": list(a), "p2": list(c), "w": w, "stepped": f"{i + 1}/{len(segs)}", "label": lab}
            nb_.pop("_placeholder", None); made.append(nb_)
        # الأطراف لآكس الركيزة القريبة
        for key, idx, sgn in (("p1", 0, -1), ("p2", -1, 1)):
            b = made[idx]; E = b[key]
            ray = LineString([E, (E[0] + sgn * u[0] * 0.8, E[1] + sgn * u[1] * 0.8)])
            hits = [s for s in sup if ray.intersects(s)]
            if hits:
                c = min(hits, key=lambda s: s.distance(Point(E))).centroid
                d = (c.x - E[0]) * u[0] + (c.y - E[1]) * u[1]
                if 0 < d * sgn <= 0.8: b[key] = [E[0] + u[0] * d, E[1] + u[1] * d]
        for b in bs: gone.add(id(b))
        new += made; n += 1
    M["beams"] = [b for b in M["beams"] if id(b) not in gone] + new
    M["tapered_failed"] = failed
    for i, b in enumerate(M["beams"]): b["id"] = i
    json.dump(M, open(f"{t}_members_c.json", "w"))
    print(t, "two-width beams rebuilt", n, [(b["stepped"], round(b["w"], 2), round(math.dist(b["p1"], b["p2"]), 2)) for b in new])


for t in sys.argv[1:]: run(t)
