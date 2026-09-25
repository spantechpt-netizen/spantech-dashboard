"""اكتشاف مساقط البلاطات في ملف فيه أكتر من شيت (من غير ليّرات):
1) عناوين الشيتات (slab_extractor.find_plan_views) - لو لقت مساقط إنشائية بتتاخد.
2) غير كده: كل مسقط فيه مجموعة أعمدة (هاتشات صغيرة مدمجة 0.04-3 م²) مفصولة عن مجموعة الشيت
   اللي جنبه بمسافة كبيرة. المجموعات (ربط بمسافة ≤ EPS) اللي فيها ≥ 6 أعمدة = مسقط؛ الإطار = حدود
   المجموعة + هامش. الاسم = أقرب عنوان تحت/جنب المجموعة (فيه FLOOR/LEVEL/BASEMENT/ROOF/B1/GF...)،
   وإلا S1, S2..."""
import math, re, sys, os
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import slab_extractor as SX, layerless_reader as LR
from shapely.geometry import Polygon, Point, MultiPoint

TITLE = re.compile(r"(FLOOR|LEVEL|BASEMENT|ROOF|CEILING|SLAB|PODIUM|MEZZ|\bB\s*-?\s*\d\b|\bBS-?\d+\b|\bGF\b|\bFF\b|\bGR\b|\b\d+(ST|ND|RD|TH)\b|GROUND|TYPICAL)", re.I)


def column_points(doc):
    pts = []
    for e in SX._explode(list(doc.modelspace())):
        if e.dxftype() != "HATCH": continue
        try:
            for r in LR.hatch_rings(e, 0.01):
                if len(r) < 3: continue
                p = Polygon(r).buffer(0)
                if not (0.04 <= p.area <= 3.0): continue
                L, S = SX._rect_dims(p)
                if S >= 0.12 and L <= 2.5: pts.append((p.centroid.x, p.centroid.y))
        except Exception:
            continue
    return pts


def clusters(pts, eps):
    """ربط بمسافة (single linkage) بشبكة خانات."""
    cell = defaultdict(list)
    for i, (x, y) in enumerate(pts): cell[(int(x // eps), int(y // eps))].append(i)
    parent = list(range(len(pts)))
    def f(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for (cx, cy), ids in cell.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cell.get((cx + dx, cy + dy), []):
                    for i in ids:
                        if i < j and math.dist(pts[i], pts[j]) <= eps: parent[f(i)] = f(j)
    g = defaultdict(list)
    for i in range(len(pts)): g[f(i)].append(pts[i])
    return list(g.values())


BUB = re.compile(r"^[A-Z]{1,2}'?$|^\d{1,2}'?$|^[A-Z]\d{1,2}$")


def grid_bubbles(doc):
    """فقاعات المحاور: دايرة (نص قطر 0.2-1.2 م) جواها حرف/رقم قصير - نص عادي أو attribute بلوك."""
    circles, labels, direct = [], [], []
    def walk(es, depth=0):
        for e in es:
            t = e.dxftype()
            if t == "CIRCLE" and 0.2 <= e.dxf.radius <= 1.2: circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
            elif t in ("TEXT", "MTEXT"):
                r = SX._text_of(e)
                if r and BUB.match(r[0].strip()): labels.append((r[1][0], r[1][1]))
            elif t == "INSERT":
                ats = [a for a in e.attribs if BUB.match(a.dxf.text.strip())]
                if ats:
                    try: has_c = any(x.dxftype() == "CIRCLE" for x in e.virtual_entities())
                    except Exception: has_c = False
                    if has_c: direct.append((e.dxf.insert.x, e.dxf.insert.y))      # بلوك فقاعة: دايرة + attribute
                    for a in ats: labels.append((a.dxf.insert.x, a.dxf.insert.y))
                if depth < 3:
                    try: walk(list(e.virtual_entities()), depth + 1)
                    except Exception: pass
    walk(list(doc.modelspace()))
    out = list(direct)
    for x, y in labels:
        if any(math.hypot(x - cx, y - cy) <= r * 1.3 for cx, cy, r in circles): out.append((x, y))
    return out


def detect(doc, log=print, eps=9.0, margin=1.0, min_cols=6):
    views = [v for v in SX.find_plan_views(doc, log=lambda *a, **k: None) if v.source == "struct"]
    pts = grid_bubbles(doc)
    big = lambda c: len(c) >= 4 and (MultiPoint(c).bounds[2] - MultiPoint(c).bounds[0]) * (MultiPoint(c).bounds[3] - MultiPoint(c).bounds[1]) >= 150
    # مسافة الربط: اللي بتطلّع أكتر عدد مساقط (الشيتات المتلاصقة بتتفصل، وفقاعات المسقط الواحد بتتجمع)
    best = []
    for eps_ in (8.0, 10.0, 12.0, 15.0, 20.0):
        cl_ = [c for c in clusters(pts, eps_) if big(c)] if pts else []
        if len(cl_) > len(best): best = cl_
    cl = best
    if views and len(views) >= len(cl) * 0.8:
        log(f"sheets: {len(views)} from titles")
        return [(v.name, tuple(v.window)) for v in views]
    texts = []
    for e in SX._explode(list(doc.modelspace())):
        if e.dxftype() in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r and TITLE.search(r[0]) and len(r[0]) <= 60: texts.append((r[0].strip(), Point(r[1]), r[2]))
    out = []
    for c in sorted(cl, key=lambda c: (round(-sum(p[1] for p in c) / len(c), -1), sum(p[0] for p in c) / len(c))):
        x0, y0, x1, y1 = MultiPoint(c).bounds
        win = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
        box = Polygon([(win[0], win[1]), (win[2], win[1]), (win[2], win[3]), (win[0], win[3])])
        # العنوان: أكبر نص عنوان تحت الإطار (لحد 25% من ارتفاعه) أو جواه، الأقرب
        cand = [(t, p, h) for t, p, h in texts if box.buffer((y1 - y0) * 0.25 + 3).contains(p)]
        cand.sort(key=lambda q: (-q[2], box.distance(q[1])))
        name = re.sub(r"[^A-Za-z0-9\-]+", "_", cand[0][0]).strip("_")[:24] if cand else None
        out.append([name, win])
    seen = {}
    for i, o in enumerate(out):
        if not o[0] or o[0] in seen: o[0] = f"{o[0] or 'S'}{i + 1}" if o[0] else f"S{i + 1}"
        seen[o[0]] = 1
    # مساقط البلاطات بس: لو فيه عناوين فيها FRAMING/SLAB/CEILING/ROOF/FLOOR بنسيب المحاور/الأساسات/التفاصيل
    SLABT = re.compile(r"FRAM|SLAB|CEIL|ROOF|FLOOR|LEVEL|BS-?\d|PODIUM", re.I)
    BAD = re.compile(r"COL|AXIS|FOUND|FOOT|SECT|DETAIL|ELEV|PILE|RAFT", re.I)
    if os.environ.get("SHEETS_DEBUG"): print([(o[0], round(o[1][0])) for o in out])
    FLOORN = re.compile(r"^(B\d|BS-?\d+|GF|GR|FF|\d+(ST|ND|RD|TH)|ROOF|MEZZ)", re.I)
    named = [o for o in out if not re.fullmatch(r"S\d+", o[0])]
    good = [o for o in named if (SLABT.search(o[0]) or FLOORN.search(o[0])) and not BAD.search(o[0])]
    # شيت من غير عنوان بيتساب لو فيه شيتات متسمية (غالبًا نسخة/تفصيلة)؛ بيتسجل في التقرير
    dropped = [o[0] for o in out if o not in good]
    if dropped: log(f"sheets skipped (no slab title): {dropped}")
    if good: out = good
    if not out:
        from ezdxf import bbox
        b = bbox.extents(doc.modelspace())
        out = [["PLAN", (b.extmin.x - 1, b.extmin.y - 1, b.extmax.x + 1, b.extmax.y + 1)]]
    log(f"sheets: {len(out)} from grid bubbles (titles gave {len(views)})")
    return [(n, tuple(w)) for n, w in out]


if __name__ == "__main__":
    import ezdxf
    d = ezdxf.readfile(sys.argv[1])
    for n, w in detect(d): print(n, [round(v, 1) for v in w])
