# -*- coding: utf-8 -*-
"""
اختبارات slab_extractor على مجموعة شيتات مصنوعة فيها كل حالة قابلناها في
المشروع الحقيقي: X عادي ومايل، كمرات مايلة بتقطع بعض (مش فتحة)، core بحوائط
hatch فيه سلم وأسانسير بباب، خطوط متكررة، لوحة عنوان جنب المسقط، حد أرض حوالين
المبنى، شبكة X لخزان، وتسمية LIFT.

    python -m pytest test_slab_extractor.py -q
"""

import math
import os
import sys

import ezdxf
import pytest
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import slab_extractor as SX  # noqa: E402

LAYERS = ["A-FURN", "S-BEAM", "0", "misc", "TXT"]   # أسماء ملخبطة عن قصد


def _rect(msp, x0, y0, x1, y1, layer="0", twice=False):
    for _ in range(2 if twice else 1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                           dxfattribs={"layer": layer})


def _x(msp, pts, layer="S-BEAM", inset=0.0):
    (a, b, c, d) = pts
    cx = sum(p[0] for p in pts) / 4
    cy = sum(p[1] for p in pts) / 4

    def pull(p):
        return (p[0] + (cx - p[0]) * inset, p[1] + (cy - p[1]) * inset)

    msp.add_line(pull(a), pull(c), dxfattribs={"layer": layer})
    msp.add_line(pull(b), pull(d), dxfattribs={"layer": layer})


def _core(msp, x0, y0, with_lift=True):
    """بير سلم صافي 2.35×4.63 بحوائط 0.2 hatch (مسار واحد فيه فتحات)، وأسانسير
    1.70×2.30 جنبه بباب في الحيطة."""
    t = 0.2
    W, H = 2.35, 4.63
    outer = [(x0 - t, y0 - t), (x0 + W + t, y0 - t), (x0 + W + t, y0 + H + t), (x0 - t, y0 + H + t)]
    h = msp.add_hatch(color=7, dxfattribs={"layer": "A-FURN"})
    h.paths.add_polyline_path(outer, is_closed=True)
    h.paths.add_polyline_path([(x0, y0), (x0 + W, y0), (x0 + W, y0 + H), (x0, y0 + H)], is_closed=True)
    # درجات: قلبتين 8 درجات
    for k in range(8):
        y = y0 + 1.1 + k * 0.3
        msp.add_line((x0, y), (x0 + 1.1, y), dxfattribs={"layer": "misc"})
        msp.add_line((x0 + 1.25, y), (x0 + 2.35, y), dxfattribs={"layer": "misc"})
    if with_lift:
        lx = x0 + W + t
        ring = [(lx, y0 - t), (lx + 1.7 + t, y0 - t), (lx + 1.7 + t, y0 + 2.3 + t),
                (lx + 1.1, y0 + 2.3 + t), (lx + 1.1, y0 + 2.3), (lx + 1.7, y0 + 2.3), (lx + 1.7, y0),
                (lx, y0)]
        h2 = msp.add_hatch(color=7, dxfattribs={"layer": "A-FURN"})
        h2.paths.add_polyline_path(ring, is_closed=True)          # حيطة يمين/تحت/جزء فوق
        h3 = msp.add_hatch(color=7, dxfattribs={"layer": "A-FURN"})
        h3.paths.add_polyline_path([(lx, y0 + 2.3), (lx + 0.3, y0 + 2.3), (lx + 0.3, y0 + 2.3 + t),
                                    (lx, y0 + 2.3 + t)], is_closed=True)  # باب 0.8 م في الحيطة اللي فوق
        return (lx, y0, lx + 1.7, y0 + 2.3)
    return None


def _struct_plan(msp, ox, oy, extra_x=False):
    """مسقط سقف 30×24 م على شكل L، حافة بخطين (كمرة حافة 0.25)."""
    outline = [(0, 0), (30, 0), (30, 24), (12, 24), (12, 16), (0, 16)]
    P = [(ox + x, oy + y) for x, y in outline]
    msp.add_lwpolyline(P, close=True, dxfattribs={"layer": "S-BEAM"})
    msp.add_lwpolyline(P, close=True, dxfattribs={"layer": "S-BEAM"})       # متكرر
    inner = Polygon(P).buffer(-0.25, join_style=2)
    msp.add_lwpolyline(list(inner.exterior.coords)[:-1], close=True, dxfattribs={"layer": "A-FURN"})
    # كمرات داخلية ومايلتين بيقطعوا بعض (مش فتحة)
    for x in (6, 18, 24):
        msp.add_line((ox + x, oy + 0.25), (ox + x, oy + 15.75), dxfattribs={"layer": "misc"})
    msp.add_line((ox + 2, oy + 2), (ox + 10, oy + 12), dxfattribs={"layer": "0"})
    msp.add_line((ox + 2, oy + 12), (ox + 10, oy + 2), dxfattribs={"layer": "0"})
    # فتحة X مستطيلة 2×1.5
    r = (ox + 20, oy + 4, ox + 22, oy + 5.5)
    _rect(msp, *r, layer="TXT")
    _x(msp, [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])])
    # فتحة مايلة (شبه منحرف) والـ X أقصر من الأركان بـ 5%
    trap = [(ox + 26, oy + 18), (ox + 28.5, oy + 18), (ox + 28.5, oy + 22), (ox + 26.8, oy + 22)]
    msp.add_lwpolyline(trap, close=True, dxfattribs={"layer": "0"})
    _x(msp, trap, inset=0.05)
    if extra_x:
        r2 = (ox + 2, oy + 13, ox + 3.5, oy + 14.5)
        _rect(msp, *r2, layer="misc")
        _x(msp, [(r2[0], r2[1]), (r2[2], r2[1]), (r2[2], r2[3]), (r2[0], r2[3])])
    _core(msp, ox + 13, oy + 6, with_lift=True)
    _core(msp, ox + 16, oy + 17, with_lift=False)


def _sheet(msp, ox, oy, title, extra_x=False):
    msp.add_lwpolyline([(ox, oy), (ox + 128, oy), (ox + 128, oy + 88), (ox, oy + 88)], close=True,
                       dxfattribs={"layer": "misc"})
    _struct_plan(msp, ox + 10, oy + 20, extra_x=extra_x)
    # لوحة عنوان طويلة ورفيعة فيها خلايا كتير (مش مسقط)
    for k in range(60):
        msp.add_line((ox + 105, oy + 2 + k * 1.4), (ox + 126, oy + 2 + k * 1.4), dxfattribs={"layer": "TXT"})
    msp.add_line((ox + 105, oy + 2), (ox + 105, oy + 86), dxfattribs={"layer": "TXT"})
    msp.add_text("AL-FAJER ENGINEERING", height=1.1, dxfattribs={"insert": (ox + 106, oy + 80)})
    msp.add_text(title, height=0.75, dxfattribs={"insert": (ox + 106, oy + 10)})
    msp.add_text("STRUCTURAL NOTES", height=0.5, dxfattribs={"insert": (ox + 106, oy + 60)})


@pytest.fixture(scope="module")
def struct_dxf(tmp_path_factory):
    p = tmp_path_factory.mktemp("s") / "str.dxf"
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    for n in LAYERS:
        if n not in doc.layers:
            doc.layers.add(n)
    msp = doc.modelspace()
    _sheet(msp, 0, 0, "GROUND FLOOR CEILING")
    _sheet(msp, 0, 150, "1ST FLOOR CEILING", extra_x=True)
    _sheet(msp, 0, 300, "RAFT DETAILS")            # لازم يتستبعد
    doc.saveas(p)
    return str(p)


@pytest.fixture(scope="module")
def arch_dxf(tmp_path_factory):
    p = tmp_path_factory.mktemp("a") / "arch.dxf"
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    ox, oy = 500, 0
    # حد الأرض: مستطيل كبير فاضي حوالين المبنى
    _rect(msp, ox - 6, oy - 6, ox + 36, oy + 30, layer="0")
    _struct_plan(msp, ox, oy)
    # غرف معمارية جوه
    for x in (3, 9):
        _rect(msp, ox + x, oy + 1, ox + x + 4, oy + 5, layer="A-FURN")
    # خزان: شبكة X 3×2
    for i in range(3):
        for j in range(2):
            c = (ox + 1 + i * 1.2, oy + 7 + j * 1.2, ox + 2.2 + i * 1.2, oy + 8.2 + j * 1.2)
            _rect(msp, *c, layer="0")
            _x(msp, [(c[0], c[1]), (c[2], c[1]), (c[2], c[3]), (c[0], c[3])])
    msp.add_text("FIRE TANK", height=0.3, dxfattribs={"insert": (ox + 1.5, oy + 8)})
    # شفت متسمي LIFT من غير X
    _rect(msp, ox + 25, oy + 10, ox + 26.8, oy + 12.3, layer="misc")
    msp.add_text("LIFT 1.80*2.30", height=0.2, dxfattribs={"insert": (ox + 25.2, oy + 11)})
    msp.add_text("GROUND FLOOR PLAN", height=1.0, dxfattribs={"insert": (ox + 5, oy - 10)})
    doc.saveas(p)
    return str(p)


def test_find_views(struct_dxf):
    views = SX.find_plan_views(ezdxf.readfile(struct_dxf), log=lambda m: None)
    assert [v.title for v in views] == ["GROUND FLOOR CEILING", "1ST FLOOR CEILING"]
    assert [v.slab_level for v in views] == [1, 2]
    for v in views:
        x0, y0, x1, y1 = v.window
        assert x1 - x0 < 35 and y1 - y0 < 30, "picked the title block or the whole sheet"


def _get(struct_dxf, title):
    doc = ezdxf.readfile(struct_dxf)
    v = next(v for v in SX.find_plan_views(doc, log=lambda m: None) if v.title == title)
    return SX.extract_slab(doc, v, log=lambda m: None)


def test_struct_slab_and_openings(struct_dxf):
    r = _get(struct_dxf, "GROUND FLOOR CEILING")
    expected = 30 * 16 + 18 * 8
    assert abs(r.area - expected) / expected < 0.01, r.area
    kinds = sorted(o.kind for o in r.openings)
    assert kinds.count("stair") == 2
    assert kinds.count("lift") == 1
    assert sum(k in ("X", "X*") for k in kinds) == 2, kinds       # الكمرات المايلة اترفضت
    assert r.rejected["beam_crossing"] >= 1
    stairs = [Polygon(o.poly) for o in r.openings if o.kind == "stair"]
    for s in stairs:
        L, S = SX._rect_dims(s)
        assert abs(L - 4.63) < 0.1 and abs(S - 2.35) < 0.1, (L, S)
    lift = next(Polygon(o.poly) for o in r.openings if o.kind == "lift")
    L, S = SX._rect_dims(lift)
    assert abs(L - 2.3) < 0.1 and abs(S - 1.7) < 0.1, (L, S)
    # الفتحة المايلة: الحدود من الوش المقفول مش من رؤوس الـ X المقصوصة
    trap = next(Polygon(o.poly) for o in r.openings if o.kind == "X" and Polygon(o.poly).area > 5)
    assert abs(trap.area - (2.5 + 1.7) / 2 * 4) < 0.2, trap.area


def test_layer_names_do_not_matter(struct_dxf, tmp_path):
    doc = ezdxf.readfile(struct_dxf)
    for e in doc.modelspace():
        e.dxf.layer = "0"
    p = tmp_path / "zero.dxf"
    doc.saveas(p)
    a = _get(struct_dxf, "GROUND FLOOR CEILING")
    b = _get(str(p), "GROUND FLOOR CEILING")
    assert abs(a.area - b.area) < 1e-6
    assert sorted(o.kind for o in a.openings) == sorted(o.kind for o in b.openings)


def test_arch_plot_tank_and_label(arch_dxf):
    doc = ezdxf.readfile(arch_dxf)
    views = SX.find_plan_views(doc, log=lambda m: None)
    assert len(views) == 1 and views[0].source == "arch" and views[0].slab_level == 0
    r = SX.extract_slab(doc, views[0], log=lambda m: None)
    expected = 30 * 16 + 18 * 8
    assert abs(r.area - expected) / expected < 0.02, (r.area, r.notes)   # حد المبنى مش حد الأرض
    assert any("حد أرض" in n for n in r.notes)
    assert r.rejected["x_grid"] >= 4                                     # خزان مش فتحات
    assert any(o.kind.startswith("label:LIFT") for o in r.openings)


def test_run_alignment_and_outputs(struct_dxf, tmp_path):
    results, report = SX.run([struct_dxf], str(tmp_path), log=lambda m: None)
    assert {s["name"] for s in report["slabs"]} == {"GROUND_FLOOR_CEILING", "1ST_FLOOR_CEILING"}
    other = next(r for r in results if r.view.title == "1ST FLOOR CEILING")
    # المسقطين نفس المكان جوه شيتات بينها 150 م
    assert abs(other.shift[0]) < 0.05 and abs(other.shift[1] + 150) < 0.05, other.shift
    d = ezdxf.readfile(tmp_path / "1ST_FLOOR_CEILING_slab_clean.dxf")
    assert d.header["$INSUNITS"] == 4
    assert {e.dxf.layer for e in d.modelspace()} == {"PT-Clean-Boundary", "PT-Clean-Openings"}
    assert (tmp_path / "openings.csv").exists() and (tmp_path / "report.json").exists()
    # الدورين متحاذيين: نفس إحداثيات حد البلاطة بالمليمتر
    g = ezdxf.readfile(tmp_path / "GROUND_FLOOR_CEILING_slab_clean.dxf")
    bnd = lambda doc: Polygon(next(e for e in doc.modelspace() if e.dxf.layer == "PT-Clean-Boundary").get_points("xy"))
    assert bnd(g).symmetric_difference(bnd(d)).area < 1e3 * 1e3 * 0.5   # < 0.5 م²


def test_continuity_rule(struct_dxf, arch_dxf, tmp_path):
    """معماري: بير في الدور ده ومش في اللي تحته -> مراجعة."""
    doc = ezdxf.readfile(arch_dxf)
    v = SX.find_plan_views(doc, log=lambda m: None)[0]
    upper = SX.extract_slab(doc, v, log=lambda m: None)
    SX.apply_continuity(upper, None)
    assert all(o.status == "review" for o in upper.openings)
    upper2 = SX.extract_slab(doc, v, log=lambda m: None)
    SX.apply_continuity(upper2, upper2)           # نفس المسقط تحت -> كله مستمر
    assert all(o.status == "ok" or o.kind == "X*" for o in upper2.openings)
