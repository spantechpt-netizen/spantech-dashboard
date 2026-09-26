"""فواصل التمدد بين الزونات - اكتشاف تلقائي (من غير ما حد يقول إن السقف زونات).

الفاصل = خط مستقيم طويل (≥ 8 م) على جانبيه "توأم": أعمدة متلاصقة اتنين اتنين (عمود كامل على كل
ناحية، قصاد بعض، والمسافة بينهم ≤ 0.35 م) - ≥ 2 أزواج. كمان الكمرتين التوأم (وش على كل ناحية)
بيأكدوا نفس الخط. كل فاصل بيتمد لحد ما يقابل حرف البلاطة أو فراغ أو فاصل تاني، والبلاطة
بتتقطع عند كل الفواصل مع بعض، وكل حتة (≥ 3% من المساحة) = زون لوحدها.
usage: python joints.py TAG OUTPREFIX   -> OUTPREFIX1.. {res,geo}.json   (hatch.pkl فيه الهاتشات)"""
import json, sys, math, pickle, os
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union
tag, pref = sys.argv[1], sys.argv[2]
R = json.load(open(f"{tag}_res.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
slab = Polygon(R["slabs"][0]["outline"]).buffer(0)
_, H = pickle.load(open(os.environ.get("HATCH_PKL", "hatch.pkl"), "rb"))
EXCL = set(os.environ.get("EXCL", "").split())
cols = [Polygon(r).buffer(0) for p, rs in H.items() if p not in EXCL for r in rs if len(r) >= 3]
cols = [c for c in cols if 0.06 <= c.area <= 2.5 and slab.buffer(0.5).contains(c.representative_point())]
# خطوط مستقيمة متصلة (تجميع المتسامت ودمج الفترات)
groups = {}
for p, q in g:
    L = math.dist(p, q)
    if L < 0.3: continue
    a_ = math.atan2(q[1] - p[1], q[0] - p[0]) % math.pi
    ux, uy = math.cos(a_), math.sin(a_); off = -p[0] * uy + p[1] * ux
    k = (round(math.degrees(a_) * 2) / 2 % 180, round(off / 0.02))
    t0, t1 = sorted([p[0] * ux + p[1] * uy, q[0] * ux + q[1] * uy])
    groups.setdefault(k, (ux, uy, off, []))[3].append((t0, t1))
runs = []
for ux, uy, off, iv in groups.values():
    iv.sort(); cur = None
    for t0, t1 in iv + [(1e18, 1e18)]:
        if cur and t0 <= cur[1] + 1.2: cur[1] = max(cur[1], t1); continue
        if cur and cur[1] - cur[0] >= 8: runs.append((ux, uy, off, cur[0], cur[1]))
        cur = [t0, t1]


def twins(ux, uy, off, t0, t1):
    nx, ny = -uy, ux
    side = []
    for c in cols:
        p = c.centroid; t = p.x * ux + p.y * uy; d = p.x * nx + p.y * ny - off
        if not (t0 - 0.5 <= t <= t1 + 0.5) or abs(d) > 1.2: continue
        # العمود كله على ناحية واحدة من الخط (مش متقسوم عليه)
        ds = [x * nx + y * ny - off for x, y in c.exterior.coords]
        if min(ds) < -0.02 and max(ds) > 0.02: continue
        side.append((t, d, c))
    L_ = [s for s in side if s[1] < 0]; R_ = [s for s in side if s[1] > 0]
    pairs = [(a, b) for a in L_ for b in R_ if abs(a[0] - b[0]) <= 0.6 and a[2].distance(b[2]) <= 0.35]
    return len({round(a[0], 1) for a, _ in pairs}), pairs


cands = []; weak = []
for ux, uy, off, t0, t1 in runs:
    n, pairs = twins(ux, uy, off, t0, t1)
    if n >= 2: cands.append((n, ux, uy, off, t0, t1))
    elif n == 1: weak.append((n, ux, uy, off, t0, t1))
# (اتشال: امتداد الفاصل بزوج توأم واحد كان بيقسم زون واحدة لاتنين - الفاصل لازم ≥ 2 أزواج أعمدة توأم)
# خطين متوازيين قريبين (≤ 0.4) لنفس الفاصل -> واحد (الأكتر أزواج)
cands.sort(key=lambda c: -c[0]); joints = []
for c in cands:
    if any(abs(math.degrees(math.atan2(c[2], c[1]) - math.atan2(j[2], j[1]))) % 180 < 1 and abs(c[3] - j[3]) <= 0.4 and
           min(c[5], j[5]) - max(c[4], j[4]) > 0 for j in joints): continue
    joints.append(c)
# الفراغات الكبيرة (X / فناء / منحدر / كور) بتتشال الأول: الفاصل بيقف عندها
voids = unary_union([Polygon(o["poly"]).buffer(0) for o in R["openings"] if Polygon(o["poly"]).area >= 6]) if R["openings"] else Polygon()
base = slab.difference(voids)
raw = []
for n, ux, uy, off, t0, t1 in joints:
    nx, ny = -uy, ux
    P = lambda t, ux=ux, uy=uy, off=off, nx=nx, ny=ny: (t * ux + off * nx, t * uy + off * ny)
    raw.append((n, ux, uy, off, t0, t1, P))
lines = []
for i, (n, ux, uy, off, t0, t1, P) in enumerate(raw):
    # الطرف بيتمد (≤ 3 م) لحد أقرب حاجة يقابلها: حرف البلاطة، فراغ، أو فاصل تاني - مش أكتر
    obst = unary_union([base.boundary] + [LineString([r[6](r[4]), r[6](r[5])]) for j, r in enumerate(raw) if j != i])
    ends = []; reach = True
    for tE, sgn in ((t0, -1), (t1, 1)):
        # الطرف بيتمد لحد أول حاجة يقابلها (حد البلاطة/فراغ/فاصل تاني) في حدود 8 م
        if not base.buffer(-0.02).contains(Point(P(tE))):
            ends.append(tE); continue                       # الطرف أصلًا على الحد أو براه
        ray = LineString([P(tE - sgn * 0.3), P(tE + sgn * 8.0)])
        hit = ray.intersection(obst)
        if hit.is_empty: ends.append(tE); reach = False; continue
        pts = [hit] if hit.geom_type == "Point" else [g_ for g_ in getattr(hit, "geoms", [hit]) if g_.geom_type == "Point"] or \
              [Point(c) for g_ in getattr(hit, "geoms", [hit]) for c in g_.coords]
        ts = [p.x * ux + p.y * uy for p in pts]
        ts = [t for t in ts if (t - tE) * sgn >= -0.3]
        ends.append(tE + sgn * 0.05 + min((t - tE for t in ts), key=lambda d: abs(d)) if ts else tE)
    lines.append(LineString([P(ends[0]), P(ends[1])]))
    print(f"joint: {n} twin column pairs, {t1 - t0:.1f} m, ({lines[-1].coords[0][0]:.1f},{lines[-1].coords[0][1]:.1f}) -> ({lines[-1].coords[1][0]:.1f},{lines[-1].coords[1][1]:.1f})")
parts = base.difference(unary_union(lines).buffer(0.03)) if lines else base
# شق مقفول من طرف واحد (جزء فاصل مابيفصلش) جوه نفس الزون بيتقفل - كل زون لوحدها عشان الفاصل الحقيقي يفضل
parts = [q.buffer(0.05, join_style=2).buffer(-0.05, join_style=2).intersection(base) for q in getattr(parts, "geoms", [parts])]
parts = [max(getattr(q, "geoms", [q]), key=lambda z: z.area) for q in parts if not q.is_empty]
parts = sorted([p for p in parts if p.area >= 0.02 * slab.area], key=lambda p: (round(-p.centroid.y, -1), p.centroid.x))
tags = []
for i, q in enumerate(parts, 1):
    t = f"{pref}{i}"; tags.append(t)
    Rn = dict(R); Rn["tag"] = t
    Rn["slabs"] = [{"outline": list(Polygon(q.exterior).simplify(0.01).exterior.coords)[:-1]}]
    ext = Polygon(q.exterior)
    Rn["openings"] = [o for o in R["openings"] if ext.contains(Polygon(o["poly"]).representative_point()) and Polygon(o["poly"]).area < 6]
    for h in q.interiors:                     # فراغ جوه الزون - بنوعه الأصلي (منحدر/كور/سلم/X)
        hp = Polygon(h)
        src = max(R["openings"], key=lambda o: Polygon(o["poly"]).buffer(0).intersection(hp).area, default=None)
        kind = src["kind"] if src is not None and Polygon(src["poly"]).buffer(0).intersection(hp).area >= 0.5 * hp.area else "X"
        Rn["openings"].append({"poly": list(h.coords)[:-1], "kind": kind, "status": "ok", "src": "void"})
    for o in R["openings"]:                   # فراغ كبير لامس الحرف بس جوه الحد الخارجي
        op = Polygon(o["poly"]).buffer(0)
        if op.area >= 6 and ext.contains(op.representative_point()) and not any(Polygon(h).buffer(0).contains(op.representative_point()) for h in q.interiors):
            Rn["openings"].append(o)
    Rn["joints"] = [list(l.coords) for l in lines]
    json.dump(Rn, open(f"{t}_res.json", "w"))
    json.dump({"segs": [s for s in g if q.buffer(0.5).contains(Point(s[0])) or q.buffer(0.5).contains(Point(s[1]))]}, open(f"{t}_geo.json", "w"))
    print(t, round(q.area), "m²", len(Rn["openings"]), "openings")
json.dump(tags, open(f"{tag}_zones.json", "w"))
