# -*- coding: utf-8 -*-
"""PT Model Builder: المرحلة 1 + رسالة التأكيد + المرحلة 2 على جلسة RAM وهمية.

    python -m pytest tests -q
    AUTOPT_SRC=Auto_PT_Suite.py python -m pytest tests -q     # المرحلة 2 (بتولّد ram_core من البرنامج)
"""
import importlib
import os
import shutil
import subprocess
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
READER = os.path.join(os.path.dirname(ROOT), "layerless_reader")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(READER, "pt_pipeline", "tests"))
import make_struct_sample as MS                      # noqa: E402
from ptmb import preflight, settings as SET, stage1  # noqa: E402


def _data(**kw):
    d = dict(SET.DEFAULTS, reader_dir=READER)
    d.update(kw)
    return d


def test_stage1_and_check_lists_what_is_missing(tmp_path):
    """بلاطة مسطحة دروباتها من غير سُمك مكتوب ومن غير --drop-thickness: رسالة التأكيد بتقول هياخد الافتراضي."""
    src = str(tmp_path / "f.dxf"); MS.build_flat(src, drop_note=False)
    rc, zones, rep = stage1.run(src, str(tmp_path / "out"), _data(drop_thickness=0), log=lambda *a, **k: None)
    assert rc == 0 and len(zones) == 1
    [z] = [preflight.inspect_zone(p) for p in zones]
    assert z["slab_t"] == 250 and z["drops"] == 12 and z["drops_no_t"] == 12 and z["levels"] == []
    txt = "\n".join(preflight.summary([z], _data(drop_thickness=380)))
    assert "12 with no thickness written -> default 380 mm" in txt
    assert "the whole slab at one level" in txt
    assert "NO default set" in "\n".join(preflight.summary([z], _data(drop_thickness=0)))
    assert "SDL 2.00" in txt and "SUPPORT LINES / DESIGN STRIPS: drawn" in txt


def test_stage1_beams_with_depth(tmp_path):
    src = str(tmp_path / "s.dxf"); truth = MS.build(src)
    rc, zones, _ = stage1.run(src, str(tmp_path / "out"), _data(), log=lambda *a, **k: None)
    [z] = [preflight.inspect_zone(p) for p in zones]
    assert z["beams"] == truth["spans"] and z["beams_no_d"] == 0 and z["columns"] == truth["columns"]
    assert "width and depth from the drawing" in "\n".join(preflight.summary([z], _data()))


# ------------------------------------------------------------ المرحلة 2 (جلسة RAM وهمية)
SRC = os.environ.get("AUTOPT_SRC", "")


@pytest.fixture(scope="module")
def core(tmp_path_factory):
    if not os.path.isfile(SRC):
        pytest.skip("set AUTOPT_SRC to the Auto PT Suite .py file")
    for m in ("tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"):
        sys.modules.setdefault(m, types.ModuleType(m))
    sys.path.insert(0, ROOT)
    import build_core
    out = os.path.join(ROOT, "ptmb", "ram_core.py")
    n, lines, undefined = build_core.build(SRC, out)
    assert not undefined, undefined
    import ptmb.ram_core as C
    return importlib.reload(C)


class Elem:
    def __init__(self, store, kind):
        self.kind = kind; store.append(self)
        self.thickness = 0.0; self.toc = 0.0; self.priority = 0
    def delete(self): pass


class Layer:
    def __init__(self): self.items = []
    def __getattr__(self, name):
        if name.startswith("add_"):
            return lambda *a, **k: Elem(self.items, name[4:])
        raise AttributeError(name)


class FakeSession:
    last = None

    def __init__(self, job, api_path=None):
        self.job = job
        self.api = {"Point2D": lambda x, y: (x, y), "Polygon2D": lambda pts: pts,
                    "LineSegment2D": lambda a, b: (a, b), "Polyline2D": None, "ElevationReference": None}
        self.model = types.SimpleNamespace(cad_manager=types.SimpleNamespace(structure_layer=Layer()))
        FakeSession.last = self

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def open(self, p): self.cpt_path = p
    def save(self, p): open(p, "w").write("fake")


def test_stage2_builds_levels_and_thickness(tmp_path, core):
    """الزون بمنسوبين (-100/+150) ودروب من غير سُمك: المنسوب بيدخل toc، والدروب بياخد الافتراضي."""
    import ezdxf
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4; m = doc.modelspace()

    def rect(x0, y0, x1, y1, lay):
        m.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": lay})
    rect(0, 0, 12000, 12000, "PT-Clean-Boundary")
    m.add_text("t=220", dxfattribs={"layer": "PT-Clean-Boundary", "insert": (6000, 9000), "height": 300})
    rect(0, 0, 4000, 12000, "PT-Clean-Drops")
    m.add_text("LEVEL t=220 SE=-100", dxfattribs={"layer": "PT-Clean-Drops", "insert": (1000, 10000), "height": 250})
    rect(5000, 5000, 7000, 7000, "PT-Clean-Drops")
    m.add_text("DROP", dxfattribs={"layer": "PT-Clean-Drops", "insert": (5800, 5800), "height": 250})
    for x in (200, 5800, 11600):
        for y in (200, 5800, 11600):
            rect(x - 200, y - 200, x + 200, y + 200, "PT-Clean-Columns")
    p = str(tmp_path / "Z1_slab_clean.dxf"); doc.saveas(p)
    tpl = str(tmp_path / "template.cpt"); open(tpl, "w").write("x")

    z = preflight.inspect_zone(p)
    assert z["slab_t"] == 220 and z["drops_no_t"] == 1 and z["levels"] == [-100]

    from ptmb import stage2
    stage2.core = lambda: core
    data = _data(template_cpt=tpl, drop_thickness=450, write_area_loads=False, write_design_strips=False)
    log = []
    job = core.Job(log_cb=lambda msg, level="info": log.append((level, msg)))
    done, failed = stage2.run([p], data, job, str(tmp_path / "RAM"), session_cls=FakeSession)
    assert done and not failed, log[-20:]
    items = FakeSession.last.model.cad_manager.structure_layer.items
    slabs = [e for e in items if e.kind == "slab_area"]
    assert sorted(round(e.thickness) for e in slabs) == [220, 220, 450], [(e.thickness, e.toc) for e in slabs]
    assert sorted(round(e.toc) for e in slabs) == [-100, 0, 0]
    assert len([e for e in items if "column" in e.kind]) == 9
