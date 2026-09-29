"""هاتش جوه بلوك معكوس (xscale = -1، extrusion = (0,0,-1)): الحدود لازم تطلع في مكانها الحقيقي.
HDB: أعمدة الأرضي جوه بلوك معكوس كانت بتتقرا على +x بدل -x وبتضيع."""
import os, sys
import ezdxf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import slab_extractor as SX, layerless_reader as LR


def _rings(xscale):
    d = ezdxf.new(); b = d.blocks.new("COLB")
    b.add_hatch().paths.add_polyline_path([(1, 1), (1.3, 1), (1.3, 2.2), (1, 2.2)], is_closed=True)
    p = b.add_hatch().paths.add_edge_path()
    for a, c in [((3, 1), (3.3, 1)), ((3.3, 1), (3.3, 2)), ((3.3, 2), (3, 2)), ((3, 2), (3, 1))]:
        p.add_line(a, c)
    d.modelspace().add_blockref("COLB", (100, 50), dxfattribs={"xscale": xscale})
    return [LR.hatch_rings(e)[0] for e in SX._explode(list(d.modelspace())) if e.dxftype() == "HATCH"]


def _xr(r):
    return round(min(p[0] for p in r), 2), round(max(p[0] for p in r), 2)


def test_normal_block():
    assert [_xr(r) for r in _rings(1)] == [(101.0, 101.3), (103.0, 103.3)]


def test_mirrored_block():
    assert [_xr(r) for r in _rings(-1)] == [(98.7, 99.0), (96.7, 97.0)]
