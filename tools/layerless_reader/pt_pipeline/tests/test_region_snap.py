# -*- coding: utf-8 -*-
"""حدود المناطق فوق بعض بالظبط: region_snap.py على زون صناعية.

منطقة منسوب حدها على بعد 13 مم من وش كمرة، ودروب حده على بعد 6 مم من حد منطقة المنسوب
وفتحة حدها على بعد 20 مم من وش حيطة بتغطي نص ضلعها بس -> بعد التلزيق الخطوط واحدة.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEP = os.path.join(os.path.dirname(HERE), "steps", "region_snap.py")


def test_regions_snap_onto_faces_and_each_other(tmp_path):
    R = {"slabs": [{"outline": [[0, 0], [20, 0], [20, 12], [0, 12]]}],
         "openings": [{"poly": [[14, 4.02], [17, 4.02], [17, 7], [14, 7]], "kind": "stair"}],
         "level_zones": [{"poly": [[0, 0], [9.837, 0], [9.837, 12], [0, 12]], "level_m": 0.5, "se_mm": -100}],
         "thick_zones": [],
         "drops": [{"poly": [[9.831, 5], [11.5, 5], [11.5, 7], [9.831, 7]], "thickness_mm": 400}]}
    M = {"beams": [{"p1": [10, 0], "p2": [10, 12], "w": 0.30, "mark": "B1"}],   # وشها الغربي x=9.85
         "walls": [{"p1": [15, 3.85], "p2": [16.5, 3.85], "t": 0.30}],           # وشها x: 15..16.5, y=4.0
         "cols": []}
    json.dump(R, open(tmp_path / "Z_res_c.json", "w")); json.dump(M, open(tmp_path / "Z_members_c.json", "w"))
    r = subprocess.run([sys.executable, STEP, "Z"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    R = json.load(open(tmp_path / "Z_res_c.json"))
    lz = {round(x, 4) for x, y in R["level_zones"][0]["poly"] if x > 5}
    assert lz == {9.85}, lz                                           # على وش الكمرة
    dr = {round(x, 4) for x, y in R["drops"][0]["poly"] if x < 11}
    assert dr == {9.85}, dr                                           # نفس خط منطقة المنسوب
    op = {round(y, 4) for x, y in R["openings"][0]["poly"] if y < 5}
    assert op == {4.0}, op                                            # على وش الحيطة


def test_beams_cut_at_column_wall_and_girder_axes(tmp_path):
    """كمرة طويلة معدّية على عمود في النص وكمرة شايلة وحيطة: بتتقطع عند آكس كل واحدة، والحتت ورا بعض بالظبط.
    قطع جنب طرف الكمرة (≤ 30 سم) مابيتعملش."""
    STEP2 = os.path.join(os.path.dirname(HERE), "steps", "beam_split.py")
    M = {"cols": [{"rect": {"corners": [[5.8, -0.2], [6.2, -0.2], [6.2, 0.2], [5.8, 0.2]]}}],
         "walls": [{"p1": [15, -3], "p2": [15, 3], "t": 0.25}],
         "beams": [{"p1": [0, 0], "p2": [18, 0], "w": 0.3, "mark": "B1", "priority": 5},
                   {"p1": [10, -6], "p2": [10, 6], "w": 0.4, "mark": "G1", "priority": 9},       # شايلة
                   {"p1": [17.85, 0], "p2": [17.85, 5], "w": 0.3, "mark": "B2", "priority": 4}]}  # جنب الطرف
    json.dump(M, open(tmp_path / "Z_members_c.json", "w"))
    r = subprocess.run([sys.executable, STEP2, "Z"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    B = json.load(open(tmp_path / "Z_members_c.json"))["beams"]
    b1 = sorted([b for b in B if b["mark"] == "B1"], key=lambda b: b["p1"][0])
    assert [round(b["p1"][0], 3) for b in b1] == [0, 6, 10, 15]
    assert [round(b["p2"][0], 3) for b in b1] == [6, 10, 15, 18]
    assert all(b["w"] == 0.3 and b["priority"] == 5 for b in b1)
    g1 = sorted([b for b in B if b["mark"] == "G1"], key=lambda b: b["p1"][1])
    assert [round(b["p1"][1], 3) for b in g1] == [-6, 0] and round(g1[0]["p2"][1], 3) == 0
