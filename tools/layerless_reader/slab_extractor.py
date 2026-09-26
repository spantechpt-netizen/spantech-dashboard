# -*- coding: utf-8 -*-
"""
================================================================================
 Slab Extractor  —  مجموعة مخططات (DWG/DXF، معماري أو إنشائي) -> حدود البلاطات
                    والفتحات لكل دور، بصيغة Auto PT Suite
================================================================================

 ولا قرار هنا مبني على اسم ليّر. البرنامج بيقرا:
   • الشكل: خطوط، أوجه مقفولة، X، درجات سلم، hatch الحوائط.
   • النص المكتوب في الرسمة (مش أسماء الليّرات): عنوان الشيت عشان يعرف الدور،
     وتسميات زي LIFT / FIRE TANK عشان يفرّق الفتحة من الخزان.

 الخطوات لكل مسقط:
   1) حد البلاطة: كل الخطوط تتخن 10 سم، تتملي، الغلاف الخارجي، وترجع تاني.
      لو الخط الخارجي حد أرض (معماري) والحلقة بينه وبين المبنى فاضية ->
      حد المبنى هو اللي بيتاخد.
   2) فتحات X: خطين بيقطعوا بعض في نصهم. الفتحة = الوش المقفول اللي فيه
      التقاطع (لو أطراف الـ X على حدوده)، وإلا رؤوس الـ X ("X*" للمراجعة).
      بتترفض: X من غير أضلاع مرسومة (كمرات مايلة بتقطع بعض)، شبكة 4 خلايا
      أو أكتر (خزان/نقش)، X جوه أوضة مكتوب فيها TANK/ROOM...
   3) بيارات السلالم: درجات متوازية -> المسافة الصافية بين الحوائط.
   4) الأسانسير: أوضة مقفولة بحوائط (hatch) جنب السلم، 1.2-3.4 م، فاضية.
   5) معماري: تسمية LIFT / SHAFT / VOID / DUCT جوه وش مقفول -> فتحة.

 على مستوى المجموعة:
   • الأدوار بتتعرف من العنوان: "X CEILING" (إنشائي) = البلاطة فوق X،
     "X FLOOR PLAN" (معماري) = البلاطة تحت X.
   • المحاذاة: كل الأدوار على بيارات السلالم (متطابقة في كل دور).
   • قاعدة الاستمرار (معماري): فتحة البير في بلاطة تحت الدور N لازم تكون موجودة
     في مسقط الدور N-1 كمان، وإلا بتتعلّم "مراجعة".
   • لو فيه إنشائي ومعماري لنفس البلاطة: الإنشائي هو المرجع، والمعماري مقارنة.

 الاستخدام:
     python slab_extractor.py STR.dwg ARCH.dwg -o out/
     python slab_extractor.py STR.dwg --list                 # الشيتات اللي اتلقت
     python slab_extractor.py plan.dxf --window S4=1081,410,1123,459

 DWG بيتقرا بـ LibreDWG (`dwgread`) - حط مساره في LIBREDWG_DWGREAD لو مش في PATH.
 التحقق الهندسي مسؤولية المهندس المصمم.
================================================================================
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import ezdxf
from ezdxf import bbox as ezbbox, path as ezpath
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layerless_reader as LR  # noqa: E402

__version__ = "0.2.0"

# ------------------------------------------------------------------------------
#  نصوص (محتوى الرسمة، مش أسماء ليّرات)
# ------------------------------------------------------------------------------
OPEN_KW = re.compile(r"\b(LIFT|ELEV\w*|STAIR\w*|SHAFT|VOID|DUCT|SHOOT|CHUTE|OPEN\s*TO\s*BELOW|OPENING)\b"
                     r"|مصعد|اسانسير|أسانسير|سلم|منور|فتحة|شفت|بئر", re.I)
ROOM_KW = re.compile(r"(TANK|ROOM|STORE|PUMP|HALL|SHOP|TOILET|\bTOI\b|BATH|KITCHEN|BED|LIVING"
                     r"|خزان|غرفة|مخزن)", re.I)
TITLE_KW = re.compile(r"(CEILING|SLAB|\bROOF\b(?!ING)|FLOOR\s*PLAN|P\.?\s*HOUSE|PENT\s*HOUSE|سقف|بلاطة|مسقط)", re.I)
EXCLUDE_KW = re.compile(r"(FOUNDATION|RAFT|FOOTING|ELEVATION|SECTION|DETAIL|COLUMN|AXES|GRID|NOTES"
                        r"|SCHEDULE|LEGEND|لبشة|قواعد|واجهة|قطاع|تفاصيل|محاور)", re.I)
SKIP_TYPES = {"DIMENSION", "POINT", "LEADER", "MLEADER", "MULTILEADER", "IMAGE", "WIPEOUT", "VIEWPORT"}


# ------------------------------------------------------------------------------
#  1) فتح الملف
# ------------------------------------------------------------------------------
def load_drawing(path, log=print, workdir=None):
    """DXF مباشرة، أو DWG عن طريق LibreDWG JSON -> DXF نضيف."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dxf":
        try:
            return ezdxf.readfile(path)
        except Exception:
            from ezdxf import recover
            doc, _aud = recover.readfile(path)
            return doc
    if ext != ".dwg":
        raise ValueError(f"unsupported file type: {path}")
    exe = os.environ.get("LIBREDWG_DWGREAD") or shutil.which("dwgread")
    if not exe:
        raise RuntimeError("DWG needs LibreDWG's `dwgread` (set LIBREDWG_DWGREAD), "
                           "or convert the file to DXF first")
    import dwg_json_to_dxf as J
    wd = workdir or tempfile.mkdtemp(prefix="slabx_")
    base = os.path.join(wd, os.path.splitext(os.path.basename(path))[0])
    subprocess.run([exe, "-O", "JSON", "-o", base + ".json", path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    J.convert(J.load_json(base + ".json"), base + ".dxf", log=log)
    return ezdxf.readfile(base + ".dxf")


def _explode(es, depth=0):
    for e in es:
        if e.dxftype() == "INSERT" and depth < 4:
            try:
                yield from _explode(e.virtual_entities(), depth + 1)
            except Exception:
                pass
        else:
            yield e


def _bbox(e):
    try:
        b = ezbbox.extents([e], fast=True)
    except Exception:
        return None
    if not b.has_data:
        return None
    return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)


def _text_of(e):
    try:
        if e.dxftype() == "MTEXT":
            t, p = e.plain_text(), e.dxf.insert
            h = e.dxf.char_height
        else:
            t, p = e.dxf.text, e.dxf.insert
            if e.dxftype() == "TEXT" and (e.dxf.halign or e.dxf.valign):
                p = e.dxf.align_point
            h = e.dxf.height
        return (t or "").strip(), (p.x, p.y), h
    except Exception:
        return None


# ------------------------------------------------------------------------------
#  2) لقي المساقط في مجموعة الشيتات
# ------------------------------------------------------------------------------
@dataclass
class PlanView:
    name: str
    title: str
    window: tuple
    source: str = ""          # struct / arch
    level: float | None = None
    level_to: float | None = None
    slab_level: float | None = None   # البلاطة تحت الدور ده (0 = سقف البدروم)


def _level_from_title(t):
    """(من، إلى) رقم الدور من العنوان. البدروم -1، الأرضي 0، ..."""
    T = t.upper()
    if re.search(r"BASEMENT|بدروم", T):
        return -1, -1
    if re.search(r"GROUND|أرضي|ارضي", T):
        return 0, 0
    if re.search(r"P\.?\s*HOUSE|PENT|روف|ROOF", T):
        return 99, 99
    nums = [int(n) for n in re.findall(r"(\d+)\s*(?:ST|ND|RD|TH)\b", T)]
    if re.search(r"\bFIRST\b", T):
        nums.append(1)
    if re.search(r"\bSECOND\b", T):
        nums.append(2)
    if re.search(r"\bTYPICAL\b|متكرر", T) and not nums:
        return 2, 2
    if nums:
        return min(nums), max(nums)
    return None, None


def find_plan_views(doc, log=print, min_entities=25, min_area=300.0):
    """المساقط = تجمعات خطوط كبيرة (15-200 م)، واسمها من عنوان جنبها/في نفس الإطار."""
    msp = doc.modelspace()
    items, texts, frames = [], [], []
    for e in msp:
        et = e.dxftype()
        if et in ("TEXT", "MTEXT"):
            r = _text_of(e)
            if r and r[0]:
                texts.append(r)
            continue
        if et == "INSERT":
            try:
                for a in e.attribs:
                    texts.append((a.dxf.text.strip(), (a.dxf.insert.x, a.dxf.insert.y), a.dxf.height))
            except Exception:
                pass
        if et in SKIP_TYPES:
            continue
        b = _bbox(e)
        if not b:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        if w > 250 or h > 250:
            continue
        if et == "LWPOLYLINE" and w > 40 and h > 25 and 4 <= len(e) <= 5 and 1.25 <= w / h <= 1.75:
            pts = [tuple(p) for p in e.get_points("xy")]
            if all(abs(p[0] - b[0]) < 0.01 * w or abs(p[0] - b[2]) < 0.01 * w for p in pts) and \
                    abs(Polygon(pts).area - w * h) < 0.01 * w * h:
                frames.append(b)      # إطار شيت: مستطيل أفقي بنسبة ورق (A-series ≈ 1.41)
                continue
        if max(w, h) > 60:
            continue          # حدود/خطوط تايهة بتلزق المساقط في بعض
        items.append(b)
    if not items:
        return []
    # union-find على صناديق متقاربة (شبكة 2 م)
    tol = 1.2
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = 4.0
    grid = {}
    for i, (x0, y0, x1, y1) in enumerate(items):
        for gx in range(int((x0 - tol) // cell), int((x1 + tol) // cell) + 1):
            for gy in range(int((y0 - tol) // cell), int((y1 + tol) // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    for lst in grid.values():
        for a in range(len(lst)):
            ia = lst[a]
            A = items[ia]
            for b in range(a + 1, len(lst)):
                ib = lst[b]
                B = items[ib]
                if A[0] - tol <= B[2] and B[0] - tol <= A[2] and A[1] - tol <= B[3] and B[1] - tol <= A[3]:
                    ra, rb = find(ia), find(ib)
                    if ra != rb:
                        parent[ra] = rb
    comps = {}
    for i in range(len(items)):
        comps.setdefault(find(i), []).append(i)
    cands = []
    for idx in comps.values():
        if len(idx) < min_entities:
            continue
        x0 = min(items[i][0] for i in idx)
        y0 = min(items[i][1] for i in idx)
        x1 = max(items[i][2] for i in idx)
        y1 = max(items[i][3] for i in idx)
        if not (12 <= x1 - x0 <= 200 and 12 <= y1 - y0 <= 200) or (x1 - x0) * (y1 - y0) < min_area:
            continue
        cands.append((x0, y0, x1, y1, len(idx)))

    def frame_of(bx):
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
        fs = [f for f in frames if f[0] <= cx <= f[2] and f[1] <= cy <= f[3]]
        return min(fs, key=lambda f: (f[2] - f[0]) * (f[3] - f[1])) if fs else None

    views, used_frames = [], {}
    # أكبر تجمع بنسبة أبعاد معقولة الأول: لوحة العنوان والجداول طويلة/صغيرة
    def score(c):
        w, h = c[2] - c[0], c[3] - c[1]
        return (max(w, h) / max(min(w, h), 1e-6) <= 2.5, w * h)
    for c in sorted(cands, key=score, reverse=True):
        if max(c[2] - c[0], c[3] - c[1]) / max(min(c[2] - c[0], c[3] - c[1]), 1e-6) > 2.5:
            continue
        fr = frame_of(c)
        if fr is not None:
            pool = [t for t in texts if fr[0] <= t[1][0] <= fr[2] and fr[1] <= t[1][1] <= fr[3]]
        else:
            hgt = c[3] - c[1]
            pool = [t for t in texts if c[0] - 5 <= t[1][0] <= c[2] + 5
                    and c[1] - 14 <= t[1][1] <= c[1] + 0.15 * hgt]
        # عنوان الشيت = أكبر نص من نوع "مسقط" أو "مستبعد" (RAFT DETAILS...)
        titled = [t for t in pool if TITLE_KW.search(t[0]) or EXCLUDE_KW.search(t[0])]
        if not titled:
            continue
        title = max(titled, key=lambda t: t[2])[0]
        if not TITLE_KW.search(title):
            continue
        title = " ".join(title.replace("%%U", "").replace("%%u", "").split())
        if EXCLUDE_KW.search(title) and not re.search(r"CEILING|SLAB|FLOOR\s*PLAN", title, re.I):
            continue
        if fr is not None:
            if fr in used_frames:   # نفس الإطار: جدول/لوحة عنوان جنب المسقط
                continue
            used_frames[fr] = True
        src = "struct" if re.search(r"CEILING|SLAB|سقف|بلاطة", title, re.I) else "arch"
        lo, hi = _level_from_title(title)
        v = PlanView(name="", title=title, window=(c[0] - 0.5, c[1] - 0.5, c[2] + 0.5, c[3] + 0.5),
                     source=src, level=lo, level_to=hi)
        if lo is not None:
            v.slab_level = (lo + 1) if src == "struct" else lo
        views.append(v)
    # أسماء: رقم الشيت لو مكتوب (S4...) وإلا من العنوان
    views.sort(key=lambda v: (v.slab_level if v.slab_level is not None else 1e9, v.window[0]))
    seen = {}
    for v in views:
        base = re.sub(r"[^A-Z0-9]+", "_", v.title.upper()).strip("_")[:40] or "PLAN"
        seen[base] = seen.get(base, 0) + 1
        v.name = base if seen[base] == 1 else f"{base}_{seen[base]}"
    log(f"المساقط: {len(views)} - " + "، ".join(f"{v.name} [{v.source}]" for v in views))
    return views


# ------------------------------------------------------------------------------
#  3) قراءة مسقط واحد
# ------------------------------------------------------------------------------
@dataclass
class Opening:
    poly: list
    kind: str                 # X / X* / stair / lift / label:<word>
    status: str = "ok"        # ok / review
    note: str = ""


@dataclass
class SlabResult:
    view: PlanView
    outline: list
    openings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    segs: list = field(default_factory=list)       # للرسم بس
    rejected: dict = field(default_factory=dict)
    shift: tuple = (0.0, 0.0)                       # للمحاذاة المشتركة
    parts: list = field(default_factory=list)       # حدود كل مبنى منفصل كبير في نفس الإطار (bounds)

    @property
    def area(self):
        return Polygon(self.outline).area

    def polys(self):
        return [Polygon(o.poly) for o in self.openings]


def _ang(c):
    return math.degrees(math.atan2(c[1][1] - c[0][1], c[1][0] - c[0][0])) % 180


def _rect_dims(g):
    r = g.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return 0.0, 0.0
    cs = list(r.exterior.coords)
    a, b = math.dist(cs[0], cs[1]), math.dist(cs[1], cs[2])
    return max(a, b), min(a, b)


def collect(doc, window):
    x0, y0, x1, y1 = window
    lines, segs, hatches, texts, rings = [], [], [], [], []
    for e in doc.modelspace():
        b = _bbox(e)
        if not b or not (b[0] >= x0 and b[2] <= x1 and b[1] >= y0 and b[3] <= y1):
            continue
        if e.dxftype() == "INSERT":
            try:
                for a in e.attribs:
                    texts.append((Point(a.dxf.insert.x, a.dxf.insert.y), a.dxf.text.strip()))
            except Exception:
                pass
        for s in _explode([e]):
            et = s.dxftype()
            if et in ("HATCH", "SOLID"):
                try:
                    acc = None
                    rings = (LR.hatch_rings(s) if et == "HATCH" else
                             [[(v.x, v.y) for v in ezpath.make_path(s).flattening(0.01)]])
                    for pp in rings:
                        if len(pp) >= 3:
                            hp = Polygon(pp).buffer(0)
                            if not hp.is_empty:
                                acc = hp if acc is None else acc.symmetric_difference(hp)  # even-odd
                    if acc is not None:
                        hatches.extend(g for g in getattr(acc, "geoms", [acc])
                                       if g.geom_type == "Polygon" and g.area > 1e-4)
                except Exception:
                    pass
                continue
            if et in ("TEXT", "MTEXT", "ATTRIB"):
                r = _text_of(s)
                if r and r[0]:
                    texts.append((Point(r[1]), r[0]))
                continue
            if et in SKIP_TYPES or et in ("INSERT",):
                continue
            try:
                pts = [(v.x, v.y) for v in ezpath.make_path(s).flattening(0.01)]
            except Exception:
                continue
            if et == "LWPOLYLINE" and s.closed and len(pts) > 2:
                pts.append(pts[0])
            if len(pts) >= 2:
                ls = LineString(pts)
                # دايرة كاملة قطرها > 3 م (شجرة/دوران/رمز) مش حد بلاطة - بتتشال من الحد بس
                ring_symbol = False
                if et in ("CIRCLE", "ELLIPSE", "SPLINE") and ls.is_ring and len(pts) > 12:
                    pg = Polygon(pts)
                    ring_symbol = (pg.is_valid and pg.area > math.pi * 1.5 ** 2
                                   and pg.area / pg.minimum_rotated_rectangle.area > 0.7)
                (rings if ring_symbol else lines).append(ls)
                for i in range(len(pts) - 1):
                    if math.dist(pts[i], pts[i + 1]) > 1e-4:
                        segs.append((pts[i], pts[i + 1]))
    # نفس الخط مرسوم أكتر من مرة (شائع) بيبوّظ مسافات الدرجات
    seen, uniq = set(), []
    for s in segs:
        k = tuple(sorted([(round(s[0][0], 3), round(s[0][1], 3)), (round(s[1][0], 3), round(s[1][1], 3))]))
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return lines, uniq, hatches, texts, rings


def extract_slab(doc, view: PlanView, gap=0.10, log=print) -> SlabResult:
    lines, segs, hatches, texts, _rings = collect(doc, view.window)
    notes, rejected = [], {}

    # ---- X: خطين بيقطعوا بعض في نصهم ----
    diag = [LineString(s) for s in segs if 0.6 <= math.dist(*s) <= 25]
    tree = STRtree(diag) if diag else None
    pairs, used = [], set()
    for i, a in enumerate(diag):
        if i in used:
            continue
        for j in tree.query(a):
            j = int(j)
            if j <= i or j in used:
                continue
            b = diag[j]
            if not a.crosses(b):
                continue
            p = a.intersection(b)
            if p.geom_type != "Point":
                continue
            if not (0.25 < a.project(p) / a.length < 0.75 and 0.25 < b.project(p) / b.length < 0.75):
                continue
            dd = abs(_ang(list(a.coords)) - _ang(list(b.coords)))
            if min(dd, 180 - dd) < 20:
                continue
            (a0, a1), (b0, b1) = list(a.coords), list(b.coords)
            q = Polygon([a0, b0, a1, b1])
            if not q.is_valid:
                q = Polygon([a0, b1, a1, b0])
            if not q.is_valid or q.area < 0.2 or q.convex_hull.area > 1.05 * q.area:
                continue
            used.update((i, j))
            pairs.append((p, q, a, b))
            break

    # ---- درجات السلالم ----
    prims = [LR.Prim("seg", pts=[s[0], s[1]]) for s in segs]
    flights = LR.detect_stairs(prims, lambda m: None)
    diag_keys = {tuple(round(v, 3) for c in l.coords for v in c) for _, _, a, b in pairs for l in (a, b)}
    keep = [LineString(s) for pr, s in zip(prims, segs)
            if pr.tag != "stair" and tuple(round(v, 3) for c in s for v in c) not in diag_keys]

    # حوائط = hatch رفيع (سمك متوسط ≤ 60 سم) وطويل (≥ 1 م). دوّاير الـ hatch الكبيرة مش حوائط.
    wall_h = [h for h in hatches if h.area < 60 and _rect_dims(h)[0] >= 1.0 and h.area / (h.length / 2) <= 0.6]
    hb = []
    for h in wall_h:
        hb.append(LineString(h.exterior.coords))
        hb += [LineString(r.coords) for r in h.interiors]
    faces = [f for f in polygonize(unary_union(keep + hb)) if f.area > 0.2]
    ftree = STRtree(faces) if faces else None

    def smallest_face(pt):
        if ftree is None:
            return None
        c = [faces[int(k)] for k in ftree.query(pt) if faces[int(k)].contains(pt)]
        return min(c, key=lambda f: f.area) if c else None

    xs = []
    for p, q, a, b in pairs:
        f = smallest_face(p)
        qr = q.minimum_rotated_rectangle
        ends = [c for l in (a, b) for c in (list(l.coords)[0], list(l.coords)[-1])]
        ends_ok = f is not None and sum(f.exterior.distance(Point(c)) <= 0.3 for c in ends) >= 3
        if f is not None and ends_ok and 0.6 * q.area <= f.area <= 1.3 * qr.area:
            if f.area / f.minimum_rotated_rectangle.area > 0.8 and len(f.exterior.coords) > 5:
                f = f.minimum_rotated_rectangle
            xs.append((f, "X"))
        else:
            xs.append((q, "X*"))

    stree = STRtree(keep) if keep else None

    def sides_ok(poly):
        cs = list(poly.exterior.coords)
        n, ok = len(cs) - 1, 0
        for k in range(n):
            e = LineString([cs[k], cs[k + 1]])
            if e.length < 0.05:
                ok += 1
                continue
            cov = 0.0
            for kk in (stree.query(e.buffer(0.08)) if stree else []):
                l = keep[int(kk)]
                dd = abs(_ang(list(e.coords)) - _ang(list(l.coords)))
                if min(dd, 180 - dd) < 6:
                    cov += e.intersection(l.buffer(0.08)).length
            if cov >= 0.6 * e.length:
                ok += 1
        return ok >= n - 1

    xs = [(f, s) for f, s in xs if s == "X" or sides_ok(f)]
    rejected["beam_crossing"] = len(pairs) - len(xs)

    # شبكة X (خزان/نقش) أو X جوه أوضة مسماة -> مش فتحة
    def labels_in(poly):
        g = poly.buffer(0.05)
        return [t for p, t in texts if t and g.contains(p)]

    polys = [f for f, _ in xs]
    comp = list(range(len(polys)))

    def cf(i):
        while comp[i] != i:
            comp[i] = comp[comp[i]]
            i = comp[i]
        return i

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if polys[i].distance(polys[j]) < 0.12:
                comp[cf(i)] = cf(j)
    sizes = {}
    for i in range(len(polys)):
        sizes[cf(i)] = sizes.get(cf(i), 0) + 1
    kept, n_grid, n_room = [], 0, 0
    for i, (f, s) in enumerate(xs):
        labs = labels_in(f)
        glabs = labels_in(unary_union([polys[k] for k in range(len(polys)) if cf(k) == cf(i)]))
        if any(OPEN_KW.search(t) for t in labs + glabs):
            kept.append((f, s))
        elif sizes[cf(i)] >= 4:
            n_grid += 1
        elif any(ROOM_KW.search(t) for t in labs):
            n_room += 1
        else:
            kept.append((f, s))
    rejected["x_grid"], rejected["x_in_named_room"] = n_grid, n_room
    ded = []
    for f, s in kept:
        if not any(f.intersection(g).area > 0.7 * min(f.area, g.area) for g, _ in ded):
            ded.append((f, s))
    xs = ded

    # ---- بيارات السلالم ----
    wall_b = unary_union(wall_h).boundary if wall_h else None
    long_keep = [l for l in keep if l.length > 0.5]

    def probe_well(gb, reach=1.8, side=0.35):
        bx0, by0, bx1, by1 = gb.bounds
        w_, h_ = bx1 - bx0, by1 - by0

        def hit(p0, p1):
            ray = LineString([(p0[0] - (p1[0] - p0[0]) * 0.01, p0[1] - (p1[1] - p0[1]) * 0.01), p1])
            if wall_b is not None:
                pt = wall_b.intersection(ray)
                if not pt.is_empty:
                    return min(Point(p0).distance(g) for g in getattr(pt, "geoms", [pt]))
            best = None
            for l in long_keep:
                if l.intersects(ray):
                    d_ = Point(p0).distance(l.intersection(ray))
                    best = d_ if best is None or d_ < best else best
            return best

        def extend(dirn, lim):
            ds = []
            for t in (0.2, 0.5, 0.8):
                if dirn in "NS":
                    x, y = bx0 + t * w_, (by1 if dirn == "N" else by0)
                    ds.append(hit((x, y), (x, y + lim) if dirn == "N" else (x, y - lim)))
                else:
                    x, y = (bx1 if dirn == "E" else bx0), by0 + t * h_
                    ds.append(hit((x, y), (x + lim, y) if dirn == "E" else (x - lim, y)))
            ds = [d_ for d_ in ds if d_ is not None]
            return min(ds) if len(ds) >= 2 else 0.0

        ns = h_ >= w_ * 0.8
        return box(bx0 - extend("W", side if ns else reach), by0 - extend("S", reach if ns else side),
                   bx1 + extend("E", side if ns else reach), by1 + extend("N", reach if ns else side))

    groups = []
    for fl in flights:
        fb = box(*LR._bbox(fl))
        for k, g in enumerate(groups):
            if g.distance(fb) < 0.6:
                groups[k] = g.union(fb).envelope
                break
        else:
            groups.append(fb)
    wells = []
    for gb in groups:
        cand = [Polygon(f.exterior) for f in faces
                if Polygon(f.exterior).buffer(0.05).contains(gb) and Polygon(f.exterior).area < 60]
        f = min(cand, key=lambda p: p.area) if cand else None
        if f is not None and f.area > 3.0 * gb.area:
            f = None                        # الوش فيه لوبي/طرقة مع السلم
        if f is not None:
            mrr = f.minimum_rotated_rectangle
            w = mrr if f.area / mrr.area > 0.7 else f
        else:
            w = probe_well(gb)
        if not any(x.intersects(w.buffer(-0.05)) for x in wells):
            wells.append(w)

    # ---- أسانسير: أوضة مقفولة بحوائط جنب السلم ----
    lifts = []
    if wall_h and wells:
        cw = unary_union(wall_h).buffer(0.6, join_style=2).buffer(-0.6, join_style=2)
        rooms = [Polygon(r.coords) for p in getattr(cw, "geoms", [cw]) for r in p.interiors]
        for f in rooms:
            if not (1.4 <= f.area <= 10):
                continue
            if any(f.intersects(w.buffer(-0.1)) for w in wells) or min(f.distance(w) for w in wells) > 0.6:
                continue
            L, S = _rect_dims(f)
            if not (1.2 <= S and L <= 3.4 and f.area / f.minimum_rotated_rectangle.area > 0.85):
                continue
            if any(x.intersects(f.buffer(-0.05)) for x, _ in xs):
                continue
            lifts.append(f.minimum_rotated_rectangle)

    # ---- تسمية LIFT/SHAFT/VOID جوه وش مقفول (معماري) ----
    labelled = []
    for p, t in texts:
        if not OPEN_KW.search(t or ""):
            continue
        cand = [Polygon(f.exterior) for f in faces if Polygon(f.exterior).contains(p) and 0.4 <= Polygon(f.exterior).area <= 40]
        if not cand:
            continue
        f = min(cand, key=lambda q: q.area)
        taken = [x for x, _ in xs] + wells + lifts + [l for l, _ in labelled]
        if any(f.intersects(o.buffer(-0.05)) for o in taken):
            continue
        mrr = f.minimum_rotated_rectangle
        labelled.append((mrr if f.area / mrr.area > 0.85 else f, OPEN_KW.search(t).group(0).upper()))

    # ---- حد البلاطة ----
    thick = unary_union([l.buffer(gap, cap_style=2, join_style=2) for l in lines] + [x.buffer(0.01) for x, _ in xs])
    filled = [Polygon(p.exterior) for p in getattr(thick, "geoms", [thick])]
    # كذا مبنى منفصل في نفس الإطار (أبراج جنب بعض): كل واحد ≥ 25% من الأكبر و ≥ 50 م² بيتسجل
    # المباني بتتوصل ببعض أحيانًا بخط لوحده (محور، خط منسوب): رقبة أرفع من 40 سم مش بلاطة، فبتتشال الأول
    opened = []
    for p in filled:
        q = p.buffer(-0.2 - gap, join_style=2).buffer(0.2, join_style=2)
        opened += [g for g in getattr(q, "geoms", [q]) if g.geom_type == "Polygon" and not g.is_empty]
    big = max((p.area for p in opened), default=0.0)
    parts = [p.bounds for p in opened if p.area >= max(50.0, 0.25 * big)]
    slab = max(filled, key=lambda p: p.area).buffer(-gap, join_style=2).buffer(0)
    # حاجة لازقة في الحد برقبة أرفع من 40 سم (دايرة رمز، خط مستوى...) مش بلاطة
    slab = slab.buffer(-0.2, join_style=2).buffer(0.2, join_style=2).intersection(slab)
    if isinstance(slab, MultiPolygon) or slab.geom_type == "GeometryCollection":
        slab = max([g for g in getattr(slab, "geoms", [slab]) if g.geom_type == "Polygon"], key=lambda p: p.area)
    slab = Polygon(slab.exterior).simplify(0.02)

    # حد أرض مقابل حد مبنى (معماري): الخط الخارجي لوحده والحلقة بينه وبين المبنى فاضية
    try:
        edge = slab.exterior.buffer(0.25)
        dls = [a for _, _, a, _ in pairs] + [b for _, _, _, b in pairs]
        dtree = STRtree(dls) if dls else None

        def is_diag(l):
            return dtree is not None and any(dls[int(k)].buffer(0.02).contains(l) for k in dtree.query(l))

        inner_lines = [l for l in lines if not l.within(edge) and l.length > 0.05 and not is_diag(l)]
        if inner_lines:
            th = unary_union([l.buffer(gap, cap_style=2, join_style=2) for l in inner_lines])
            th = unary_union([Polygon(p.exterior) for p in getattr(th, "geoms", [th])])
            inn = th.buffer(-gap, join_style=2)
            inn = max(getattr(inn, "geoms", [inn]), key=lambda p: p.area)
            inner = Polygon(inn.exterior).simplify(0.02)
            ring = slab.difference(inner.buffer(0.3, join_style=2))
            dens = sum(l.intersection(ring).length for l in inner_lines if l.length < 8) / max(ring.area, 1e-6)
            # قاعدة المسقط المعماري بس: في الإنشائي الخط الخارجي هو حد البلاطة دايمًا
            # (مسقط برج فيه أعمدة و drop panels بس في الحلقة كان بيتقري "أرض فاضية")
            if (inner.area < 0.9 * slab.area and dens < 0.15 and ring.area > 30
                    and view.source != "struct"):
                notes.append(f"الخط الخارجي حد أرض (الحلقة {ring.area:.0f} م² فاضية تقريبًا) - اتاخد حد المبنى")
                slab = inner
    except Exception as ex:  # الفحص ده تحسين، مش شرط
        notes.append(f"فحص حد الأرض اتخطّى: {ex}")

    ops = []
    for q, k in xs:
        if not slab.buffer(0.1).contains(q.centroid):
            continue
        qq = q.intersection(slab)
        if qq.is_empty or qq.area < 0.5 * q.area:
            continue
        qq = max(getattr(qq, "geoms", [qq]), key=lambda g: g.area)
        ops.append(Opening(list(qq.exterior.coords)[:-1], k,
                           "review" if k == "X*" else "ok",
                           "الحدود من رؤوس الـ X" if k == "X*" else ""))
    ops += [Opening(list(w.exterior.coords)[:-1], "stair", "ok", "المسافة الصافية بين الحوائط") for w in wells]
    ops += [Opening(list(w.exterior.coords)[:-1], "lift", "ok", "أوضة مقفولة بحوائط جنب السلم") for w in lifts]
    ops += [Opening(list(w.exterior.coords)[:-1], "label:" + lab, "ok", f"مكتوب {lab}") for w, lab in labelled]
    ops = [o for o in ops if Polygon(o.poly).area > 0.05]
    ops.sort(key=lambda o: (-round(Polygon(o.poly).centroid.y / 2), Polygon(o.poly).centroid.x))
    out = SlabResult(view, list(slab.exterior.coords)[:-1], ops, notes, segs, rejected)
    out.parts = parts if len(parts) >= 2 else []
    return out


# ------------------------------------------------------------------------------
#  4) المحاذاة وقاعدة الاستمرار والمقارنة
# ------------------------------------------------------------------------------
def _stairs(r):
    return [Polygon(o.poly).centroid for o in r.openings if o.kind == "stair"]


def align_shift(ref: SlabResult, other: SlabResult, tol=0.5):
    """إزاحة other عشان بيارات سلالمه تيجي على بيارات ref. بترجع (dx, dy, خطأ) أو None."""
    a, b = _stairs(ref), _stairs(other)
    best = None
    if len(a) >= 2 and len(b) >= 2:
        for i in a:
            for j in a:
                if i is j:
                    continue
                d1 = (j.x - i.x, j.y - i.y)
                for k in b:
                    for l in b:
                        if k is l:
                            continue
                        e = math.dist(d1, (l.x - k.x, l.y - k.y))
                        if best is None or e < best[0]:
                            best = (e, ((i.x + j.x) - (k.x + l.x)) / 2, ((i.y + j.y) - (k.y + l.y)) / 2)
    if best and best[0] <= tol:
        return best[1], best[2], best[0]
    return None


def match_ratio(p, pool):
    m = [q.intersection(p).area / min(q.area, p.area) for q in pool if q.intersects(p)]
    return max(m) if m else 0.0


def apply_continuity(upper: SlabResult, lower: SlabResult | None):
    """معماري: فتحة في البلاطة تحت الدور N = بير موجود في مسقط N-1 كمان."""
    for o in upper.openings:
        if o.kind in ("X", "X*") or o.kind.startswith("label") or o.kind in ("stair", "lift"):
            if lower is None:
                o.status, o.note = "review", (o.note + "; " if o.note else "") + "مفيش مسقط تحت للتأكيد"
                continue
            # إحداثيات upper -> المرجع (+upper.shift) -> إحداثيات lower (-lower.shift)
            p = affinity.translate(Polygon(o.poly), upper.shift[0] - lower.shift[0], upper.shift[1] - lower.shift[1])
            if match_ratio(p, lower.polys()) < 0.5:
                o.status = "review"
                o.note = (o.note + "; " if o.note else "") + "مش موجود في الدور اللي تحت - غالبًا مش بيقطع البلاطة"


def compare(primary: SlabResult, other: SlabResult):
    sh = align_shift(primary, other)
    if sh is None:
        return None
    ap = affinity.translate(Polygon(other.outline), sh[0], sh[1])
    sp = Polygon(primary.outline)
    iou = sp.intersection(ap).area / sp.union(ap).area
    ao = [affinity.translate(p, sh[0], sh[1]) for p in other.polys()]
    so = primary.polys()
    matched = sum(1 for q in ao if match_ratio(q, so) >= 0.5)
    ox, oy = min(p[0] for p in primary.outline), min(p[1] for p in primary.outline)
    only_other = [{"type": o.kind, "area_m2": round(q.area, 1),
                   "at": (round(q.centroid.x - ox, 2), round(q.centroid.y - oy, 2))}
                  for o, q in zip(other.openings, ao) if match_ratio(q, so) < 0.5]
    only_primary = [{"type": o.kind, "area_m2": round(p.area, 1),
                     "at": (round(p.centroid.x - ox, 2), round(p.centroid.y - oy, 2))}
                    for o, p in zip(primary.openings, so) if match_ratio(p, ao) < 0.5]
    return {"only_in_architectural": only_other, "only_in_structural": only_primary,"iou": round(iou, 4), "max_boundary_dev_m": round(sp.exterior.hausdorff_distance(ap.exterior), 2),
            "openings_primary": len(so), "openings_other": len(ao), "matched": matched,
            "shift": (round(sh[0], 3), round(sh[1], 3)), "stair_fit_error_m": round(sh[2], 3)}


# ------------------------------------------------------------------------------
#  5) الكتابة
# ------------------------------------------------------------------------------
def write_clean_dxf(path, r: SlabResult, origin=(0.0, 0.0)):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    doc.layers.add("PT-Clean-Boundary", color=7)
    doc.layers.add("PT-Clean-Openings", color=2)
    msp = doc.modelspace()
    ox, oy = origin

    def mm(pts):
        return [((x - ox) * 1000.0, (y - oy) * 1000.0) for x, y in pts]

    msp.add_lwpolyline(mm(r.outline), close=True, dxfattribs={"layer": "PT-Clean-Boundary"})
    for o in r.openings:
        msp.add_lwpolyline(mm(o.poly), close=True, dxfattribs={"layer": "PT-Clean-Openings"})
    doc.saveas(path)


def write_overlay_png(path, r: SlabResult, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MP
    xs = [p[0] for p in r.outline]
    ys = [p[1] for p in r.outline]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    fig = plt.figure(figsize=(12, 12 * h / max(w, 1e-6) + 0.8))
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.9])
    for a, b in r.segs:
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#b5b5b5", lw=0.35)
    ax.add_patch(MP(r.outline, closed=True, fill=True, fc="#ffd96633", ec="#d62728", lw=2.2))
    for i, o in enumerate(r.openings):
        rev = o.status != "ok"
        ax.add_patch(MP(o.poly, closed=True, fill=True, fc="#ff990088" if rev else "#1f77b466",
                        ec="#cc6600" if rev else "#1f4fb4", lw=1.5))
        c = Polygon(o.poly).centroid
        ax.text(c.x, c.y, f"O{i + 1}", color="#8a4500" if rev else "#0b2a80", fontsize=9,
                weight="bold", ha="center", va="center")
    ax.set_xlim(min(xs) - 1, max(xs) + 1)
    ax.set_ylim(min(ys) - 1, max(ys) + 1)
    ax.set_aspect("equal")
    ax.axis("off")
    net = r.area - sum(p.area for p in r.polys())
    fig.suptitle(f"{title or r.view.title}\nslab {r.area:.0f} m2, net {net:.0f} m2, {len(r.openings)} openings"
                 f"  (blue = ok, orange = review)", fontsize=12)
    fig.savefig(path, dpi=90, facecolor="white")
    plt.close(fig)


def run(paths, out_dir, windows=None, only=None, log=print):
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for path in paths:
        doc = load_drawing(path, log=log, workdir=out_dir)
        if windows:
            views = [PlanView(name=n, title=n, window=w, source="struct") for n, w in windows.items()]
        else:
            views = find_plan_views(doc, log=log)
        for v in views:
            if only and v.name not in only:
                continue
            r = extract_slab(doc, v, log=log)
            r.source_file = os.path.basename(path)
            results.append(r)

    # ---- محاذاة: المرجع أول إنشائي فيه سلمين ----
    ref = next((r for r in results if r.view.source == "struct" and len(_stairs(r)) >= 2), None) \
        or next((r for r in results if len(_stairs(r)) >= 2), None)
    for r in results:
        if ref is None or r is ref:
            continue
        sh = align_shift(ref, r)
        if sh:
            r.shift = (sh[0], sh[1])
        else:
            r.notes.append("مااتحاذاش مع باقي الأدوار (أقل من سلمين مشتركين)")
    if ref is not None:
        rx0, ry0 = min(p[0] for p in ref.outline), min(p[1] for p in ref.outline)
    else:
        rx0 = ry0 = 0.0

    # ---- قاعدة الاستمرار للمعماري ----
    arch = sorted([r for r in results if r.view.source == "arch" and r.view.slab_level is not None],
                  key=lambda r: r.view.slab_level)
    for r in arch:
        lvl = r.view.slab_level
        if lvl < 0:
            continue                      # بلاطة الأرض/اللبشة: مفيش دور تحتها
        if lvl == 99:                     # بنتهاوس/سطح: اللي تحته آخر دور متكرر
            below = [x for x in arch if 2 <= x.view.slab_level < 99]
            lower = max(below, key=lambda x: x.view.slab_level) if below else None
        else:
            lower = next((x for x in arch if x.view.slab_level == lvl - 1), None)
        apply_continuity(r, lower)

    # ---- مقارنة إنشائي/معماري لنفس البلاطة ----
    comps = []
    for a in [r for r in results if r.view.source == "arch"]:
        for s in [r for r in results if r.view.source == "struct"]:
            if a.view.slab_level is None or s.view.slab_level is None:
                continue
            s_lo = s.view.slab_level
            s_hi = (s.view.level_to + 1) if s.view.level_to is not None else s_lo
            a_lvl = a.view.slab_level if a.view.slab_level != 99 else None
            same = (a_lvl is not None and s_lo <= a_lvl <= s_hi) or \
                   (a.view.slab_level == 99 and s.view.level_to is not None and s_hi == max(
                       (x.view.level_to or -9) + 1 for x in results if x.view.source == "struct"))
            if same:
                c = compare(s, a)
                if c:
                    comps.append({"structural": s.view.name, "architectural": a.view.name, **c})

    for r in results:
        log(f"{r.view.name} [{r.view.source}]: بلاطة {r.area:.0f} م²، {len(r.openings)} فتحة "
            f"({sum(o.status != 'ok' for o in r.openings)} مراجعة)")

    # ---- الكتابة ----
    rows, report = [], {"version": __version__, "slabs": [], "comparisons": comps}
    for r in results:
        ox, oy = rx0 - r.shift[0], ry0 - r.shift[1]
        write_clean_dxf(os.path.join(out_dir, f"{r.view.name}_slab_clean.dxf"), r, origin=(ox, oy))
        write_overlay_png(os.path.join(out_dir, f"{r.view.name}_overlay.png"), r)
        for i, o in enumerate(r.openings):
            p = Polygon(o.poly)
            L, S = _rect_dims(p)
            rows.append([r.view.name, r.view.source, f"O{i + 1}", o.kind, o.status, round(L, 2), round(S, 2),
                         round(p.area, 2), round(p.centroid.x - ox, 2), round(p.centroid.y - oy, 2), o.note])
        report["slabs"].append({
            "name": r.view.name, "title": r.view.title, "source": r.view.source,
            "file": getattr(r, "source_file", ""), "window": r.view.window,
            "slab_level": r.view.slab_level, "area_m2": round(r.area, 1),
            "net_area_m2": round(r.area - sum(p.area for p in r.polys()), 1),
            "openings": len(r.openings), "review": sum(o.status != "ok" for o in r.openings),
            "rejected": r.rejected, "notes": r.notes})
    with open(os.path.join(out_dir, "openings.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["slab", "source", "id", "type", "status", "length_m", "width_m", "area_m2", "x_m", "y_m", "note"])
        w.writerows(rows)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    for c in comps:
        log(f"مقارنة {c['structural']} × {c['architectural']}: تطابق الحدود {c['iou']:.3f}، "
            f"فتحات متطابقة {c['matched']}/{c['openings_other']}")
    return results, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Slab boundaries and openings from DWG/DXF sets "
                                             "(architectural or structural), without layer names.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", default="slab_out")
    ap.add_argument("--list", action="store_true", help="only list the plan views found")
    ap.add_argument("--only", help="comma-separated view names")
    ap.add_argument("--window", action="append", help="NAME=x0,y0,x1,y1 (skips auto-detection)")
    a = ap.parse_args(argv)
    if a.list:
        for p in a.inputs:
            for v in find_plan_views(load_drawing(p)):
                print(f"{v.name:40s} {v.source:6s} slab_level={v.slab_level}  window={tuple(round(x, 1) for x in v.window)}")
        return 0
    windows = None
    if a.window:
        windows = {}
        for s in a.window:
            n, w = s.split("=")
            windows[n] = tuple(float(x) for x in w.split(","))
    run(a.inputs, a.out, windows=windows, only=set(a.only.split(",")) if a.only else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
