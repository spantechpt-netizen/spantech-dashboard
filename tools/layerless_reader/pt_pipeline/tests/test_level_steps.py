"""كابل بيعدّي بين منسوبين (Auto PT Suite 18.160) - من غير RAM.

    AUTOPT_SRC=Auto_PT_Suite.py python -m pytest pt_pipeline/tests/test_level_steps.py -q
"""
import os
import pytest

from test_mesh_doctor import A, Job   # بيعمل skip لو AUTOPT_SRC مش موجود


def _run(se_mm, t_mm=300.0, cover=50.0):
    p = A.TendonDesignParams()
    p.slab_thickness = t_mm
    p.per_direction_covers = True
    p.top_cover_x = cover
    site = {"slabs": [{"points": [(10, -5), (20, -5), (20, 5), (10, 5)], "is_drop": False,
                       "thickness": t_mm, "surface_elevation_mm": se_mm}]}
    t = {"dir": "X", "profile": [{"pos": (0, 0), "depth": 150, "anchor": True},
                                 {"pos": (5, 0), "depth": 250, "sag": True},
                                 {"pos": (15, 0), "depth": 50, "high": True},
                                 {"pos": (20, 0), "depth": 150}]}
    return A.split_tendons_at_level_steps([t], p, Job(), site)


def test_small_step_keeps_one_tendon():
    out, cuts, passes = _run(-60.0)            # 60 + 50 = 110 < 150: continuous
    assert (cuts, passes) == (0, 1) and len(out) == 1
    st = [q for q in out[0]["profile"] if q.get("level_step")]
    assert [q["depth"] for q in st] == [110.0, 50.0]     # higher side first, lower side after
    assert abs(st[0]["pos"][0] - 9.95) < 0.01 and abs(st[1]["pos"][0] - 10.05) < 0.01


def test_big_step_splits_tendons():
    out, cuts, passes = _run(-150.0)           # 150 + 50 = 200 > 150: separate tendons
    assert (cuts, passes) == (1, 0) and len(out) == 2
    a, b = out
    assert a["profile"][-1]["depth"] == 150.0 and abs(a["profile"][-1]["pos"][0] - 9.95) < 0.01
    assert b["profile"][0]["depth"] == 150.0 and abs(b["profile"][0]["pos"][0] - 10.05) < 0.01
    assert all(q["pos"][0] < 10 for q in a["profile"]) and all(q["pos"][0] > 10 for q in b["profile"])


def test_no_levels_untouched():
    p = A.TendonDesignParams()
    t = {"dir": "X", "profile": [{"pos": (0, 0), "depth": 150}, {"pos": (9, 0), "depth": 150}]}
    out, cuts, passes = A.split_tendons_at_level_steps([t], p, Job(), {"slabs": []})
    assert out == [t] and cuts == passes == 0


def test_pieces_recorded_for_jacks():
    p = A.TendonDesignParams(); p.slab_thickness = 300.0; p.per_direction_covers = True; p.top_cover_x = 50.0
    site = {"slabs": [{"points": [(10, -5), (20, -5), (20, 5), (10, 5)], "is_drop": False,
                       "thickness": 300.0, "elevation": -150.0}]}      # the level as read from a .cpt (TOC)
    t = {"dir": "X", "profile": [{"pos": (0, 0), "depth": 150}, {"pos": (18, 0), "depth": 150}]}
    out, cuts, _ = A.split_tendons_at_level_steps([t], p, Job(), site)
    assert cuts == 1 and t["_level_pieces"] == out and all("_level_pieces" not in q for q in out)
    again, cuts2, _ = A.split_tendons_at_level_steps(out, p, Job(), site)   # a second write does not cut twice
    assert cuts2 == 0 and len(again) == 2
