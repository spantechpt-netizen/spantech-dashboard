"""X void = diagonals of a rectangle; a '+' (joint line crossing a wall line) is not a void."""
import json, os, pickle, subprocess, sys

STEP = os.path.join(os.path.dirname(__file__), "..", "steps", "xvoids.py")


def _run(tmp, segs):
    json.dump({"slabs": [{"outline": [(0, 0), (40, 0), (40, 40), (0, 40)]}], "openings": []}, open(tmp / "T_res.json", "w"))
    json.dump({"segs": segs}, open(tmp / "T_geo.json", "w"))
    pickle.dump((None, [], []), open(tmp / "cache.pkl", "wb"))
    subprocess.run([sys.executable, os.path.abspath(STEP), "T"], cwd=tmp, check=True, capture_output=True)
    return json.load(open(tmp / "T_xvoids.json"))["voids"]


def test_x_is_void(tmp_path):
    box = [[[10, 10], [20, 10]], [[20, 10], [20, 18]], [[20, 18], [10, 18]], [[10, 18], [10, 10]]]
    assert len(_run(tmp_path, box + [[[10, 10], [20, 18]], [[10, 18], [20, 10]]])) == 1


def test_x_without_box_is_void(tmp_path):
    assert len(_run(tmp_path, [[[10, 10], [20, 18]], [[10, 18], [20, 10]]])) == 1


def test_plus_is_not_void(tmp_path):
    assert _run(tmp_path, [[[20, 0], [20, 40]], [[2, 20], [38, 20]]]) == []


def test_square_plus_is_not_void(tmp_path):
    walls = [[[0, 0], [40, 0]], [[40, 0], [40, 40]], [[40, 40], [0, 40]], [[0, 40], [0, 0]]]
    assert _run(tmp_path, walls + [[[20, 2], [20, 38]], [[2, 20], [38, 20]]]) == []
