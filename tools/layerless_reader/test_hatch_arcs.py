"""Hatch boundaries with clockwise arc edges.

The case comes from a real structural DWG: a small curved stopped column
(about 1.2 x 0.3 m) hatched with a boundary of arc, line, arc, line where the
outer arc runs clockwise. Converted the old way, the arc landed on the other
side of its centre and the hatch stretched 8 m down the sheet, over a rebar
line, and was read as a concrete wall under the slab.
"""
import math
import os
import sys

import ezdxf

sys.path.insert(0, os.path.dirname(__file__))
import dwg_json_to_dxf as DJ  # noqa: E402
import layerless_reader as LR  # noqa: E402

from shapely.geometry import Polygon  # noqa: E402

C_OUT = (1109.7512618084058, 452.1652429004605)
R_OUT = 8.37029087713981
C_IN = (1109.7407432277982, 452.15994176472645)
R_IN = 8.08206858817024


def _dwg_json():
    """Minimal LibreDWG JSON: one layer, model space, one hatch.

    The outer arc is stored the way DWG stores a clockwise arc edge: angles
    mirrored (329..337 degrees standing for 31..23) with is_ccw = 0."""
    hatch = {
        "entity": "HATCH", "handle": [0, 1, 0x30], "layer": [5, 1, 0x10],
        "name": "ANSI31", "is_solid_fill": 0,
        "paths": [{"flag": 1, "segs": [
            {"curve_type": 2, "center": list(C_OUT), "radius": R_OUT,
             "start_angle": math.radians(329.0255929974356),
             "end_angle": math.radians(337.4105838808449), "is_ccw": 0},
            {"curve_type": 1, "first_endpoint": [1117.48, 455.38],
             "second_endpoint": [1117.2, 455.26]},
            {"curve_type": 2, "center": list(C_IN), "radius": R_IN,
             "start_angle": math.radians(22.565837532672578),
             "end_angle": math.radians(30.938544111673686), "is_ccw": 1},
            {"curve_type": 1, "first_endpoint": [1116.67, 456.32],
             "second_endpoint": [1116.93, 456.47]},
        ]}],
    }
    return {"OBJECTS": [
        {"object": "LAYER", "handle": [0, 1, 0x10], "name": "STOPPED COLUMN"},
        {"object": "BLOCK_HEADER", "handle": [0, 1, 0x20], "name": "*Model_Space",
         "entities": [[5, 1, 0x30]]},
        hatch,
    ]}


def _area(rings):
    acc = None
    for r in rings:
        p = Polygon(r).buffer(0)
        acc = p if acc is None else acc.symmetric_difference(p)
    return acc


def test_clockwise_arc_edge_stays_on_its_side(tmp_path):
    out = tmp_path / "h.dxf"
    DJ.convert(_dwg_json(), str(out), log=lambda *_: None)
    hatch = ezdxf.readfile(str(out)).modelspace().query("HATCH")[0]

    rings = LR.hatch_rings(hatch)
    assert len(rings) == 1
    ys = [p[1] for p in rings[0]]
    # the column sits between y = 455.26 and 456.47 - nothing reaches down to 447.9
    assert min(ys) > 455.2 and max(ys) < 456.5

    g = _area(rings)
    assert g.geom_type == "Polygon"              # one piece, not a zigzag of slivers
    # band between two arcs about 1.2 m long and 0.29 m thick
    assert 0.3 < g.area < 0.4


def test_hatch_rings_chain_reversed_edges():
    """Edges out of order and pointing the wrong way still close one ring."""
    doc = ezdxf.new()
    h = doc.modelspace().add_hatch()
    ep = h.paths.add_edge_path()
    ep.add_line((0, 0), (4, 0))
    ep.add_line((0, 1), (4, 1))        # reversed: should run 4,1 -> 0,1
    ep.add_line((4, 0), (4, 1))
    ep.add_line((0, 1), (0, 0))
    rings = LR.hatch_rings(h)
    assert len(rings) == 1
    assert abs(Polygon(rings[0]).area - 4.0) < 1e-6
