# -*- coding: utf-8 -*-
"""
اختبارات: نفس الرسمة لازم تطلع **نفس النتيجة** مهما اتغيّرت أسماء الليّرات،
أو الوحدة، أو الدوران، أو لو الخطة كلها جوه بلوك.

    python -m pytest test_layerless_reader.py -q
"""

import math
import os
import sys

import ezdxf
import pytest
from ezdxf.math import Matrix44

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import layerless_reader as LR  # noqa: E402
import make_sample  # noqa: E402

EXPECTED = {"columns": 16, "rc_walls": 4, "masonry_walls": 15, "openings": 2,
            "slab_parts": 1, "grids": 8, "stair_flights": 2}


def _run(path, tmp_path, **kw):
    out = str(tmp_path / "clean.dxf")
    summary, result = LR.convert(str(path), out, LR.Config(**kw), log=lambda m: None)
    return summary, result, out


def _check(summary, result, area=333.0, tol=0.04):
    c = summary["counts"]
    for k, v in EXPECTED.items():
        assert c[k] == v, (k, c[k], v)
    from shapely.geometry import Polygon
    a = sum(Polygon(b).area for b in result["boundary"])
    assert abs(a - area) / area < tol, a


@pytest.fixture
def sample(tmp_path):
    p = tmp_path / "arch.dxf"
    make_sample.build(str(p), insunits=4)
    return p


def _mutate(src, dst, fn):
    doc = ezdxf.readfile(str(src))
    fn(doc)
    doc.saveas(str(dst))


def test_baseline(sample, tmp_path):
    s, r, _ = _run(sample, tmp_path)
    _check(s, r)


def test_all_on_layer_zero(sample, tmp_path):
    """كل حاجة على ليّر 0 - مفيش أي معلومة من الأسماء."""
    def fn(doc):
        for e in doc.modelspace():
            e.dxf.layer = "0"
        for blk in doc.blocks:
            for e in blk:
                e.dxf.layer = "0"
    dst = tmp_path / "zero.dxf"
    _mutate(sample, dst, fn)
    s, r, _ = _run(dst, tmp_path)
    _check(s, r)


def test_swapped_layer_names(sample, tmp_path):
    """أسماء عكسية تمامًا (نفس اللي بيضحك على guess_role)."""
    names = ["S-COLUMN", "S-WALL", "SLAB-EDGE", "OPENINGS", "BEAMS", "DROP"]

    def fn(doc):
        for n in names:
            if n not in doc.layers:
                doc.layers.add(n)
        for i, e in enumerate(doc.modelspace()):
            e.dxf.layer = names[i % len(names)]
    dst = tmp_path / "swapped.dxf"
    _mutate(sample, dst, fn)
    s, r, _ = _run(dst, tmp_path)
    _check(s, r)


@pytest.mark.parametrize("unit,factor,ins", [("cm", 0.1, 0), ("m", 0.001, 0), ("mm", 1.0, 0)])
def test_units_without_insunits(sample, tmp_path, unit, factor, ins):
    def fn(doc):
        doc.header["$INSUNITS"] = ins
        m = Matrix44.scale(factor, factor, factor)
        for e in doc.modelspace():
            e.transform(m)
    dst = tmp_path / f"units_{unit}.dxf"
    _mutate(sample, dst, fn)
    s, r, _ = _run(dst, tmp_path)
    assert abs(s["unit_scale_to_m"] - LR.UNIT_SCALE["mm"] / factor) < 1e-9
    _check(s, r)


def test_rotated_plan(sample, tmp_path):
    def fn(doc):
        m = Matrix44.z_rotate(math.radians(27.0)) @ Matrix44.translate(50000, -20000, 0)
        for e in doc.modelspace():
            e.transform(m)
    dst = tmp_path / "rot.dxf"
    _mutate(sample, dst, fn)
    s, r, _ = _run(dst, tmp_path)
    _check(s, r)


def test_whole_plan_inside_block(sample, tmp_path):
    """الخطة كلها جوه بلوك واحد (زي xref اتعمله bind)."""
    def fn(doc):
        msp = doc.modelspace()
        blk = doc.blocks.new("PLAN_XREF")
        for e in list(msp):
            msp.move_to_layout(e, blk)
        msp.add_blockref("PLAN_XREF", (0, 0))
    dst = tmp_path / "block.dxf"
    _mutate(sample, dst, fn)
    s, r, _ = _run(dst, tmp_path)
    _check(s, r)


def test_output_layers_match_pt_suite(sample, tmp_path):
    """الطبقات اللي بنكتبها لازم تبقى نفس اللي البرنامج بيعرفها."""
    _s, _r, out = _run(sample, tmp_path)
    doc = ezdxf.readfile(out)
    assert doc.header["$INSUNITS"] == 4
    used = {e.dxf.layer for e in doc.modelspace()}
    assert used <= set(LR.CLEAN_LAYERS)
    assert all(e.dxftype() in ("LWPOLYLINE", "CIRCLE") for e in doc.modelspace())


def test_furniture_not_columns(sample, tmp_path):
    """الكومودينو 400×400 والكراسي مربعات فاضية بمقاس عمود - لازم تترفض."""
    _s, r, _ = _run(sample, tmp_path)
    truth = {(x, y) for x in (0, 6, 12, 18) for y in (0, 6, 12, 18)}
    for c in r["columns"]:
        cx, cy = c["rect"]["center"]
        assert (round(cx), round(cy)) in truth, (cx, cy)


def test_ai_path_with_fake_client(sample, tmp_path, monkeypatch):
    """مسار الـ AI من غير نت: الطلب فيه صورة لكل عنصر، والرد بيتطبّق بالـ id."""
    import json
    import types
    anthropic = pytest.importorskip("anthropic")
    sent = []

    class FakeMessages:
        def create(self, **kw):
            sent.append(kw)
            ids = [b["text"].split("id=")[1].split(".")[0] for b in kw["messages"][0]["content"]
                   if b["type"] == "text" and "id=" in b["text"]]
            body = {"items": [{"id": i, "role": "column", "confidence": 0.95,
                               "reason": "filled rectangle on grid"} for i in ids]}
            return types.SimpleNamespace(
                stop_reason="end_turn",
                content=[types.SimpleNamespace(type="text", text=json.dumps(body))])

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    # كل الأعمدة تبقى "مراجعة" عشان تتبعت
    s, r, _ = _run(sample, tmp_path, ai=True, col_accept=5.0, col_review=0.4)
    assert sent, "no request sent"
    first = sent[0]
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default"
    assert any(b["type"] == "image" for b in first["messages"][0]["content"])
    assert s["counts"]["columns"] == 16
