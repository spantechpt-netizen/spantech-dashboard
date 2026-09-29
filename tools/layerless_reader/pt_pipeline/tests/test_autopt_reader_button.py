# -*- coding: utf-8 -*-
"""
زرار "Read a DWG / DXF drawing" في Auto PT Suite: المسار كله من غير شاشة -
الأداة بتشتغل فعلًا على المسقط الصناعي، والزونات بتتحط في خانة الـ DXF،
و Stop بيوقفها، والملف البايظ بيطلع رسالة واضحة.

    AUTOPT_SRC=Auto_PT_Suite.py python -m pytest pt_pipeline/tests/test_autopt_reader_button.py -q
"""
import glob
import os
import sys
import threading
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from test_mesh_doctor import A  # noqa: E402  (بيعمل skip لو AUTOPT_SRC مش موجود)
import make_struct_sample as MS  # noqa: E402


class Var:
    def __init__(self, v=""): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v


class J:
    def __init__(self):
        self.lines = []
        self.cancel_event = threading.Event()

    def __getattr__(self, k):
        if k in ("ok", "warn", "info", "error", "flag", "step"):
            return lambda *a: self.lines.append((k, " ".join(map(str, a))))
        if k == "log":
            return lambda m, lv="info": self.lines.append((lv, m))
        raise AttributeError(k)


def _app(monkeypatch, out):
    monkeypatch.setenv("AUTOPT_DRAWING_READER", ROOT)
    app = types.SimpleNamespace(v={"dxf": Var(), "drawing_reader_dir": Var(), "dwgread_path": Var()})
    app.bridge = types.SimpleNamespace(
        ask=lambda fn: sorted(glob.glob(os.path.join(out, "*_slab_clean.dxf"))))
    app.root = types.SimpleNamespace(after=lambda t, f: None)
    app.nav = types.SimpleNamespace(select=lambda *a: None)
    app._finish = lambda: None
    app.READER_PREFS = os.path.join(out + "_prefs.json")
    app.save_config = lambda silent=False: None
    for n in ("_find_reader_dir", "_find_dwgread", "_drawing_pipeline", "_reader_prefs", "_remember_reader"):
        setattr(app, n, getattr(A.AutoPTApp, n).__get__(app))
    app._drawing_zone_info = A.AutoPTApp._drawing_zone_info
    app._reader_python = A.AutoPTApp._reader_python
    return app


def test_button_reads_drawing_into_dxf_box(tmp_path, monkeypatch):
    src = str(tmp_path / "plan.dxf"); MS.build(src)
    out = str(tmp_path / "plan_PT")
    app = _app(monkeypatch, out)
    assert app._find_reader_dir() == ROOT
    job = J()
    app._drawing_pipeline(src, out, ROOT, None, app._reader_python(), job)
    assert not [t for k, t in job.lines if k == "error"], job.lines
    [p] = app.v["dxf"].get().split("; ")
    assert p.endswith("_slab_clean.dxf") and os.path.isfile(p)
    [z] = app._drawing_zone_info(out, [p])
    assert (z["columns"], z["beams"], z["review"]) == (12, 17, 0) and z["image"]


def test_button_stop_and_bad_file(tmp_path, monkeypatch):
    src = str(tmp_path / "plan.dxf"); MS.build(src)
    app = _app(monkeypatch, str(tmp_path / "o"))
    job = J(); job.cancel_event.set()
    app._drawing_pipeline(src, str(tmp_path / "o"), ROOT, None, app._reader_python(), job)
    assert ("warn", "Stopped.") in job.lines and not app.v["dxf"].get()
    bad = tmp_path / "bad.dxf"; bad.write_text("garbage")
    job = J()
    app._drawing_pipeline(str(bad), str(tmp_path / "b"), ROOT, None, app._reader_python(), job)
    assert any("drawing reader stopped" in t for k, t in job.lines if k == "error")
    assert not app.v["dxf"].get()


def test_reader_folder_is_asked_once(tmp_path, monkeypatch):
    """المكان بيتحفظ في ملف لوحده أول ما يتعرف: نسخة تانية من البرنامج (أو مشروع تاني) بتلاقيه من غير ما تسأل."""
    monkeypatch.delenv("AUTOPT_DRAWING_READER", raising=False)
    monkeypatch.setattr(A.sys, "argv", [str(tmp_path / "Auto_PT_Suite.py")])
    out = str(tmp_path / "x")
    app = _app(monkeypatch, out); monkeypatch.delenv("AUTOPT_DRAWING_READER", raising=False)
    assert app._find_reader_dir() is None                 # أول مرة: مش لاقيه -> البرنامج بيسأل
    app._remember_reader("drawing_reader_dir", ROOT)       # المستخدم اختار الفولدر
    app2 = _app(monkeypatch, out); monkeypatch.delenv("AUTOPT_DRAWING_READER", raising=False)
    assert app2.v["drawing_reader_dir"].get() == ""        # إعدادات مشروع تاني فاضية
    assert app2._find_reader_dir() == ROOT                 # ... ومع ذلك مابيسألش
