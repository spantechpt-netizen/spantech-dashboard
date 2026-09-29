"""الكمرة بتتقطع عند آكس كل ركيزة بتعدّي عليها (قاعدة المكتب، قبل ما الملف يروح RAM).

كمرة طويلة معدّية على أعمدة أو حوائط أو كمرات تانية:
  - عمود: مركزه على بعد ≤ نص عرض الكمرة + نص العمود من محورها -> قطع عند إسقاط مركز العمود على المحور.
  - حيطة معدّية تحت الكمرة (مش موازية): قطع عند تقاطع محور الكمرة مع محور الحيطة.
  - كمرة تانية بتقاطعها (زاوية > 10°): قطع عند تقاطع المحورين - الكمرة المحمولة (secondary) بتتقطع
    عند آكس الكمرة الشايلة (main girder)، والشايلة بتتقطع عند النقطة اللي المحمولة بتقع عليها.
الحتت ورا بعض بالظبط: آخر حتة = أول اللي بعدها (نفس النقطة)، فكأنها كمرة واحدة مكملة، وكل حتة
بنفس العلامة والمقاس والأولوية والمنسوب. قطعين أقرب من 30 سم بيتلموا (العمود أولى)، ومافيش قطع
على ≤ 30 سم من طرف الكمرة.
الأطراف نفسها مابتتحركش (connect.py وbeam_merge.py حطوها على آكس الركيزة).
usage: python beam_split.py TAG...   ({tag}_members_c.json)
"""
import json, math, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from shapely.geometry import Polygon

MIN = 0.05
GROUP = 0.30


def cross_t(p1, p2, q1, q2):
    """(t على الأول بالمتر، s على التاني من 0 لـ 1) لتقاطع خطين، أو None لو متوازيين."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]; ex, ey = q2[0] - q1[0], q2[1] - q1[1]
    den = dx * ey - dy * ex
    L = math.hypot(dx, dy); M = math.hypot(ex, ey)
    if L < 1e-9 or M < 1e-9 or abs(den) / (L * M) < math.sin(math.radians(10)):
        return None
    wx, wy = q1[0] - p1[0], q1[1] - p1[1]
    u = (wx * ey - wy * ex) / den          # على الأول (0..1)
    s = (wx * dy - wy * dx) / den          # على التاني (0..1)
    return u * L, s


for tag in sys.argv[1:]:
    fn = f"{tag}_members_c.json"
    M = json.load(open(fn))
    beams = M.get("beams", [])
    cols = [Polygon(c["rect"]["corners"]).buffer(0) for c in M.get("cols", []) if c.get("rect")]
    walls = M.get("walls", [])
    out, n_cut, why = [], 0, {"column": 0, "wall": 0, "beam": 0}
    for i, b in enumerate(beams):
        p1, p2 = b["p1"], b["p2"]
        L = math.dist(p1, p2)
        if L < 2 * MIN:
            out.append(b); continue
        ux, uy = (p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L
        cuts = []
        for c in cols:
            cx, cy = c.centroid.x, c.centroid.y
            t = (cx - p1[0]) * ux + (cy - p1[1]) * uy
            d = abs((cx - p1[0]) * uy - (cy - p1[1]) * ux)
            x0, y0, x1, y1 = c.bounds
            half = max(x1 - x0, y1 - y0) / 2
            if MIN < t < L - MIN and d < b["w"] / 2 + half - 0.02:
                cuts.append((t, "column"))
        for w in walls:
            r = cross_t(p1, p2, w["p1"], w["p2"])
            if r and MIN < r[0] < L - MIN and -1e-6 <= r[1] <= 1 + 1e-6:
                cuts.append((r[0], "wall"))
        for j, o in enumerate(beams):
            if j == i:
                continue
            r = cross_t(p1, p2, o["p1"], o["p2"])
            # التانية لازم توصل للنقطة (بطرفها أو معدّية) - هامش نص عرض الكمرة دي
            if r:
                Lo = math.dist(o["p1"], o["p2"])
                tol = (b["w"] / 2 + 0.02) / max(Lo, 1e-6)
                if MIN < r[0] < L - MIN and -tol <= r[1] <= 1 + tol:
                    cuts.append((r[0], "beam"))
        # قطعين أقرب من GROUP (30 سم) = ركيزة واحدة: العمود أولى من الحيطة من الكمرة (كمرة واقعة على
        # كمرة جنب عمود). ومافيش قطع على ≤ 30 سم من طرف الكمرة: الطرف أصلًا على آكس الركيزة، والحتة
        # الصغيرة (9 سم) بتعمل عنصر مشوّه في الشبكة.
        rank = {"column": 0, "wall": 1, "beam": 2}
        cuts = [(t, k) for t, k in cuts if GROUP <= t <= L - GROUP]
        cuts.sort()
        groups = []
        for t, k in cuts:
            if groups and t - groups[-1][-1][0] < GROUP:
                groups[-1].append((t, k))
            else:
                groups.append([(t, k)])
        pts = [0.0]
        for g in groups:
            t, k = min(g, key=lambda q: (rank[q[1]], q[0]))
            if t - pts[-1] >= GROUP and L - t >= GROUP:
                pts.append(t); why[k] += 1
        pts.append(L)
        if len(pts) == 2:
            out.append(b); continue
        n_cut += len(pts) - 2
        P = lambda t: [p1[0] + ux * t, p1[1] + uy * t]
        for k in range(len(pts) - 1):
            q = dict(b)
            q["p1"] = list(p1) if k == 0 else P(pts[k])
            q["p2"] = list(p2) if k == len(pts) - 2 else P(pts[k + 1])
            q["split_from"] = b.get("id", i)
            out.append(q)
    for k, b in enumerate(out):
        b["id"] = k
    M["beams"] = out
    json.dump(M, open(fn, "w"))
    print(f"{tag}: beams {len(beams)} -> {len(out)} (cut at {n_cut} support axes: {why})")
