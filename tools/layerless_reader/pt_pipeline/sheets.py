"""اكتشاف مساقط البلاطات في ملف فيه أكتر من شيت (من غير ليّرات):
1) عناوين الشيتات (slab_extractor.find_plan_views) - لو لقت مساقط إنشائية بتتاخد.
2) غير كده: كل مسقط فيه مجموعة أعمدة (هاتشات صغيرة مدمجة 0.04-3 م²) مفصولة عن مجموعة الشيت
   اللي جنبه بمسافة كبيرة. المجموعات (ربط بمسافة ≤ EPS) اللي فيها ≥ 6 أعمدة = مسقط؛ الإطار = حدود
   المجموعة + هامش. الاسم = أقرب عنوان تحت/جنب المجموعة (فيه FLOOR/LEVEL/BASEMENT/ROOF/B1/GF...)،
   وإلا S1, S2...
3) لو المساقط اللي طلعت مش شايلة 30% من أعمدة الرسمة: أقسام بعناوين كبيرة ("FRAMING PLANS" تحت
   عمود مساقط) - كل صف جوه قسم البلاطات = مسقط (section_sheets)."""
import collections, math, re, sys, os
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


LAST_COLS = []         # نقط الأعمدة في الرسمة كلها (column_points) - بتتستخدم تاني في تقسيم الصفوف
LAST_SOURCE = None     # "section" لو الشيتات جت من عناوين الأقسام (شبابيكها محسوبة من الرسم: مابتكبرش)


def detect(doc, log=print, eps=9.0, margin=1.0, min_cols=6):
    global LAST_SOURCE
    LAST_SOURCE = None
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
    # 3) رسمة مقسومة أقسام بعناوين كبيرة ("FRAMING PLANS" تحت عمود مساقط) والمساقط نفسها من غير
    #    فقاعات ولا عناوين (برج HDB): لو الشيتات اللي فوق مش شايلة أغلب أعمدة الرسمة، الأقسام بتكسب
    cols = column_points(doc)
    global LAST_COLS
    LAST_COLS = cols
    def cover(ws):
        return sum(1 for x, y in cols if any(w[0] <= x <= w[2] and w[1] <= y <= w[3] for _, w in ws))
    if cols and cover(out) < 0.3 * len(cols):
        sec = section_sheets(doc, cols, log)
        if sec and cover(sec) > cover(out):
            log(f"sheets: {len(sec)} from section headers (the other sheets held {cover(out)}/{len(cols)} columns)")
            LAST_SOURCE = "section"
            return [(n, tuple(w)) for n, w in sec]
    if not out:
        from ezdxf import bbox
        b = bbox.extents(doc.modelspace())
        out = [["PLAN", (b.extmin.x - 1, b.extmin.y - 1, b.extmax.x + 1, b.extmax.y + 1)]]
    log(f"sheets: {len(out)} from grid bubbles (titles gave {len(views)})")
    return [(n, tuple(w)) for n, w in out]


HEADER = re.compile(r"FRAM|SLAB|CEIL|LOADING|FOUNDATION|RAFT|COLUMN|AXES|PILE|DETAIL", re.I)
SLAB_HEADER = re.compile(r"FRAM|SLAB|CEIL", re.I)
SIZED = re.compile(r"\(\s*\d{2,4}\s*[*xX×]\s*\d{2,5}\s*\)")
FLOOR_WORD = re.compile(r"(UPPER\s*ROOF|ROOF|GROUND|BASEMENT|MEZZ\w*|TYPICAL|\b\d+\s*(ST|ND|RD|TH)\b|\bGF\b|\bB\d\b)", re.I)


def section_sheets(doc, cols, log=print):
    """
    الرسمة مقسومة أعمدة، وتحت كل عمود عنوان قسم كبير (FRAMING PLANS / LOADING PLANS / FOUNDATION /
    COLUMNS AND AXES). عمود البلاطات = اللي عنوانه FRAMING/SLAB/CEILING. عرضه لحد نص المسافة للعنوان
    اللي جنبه، وجواه المساقط صفوف مفصولة بفراغ رأسي كبير. الاسم من اسم بلوك فيه اسم دور
    (GROUND / 1ST / ROOF...) جوه الصف لو الاسم مش متكرر في صف تاني، وإلا 04_FRAMING (رقم الصف من تحت).
    """
    import statistics
    texts, blocks = [], []
    for e in doc.modelspace():
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r: texts.append(r)
        elif t == "INSERT":
            m = FLOOR_WORD.search(e.dxf.name)
            if m:
                try:
                    from ezdxf import bbox
                    ve = list(SX._explode([e]))
                    b = bbox.extents(ve, fast=True)
                    # البلوك اللي فيه تسميات الكمرات (B4(200X700)) هو بلوك الدور نفسه - وزنه أكبر
                    lab = sum(1 for v in ve if v.dxftype() in ("TEXT", "MTEXT") and SIZED.search(SX._text_of(v)[0] if SX._text_of(v) else ""))
                    if b.has_data:
                        blocks.append((re.sub(r"\s+", "_", m.group(1).upper()), (b.center.x, b.center.y), 3 if lab >= 3 else 1))
                except Exception:
                    pass
    if not texts:
        return []
    # مراكز الرسم الصغير (خطوط/مضلعات/هاتشات < 40 م) - لعرض الصفوف
    geo = []
    from ezdxf import bbox as _bb
    for e in SX._explode(list(doc.modelspace())):
        if e.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE", "HATCH", "CIRCLE", "ARC"):
            try:
                b = _bb.extents([e], fast=True)
                if b.has_data and b.size.x <= 40 and b.size.y <= 40:
                    # الطرفين مش المركز: عنصر عرضه 30 م مركزه جوه وطرفه برّه
                    geo.append((b.extmin.x, b.center.y)); geo.append((b.extmax.x, b.center.y))
            except Exception:
                pass
    hmed = statistics.median(h for _, _, h in texts)
    # مكان العنوان = نص عرضه (نقطة الإدراج أول النص، والعنوان الكبير ممكن يبقى 300 م طول)
    heads = []
    for e in doc.modelspace().query("TEXT MTEXT"):
        r = SX._text_of(e)
        if not r or r[2] < 20 * hmed or not HEADER.search(r[0]) or len(r[0]) > 40:
            continue
        try:
            b = _bb.extents([e]); cx = b.center.x
        except Exception:
            cx = r[1][0] + 0.45 * len(r[0].strip()) * r[2]
        heads.append((r[0].strip(), (cx, r[1][1])))
    heads.sort(key=lambda q: q[1][0])
    if len(heads) < 2:
        return []
    out = []
    for i, (name, (hx, hy)) in enumerate(heads):
        if not SLAB_HEADER.search(name):
            continue
        left = (heads[i - 1][1][0] + hx) / 2 if i > 0 else -1e18
        right = (heads[i + 1][1][0] + hx) / 2 if i + 1 < len(heads) else 1e18
        pts = [(x, y) for x, y in cols if left < x < right and y > hy]
        if len(pts) < 6:
            continue
        ys = sorted(y for _, y in pts)
        span = ys[-1] - ys[0]
        gap = max(10.0, 0.05 * span)
        rows, cur = [], [ys[0]]
        for y in ys[1:]:
            if y - cur[-1] > gap:
                rows.append(cur); cur = [y]
            else:
                cur.append(y)
        rows.append(cur)
        k = 0
        for r in rows:
            rp = [(x, y) for x, y in pts if r[0] <= y <= r[-1]]
            if len(rp) < 6:
                continue
            k += 1
            # عرض الصف من كل الرسم في الصف (مش الأعمدة المهاشرة بس: جزء من المسقط ممكن أعمدته
            # مش مهاشرة)، والحد مع القسم اللي جنبه = أوسع فراغ قريب من نص المسافة بين العنوانين
            gx = sorted(x for x, y in geo if r[0] - 3 <= y <= r[-1] + 3)

            def cut(other):
                # من نص القسم لبرّه: أول فراغ ≥ 25 م = آخر المسقط (الفراغ بين مباني المسقط الواحد
                # ~10 م، وبين قسمين ~100 م)؛ ومايعدّيش 80% من المسافة للعنوان التاني
                lim = hx + 0.8 * (other - hx)
                side = [x for x in gx if (hx <= x <= lim if other > hx else lim <= x <= hx)]
                side.sort(reverse=other < hx)
                for a, b in zip(side, side[1:]):
                    if abs(b - a) >= 25.0:
                        return (a + b) / 2
                return lim
            lo = cut(heads[i - 1][1][0]) if i > 0 else -1e18
            hi = cut(heads[i + 1][1][0]) if i + 1 < len(heads) else 1e18
            inx = [x for x in gx if lo < x < hi]
            if not inx:
                continue
            win = (inx[0] - 1.0, r[0] - 3.0, inx[-1] + 1.0, r[-1] + 3.0)
            score = {}
            for n, (bx, by), w in blocks:
                if win[0] <= bx <= win[2] and win[1] <= by <= win[3]:
                    score[n] = score.get(n, 0) + w
            # رقم الصف من تحت + اسم الدور من البلوك (نفس الاسم ممكن يتكرر في دور متكرر)
            nm = f"{k:02d}_" + (max(score, key=score.get) if score else re.sub(r"[^A-Za-z]+", "_", name).strip("_")[:12])
            out.append([nm, win])
    # اسم البلوك مش دليل أكيد (البلوك بيتنسخ من دور لدور): الاسم المتكرر في أكتر من صف بيتشال،
    # والصف بياخد اسم القسم برقمه بس
    base = collections.Counter(o[0][3:] for o in out)
    for o in out:
        if base[o[0][3:]] > 1:
            o[0] = o[0][:3] + "FRAMING"
    if out:
        log(f"section headers: {[h for h, _ in heads]} -> slab rows {[o[0] for o in out]}")
    return out


if __name__ == "__main__":
    import ezdxf
    d = ezdxf.readfile(sys.argv[1])
    for n, w in detect(d): print(n, [round(v, 1) for v in w])
