# -*- coding: utf-8 -*-
"""
اختبار من الأول للآخر: مسقط إنشائي صناعي -> python -m pt_pipeline.convert -> DXF لـ Auto PT Suite.
الحقيقة معروفة (make_struct_sample)، والنتيجة لازم تطابقها مهما اتغيرت الإحداثيات أو الوحدة أو الزاوية.

    python -m pytest pt_pipeline/tests -q
"""
import collections
import csv
import json
import math
import os
import subprocess
import sys

import ezdxf
import pytest
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import make_struct_sample as MS  # noqa: E402


def _transform(path, scale=1.0, angle=0.0):
    doc = ezdxf.readfile(path)
    from ezdxf.math import Matrix44
    m = Matrix44.chain(Matrix44.scale(scale, scale, 1), Matrix44.z_rotate(math.radians(angle)))
    for e in doc.modelspace():
        try:
            e.transform(m)
        except Exception:
            pass
    if scale != 1.0:
        doc.header["$INSUNITS"] = 5
    doc.saveas(path)


def _run(tmp_path, origin=(0, 0), scale=1.0, angle=0.0):
    src = str(tmp_path / "s.dxf")
    truth = MS.build(src, origin)
    if scale != 1.0 or angle:
        _transform(src, scale, angle)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "pt_pipeline.convert", src, "-o", str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    return truth, r, out


def _read(out):
    [dxf] = [f for f in os.listdir(out) if f.endswith("_slab_clean.dxf")]
    doc = ezdxf.readfile(os.path.join(out, dxf))
    msp = doc.modelspace()
    lay = collections.Counter(e.dxf.layer for e in msp if e.dxftype() == "LWPOLYLINE")
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    [b] = msp.query('LWPOLYLINE[layer=="PT-Clean-Boundary"]')
    area = Polygon([p[:2] for p in b.get_points()]).area / 1e6
    rows = list(csv.reader(open(os.path.join(out, "members.csv"), encoding="utf-8")))
    return doc, lay, texts, area, rows


@pytest.mark.parametrize("case", [
    dict(),
    dict(origin=(512000.0, 3104000.0)),       # إحداثيات مشروع كبيرة
    dict(scale=0.1),                          # سم
    dict(angle=27.0),                         # مسقط ملفوف
])
def test_end_to_end(tmp_path, case):
    truth, r, out = _run(tmp_path, **case)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "CHECK OK" in r.stdout
    doc, lay, texts, area, rows = _read(out)
    assert doc.header["$INSUNITS"] == 4
    assert lay["PT-Clean-Columns"] == truth["columns"]
    assert lay["PT-Clean-Beams"] == truth["beams"]
    assert lay["PT-Clean-Openings"] == truth["openings"]
    assert f"t={truth['thickness']}" in texts
    # الحد على الوش الخارجي للكمرات الطرفية وبيغطي الأعمدة: بين الاتنين
    assert 18.3 * 12.3 - 0.5 <= area <= 18.4 * 12.4 + 0.01
    beams = [x for x in rows if x and x[1] == "beam"]
    assert all(x[2] == "B1" and x[3] == "300" and x[4] == "700" for x in beams)
    assert not [x for x in rows if x and x[1] == "REVIEW"]
    rep = json.load(open(os.path.join(out, "report.json")))
    assert rep["ok"] is True


def _work(tmp_path):
    src = str(tmp_path / "s.dxf"); MS.build(src)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "pt_pipeline.convert", src, "-o", str(out), "--keep-work"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:]
    for root, dirs, files in os.walk(out):
        tags = [f[:-len("_members_c.json")] for f in files if f.endswith("_members_c.json")]
        if tags:
            return root, tags
    raise AssertionError("no work folder")


def _check(work, tags):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "pt_pipeline", "steps", "zone_check.py"), *tags],
                       cwd=work, capture_output=True, text=True)
    return r.stdout


def test_zone_check_catches_uncovered_and_twin(tmp_path):
    """الفحص لازم يمسك عمود برّه البلاطة وكمرة مكررة - ومايعدّيش الملف."""
    work, tags = _work(tmp_path)
    assert "CHECK OK" in _check(work, tags)
    t = tags[0]
    p = os.path.join(work, f"{t}_members_c.json")
    M = json.load(open(p))
    c = json.loads(json.dumps(M["cols"][0]))
    c["rect"]["corners"] = [(x + 100.0, y) for x, y in c["rect"]["corners"]]
    M["cols"].append(c)
    json.dump(M, open(p, "w"))
    out = _check(work, tags)
    assert "CHECK FAILED" in out and "not covered by slab 1" in out
    M["cols"].pop()
    M["beams"].append(json.loads(json.dumps(M["beams"][0])))
    json.dump(M, open(p, "w"))
    assert "CHECK FAILED" in _check(work, tags)


@pytest.mark.parametrize("note", [True, False])
def test_flat_slab_box_drops_and_planted_note(tmp_path, note):
    """دروب مرسوم مستطيل عادي حوالين كل عمود + ملاحظة 'Planted Column' على عمود واحد بس."""
    src = str(tmp_path / "f.dxf")
    truth = MS.build_flat(src, drop_note=note)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "pt_pipeline.convert", src, "-o", str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    doc, lay, texts, area, rows = _read(out)
    assert lay["PT-Clean-Columns"] == truth["columns"]
    assert lay["PT-Clean-Columns-Above"] == truth["planted"]
    drops = [t for t in texts if t.startswith("DROP")]
    assert len(drops) == truth["drops"]
    if truth["drop_t"]:
        assert all(t.startswith(f"DROP t={truth['drop_t']}") for t in drops)
        assert not [x for x in rows if x and x[1] == "REVIEW" and x[2] == "drop thickness"]
    else:
        assert all(not t.startswith("DROP t=") for t in drops)
        assert [x for x in rows if x and x[1] == "REVIEW" and x[2] == "drop thickness"]


def test_box_drops_take_given_thickness(tmp_path):
    """دروب من غير سُمك مكتوب + --drop-thickness 400 -> DROP t=400، والسُمك المكتوب لو موجود يغلب."""
    src = str(tmp_path / "f.dxf")
    MS.build_flat(src, drop_note=False)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "pt_pipeline.convert", src, "-o", str(out), "--drop-thickness", "400"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:]
    doc, lay, texts, area, rows = _read(out)
    drops = [t for t in texts if t.startswith("DROP")]
    assert drops and all(t.startswith("DROP t=400") for t in drops)
    assert not [x for x in rows if x and x[1] == "REVIEW" and x[2] == "drop thickness"]
