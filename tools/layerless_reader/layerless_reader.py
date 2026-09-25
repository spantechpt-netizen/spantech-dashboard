# -*- coding: utf-8 -*-
"""
================================================================================
 Layerless Reader  —  مخطط معماري/إنشائي DXF  ->  DXF نضيف لـ Auto PT Suite
================================================================================

 الفكرة: **ولا قرار واحد هنا مبني على اسم الليّر.** كل عنصر في الرسمة بيتصنّف
 لوحده من شكله ومقاسه وتعبئته (hatch) وتكراره ومكانه من المحاور. الليّر بيتقرا
 بس عشان نعرف لو مقفول/مطفي (عنصر مش ظاهر في الرسمة) وعشان نحل ByLayer للون
 ونوع الخط - يعني خصائص الرسم نفسه، مش التسمية.

 الناتج بنفس صيغة `_write_clean_dxf` في البرنامج الأساسي (مليمتر،
 $INSUNITS = 4)، على طبقات `guess_role` بيعرفها بثقة 1.0:

     PT-Clean-Columns      -> column
     PT-Clean-Walls        -> wall      (حوائط خرسانية = ركائز)
     PT-Clean-Arch-Walls   -> arch_wall (حوائط مباني = أحمال خطية)
     PT-Clean-Openings     -> opening
     PT-Clean-Boundary     -> slab
     PT-Clean-Beams        -> beam      (ملف إنشائي بس)

 يعني الملف ده بيدخل البرنامج زي أي DXF، شاشة الليّرات بتتملي لوحدها صح،
 ومفيش سطر اتغيّر في البرنامج نفسه.

 الخطوات:
   1) قراءة كل الكيانات من كل الليّرات (مع فك البلوكات) -> primitives بالمتر.
   2) الوحدة: $INSUNITS مع فحص معقولية من مقاس المبنى ونصف قطر الأبواب.
   3) المحاور: خط طويل آخره دايرة فيها حرف/رقم (أو نوع خط CENTER/DASHDOT).
   4) الضوضاء: أبواب (قوس + ضلفة)، سلالم (درجات متوازية متساوية)، رموز صغيرة
      (عفش/صحي)، أبعاد ونصوص.
   5) الأعمدة: شكل مقفول بمقاس عمود + تقييم (تعبئة، على تقاطع محاور، تكرار،
      محاذاة، فاضي من جوه).
   6) الحوائط: تزاوج الوشوش المتوازية -> قطع حوائط بسمكها، وبعدين خرساني ولا
      مباني (نفس تعبئة الأعمدة؟ حوالين سلم/أسانسير؟ السمك؟).
   7) الفتحات: مستطيل عليه X، وبير السلم.
   8) حد البلاطة: الغلاف الخارجي للحوائط والأعمدة (closing morphology).
   9) (اختياري) Claude للعناصر اللي ثقتها متوسطة بس - بصورة crop، وبيرجّع
      دور من قايمة ثابتة. عمره ما بيرجّع إحداثيات.
  10) تقرير JSON + ملف مراجعة DXF بالألوان حسب الثقة.

 الاستخدام:
     python layerless_reader.py plan.dxf -o plan_clean.dxf
     python layerless_reader.py plan.dxf -o plan_clean.dxf --kind struct
     python layerless_reader.py plan.dxf -o plan_clean.dxf --ai

 التحقق الهندسي مسؤولية المهندس المصمم. راجع ملف المراجعة قبل RAM Concept.
================================================================================
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict

__version__ = "0.1.0"

# ------------------------------------------------------------------------------
#  الإعدادات
# ------------------------------------------------------------------------------


@dataclass
class Config:
    kind: str = "auto"               # arch / struct / auto
    units: str | None = None         # mm / cm / m / in / ft ، أو None = تلقائي
    window: tuple | None = None      # (x1, y1, x2, y2) بوحدات الرسمة الأصلية
    # الأعمدة (متر)
    col_min: float = 0.15
    col_max: float = 1.50
    col_max_aspect: float = 4.0
    col_accept: float = 0.60
    col_review: float = 0.40
    # الحوائط (متر)
    wall_min_t: float = 0.07
    wall_max_t: float = 0.45
    wall_min_len: float = 0.30
    rc_accept: float = 0.60
    # حد البلاطة
    closing_m: float = 1.2
    # AI
    ai: bool = False
    ai_model: str = "claude-opus-5"
    ai_max_items: int = 40
    ai_batch: int = 6


CLEAN_LAYERS = {
    "PT-Clean-Columns": 1,
    "PT-Clean-Walls": 3,
    "PT-Clean-Arch-Walls": 8,
    "PT-Clean-Beams": 5,
    "PT-Clean-Openings": 2,
    "PT-Clean-Boundary": 7,
}

INSUNITS_SCALE = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}

# أنماط تعبئة: ده اسم الـ pattern نفسه (جزء من الرسم)، مش اسم ليّر.
CONCRETE_PATTERNS = {"SOLID", "AR-CONC", "ANSI37", "ANSI38", "AR-SAND"}
MASONRY_PATTERNS = {"AR-B816", "AR-B816C", "AR-B88", "AR-BRSTD", "AR-BRELM",
                    "BRICK", "BRSTONE", "ANSI32", "AR-HBONE"}

DASHED_LT = re.compile(r"(DASH|HIDDEN|CENTER|PHANTOM|DOT|DIVIDE|BORDER)", re.I)
CENTER_LT = re.compile(r"(CENTER|DASHDOT|PHANTOM|CHAIN)", re.I)
GRID_LABEL = re.compile(r"^\s*([A-Z]{1,2}'?|\d{1,3}'?|[ء-ي]{1,2})\s*$")


# ------------------------------------------------------------------------------
#  هندسة أساسية (متر)
# ------------------------------------------------------------------------------

def _d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _centroid(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _hull(points):
    pts = sorted(set((round(p[0], 6), round(p[1], 6)) for p in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def min_area_rect(points):
    """أصغر مستطيل محيط: {center, long, short, angle_deg, corners}."""
    h = _hull(points)
    if len(h) < 3:
        return None
    best = None
    for i in range(len(h)):
        a, b = h[i], h[(i + 1) % len(h)]
        L = _d(a, b)
        if L < 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        us = [p[0] * ux + p[1] * uy for p in h]
        vs = [-p[0] * uy + p[1] * ux for p in h]
        w, t = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * t < best[0]:
            best = (w * t, ux, uy, min(us), max(us), min(vs), max(vs))
    _, ux, uy, u0, u1, v0, v1 = best
    w, t = u1 - u0, v1 - v0
    uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
    cx, cy = uc * ux - vc * uy, uc * uy + vc * ux
    if w >= t:
        ang, lng, sht = math.degrees(math.atan2(uy, ux)), w, t
    else:
        ang, lng, sht = math.degrees(math.atan2(ux, -uy)), t, w
    corners = []
    for su, sv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
        corners.append((su * ux - sv * uy, su * uy + sv * ux))
    return {"center": (cx, cy), "long": lng, "short": sht,
            "angle_deg": ang % 180.0, "corners": corners}


def _point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = xi + (y - yi) * (xj - xi) / ((yj - yi) or 1e-12)
            if x < xc:
                inside = not inside
        j = i
    return inside


def _seg_point_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return _d(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return _d(p, (ax + t * dx, ay + t * dy))


def _line_intersection(a1, a2, b1, b2):
    """تقاطع خطين لا نهائيين."""
    x1, y1 = a1
    x2, y2 = a2
    x3, y3 = b1
    x4, y4 = b2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return (px, py)


def _angle_mod180(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def _ang_diff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


# ------------------------------------------------------------------------------
#  1) القراءة: كل الكيانات -> primitives
# ------------------------------------------------------------------------------

@dataclass
class Prim:
    kind: str                     # seg / poly / circle / arc / hatch / text
    pts: list = field(default_factory=list)
    closed: bool = False
    color: int = 7
    ltype: str = "CONTINUOUS"
    pattern: str = ""             # للـ hatch بس
    symbol: int = -1              # رقم البلوك الصغير (رمز) أو -1
    text: str = ""
    center: tuple = None
    radius: float = 0.0
    a0: float = 0.0
    a1: float = 0.0
    tag: str = ""                 # اللي اتعلّم عليه بعدين (grid/door/stair...)


class Reader:
    """بيقرا DXF ويطلع primitives بالمتر. مفيش أي منطق مبني على اسم ليّر."""

    SYMBOL_MAX_DIAG = 6.0         # بلوك أصغر من كده = رمز (عفش/باب/صحي/عمود)

    def __init__(self, path, cfg: Config, log):
        import ezdxf
        from ezdxf import recover
        self.log = log
        self.cfg = cfg
        try:
            self.doc = ezdxf.readfile(path)
        except Exception:
            self.doc, auditor = recover.readfile(path)
            log(f"الملف كان فيه أخطاء واتصلّح وقت القراءة ({len(auditor.fixes)} إصلاح).")
        self.prims: list[Prim] = []
        self.symbol_count = 0
        self.skipped = defaultdict(int)
        self.hidden_layers = set()
        for layer in self.doc.layers:
            try:
                if layer.is_off() or layer.is_frozen():
                    self.hidden_layers.add(layer.dxf.name.lower())
            except Exception:
                pass
        self.raw_scale = 1.0
        self.sym_diag = {}

    # ---- خصائص الرسم (لون/نوع خط) مع حل ByLayer ----
    def _color(self, e, layer):
        c = getattr(e.dxf, "color", 256)
        if c in (0, 256, None):
            try:
                c = abs(self.doc.layers.get(layer).dxf.color)
            except Exception:
                c = 7
        return int(c)

    def _ltype(self, e, layer):
        lt = (getattr(e.dxf, "linetype", "") or "BYLAYER").upper()
        if lt in ("BYLAYER", "BYBLOCK", ""):
            try:
                lt = (self.doc.layers.get(layer).dxf.linetype or "CONTINUOUS").upper()
            except Exception:
                lt = "CONTINUOUS"
        return lt

    def read(self):
        msp = self.doc.modelspace()
        raw = []
        self._walk(msp, raw, depth=0, inherited=None, symbol=-1)
        self.raw = raw
        return raw

    def _walk(self, container, out, depth, inherited, symbol):
        from ezdxf import bbox as ezbbox
        for e in container:
            try:
                et = e.dxftype()
            except Exception:
                self.skipped["broken"] += 1
                continue
            own = (getattr(e.dxf, "layer", "") or "").strip()
            layer = inherited if (own in ("", "0") and inherited) else own
            if layer.lower() in self.hidden_layers:
                self.skipped["hidden_layer"] += 1
                continue
            if getattr(e.dxf, "invisible", 0):
                continue
            if et == "INSERT":
                # نصوص الـ attributes (فقاعات المحاور غالبًا بلوك فيه attribute)
                try:
                    for att in e.attribs:
                        out.append(("text", att, layer, symbol))
                except Exception:
                    pass
                if depth >= 6:
                    self.skipped["too_deep"] += 1
                    continue
                try:
                    subs = list(e.virtual_entities())
                except Exception:
                    self.skipped["block_failed"] += 1
                    continue
                sym = symbol
                if symbol < 0:
                    # بلوك على المستوى الأعلى: رقم جديد، ومقاسه يتحسم بعد الوحدة
                    try:
                        ext = ezbbox.extents(subs, fast=True)
                        diag = math.hypot(ext.size.x, ext.size.y) if ext.has_data else 0
                    except Exception:
                        diag = 0
                    self.symbol_count += 1
                    sym = self.symbol_count
                    self.sym_diag[sym] = diag
                self._walk(subs, out, depth + 1, layer, sym)
                continue
            if et in ("DIMENSION", "ARC_DIMENSION", "LEADER", "MLEADER",
                      "MULTILEADER", "TOLERANCE", "IMAGE", "WIPEOUT",
                      "VIEWPORT", "OLE2FRAME", "POINT", "XLINE", "RAY"):
                self.skipped[et] += 1
                continue
            out.append((et, e, layer, symbol))

    def to_prims(self):
        """تحويل للمتر بعد تحديد الوحدة."""
        s = self.raw_scale
        # البلوكات: رمز صغير (عفش/صحي/عمود) ولا "شفاف" (خطة كاملة جوه بلوك/xref)
        small = {k for k, diag in self.sym_diag.items() if diag * s <= self.SYMBOL_MAX_DIAG}
        prims = self.prims
        win = self.cfg.window
        for et, e, layer, symbol in self.raw:
            sym = symbol if symbol in small else -1
            try:
                new = self._convert(et, e, layer, s)
            except Exception:
                self.skipped["convert_failed"] += 1
                continue
            for p in new:
                p.symbol = sym
                if win and not self._in_window(p, win, s):
                    continue
                prims.append(p)
        return prims

    @staticmethod
    def _in_window(p, win, s):
        x1, y1, x2, y2 = (v * s for v in win)
        pts = p.pts or ([p.center] if p.center else [])
        return any(x1 <= q[0] <= x2 and y1 <= q[1] <= y2 for q in pts)

    def _convert(self, et, e, layer, s):
        from ezdxf import path as ezpath
        col = self._color(e, layer)
        lt = self._ltype(e, layer)

        def P(v):
            return (float(v[0]) * s, float(v[1]) * s)

        if et == "text":
            txt = e.dxf.text if hasattr(e.dxf, "text") else ""
            return [Prim("text", pts=[P(e.dxf.insert)], text=_plain(txt), color=col)]
        if et in ("TEXT", "ATTRIB"):
            ins = e.dxf.insert
            if getattr(e.dxf, "halign", 0) or getattr(e.dxf, "valign", 0):
                ins = getattr(e.dxf, "align_point", None) or ins
            return [Prim("text", pts=[P(ins)], text=_plain(e.dxf.text), color=col)]
        if et == "MTEXT":
            return [Prim("text", pts=[P(e.dxf.insert)], text=_plain(e.plain_text()),
                         color=col)]
        if et == "LINE":
            a, b = P(e.dxf.start), P(e.dxf.end)
            if _d(a, b) < 1e-4:
                return []
            return [Prim("seg", pts=[a, b], color=col, ltype=lt)]
        if et == "CIRCLE":
            return [Prim("circle", center=P(e.dxf.center), radius=e.dxf.radius * s,
                         color=col, ltype=lt,
                         pts=[P(e.dxf.center)])]
        if et == "ARC":
            c = P(e.dxf.center)
            r = e.dxf.radius * s
            a0, a1 = e.dxf.start_angle, e.dxf.end_angle
            out = [Prim("arc", center=c, radius=r, a0=a0, a1=a1, color=col, ltype=lt,
                        pts=[c])]
            # قوس كبير (حائط منحني) -> قطع مستقيمة للمزاوجة
            if r > 1.8:
                pts = [P(v) for v in ezpath.make_path(e).flattening(0.02 / s)]
                out += _polyline_to_segs(pts, col, lt)
            return out
        if et in ("LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
            if et == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
                return []
            pts = [P(v) for v in ezpath.make_path(e).flattening(0.01 / s)]
            pts = _dedupe_consecutive(pts)
            if len(pts) < 2:
                return []
            closed = bool(getattr(e, "closed", False) or
                          (et == "LWPOLYLINE" and e.closed) or
                          (len(pts) > 3 and _d(pts[0], pts[-1]) < 1e-3))
            if closed and _d(pts[0], pts[-1]) < 1e-3:
                pts = pts[:-1]
            if closed and len(pts) >= 3:
                return [Prim("poly", pts=pts, closed=True, color=col, ltype=lt)]
            return _polyline_to_segs(pts, col, lt)
        if et in ("SOLID", "TRACE", "3DFACE"):
            vs = [P(e.dxf.get(k)) for k in ("vtx0", "vtx1", "vtx3", "vtx2")
                  if e.dxf.hasattr(k)]
            vs = _dedupe_consecutive(vs)
            if len(vs) >= 3:
                return [Prim("hatch", pts=vs, closed=True, color=col, pattern="SOLID")]
            return []
        if et == "HATCH":
            pat = (e.dxf.pattern_name or "").upper()
            if e.dxf.solid_fill:
                pat = "SOLID"
            out = []
            for bp in e.paths:
                try:
                    pth = ezpath.from_hatch_boundary_path(bp)
                    pts = [P(v) for v in pth.flattening(0.01 / s)]
                except Exception:
                    continue
                pts = _dedupe_consecutive(pts)
                if len(pts) > 3 and _d(pts[0], pts[-1]) < 1e-3:
                    pts = pts[:-1]
                if len(pts) >= 3:
                    out.append(Prim("hatch", pts=pts, closed=True, color=col,
                                    pattern=pat))
            return out
        self.skipped[et] += 1
        return []


def _plain(t):
    t = t or ""
    t = re.sub(r"\\[A-Za-z][^;]*;", "", t)
    t = re.sub(r"[{}]", "", t)
    t = t.replace("\\P", " ").replace("%%c", "Ø").replace("%%C", "Ø")
    return t.strip()


def _dedupe_consecutive(pts, tol=1e-4):
    out = []
    for p in pts:
        if not out or _d(out[-1], p) > tol:
            out.append(p)
    return out


def _polyline_to_segs(pts, col, lt):
    out = []
    for i in range(len(pts) - 1):
        if _d(pts[i], pts[i + 1]) > 1e-4:
            out.append(Prim("seg", pts=[pts[i], pts[i + 1]], color=col, ltype=lt))
    return out


# ------------------------------------------------------------------------------
#  2) الوحدة
# ------------------------------------------------------------------------------

def _raw_extent(raw):
    xs, ys = [], []
    for et, e, _layer, _s in raw:
        try:
            if et == "LINE":
                for v in (e.dxf.start, e.dxf.end):
                    xs.append(v[0])
                    ys.append(v[1])
            elif et == "LWPOLYLINE":
                for v in e.get_points("xy"):
                    xs.append(v[0])
                    ys.append(v[1])
            elif et in ("CIRCLE", "ARC"):
                xs.append(e.dxf.center[0])
                ys.append(e.dxf.center[1])
        except Exception:
            pass
    if len(xs) < 4:
        return 0.0, []
    xs.sort()
    ys.sort()
    k = max(1, len(xs) // 50)
    span = max(xs[-k] - xs[k - 1], ys[-k] - ys[k - 1])
    return span, xs


def _door_radii(raw):
    rs = []
    for et, e, _l, _s in raw:
        if et == "ARC":
            try:
                sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360.0
                if 60.0 <= sweep <= 100.0:
                    rs.append(e.dxf.radius)
            except Exception:
                pass
    rs.sort()
    return rs[len(rs) // 2] if rs else None


def resolve_scale(reader: Reader, cfg: Config, log):
    """وحدة الرسمة -> متر. $INSUNITS لو معقول، وإلا من المقاسات."""
    if cfg.units:
        s = UNIT_SCALE[cfg.units]
        log(f"الوحدة: {cfg.units} (من الإعداد).")
        return s
    span, _ = _raw_extent(reader.raw)
    try:
        ins = int(reader.doc.header.get("$INSUNITS", 0))
    except Exception:
        ins = 0
    door_r = _door_radii(reader.raw)

    def plausible(sc):
        ok_span = span <= 0 or 3.0 <= span * sc <= 800.0
        ok_door = door_r is None or 0.5 <= door_r * sc <= 1.8
        return ok_span and ok_door

    if ins in INSUNITS_SCALE and plausible(INSUNITS_SCALE[ins]):
        log(f"الوحدة: من $INSUNITS={ins} (مقاس المبنى {span * INSUNITS_SCALE[ins]:.1f} م).")
        return INSUNITS_SCALE[ins]
    # تخمين: الأبواب أقوى دليل، وبعدها مقاس المبنى
    for name in ("mm", "cm", "m"):
        sc = UNIT_SCALE[name]
        if door_r is not None and 0.5 <= door_r * sc <= 1.8 and plausible(sc):
            log(f"الوحدة: {name} (من نصف قطر الأبواب ≈ {door_r * sc:.2f} م).")
            return sc
    for name in ("mm", "cm", "m"):
        sc = UNIT_SCALE[name]
        if 8.0 <= span * sc <= 400.0:
            log(f"الوحدة: {name} (من مقاس الرسمة ≈ {span * sc:.0f} م) - اتأكد منها.",)
            return sc
    log("الوحدة: مش واضحة، افترضت mm. استخدم --units لو غلط.")
    return 0.001


# ------------------------------------------------------------------------------
#  3) المحاور
# ------------------------------------------------------------------------------

def detect_grids(prims, log):
    segs = [p for p in prims if p.kind == "seg"]
    circles = [p for p in prims if p.kind == "circle" and 0.15 <= p.radius <= 1.3]
    texts = [p for p in prims if p.kind == "text" and GRID_LABEL.match(p.text or "")]
    if not segs:
        return []
    allpts = [q for p in segs for q in p.pts]
    x0, y0, x1, y1 = _bbox(allpts)
    ext = max(x1 - x0, y1 - y0)
    min_len = max(5.0, 0.25 * ext)

    # فقاعة = دايرة جواها تسمية محور
    bubbles = []
    for c in circles:
        lab = None
        for t in texts:
            if _d(t.pts[0], c.center) <= c.radius * 1.1:
                lab = t.text.strip()
                break
        if lab is None:
            # تسمية بمحاذاة وسط النص: نقطة الإدراج ممكن تكون على حافة الدايرة
            for t in texts:
                if _d(t.pts[0], c.center) <= c.radius * 1.6:
                    lab = t.text.strip()
                    break
        if lab is not None:
            bubbles.append((c, lab))

    grids = []
    for s in segs:
        a, b = s.pts
        L = _d(a, b)
        if L < min_len:
            continue
        label = None
        used_bubble = None
        for c, lab in bubbles:
            near_end = min(_d(a, c.center), _d(b, c.center)) <= c.radius * 2.5
            if near_end and _line_dist(c.center, a, b) <= c.radius * 0.5:
                label, used_bubble = lab, c
                break
        center_lt = bool(CENTER_LT.search(s.ltype or ""))
        if label or center_lt:
            s.tag = "grid"
            if used_bubble is not None:
                used_bubble.tag = "grid_bubble"
            grids.append({"p1": a, "p2": b, "label": label or "",
                          "angle": _angle_mod180(a, b)})
    for c, _lab in bubbles:
        if c.tag == "grid_bubble":
            for t in texts:
                if _d(t.pts[0], c.center) <= c.radius * 1.6:
                    t.tag = "grid_label"
    if grids:
        labs = sorted({g["label"] for g in grids if g["label"]})
        log(f"المحاور: {len(grids)} خط ({', '.join(labs[:20])}).")
    else:
        log("المحاور: ملقتش محاور - تقييم الأعمدة هيعتمد على الباقي.")
    return grids


def _line_dist(p, a, b):
    L = _d(a, b)
    if L < 1e-9:
        return _d(p, a)
    return abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / L


def grid_intersections(grids):
    pts = []
    for i in range(len(grids)):
        for j in range(i + 1, len(grids)):
            g, h = grids[i], grids[j]
            if _ang_diff(g["angle"], h["angle"]) < 20:
                continue
            q = _line_intersection(g["p1"], g["p2"], h["p1"], h["p2"])
            if q and _seg_point_dist(q, g["p1"], g["p2"]) < 1.0 and \
                    _seg_point_dist(q, h["p1"], h["p2"]) < 1.0:
                pts.append(q)
    return pts


# ------------------------------------------------------------------------------
#  4) الضوضاء: أبواب وسلالم
# ------------------------------------------------------------------------------

def detect_doors(prims, log):
    arcs = [p for p in prims if p.kind == "arc"]
    segs = [p for p in prims if p.kind == "seg" and not p.tag]
    doors = []
    for a in arcs:
        sweep = (a.a1 - a.a0) % 360.0
        if not (60.0 <= sweep <= 100.0 and 0.45 <= a.radius <= 1.7):
            continue
        a.tag = "door"
        doors.append({"center": a.center, "radius": a.radius})
        # الضلفة: خط طرفه في مركز القوس وطوله ≈ نصف القطر
        for s in segs:
            if s.tag:
                continue
            p, q = s.pts
            L = _d(p, q)
            if abs(L - a.radius) <= 0.08 * a.radius and \
                    min(_d(p, a.center), _d(q, a.center)) <= 0.06:
                s.tag = "door"
    # ضلفة مرسومة كمستطيل رفيع مقفول
    for p in prims:
        if p.kind == "poly" and not p.tag:
            r = min_area_rect(p.pts)
            if r and r["short"] <= 0.07 and 0.45 <= r["long"] <= 1.7:
                for d in doors:
                    if min(_d(c, d["center"]) for c in r["corners"]) <= 0.1:
                        p.tag = "door"
                        break
    if doors:
        log(f"الأبواب: {len(doors)} (اتشالوا من التحليل).")
    return doors


def detect_stairs(prims, log):
    """درجات: ≥5 خطوط متوازية بنفس الطول وبمسافات متساوية 0.22-0.40 م."""
    segs = [p for p in prims if p.kind == "seg" and not p.tag
            and 0.7 <= _d(*p.pts) <= 2.6]
    flights = []
    def ang(s):  # 179.9° و 0.1° نفس الاتجاه
        a = _angle_mod180(*s.pts)
        return a - 180.0 if a > 179.0 else a

    for group in _cluster_sorted(segs, ang, 1.0):
        if len(group) < 5:
            continue
        a = math.radians(_angle_mod180(*group[0].pts))
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        items = []
        for s in group:
            m = ((s.pts[0][0] + s.pts[1][0]) / 2, (s.pts[0][1] + s.pts[1][1]) / 2)
            items.append((m[0] * nx + m[1] * ny, m[0] * ux + m[1] * uy, _d(*s.pts), s))
        # قلبتين جنب بعض بنفس المناسيب: نفصلهم ببداية الدرجة وطولها الأول
        sub = [ln for st in _cluster_sorted(items, lambda t: t[1], 0.1)
               for ln in _cluster_sorted(st, lambda t: t[2], 0.05)]

        def flush(run):
            if len(run) >= 5:
                gaps = [run[i + 1][0] - run[i][0] for i in range(len(run) - 1)]
                g = sorted(gaps)[len(gaps) // 2]
                if 0.22 <= g <= 0.40 and max(abs(x - g) for x in gaps) <= 0.03:
                    pts = [q for r in run for q in r[3].pts]
                    for r in run:
                        r[3].tag = "stair"
                    flights.append(pts)

        for lst in sub:
            if len(lst) < 5:
                continue
            lst.sort(key=lambda t: t[0])
            run = [lst[0]]
            for it in lst[1:]:
                if 0.2 <= it[0] - run[-1][0] <= 0.42:
                    run.append(it)
                else:
                    flush(run)
                    run = [it]
            flush(run)
    # الدرابزين/خط المنتصف جوه الـ flight
    boxes = [_bbox(f) for f in flights]
    for p in prims:
        if p.kind == "seg" and not p.tag:
            m = ((p.pts[0][0] + p.pts[1][0]) / 2, (p.pts[0][1] + p.pts[1][1]) / 2)
            for (x0, y0, x1, y1) in boxes:
                if x0 - 0.05 <= m[0] <= x1 + 0.05 and y0 - 0.05 <= m[1] <= y1 + 0.05 \
                        and _d(*p.pts) <= max(x1 - x0, y1 - y0) + 0.1:
                    p.tag = "stair"
                    break
    if flights:
        log(f"السلالم: {len(flights)} قلبة.")
    return flights


# ------------------------------------------------------------------------------
#  5) الفتحات بعلامة X
# ------------------------------------------------------------------------------

def detect_x_openings(prims, log, min_size=0.3, max_size=20.0):
    """خطين قطريين بيتقاطعوا في منتصفهم وبنفس الطول -> مستطيل فتحة."""
    segs = [p for p in prims if p.kind == "seg" and not p.tag
            and min_size * 1.41 <= _d(*p.pts) <= max_size * 1.42]
    # أقطار جوه بولي لاين مقفول مرسوم بـ X كمان
    mids = defaultdict(list)
    for s in segs:
        m = ((s.pts[0][0] + s.pts[1][0]) / 2, (s.pts[0][1] + s.pts[1][1]) / 2)
        mids[(round(m[0] / 0.05), round(m[1] / 0.05))].append((m, s))
    openings = []
    seen = set()
    for key, lst in mids.items():
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand += mids.get((key[0] + dx, key[1] + dy), [])
        for m1, s1 in lst:
            if id(s1) in seen:
                continue
            L1 = _d(*s1.pts)
            for m2, s2 in cand:
                if s2 is s1 or id(s2) in seen:
                    continue
                if _d(m1, m2) > 0.05 or abs(_d(*s2.pts) - L1) > 0.03 * L1 + 0.02:
                    continue
                if _ang_diff(_angle_mod180(*s1.pts), _angle_mod180(*s2.pts)) < 15:
                    continue
                corners = [s1.pts[0], s2.pts[0], s1.pts[1], s2.pts[1]]
                r = min_area_rect(corners)
                if not r or r["short"] < min_size or _area(corners) < 0.8 * r["long"] * r["short"]:
                    continue
                seen.add(id(s1))
                seen.add(id(s2))
                s1.tag = s2.tag = "x_mark"
                openings.append({"poly": corners, "source": "x_mark", "score": 0.9})
                break
    if openings:
        log(f"الفتحات بعلامة X: {len(openings)}.")
    return openings


# ------------------------------------------------------------------------------
#  6) الأعمدة
# ------------------------------------------------------------------------------

def _shape_candidates(prims, cfg):
    """كل شكل مقفول ممكن يبقى عمود: بولي لاين، دايرة، hatch، أو خطوط قصيرة
    بتقفل مستطيل (polygonize)."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union

    cands = []
    for i, p in enumerate(prims):
        if p.tag:
            continue
        if p.kind in ("poly", "hatch"):
            cands.append({"pts": p.pts, "src": p.kind, "prim": i})
        elif p.kind == "circle" and cfg.col_min / 2 <= p.radius <= cfg.col_max / 2:
            n = 24
            pts = [(p.center[0] + p.radius * math.cos(2 * math.pi * k / n),
                    p.center[1] + p.radius * math.sin(2 * math.pi * k / n))
                   for k in range(n)]
            cands.append({"pts": pts, "src": "circle", "prim": i, "circle": True,
                          "radius": p.radius})
    short = [LineString(p.pts) for p in prims
             if p.kind == "seg" and not p.tag and _d(*p.pts) <= cfg.col_max * 1.05]
    if short:
        try:
            merged = unary_union(short)
            for poly in polygonize(merged):
                if isinstance(poly, Polygon) and poly.area > cfg.col_min ** 2 * 0.8:
                    pts = list(poly.exterior.coords)[:-1]
                    cands.append({"pts": pts, "src": "lines", "prim": -1})
        except Exception:
            pass
    return cands


def detect_columns(prims, grids, cfg: Config, log):
    from shapely.geometry import Polygon, Point
    from shapely.strtree import STRtree

    inters = grid_intersections(grids)
    hatches = [p for p in prims if p.kind == "hatch"]
    hatch_polys = []
    for h in hatches:
        try:
            hp = Polygon(h.pts).buffer(0)
            if not hp.is_empty:
                hatch_polys.append((hp, h))
        except Exception:
            pass
    htree = STRtree([hp for hp, _ in hatch_polys]) if hatch_polys else None

    # نقاط الرسم كلها (للتأكد إن العمود "فاضي من جوه" مش ترابيزة/سرير)
    inner_pts = []
    for p in prims:
        if p.kind == "seg" and not p.tag:
            inner_pts.append(((p.pts[0][0] + p.pts[1][0]) / 2,
                              (p.pts[0][1] + p.pts[1][1]) / 2))
        elif p.kind == "text" and not p.tag:
            inner_pts.append(p.pts[0])
    ptree = STRtree([Point(q) for q in inner_pts]) if inner_pts else None

    raw = []
    for c in _shape_candidates(prims, cfg):
        pts = c["pts"]
        if len(pts) < 3:
            continue
        r = min_area_rect(pts)
        if not r:
            continue
        if not (cfg.col_min <= r["short"] <= cfg.col_max and r["long"] <= cfg.col_max * 1.6):
            continue
        aspect = r["long"] / max(r["short"], 1e-6)
        area = _area(pts)
        fill = area / max(r["long"] * r["short"], 1e-9)
        is_circle = c.get("circle") or (len(pts) >= 12 and fill > 0.74 and aspect < 1.15
                                        and fill < 0.83)
        if not is_circle and fill < 0.80:
            continue  # شكل مش مستطيل (L أو T) - يروح للحوائط لو هو كور
        if aspect > cfg.col_max_aspect:
            continue  # ضيق وطويل: حائط، مش عمود
        raw.append({"rect": r, "pts": pts, "src": c["src"], "prim": c["prim"],
                    "circle": bool(is_circle), "aspect": aspect})

    # دمج التكرار: hatch + outline لنفس العمود
    raw.sort(key=lambda k: (0 if k["src"] == "hatch" else 1))
    uniq = []
    for k in raw:
        dup = None
        for u in uniq:
            if _d(k["rect"]["center"], u["rect"]["center"]) < 0.05 and \
                    abs(k["rect"]["long"] - u["rect"]["long"]) < 0.05 and \
                    abs(k["rect"]["short"] - u["rect"]["short"]) < 0.05:
                dup = u
                break
        if dup:
            dup.setdefault("also", []).append(k["src"])
            if k["prim"] >= 0:
                dup.setdefault("prims", []).append(k["prim"])
        else:
            k["prims"] = [k["prim"]] if k["prim"] >= 0 else []
            uniq.append(k)

    # مقاس متكرر
    size_count = defaultdict(int)
    for u in uniq:
        size_count[(round(u["rect"]["long"] / 0.05), round(u["rect"]["short"] / 0.05))] += 1

    cols = []
    for u in uniq:
        r = u["rect"]
        cx, cy = r["center"]
        why = []
        score = 0.30
        poly = Polygon(r["corners"]) if not u["circle"] else Point(cx, cy).buffer(r["long"] / 2)
        # تعبئة
        filled_pat = None
        if u["src"] == "hatch" or "hatch" in u.get("also", []):
            filled_pat = prims[u["prim"]].pattern if u["src"] == "hatch" else "?"
        elif htree is not None:
            for idx in htree.query(poly):
                hp, h = hatch_polys[int(idx)]
                inter = hp.intersection(poly).area
                if inter >= 0.7 * poly.area and hp.area <= 1.6 * poly.area:
                    filled_pat = h.pattern
                    break
        if filled_pat:
            score += 0.35
            why.append(f"معبّى ({filled_pat})")
        # المحاور
        if inters:
            dmin = min(_d((cx, cy), q) for q in inters)
            if dmin <= 0.6:
                score += 0.25
                why.append("على تقاطع محاور")
            elif grids and min(_seg_point_dist((cx, cy), g["p1"], g["p2"]) for g in grids) <= 0.35:
                score += 0.12
                why.append("على محور")
        # تكرار
        n_same = size_count[(round(r["long"] / 0.05), round(r["short"] / 0.05))]
        if n_same >= 3:
            score += 0.15
            why.append(f"مقاس متكرر ×{n_same}")
        # حاجات جواه (ترابيزة/سرير/حوض)
        if ptree is not None:
            inside = 0
            shrunk = poly.buffer(-0.03)
            if not shrunk.is_empty:
                for idx in ptree.query(shrunk):
                    if shrunk.contains(Point(inner_pts[int(idx)])):
                        inside += 1
            if inside >= 2:
                score -= 0.35
                why.append(f"جواه {inside} عنصر (غالبًا عفش)")
        # رمز صغير (بلوك) من غير تعبئة ولا محاور = غالبًا عفش
        syms = {prims[i].symbol for i in u["prims"] if i >= 0}
        if syms and all(s >= 0 for s in syms) and not filled_pat and score < 0.55:
            score -= 0.1
            why.append("جزء من بلوك رمز")
        u.update(score=round(score, 2), why=why, filled=filled_pat)
        cols.append(u)

    # محاذاة: عمودين على نفس الخط الأفقي/الرأسي بيقوّوا بعض (بعد التقييم الأولي)
    strong = [c for c in cols if c["score"] >= cfg.col_review]
    for c in cols:
        cx, cy = c["rect"]["center"]
        n = sum(1 for o in strong if o is not c and
                (abs(o["rect"]["center"][0] - cx) < 0.08 or abs(o["rect"]["center"][1] - cy) < 0.08))
        if n >= 2:
            c["score"] = round(c["score"] + 0.1, 2)
            c["why"].append("على صف أعمدة")

    acc = [c for c in cols if c["score"] >= cfg.col_accept]
    rev = [c for c in cols if cfg.col_review <= c["score"] < cfg.col_accept]
    log(f"الأعمدة: {len(acc)} مؤكد، {len(rev)} محتاج مراجعة، "
        f"{len(cols) - len(acc) - len(rev)} اترفض (عفش/رموز).")
    return cols


# ------------------------------------------------------------------------------
#  7) الحوائط
# ------------------------------------------------------------------------------

def pair_faces(segs, cfg: Config):
    """تزاوج الوشوش المتوازية. segs = [(a, b, meta)]. بيرجّع قطع حوائط
    {p1, p2, t, faces:(i, j)} - الخط الأقرب على كل ناحية بس."""
    items = []
    for i, (a, b, _m) in enumerate(segs):
        L = _d(a, b)
        if L < cfg.wall_min_len * 0.5:
            continue
        items.append((i, _angle_mod180(a, b), a, b, L))
    items.sort(key=lambda t: t[1])
    # تجميع الزوايا (±0.75°) مع لف 180
    groups = []
    for it in items:
        if groups and it[1] - groups[-1][-1][1] <= 0.75:
            groups[-1].append(it)
        else:
            groups.append([it])
    if len(groups) > 1 and (groups[0][0][1] + 180.0) - groups[-1][-1][1] <= 0.75:
        groups[0] = groups[-1] + groups[0]
        groups.pop()

    pieces = []
    for g in groups:
        if len(g) < 2:
            continue
        # اتجاه مرجعي
        ang = math.radians(g[len(g) // 2][1])
        ux, uy = math.cos(ang), math.sin(ang)
        nx, ny = -uy, ux
        rows = []
        for (i, _a, a, b, _L) in g:
            ca = a[0] * nx + a[1] * ny
            cb = b[0] * nx + b[1] * ny
            sa = a[0] * ux + a[1] * uy
            sb = b[0] * ux + b[1] * uy
            rows.append(((ca + cb) / 2, min(sa, sb), max(sa, sb), i))
        rows.sort()
        cands = []
        for k, (c1, s0, s1, i) in enumerate(rows):
            for m in range(k + 1, len(rows)):
                c2, t0, t1, j = rows[m]
                gap = c2 - c1
                if gap < cfg.wall_min_t:
                    continue
                if gap > cfg.wall_max_t:
                    break
                lo, hi = max(s0, t0), min(s1, t1)
                if hi - lo >= min(cfg.wall_min_len, 0.5 * min(s1 - s0, t1 - t0)):
                    cands.append((gap, k, m, lo, hi))
        cands.sort()
        cover_pos = defaultdict(list)   # وش k: فترات اتغطّت من ناحية +
        cover_neg = defaultdict(list)

        def covered(lst, lo, hi):
            tot = 0.0
            for a0, a1 in lst:
                tot += max(0.0, min(hi, a1) - max(lo, a0))
            return tot >= 0.5 * (hi - lo)

        for gap, k, m, lo, hi in cands:
            if covered(cover_pos[k], lo, hi) or covered(cover_neg[m], lo, hi):
                continue
            # مفيش وش تالت بينهم على نفس الفترة (لو فيه، هو الأقرب وهيتاخد)
            cover_pos[k].append((lo, hi))
            cover_neg[m].append((lo, hi))
            cmid = (rows[k][0] + rows[m][0]) / 2
            p1 = (lo * ux + cmid * nx, lo * uy + cmid * ny)
            p2 = (hi * ux + cmid * nx, hi * uy + cmid * ny)
            pieces.append({"p1": p1, "p2": p2, "t": gap,
                           "faces": (rows[k][3], rows[m][3]),
                           "angle": math.degrees(ang) % 180.0})
    return pieces


def _cluster_sorted(items, key, tol):
    """تجميع متتالي بالتسامح (مش تقريب لخانات - خانة ممكن تقسم نفس الحائط)."""
    items = sorted(items, key=key)
    groups = []
    for it in items:
        if groups and key(it) - key(groups[-1][-1]) <= tol:
            groups[-1].append(it)
        else:
            groups.append([it])
    return groups


def merge_pieces(pieces, tol_off=0.03, tol_t=0.02, gap=0.06):
    """قطع على نفس الخط وبنفس السمك ومتلاصقة -> حائط واحد."""
    if not pieces:
        return []
    ang_groups = _cluster_sorted(pieces, lambda p: p["angle"], 1.0)
    if len(ang_groups) > 1 and ang_groups[0][0]["angle"] + 180.0 - ang_groups[-1][-1]["angle"] <= 1.0:
        ang_groups[0] = ang_groups.pop() + ang_groups[0]
    out = []
    for grp in ang_groups:
        a = math.radians(grp[len(grp) // 2]["angle"])
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        rows = []
        for p in grp:
            off = (p["p1"][0] + p["p2"][0]) / 2 * nx + (p["p1"][1] + p["p2"][1]) / 2 * ny
            s0 = p["p1"][0] * ux + p["p1"][1] * uy
            s1 = p["p2"][0] * ux + p["p2"][1] * uy
            rows.append((off, min(s0, s1), max(s0, s1), p))
        for line in _cluster_sorted(rows, lambda r: r[0], tol_off):
            for th in _cluster_sorted(line, lambda r: r[3]["t"], tol_t):
                th.sort(key=lambda r: r[1])
                off = sum(r[0] for r in th) / len(th)
                cur = None
                for _o, s0, s1, p in th:
                    if cur and s0 <= cur["s1"] + gap:
                        cur["s1"] = max(cur["s1"], s1)
                        cur["src"].append(p)
                    else:
                        if cur:
                            out.append(cur)
                        cur = {"s0": s0, "s1": s1, "off": off,
                               "angle": math.degrees(a) % 180.0, "t": p["t"], "src": [p]}
                if cur:
                    out.append(cur)
    walls = []
    for w in out:
        a = math.radians(w["angle"])
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        p1 = (w["s0"] * ux + w["off"] * nx, w["s0"] * uy + w["off"] * ny)
        p2 = (w["s1"] * ux + w["off"] * nx, w["s1"] * uy + w["off"] * ny)
        faces = set()
        for s in w["src"]:
            faces.update(s["faces"])
        walls.append({"p1": p1, "p2": p2, "t": w["t"], "angle": w["angle"],
                      "faces": sorted(faces)})
    return walls


def _wall_poly(w):
    from shapely.geometry import Polygon
    (x1, y1), (x2, y2) = w["p1"], w["p2"]
    L = math.hypot(x2 - x1, y2 - y1) or 1.0
    nx, ny = -(y2 - y1) / L * w["t"] / 2, (x2 - x1) / L * w["t"] / 2
    return Polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                    (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])


def detect_walls(prims, columns, openings, stairs, cfg: Config, kind, log):
    from shapely.geometry import Polygon, Point, box
    from shapely.strtree import STRtree
    from shapely.ops import unary_union

    col_ok = [c for c in columns if c["score"] >= cfg.col_review]
    col_polys = [Polygon(c["rect"]["corners"]) for c in col_ok]
    col_union = unary_union([p.buffer(0.01) for p in col_polys]) if col_polys else None

    # الوشوش: خطوط + أضلاع الأشكال المقفولة اللي مش أعمدة (كور، حائط مرسوم مقفول)
    col_prims = set()
    for c in col_ok:
        col_prims.update(c.get("prims", []))
    faces = []
    closed_wall_polys = []
    for i, p in enumerate(prims):
        if p.tag or p.symbol >= 0:
            continue  # عفش/أبواب/صحي/درجات/محاور
        if DASHED_LT.search(p.ltype or ""):
            continue  # خط مخفي = حاجة فوق (كمرة/بلكونة دور تاني)، مش حائط هنا
        if p.kind == "seg":
            a, b = p.pts
            if col_union is not None:
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if col_union.contains(Point(mid)) and _d(a, b) <= cfg.col_max * 1.1:
                    continue
            faces.append((a, b, {"prim": i, "closed": False}))
        elif p.kind in ("poly", "hatch") and i not in col_prims:
            pts = p.pts
            r = min_area_rect(pts)
            if r and r["short"] < cfg.col_min * 0.5:
                continue
            if p.kind == "poly" or (r and r["long"] > cfg.col_max):
                closed_wall_polys.append((i, pts))
                for k in range(len(pts)):
                    a, b = pts[k], pts[(k + 1) % len(pts)]
                    if _d(a, b) > 0.02:
                        faces.append((a, b, {"prim": i, "closed": True}))

    pieces = pair_faces(faces, cfg)
    walls = merge_pieces(pieces)

    # قص الحوائط عند الأعمدة، وشيل اللي جوه فتحة/سلم
    open_union = unary_union([Polygon(o["poly"]).buffer(-0.02) for o in openings]) \
        if openings else None
    stair_union = unary_union([box(*_bbox(f)) for f in stairs]) if stairs else None
    out = []
    for w in walls:
        L = _d(w["p1"], w["p2"])
        if L < cfg.wall_min_len:
            continue
        wp = _wall_poly(w)
        if col_union is not None and wp.intersection(col_union).area > 0.9 * wp.area:
            continue
        if open_union is not None and wp.intersection(open_union).area > 0.5 * wp.area:
            continue
        if stair_union is not None and wp.intersection(stair_union).area > 0.6 * wp.area:
            continue
        w["len"] = L
        out.append(w)

    # ---- خرساني ولا مباني ----
    hatches = [(Polygon(p.pts).buffer(0), p) for p in prims
               if p.kind == "hatch" and len(p.pts) >= 3]
    hatches = [(hp, p) for hp, p in hatches if not hp.is_empty]
    htree = STRtree([hp for hp, _ in hatches]) if hatches else None
    col_sig = defaultdict(int)     # بصمة تعبئة الأعمدة: (pattern, color)
    for c in col_ok:
        if c.get("filled"):
            for i in c.get("prims", []):
                if prims[i].kind == "hatch":
                    col_sig[(prims[i].pattern, prims[i].color)] += 1
            if c["src"] == "hatch":
                p = prims[c["prim"]]
                col_sig[(p.pattern, p.color)] += 1
    # الأشكال المقفولة حوالين الأسانسير/السلم = كور
    core_zones = [Polygon(o["poly"]).buffer(0.6) for o in openings]
    core_zones += [box(*_bbox(f)).buffer(0.6) for f in stairs]
    core_union = unary_union(core_zones) if core_zones else None
    col_near = unary_union([p.buffer(0.05) for p in col_polys]) if col_polys else None

    for w in out:
        wp = _wall_poly(w)
        score = 0.3 if kind == "arch" else 0.55
        why = []
        pat = None
        if htree is not None:
            for idx in htree.query(wp):
                hp, h = hatches[int(idx)]
                if hp.intersection(wp).area >= 0.6 * wp.area:
                    pat = (h.pattern, h.color)
                    break
        if pat:
            p_name = pat[0]
            if pat in col_sig:
                score += 0.4
                why.append(f"نفس تعبئة الأعمدة ({p_name})")
            elif p_name in CONCRETE_PATTERNS:
                score += 0.3
                why.append(f"تعبئة خرسانة ({p_name})")
            elif p_name in MASONRY_PATTERNS:
                score -= 0.3
                why.append(f"تعبئة طوب ({p_name})")
            else:
                score += 0.05
                why.append(f"معبّى ({p_name})")
        elif kind == "arch":
            score -= 0.05
            why.append("مش معبّى")
        if core_union is not None and wp.intersects(core_union) and w["t"] >= 0.18:
            score += 0.2
            why.append("حوالين سلم/أسانسير")
        if col_near is not None and wp.buffer(0.05).intersects(col_near) and w["t"] >= 0.2 \
                and w["len"] >= 1.0 and pat:
            score += 0.05
            why.append("متصل بعمود")
        if w["t"] <= 0.15:
            score -= 0.3
            why.append(f"سمك {w['t'] * 1000:.0f} مم (قاطوع)")
        elif w["t"] >= 0.25 and pat:
            score += 0.05
        w["rc_score"] = round(score, 2)
        w["why"] = why
        w["role"] = "wall" if score >= cfg.rc_accept else "arch_wall"
        w["review"] = abs(score - cfg.rc_accept) < 0.12 and w["t"] >= 0.18
    n_rc = sum(1 for w in out if w["role"] == "wall")
    n_rev = sum(1 for w in out if w["review"])
    log(f"الحوائط: {len(out)} قطعة - {n_rc} خرساني، {len(out) - n_rc} مباني، "
        f"{n_rev} على الحدود (مراجعة).")
    return out


# ------------------------------------------------------------------------------
#  8) الكمرات (ملف إنشائي: خطوط مخفية متوازية)
# ------------------------------------------------------------------------------

def detect_beams(prims, columns, cfg: Config, log):
    segs = [(p.pts[0], p.pts[1], {}) for p in prims
            if p.kind == "seg" and not p.tag and DASHED_LT.search(p.ltype or "")]
    if not segs:
        return []
    c2 = Config(**{**asdict(cfg), "wall_min_t": 0.15, "wall_max_t": 1.2,
                   "wall_min_len": 0.8})
    beams = merge_pieces(pair_faces(segs, c2), gap=0.6)
    beams = [b for b in beams if _d(b["p1"], b["p2"]) >= 1.0]
    if beams:
        log(f"الكمرات (خطوط مخفية متزاوجة): {len(beams)}.")
    return beams


# ------------------------------------------------------------------------------
#  9) حد البلاطة
# ------------------------------------------------------------------------------

def slab_boundary(columns, walls, openings, cfg: Config, log, extra=None):
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union

    geoms = [_wall_poly(w) for w in walls]
    geoms += [Polygon(c["rect"]["corners"]) for c in columns if c["score"] >= cfg.col_accept]
    if extra:
        geoms += extra
    if not geoms:
        log("حد البلاطة: مفيش حوائط/أعمدة كفاية.")
        return []
    g = cfg.closing_m
    u = unary_union([x.buffer(0.001) for x in geoms])
    # closing مع ملء الفراغات **قبل** التآكل: الغلاف الخارجي بس هو اللي يرجع
    # لمكانه، والمبنى من جوه يفضل مليان (الـ ring الرفيع بيتكسر لو اتآكل لوحده).
    dil = u.buffer(g, join_style=2, mitre_limit=10)
    dil = unary_union([Polygon(p.exterior) for p in
                       (dil.geoms if isinstance(dil, MultiPolygon) else [dil])])
    closed = dil.buffer(-g, join_style=2, mitre_limit=10)
    polys = list(closed.geoms) if isinstance(closed, MultiPolygon) else [closed]
    polys = [Polygon(p.exterior).simplify(0.02) for p in polys if not p.is_empty]
    polys = [p for p in polys if p.area >= 20.0]
    polys.sort(key=lambda p: -p.area)
    total = sum(p.area for p in polys)
    out = [list(p.exterior.coords)[:-1] for p in polys]
    if out:
        log(f"حد البلاطة: {len(out)} جزء، مساحة {total:.0f} م² "
            f"(الغلاف الخارجي للحوائط والأعمدة - راجع البلكونات والكابولي).")
    return out


# ------------------------------------------------------------------------------
#  10) Claude للحالات المتوسطة
# ------------------------------------------------------------------------------

AI_ROLES = ["column", "rc_wall", "masonry_wall", "furniture_or_symbol",
            "opening", "not_structural"]

AI_SYSTEM = (
    "You review crops of architectural/structural floor-plan drawings for a "
    "post-tensioned slab design program. Each image shows ONE candidate element "
    "outlined in thick red, with the surrounding drawing in grey/black (filled "
    "areas are hatches). A scale bar of 1 m is drawn in the corner. Decide what "
    "the red element is, from the drawing alone: a structural column, a reinforced "
    "concrete (RC) wall that supports the slab, a masonry/partition wall that only "
    "loads the slab, furniture/sanitary/symbol, a slab opening (shaft/lift/stair "
    "void), or not structural (annotation, frame, dimension). Layer names are not "
    "available and must not be assumed. If the image does not let you decide, "
    "return low confidence rather than guessing."
)


def _render_crop(prims, target_poly, center, half=3.0, px=512):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MPoly, Circle, Arc

    fig = plt.figure(figsize=(px / 100, px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    x0, y0 = center[0] - half, center[1] - half
    x1, y1 = center[0] + half, center[1] + half
    for p in prims:
        pts = p.pts or []
        if p.kind in ("seg",):
            if not any(x0 - 1 <= q[0] <= x1 + 1 and y0 - 1 <= q[1] <= y1 + 1 for q in pts):
                continue
            ls = "--" if DASHED_LT.search(p.ltype or "") else "-"
            ax.plot([pts[0][0], pts[1][0]], [pts[0][1], pts[1][1]], color="black",
                    lw=0.8, ls=ls)
        elif p.kind == "poly":
            if not any(x0 - 2 <= q[0] <= x1 + 2 and y0 - 2 <= q[1] <= y1 + 2 for q in pts):
                continue
            ax.add_patch(MPoly(pts, closed=True, fill=False, ec="black", lw=0.8))
        elif p.kind == "hatch":
            if not any(x0 - 2 <= q[0] <= x1 + 2 and y0 - 2 <= q[1] <= y1 + 2 for q in pts):
                continue
            fc = "#555555" if p.pattern == "SOLID" else "#bbbbbb"
            ax.add_patch(MPoly(pts, closed=True, fill=True, fc=fc, ec="none", alpha=0.8))
        elif p.kind == "circle" and x0 - 1 <= p.center[0] <= x1 + 1 and y0 - 1 <= p.center[1] <= y1 + 1:
            ax.add_patch(Circle(p.center, p.radius, fill=False, ec="black", lw=0.8))
        elif p.kind == "arc" and x0 - 2 <= p.center[0] <= x1 + 2 and y0 - 2 <= p.center[1] <= y1 + 2:
            ax.add_patch(Arc(p.center, 2 * p.radius, 2 * p.radius, theta1=p.a0,
                             theta2=p.a1, ec="black", lw=0.6))
        elif p.kind == "text" and x0 <= pts[0][0] <= x1 and y0 <= pts[0][1] <= y1:
            ax.text(pts[0][0], pts[0][1], p.text[:20], fontsize=6, color="#333333")
    ax.add_patch(MPoly(target_poly, closed=True, fill=False, ec="red", lw=2.5))
    ax.plot([x0 + 0.2, x0 + 1.2], [y0 + 0.2, y0 + 0.2], color="blue", lw=2)
    ax.text(x0 + 0.2, y0 + 0.3, "1 m", color="blue", fontsize=7)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def ai_review(prims, items, cfg: Config, log, crop_dir=None):
    """items: [{id, poly, center, hint}] -> {id: (role, confidence, reason)}.
    Claude بيرجّع دور من AI_ROLES بس - الإحداثيات والمقاسات من الكود."""
    try:
        import anthropic
    except ImportError:
        log("AI: مكتبة anthropic مش متسطبة (pip install anthropic) - اتخطّيت.")
        return {}
    client = anthropic.Anthropic()
    items = items[:cfg.ai_max_items]
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "role": {"type": "string", "enum": AI_ROLES},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "role", "confidence", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    out = {}
    for b0 in range(0, len(items), cfg.ai_batch):
        batch = items[b0:b0 + cfg.ai_batch]
        content = []
        for it in batch:
            png = _render_crop(prims, it["poly"], it["center"])
            if crop_dir:
                with open(os.path.join(crop_dir, f"{it['id']}.png"), "wb") as f:
                    f.write(png)
            content.append({"type": "text",
                            "text": f"Candidate id={it['id']}. Program's guess: {it['hint']}."})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/png",
                                       "data": base64.standard_b64encode(png).decode()}})
        content.append({"type": "text",
                        "text": "Classify every candidate above. Return one entry per id."})
        try:
            resp = client.beta.messages.create(
                model=cfg.ai_model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=AI_SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIStatusError as e:
            log(f"AI: الطلب فشل ({e.status_code}) - العناصر دي فضلت للمراجعة اليدوية.")
            continue
        except anthropic.APIConnectionError:
            log("AI: مفيش اتصال - العناصر دي فضلت للمراجعة اليدوية.")
            continue
        if resp.stop_reason == "refusal":
            log("AI: الطلب اترفض - العناصر دي فضلت للمراجعة اليدوية.")
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log("AI: رد مش JSON - اتخطّى.")
            continue
        for r in data.get("items", []):
            out[r["id"]] = (r["role"], float(r["confidence"]), r["reason"])
    log(f"AI: {len(out)} عنصر اتراجع بـ {cfg.ai_model}.")
    return out


# ------------------------------------------------------------------------------
#  11) الكتابة
# ------------------------------------------------------------------------------

def _rect_pts(p1, p2, t):
    (x1, y1), (x2, y2) = p1, p2
    L = math.hypot(x2 - x1, y2 - y1) or 1.0
    nx, ny = -(y2 - y1) / L * t / 2, (x2 - x1) / L * t / 2
    return [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]


def write_clean_dxf(path, result):
    """نفس صيغة `_write_clean_dxf` في Auto PT Suite: مليمتر، طبقات PT-Clean-*."""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    for name, color in CLEAN_LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    M = 1000.0

    def pl(pts, layer):
        msp.add_lwpolyline([(x * M, y * M) for x, y in pts], close=True,
                           dxfattribs={"layer": layer})

    for c in result["columns"]:
        r = c["rect"]
        if c["circle"]:
            msp.add_circle((r["center"][0] * M, r["center"][1] * M), r["long"] / 2 * M,
                           dxfattribs={"layer": "PT-Clean-Columns"})
        else:
            pl(r["corners"], "PT-Clean-Columns")
    for w in result["walls"]:
        layer = "PT-Clean-Walls" if w["role"] == "wall" else "PT-Clean-Arch-Walls"
        pl(_rect_pts(w["p1"], w["p2"], w["t"]), layer)
    for b in result.get("beams", []):
        pl(_rect_pts(b["p1"], b["p2"], b["t"]), "PT-Clean-Beams")
    for o in result["openings"]:
        pl(o["poly"], "PT-Clean-Openings")
    for poly in result["boundary"]:
        pl(poly, "PT-Clean-Boundary")
    doc.saveas(path)


def write_review_dxf(path, result, prims, scale):
    """ملف مراجعة بنفس وحدة الرسمة الأصلية (يتركّب فوقها XREF): الخلفية رمادي،
    المؤكد أخضر، المراجعة أصفر، المرفوض أحمر رفيع، مع سبب كل قرار."""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    k = 1.0 / scale
    layers = {"REV-SOURCE": 9, "REV-OK": 3, "REV-CHECK": 2, "REV-REJECTED": 1,
              "REV-NOTES": 7, "REV-RC-WALL": 4, "REV-ARCH-WALL": 8,
              "REV-BOUNDARY": 6, "REV-OPENING": 2, "REV-GRID": 5}
    for n, c in layers.items():
        doc.layers.add(n, color=c)
    msp = doc.modelspace()

    def P(q):
        return (q[0] * k, q[1] * k)

    def pl(pts, layer):
        msp.add_lwpolyline([P(q) for q in pts], close=True, dxfattribs={"layer": layer})

    def note(q, txt, layer="REV-NOTES", h=0.12):
        msp.add_text(txt, height=h * k, dxfattribs={"layer": layer, "insert": P(q)})

    for p in prims:
        if p.kind == "seg":
            msp.add_line(P(p.pts[0]), P(p.pts[1]), dxfattribs={"layer": "REV-SOURCE"})
    for g in result["grids"]:
        msp.add_line(P(g["p1"]), P(g["p2"]), dxfattribs={"layer": "REV-GRID"})
    for c in result["all_columns"]:
        s = c["score"]
        layer = "REV-OK" if c.get("final") else ("REV-CHECK" if c.get("review") else "REV-REJECTED")
        pl(c["rect"]["corners"], layer)
        if c.get("review") or c.get("final"):
            note(c["rect"]["corners"][2], f"C {s:.2f} " + "; ".join(c["why"][:3]))
    for w in result["walls"]:
        layer = "REV-RC-WALL" if w["role"] == "wall" else "REV-ARCH-WALL"
        pl(_rect_pts(w["p1"], w["p2"], w["t"]), "REV-CHECK" if w["review"] else layer)
        if w["review"] or w["role"] == "wall":
            m = ((w["p1"][0] + w["p2"][0]) / 2, (w["p1"][1] + w["p2"][1]) / 2)
            note(m, f"{'RC' if w['role'] == 'wall' else 'MAS'} t={w['t'] * 1000:.0f} "
                    f"{w['rc_score']:.2f}")
    for o in result["openings"]:
        pl(o["poly"], "REV-OPENING")
        note(_centroid(o["poly"]), o["source"])
    for poly in result["boundary"]:
        pl(poly, "REV-BOUNDARY")
    doc.header["$INSUNITS"] = {0.001: 4, 0.01: 5, 1.0: 6, 0.0254: 1, 0.3048: 2}.get(scale, 0)
    doc.saveas(path)


# ------------------------------------------------------------------------------
#  12) التشغيل
# ------------------------------------------------------------------------------

def convert(in_path, out_path, cfg: Config | None = None, review_path=None,
            report_path=None, log=print, crop_dir=None):
    cfg = cfg or Config()
    notes = []

    def L(msg):
        notes.append(msg)
        log(msg)

    rd = Reader(in_path, cfg, L)
    rd.read()
    rd.raw_scale = resolve_scale(rd, cfg, L)
    prims = rd.to_prims()
    L(f"اتقرا {len(prims)} عنصر من كل الليّرات (مع فك البلوكات).")

    grids = detect_grids(prims, L)
    doors = detect_doors(prims, L)
    stairs = detect_stairs(prims, L)
    openings = detect_x_openings(prims, L)

    kind = cfg.kind
    if kind == "auto":
        kind = "arch" if (len(doors) >= 3 or rd.symbol_count >= 15) else "struct"
        L(f"نوع الرسمة: {'معماري' if kind == 'arch' else 'إنشائي'} (تلقائي).")

    columns = detect_columns(prims, grids, cfg, L)
    for c in columns:
        c["review"] = cfg.col_review <= c["score"] < cfg.col_accept
        c["final"] = c["score"] >= cfg.col_accept
    walls = detect_walls(prims, columns, openings, stairs, cfg, kind, L)
    beams = detect_beams(prims, columns, cfg, L) if kind == "struct" else []

    # بير السلم = فتحة (للمراجعة)
    from shapely.geometry import box
    from shapely.ops import unary_union
    if stairs:
        u = unary_union([box(*_bbox(f)).buffer(0.3, join_style=2) for f in stairs])
        for g in (u.geoms if hasattr(u, "geoms") else [u]):
            env = g.minimum_rotated_rectangle
            openings.append({"poly": list(env.exterior.coords)[:-1],
                             "source": "stair", "score": 0.5, "review": True})

    # ---- AI للمتوسط ----
    if cfg.ai:
        items = []
        for k, c in enumerate(columns):
            if c["review"]:
                items.append({"id": f"C{k}", "poly": c["rect"]["corners"],
                              "center": c["rect"]["center"],
                              "hint": f"column? score {c['score']} ({'; '.join(c['why'])})"})
        for k, w in enumerate(walls):
            if w["review"]:
                items.append({"id": f"W{k}", "poly": _rect_pts(w["p1"], w["p2"], w["t"]),
                              "center": ((w["p1"][0] + w["p2"][0]) / 2,
                                         (w["p1"][1] + w["p2"][1]) / 2),
                              "hint": f"{w['role']} t={w['t'] * 1000:.0f}mm "
                                      f"({'; '.join(w['why'])})"})
        if items:
            if crop_dir:
                os.makedirs(crop_dir, exist_ok=True)
            ans = ai_review(prims, items, cfg, L, crop_dir=crop_dir)
            for key, (role, conf, reason) in ans.items():
                if conf < 0.7:
                    continue
                idx = int(key[1:])
                if key[0] == "C":
                    c = columns[idx]
                    c["final"] = role == "column"
                    c["review"] = False
                    c["why"].append(f"AI: {role} ({conf:.2f}) {reason}")
                else:
                    w = walls[idx]
                    if role in ("rc_wall", "masonry_wall"):
                        w["role"] = "wall" if role == "rc_wall" else "arch_wall"
                        w["review"] = False
                        w["why"].append(f"AI: {role} ({conf:.2f}) {reason}")
        else:
            L("AI: مفيش عناصر محتاجة مراجعة.")

    final_cols = [c for c in columns if c["final"]]
    boundary = slab_boundary(final_cols, walls, openings, cfg, L)
    result = {"columns": final_cols, "all_columns": columns, "walls": walls,
              "beams": beams, "openings": openings, "boundary": boundary,
              "grids": grids}

    # ---- فحوص سلامة ----
    checks = []
    if not final_cols and not any(w["role"] == "wall" for w in walls):
        checks.append("مفيش ولا ركيزة (عمود/حائط خرساني) - الموديل مش هيتحل.")
    if not boundary:
        checks.append("ملقتش حد بلاطة.")
    if grids and final_cols:
        inters = grid_intersections(grids)
        off = [c for c in final_cols if inters and
               min(_d(c["rect"]["center"], q) for q in inters) > 0.6]
        if off:
            checks.append(f"{len(off)} عمود مش على تقاطع محاور - راجعهم.")
    if boundary:
        from shapely.geometry import Polygon, Point
        slab = unary_union([Polygon(b) for b in boundary])
        outside = [c for c in final_cols if not slab.buffer(0.05).contains(Point(c["rect"]["center"]))]
        if outside:
            checks.append(f"{len(outside)} عمود برا حد البلاطة.")
    n_review = sum(1 for c in columns if c["review"]) + sum(1 for w in walls if w["review"]) + \
        sum(1 for o in openings if o.get("review"))
    for m in checks:
        L("⚠ " + m)

    write_clean_dxf(out_path, result)
    L(f"اتكتب: {out_path}")
    if review_path:
        write_review_dxf(review_path, result, prims, rd.raw_scale)
        L(f"ملف المراجعة: {review_path}")

    summary = {
        "version": __version__,
        "input": os.path.basename(in_path),
        "kind": kind,
        "unit_scale_to_m": rd.raw_scale,
        "counts": {
            "grids": len(grids),
            "columns": len(final_cols),
            "rc_walls": sum(1 for w in walls if w["role"] == "wall"),
            "masonry_walls": sum(1 for w in walls if w["role"] == "arch_wall"),
            "masonry_wall_length_m": round(sum(w["len"] for w in walls
                                               if w["role"] == "arch_wall"), 1),
            "beams": len(beams),
            "openings": len(openings),
            "slab_parts": len(boundary),
            "doors_removed": len(doors),
            "stair_flights": len(stairs),
            "needs_review": n_review,
        },
        "checks": checks,
        "log": notes,
        "review_items": (
            [{"type": "column", "center": [round(v, 3) for v in c["rect"]["center"]],
              "size_mm": [round(c["rect"]["long"] * 1000), round(c["rect"]["short"] * 1000)],
              "score": c["score"], "why": c["why"]} for c in columns if c["review"]] +
            [{"type": "wall", "p1": [round(v, 3) for v in w["p1"]],
              "p2": [round(v, 3) for v in w["p2"]], "t_mm": round(w["t"] * 1000),
              "role": w["role"], "score": w["rc_score"], "why": w["why"]}
             for w in walls if w["review"]] +
            [{"type": "opening", "source": o["source"],
              "center": [round(v, 3) for v in _centroid(o["poly"])]}
             for o in openings if o.get("review")]),
        "skipped": dict(rd.skipped),
    }
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary, result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Architectural/structural DXF -> clean Auto PT Suite DXF, "
                    "without relying on layer names.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="clean DXF (default: <input>_clean.dxf)")
    ap.add_argument("--kind", choices=["auto", "arch", "struct"], default="auto")
    ap.add_argument("--units", choices=list(UNIT_SCALE))
    ap.add_argument("--window", help="x1,y1,x2,y2 in drawing units (one plan out of a sheet)")
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--ai", action="store_true", help="ask Claude about mid-confidence items")
    ap.add_argument("--ai-model", default=Config.ai_model)
    ap.add_argument("--crops", help="folder to save the crops sent to AI")
    a = ap.parse_args(argv)

    base = os.path.splitext(a.input)[0]
    out = a.output or base + "_clean.dxf"
    ob = os.path.splitext(out)[0]
    cfg = Config(kind=a.kind, units=a.units, ai=a.ai, ai_model=a.ai_model,
                 window=tuple(float(v) for v in a.window.split(",")) if a.window else None)
    summary, _ = convert(a.input, out, cfg,
                         review_path=None if a.no_review else ob + "_review.dxf",
                         report_path=ob + "_report.json", crop_dir=a.crops)
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
