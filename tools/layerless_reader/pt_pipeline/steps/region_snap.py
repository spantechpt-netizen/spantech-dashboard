"""حدود المناطق فوق بعض بالظبط (عشان الـ meshing في RAM).

خط دروب جنب خط منطقة منسوب بـ 5 سم، أو حد منطقة جنب حد البلاطة، بيعمل شريحة رفيعة
وعناصر مشوّهة في الشبكة. الخطين لازم يبقوا خط واحد.

الترتيب (الأعلى ثابت، والأقل بيتلزق عليه):
  1) حد البلاطة والفتحات          (اتظبطوا على وشوش الكمرات في edge_fit - مابيتحركوش)
  2) مناطق المنسوب (level_zones)
  3) مناطق السُمك (thick_zones)
  4) الدروب (drops)
كل نقطة في منطقة على بعد ≤ TOL (0.15 م) من ضلع في منطقة أعلى منها بتتنقل عليه بالظبط
(لأقرب نقطة على الضلع، ولو قريبة من ركن بتروح للركن نفسه). وبعدين النقط اللي بقت على
ضلع منطقة أعلى بيتضاف ليها ركن المنطقة الأعلى اللي بينهم، عشان الضلعين يبقوا واحد.
المنطقة اللي مساحتها اتغيرت > 10% بترجع زي ما كانت وبتطلع REVIEW (مش هنغيّر شكلها في صمت).
المنطقة بتتقص على البلاطة (مافيش منطقة برّه البلاطة).
usage: python region_snap.py TAG...   ({tag}_res_c.json)
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

TOL = float(os.environ.get("SNAP_TOL", "0.15"))
MTOL = float(os.environ.get("SNAP_MEMBER_TOL", "0.10"))   # لوش كمرة/حيطة/عمود


def ring(p):
    return [tuple(map(float, q[:2])) for q in p]


def edges(polys):
    out = []
    for pts in polys:
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if a != b:
                out.append((a, b))
    return out


_IDX = {}


def _index(ref_edges, ref_vertices):
    """فهرس مكاني للأضلاع والرؤوس (زون فيها آلاف الكمرات - HDB)؛ النتيجة نفسها بالظبط."""
    from shapely.strtree import STRtree
    key = (id(ref_edges), len(ref_edges), id(ref_vertices), len(ref_vertices))
    if key not in _IDX:
        lines = [LineString(e) for e in ref_edges]
        pts = [Point(v) for v in ref_vertices]
        if len(_IDX) > 8:                 # أضلاع الكمرات/الأعمدة (ثابتة) + المناطق (بتكبر)
            _IDX.pop(next(iter(_IDX)))
        _IDX[key] = (lines, STRtree(lines) if lines else None, pts, STRtree(pts) if pts else None)
    return _IDX[key]


def snap_pts(pts, ref_edges, ref_vertices, tol=None):
    tol = TOL if tol is None else tol
    moved = 0
    new = []
    lines, lt, vpts, vt = _index(ref_edges, ref_vertices)
    for p in pts:
        P = Point(p)
        # ركن قريب الأول (≤ tol): النقطة بتروح عليه
        cand = sorted(int(i) for i in vt.query(P.buffer(tol))) if vt is not None else []
        v = min(cand, key=lambda i: P.distance(vpts[i]), default=None)
        if v is not None and 1e-6 < P.distance(vpts[v]) <= tol:
            new.append(ref_vertices[v]); moved += 1; continue
        best = None
        for i in (sorted(int(i) for i in lt.query(P.buffer(tol))) if lt is not None else []):
            L = lines[i]; d = L.distance(P)
            if d <= tol and (best is None or d < best[0]):
                best = (d, L)
        if best and best[0] > 1e-6:
            q = best[1].interpolate(best[1].project(P))
            new.append((q.x, q.y)); moved += 1
        else:
            new.append(p)
    return new, moved


def snap_edges(pts, faces, tol):
    """
    ضلع موازي لوش عنصر (< 1°)، على بعد ≤ tol، وماشي جنبه ≥ 0.5 م (أو نص طوله): الضلع كله بيتنقل
    على خط الوش. الركن الجديد = تقاطع الضلعين اللي حواليه بعد النقل. ده بيمسك الحالة اللي أطراف
    الضلع فيها بعيدة عن أطراف الوش (حيطة بتغطي نص ضلع الفتحة).
    """
    import math
    from shapely.strtree import STRtree
    n = len(pts)
    lines, moved = [], 0
    ftree = STRtree([LineString(f) for f in faces]) if faces else None
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.dist(a, b)
        if L < 1e-6:
            lines.append(None); continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        best = None
        _E = LineString([a, b]).buffer(tol + 0.01)
        for j in (sorted(int(i) for i in ftree.query(_E)) if ftree is not None else []):
            c, d = faces[j]
            M_ = math.dist(c, d)
            if M_ < 0.3:
                continue
            v = ((d[0] - c[0]) / M_, (d[1] - c[1]) / M_)
            if abs(u[0] * v[1] - u[1] * v[0]) > math.sin(math.radians(1.0)):
                continue
            off = [(q[0] - c[0]) * v[1] - (q[1] - c[1]) * v[0] for q in (a, b)]
            if max(abs(o) for o in off) > tol or max(abs(o) for o in off) < 1e-6:
                continue
            t = sorted(((q[0] - c[0]) * v[0] + (q[1] - c[1]) * v[1]) for q in (a, b))
            ov = min(M_, t[1]) - max(0.0, t[0])
            if ov < min(0.5, 0.5 * L):
                continue
            k = max(abs(o) for o in off)
            if best is None or k < best[0]:
                best = (k, c, v)
        if best:
            lines.append((best[1], best[2])); moved += 1
        else:
            lines.append((a, u))
    if not moved:
        return pts, 0
    out = []
    for i in range(n):
        p = pts[i]
        L1, L2 = lines[i - 1], lines[i]
        q = None
        if L1 and L2:
            (p1, d1), (p2, d2) = L1, L2
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) > 1e-6:
                t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
                q = (p1[0] + t * d1[0], p1[1] + t * d1[1])
        if q is None:
            for Ln in (L2, L1):
                if Ln:
                    (c, v) = Ln
                    t = (p[0] - c[0]) * v[0] + (p[1] - c[1]) * v[1]
                    q = (c[0] + t * v[0], c[1] + t * v[1]); break
        # الركن مايتحركش أكتر من tol×3 (تقاطع ضلعين شبه متوازيين)
        out.append(q if q is not None and math.dist(q, p) <= 3 * tol else p)
    return out, moved


def insert_vertices(pts, ref_vertices):
    """ركن منطقة أعلى واقع على ضلع المنطقة دي (≤ 1 مم) بيتضاف كنقطة، فالضلعين يتطابقوا."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        L = LineString([a, b])
        if L.length < 1e-6:
            continue
        mids = [v for v in ref_vertices if L.distance(Point(v)) <= 1e-3
                and Point(v).distance(Point(a)) > 1e-3 and Point(v).distance(Point(b)) > 1e-3]
        mids.sort(key=lambda v: L.project(Point(v)))
        out += mids
    # نقط مكررة ورا بعض
    clean = [out[0]]
    for q in out[1:]:
        if Point(q).distance(Point(clean[-1])) > 1e-4:
            clean.append(q)
    if len(clean) > 1 and Point(clean[0]).distance(Point(clean[-1])) <= 1e-4:
        clean.pop()
    return clean


for tag in sys.argv[1:]:
    fn = f"{tag}_res_c.json"
    R = json.load(open(fn))
    slab_pts = ring(R["slabs"][0]["outline"])
    slab = Polygon(slab_pts).buffer(0)
    fixed = [slab_pts]
    # وشوش العناصر (كمرات، حوائط، أعمدة): ثابتة. الفتحة أو المنطقة اللي حدها على بعد ≤ 10 سم من
    # وش عنصر بتتلزق عليه (دروب على 24 مم من وش كمرة في بدروم رؤية)
    M = json.load(open(f"{tag}_members_c.json")) if os.path.exists(f"{tag}_members_c.json") else {}
    mem = []
    for b in M.get("beams", []):
        try: mem.append(ring(list(LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]}).exterior.coords)[:-1]))
        except Exception: pass
    for w in M.get("walls", []):
        try: mem.append(ring(list(LR._wall_poly(w).exterior.coords)[:-1]))
        except Exception: pass
    cols = [ring(c["rect"]["corners"]) for c in M.get("cols", []) if c.get("rect")]
    # وش الكمرة/الحيطة الأول: العمود ممكن يبرز عن وش الكمرة بمليمترات، ولو النقط اتوزعت بين
    # الاتنين الحد بيتعرّج. العمود بيتاخد بس للنقط اللي مالهاش كمرة/حيطة قريبة.
    bw_e = edges(mem); bw_v = [q for pts in mem for q in pts]
    col_e = edges(cols); col_v = [q for pts in cols for q in pts]

    BW = unary_union([LineString(e) for e in bw_e]) if bw_e else None

    def snap_members(pts):
        pts, n0 = snap_edges(pts, bw_e, MTOL)
        pts, n1 = snap_edges(pts, col_e, MTOL) if not n0 else (pts, 0)
        out, n = [], n0 + n1
        for p in pts:
            q, m = snap_pts([p], bw_e, bw_v, MTOL)
            if not m and not (BW is not None and BW.distance(Point(p)) <= MTOL):
                q, m = snap_pts([p], col_e, col_v, MTOL)
            out += q; n += m
        return out, n
    stats = {}
    n_op = 0
    for o in R.get("openings", []):
        pts = ring(o["poly"]); old = Polygon(pts).buffer(0)
        new, moved = snap_members(pts)
        g = Polygon(new).buffer(0) if len(new) >= 3 else None
        if moved and g is not None and g.geom_type == "Polygon" and abs(g.area - old.area) <= 0.10 * old.area:
            o["poly"] = [list(q) for q in list(g.exterior.coords)[:-1]]; n_op += moved
        fixed.append(ring(o["poly"]))
    stats["openings"] = n_op
    for key in ("level_zones", "thick_zones", "drops"):
        items = R.get(key) or []
        n_moved = n_items = 0
        for it in items:
            # المرجع: الأعلى + اللي قبلها من نفس النوع (منطقتين جنب بعض ضلعهم واحد)
            ref_e = edges(fixed); ref_v = [q for pts in fixed for q in pts]
            pts = ring(it["poly"])
            if len(pts) < 3:
                continue
            old = Polygon(pts).buffer(0)
            new, m1 = snap_members(pts)
            new, moved = snap_pts(new, ref_e, ref_v)
            moved += m1
            new = insert_vertices(new, ref_v)
            g = Polygon(new).buffer(0) if len(new) >= 3 else None
            if g is not None and not g.is_empty:
                g = g.intersection(slab)
                g = max(getattr(g, "geoms", [g]), key=lambda q: q.area) if not g.is_empty else None
            if g is None or g.is_empty or g.geom_type != "Polygon" or abs(g.area - old.area) > 0.10 * old.area:
                fixed.append(pts)
                R.setdefault("review", []).append([key, f"edge of a {key[:-1].replace('_', ' ')} at "
                                                   f"({old.centroid.x:.2f}, {old.centroid.y:.2f}) is within "
                                                   f"{TOL:.2f} m of another edge but could not be snapped - check it"])
                continue
            if moved or g.area != old.area:
                it["poly"] = [list(q) for q in list(g.exterior.coords)[:-1]]
                n_items += 1; n_moved += moved
            fixed.append(ring(it["poly"]))
        stats[key] = (n_items, n_moved)
    json.dump(R, open(fn, "w"))
    print(tag, "snapped (regions, points):", stats)
