# -*- coding: utf-8 -*-
"""
DWG -> DXF عن طريق LibreDWG (`dwgread -O JSON`) من غير ODA.

`dwg2dxf` بتاع LibreDWG بيطلع DXF مكسور على ملفات كتير (handles مكررة،
group codes فاضية) وezdxf بيرفضه. الـ JSON بتاعه أكمل بكتير، فبنبني منه DXF
نضيف بـ ezdxf: الليّرات، البلوكات، والكيانات اللي بتفرق في قراءة المسقط
(خطوط، بولي لاين، دواير، أقواس، hatch، solid، نصوص، inserts، attributes).
الأبعاد (DIMENSION) والـ leaders بتتشال - مالهاش لازمة للمسقط.

    dwgread -O JSON -o plan.json plan.dwg
    python dwg_json_to_dxf.py plan.json plan.dxf
"""

import json
import math
import sys

import ezdxf



def _edge_angles(s):
    """زوايا قوس/إهليلج في حد الـ hatch. الـ DWG بيخزن القوس اللي مع عقارب الساعة
    بزوايا معكوسة (زي DXF)، وezdxf جوّاه بيشيله عكس عقارب الساعة: البداية
    = 360 - النهاية والنهاية = 360 - البداية. من غير التحويل ده القوس بيترسم
    في الناحية التانية من المركز والـ hatch بيتمط لمسافة كبيرة."""
    sa = math.degrees(s["start_angle"]); ea = math.degrees(s["end_angle"])
    ccw = bool(s.get("is_ccw", 1))
    if not ccw:
        sa, ea = 360.0 - ea, 360.0 - sa
    return sa, ea, ccw

def _ref(r):
    return r[-1] if isinstance(r, list) and r else None


def _aci(color, default=256):
    if not isinstance(color, dict):
        return default
    idx = color.get("index")
    if idx is not None:
        return idx
    rgb = color.get("rgb", "")
    if rgb.startswith("c3") and len(rgb) == 8:
        return int(rgb[-2:], 16)
    return default


def load_json(path):
    raw = open(path, "rb").read().decode("utf-8", "replace")
    return json.loads(raw, strict=False)


def convert(data, out_path, log=print):
    objs = data["OBJECTS"]
    H = {}
    for o in objs:
        h = o.get("handle")
        if h:
            H[h[-1]] = o

    doc = ezdxf.new("R2010", setup=False)
    ins = data.get("HEADER", {}).get("INSUNITS")
    if isinstance(ins, int):
        doc.header["$INSUNITS"] = ins

    # ---- linetypes (بالاسم بس، النمط مش مهم للقراءة) ----
    lt_name = {}
    for o in objs:
        if o.get("object") == "LTYPE":
            n = (o.get("name") or "").replace("$0$", "_")
            lt_name[o["handle"][-1]] = n
            if n and n not in doc.linetypes and n.upper() not in ("BYLAYER", "BYBLOCK"):
                try:
                    doc.linetypes.add(n, pattern=[0.0], description=n)
                except Exception:
                    pass

    # ---- layers ----
    layer_name = {}
    for o in objs:
        if o.get("object") != "LAYER":
            continue
        n = o.get("name") or "0"
        layer_name[o["handle"][-1]] = n
        if n in doc.layers:
            continue
        f = o.get("flag0", 0) or 0
        lay = doc.layers.add(n, color=max(1, min(255, _aci(o.get("color"), 7))))
        lt = lt_name.get(_ref(o.get("ltype")))
        if lt and lt in doc.linetypes:
            lay.dxf.linetype = lt
        if f & 1:
            lay.freeze()
        if f & 2:
            lay.off()

    # ---- block headers ----
    bh = {o["handle"][-1]: o for o in objs if o.get("object") == "BLOCK_HEADER"}
    msp_h = next(h for h, o in bh.items() if o.get("name") == "*Model_Space")
    block_names = {}
    for h, o in bh.items():
        n = o.get("name") or f"B{h}"
        if n.lower().startswith(("*model_space", "*paper_space")):
            continue
        if n.startswith("*"):
            n = f"ANON_{h}"
        block_names[h] = n
    for h, n in block_names.items():
        if n not in doc.blocks:
            bp = bh[h].get("base_pt") or [0, 0, 0]
            doc.blocks.new(n, base_point=tuple(bp[:3]) if len(bp) >= 2 else (0, 0))

    stats = {"written": 0, "skipped": 0, "cyclic_inserts": 0}

    # ---- مراجع بلوكات دايرية (بلوك جواه نفسه، مباشرة أو بعد كذا مستوى) ----
    # ملفات حقيقية فيها كده (غالبًا بعد bind لـ xref)، وezdxf بيدخل في
    # recursion لا نهائي وقت فكّها. بنشيل الـ INSERT اللي بيقفل الدايرة.
    children = {}
    for h in list(block_names):
        kids = set()
        for r in bh[h].get("entities", []) or []:
            o = H.get(_ref(r))
            if o and o.get("entity") in ("INSERT", "MINSERT"):
                kids.add(_ref(o.get("block_header")))
        children[h] = kids
    bad_edges = set()
    state = {}

    def dfs(h):
        state[h] = 1
        for k in children.get(h, ()):
            if k not in block_names:
                continue
            if state.get(k) == 1:
                bad_edges.add((h, k))
            elif k not in state:
                dfs(k)
        state[h] = 2

    import sys as _sys
    _sys.setrecursionlimit(max(_sys.getrecursionlimit(), 20000))
    for h in list(block_names):
        if h not in state:
            dfs(h)

    def attribs(o):
        a = {"layer": layer_name.get(_ref(o.get("layer")), "0"),
             "color": _aci(o.get("color"))}
        lf = o.get("ltype_flags")
        if lf == 3:
            lt = lt_name.get(_ref(o.get("ltype")))
            if lt and lt in doc.linetypes:
                a["linetype"] = lt
        elif lf == 1:
            a["linetype"] = "BYBLOCK"
        elif lf == 2:
            a["linetype"] = "Continuous" if "Continuous" in doc.linetypes else "BYLAYER"
        if o.get("invisible"):
            a["invisible"] = 1
        return a

    def add(space, o, owner=None):
        et = o.get("entity")
        A = attribs(o)
        try:
            if et == "LINE":
                space.add_line(o["start"][:2], o["end"][:2], dxfattribs=A)
            elif et == "LWPOLYLINE":
                pts = o.get("points") or []
                bul = o.get("bulges") or []
                if len(pts) < 2:
                    return
                data_ = [(p[0], p[1], 0, 0, bul[i] if i < len(bul) else 0)
                         for i, p in enumerate(pts)]
                space.add_lwpolyline(data_, format="xyseb", close=bool(o.get("flag", 0) & 512)
                                     or bool(o.get("flag", 0) & 1), dxfattribs=A)
            elif et == "POLYLINE_2D":
                verts = [H.get(_ref(v)) for v in o.get("vertex", [])]
                pts = [(v["point"][0], v["point"][1], 0, 0, v.get("bulge", 0.0))
                       for v in verts if v and "point" in v and not (v.get("flag", 0) & 16)]
                if len(pts) < 2:
                    pts = [(v["point"][0], v["point"][1], 0, 0, 0) for v in verts
                           if v and "point" in v]
                if len(pts) >= 2:
                    space.add_lwpolyline(pts, format="xyseb", close=bool(o.get("flag", 0) & 1),
                                         dxfattribs=A)
            elif et == "CIRCLE":
                space.add_circle(o["center"][:2], o["radius"], dxfattribs=A)
            elif et == "ARC":
                space.add_arc(o["center"][:2], o["radius"], math.degrees(o["start_angle"]),
                              math.degrees(o["end_angle"]), dxfattribs=A)
            elif et == "ELLIPSE":
                c, ma = o["center"], o["sm_axis"]
                space.add_ellipse(c[:3], ma[:3], o["axis_ratio"], o["start_angle"],
                                  o["end_angle"], dxfattribs=A)
            elif et == "SPLINE":
                cps = [(p["x"], p["y"], p.get("z", 0)) for p in o.get("ctrl_pts", [])]
                fps = o.get("fit_pts") or []
                if cps and o.get("knots"):
                    sp = space.add_open_spline(cps, degree=o.get("degree", 3),
                                               knots=o["knots"], dxfattribs=A)
                elif fps:
                    space.add_spline([(p["x"], p["y"], p.get("z", 0)) if isinstance(p, dict)
                                      else tuple(p) for p in fps], dxfattribs=A)
            elif et in ("SOLID", "TRACE"):
                pts = [o[k][:2] for k in ("corner1", "corner2", "corner3", "corner4") if k in o]
                space.add_solid(pts, dxfattribs=A)
            elif et == "TEXT":
                t = space.add_text(o.get("text_value", ""), height=o.get("height", 1.0),
                                   rotation=math.degrees(o.get("rotation", 0.0)), dxfattribs=A)
                t.dxf.insert = tuple(o["ins_pt"][:2])
                ha, va = o.get("horiz_alignment", 0), o.get("vert_alignment", 0)
                if (ha or va) and o.get("alignment_pt"):
                    t.dxf.halign, t.dxf.valign = ha, va
                    t.dxf.align_point = tuple(o["alignment_pt"][:2])
            elif et == "MTEXT":
                m = space.add_mtext(o.get("text", ""), dxfattribs=A)
                m.dxf.insert = tuple(o["ins_pt"][:3])
                m.dxf.char_height = o.get("text_height", 1.0)
                m.dxf.attachment_point = o.get("attachment", 1) or 1
                xd = o.get("x_axis_dir") or [1, 0, 0]
                m.dxf.text_direction = tuple(xd[:3])
                if o.get("rect_width"):
                    m.dxf.width = o["rect_width"]
            elif et == "HATCH":
                h = space.add_hatch(color=A.get("color", 256), dxfattribs={
                    k: v for k, v in A.items() if k != "color"})
                name = o.get("name") or "SOLID"
                if o.get("is_solid_fill"):
                    h.set_solid_fill(color=A.get("color", 256))
                else:
                    try:
                        h.set_pattern_fill(name, color=A.get("color", 256))
                    except Exception:
                        h.dxf.pattern_name = name
                        h.dxf.solid_fill = 0
                for p in o.get("paths", []):
                    if p.get("flag", 0) & 2:
                        pts = [(q["point"][0], q["point"][1], q.get("bulge", 0.0))
                               for q in p.get("polyline_paths", [])]
                        if len(pts) >= 2:
                            h.paths.add_polyline_path(pts, is_closed=bool(p.get("closed", 1)))
                    else:
                        ep = h.paths.add_edge_path()
                        for s in p.get("segs", []):
                            ct = s.get("curve_type")
                            if ct == 1:
                                ep.add_line(s["first_endpoint"], s["second_endpoint"])
                            elif ct == 2:
                                sa, ea, ccw = _edge_angles(s)
                                ep.add_arc(s["center"], s["radius"], sa, ea, ccw=ccw)
                            elif ct == 3:
                                sa, ea, ccw = _edge_angles(s)
                                ep.add_ellipse(s["center"], s["endpoint"],
                                               s["minor_major_ratio"], sa, ea, ccw=ccw)
                            elif ct == 4:
                                cps = [c["point"] for c in s.get("control_points", [])]
                                if len(cps) >= 2:
                                    ep.add_spline(control_points=cps, knot_values=s.get("knots"),
                                                  degree=s.get("degree", 3))
            elif et == "INSERT" or et == "MINSERT":
                if (owner, _ref(o.get("block_header"))) in bad_edges:
                    stats["cyclic_inserts"] += 1
                    return
                n = block_names.get(_ref(o.get("block_header")))
                if not n:
                    stats["skipped"] += 1
                    return
                sc = o.get("scale") or [1, 1, 1]
                ref = space.add_blockref(n, o["ins_pt"][:3], dxfattribs={
                    **A, "xscale": sc[0], "yscale": sc[1], "zscale": sc[2],
                    "rotation": math.degrees(o.get("rotation", 0.0))})
                for ah in o.get("attribs", []) or []:
                    at = H.get(_ref(ah))
                    if at and at.get("text_value"):
                        a = ref.add_attrib(at.get("tag", "T"), at["text_value"],
                                           insert=tuple(at["ins_pt"][:2]),
                                           dxfattribs={"height": at.get("height", 1.0)})
                        a.dxf.layer = layer_name.get(_ref(at.get("layer")), "0")
            else:
                stats["skipped"] += 1
                return
            stats["written"] += 1
        except Exception:
            stats["skipped"] += 1

    msp = doc.modelspace()
    seen = set()
    for r in bh[msp_h].get("entities", []) or []:
        # قايمة الكيانات في بعض الملفات فيها نفس الـ handle أكتر من مرة
        if _ref(r) in seen:
            stats["duplicates"] = stats.get("duplicates", 0) + 1
            continue
        seen.add(_ref(r))
        o = H.get(_ref(r))
        if o and o.get("entity"):
            add(msp, o)
    for h, n in block_names.items():
        blk = doc.blocks.get(n)
        seen_b = set()
        for r in bh[h].get("entities", []) or []:
            if _ref(r) in seen_b:
                continue
            seen_b.add(_ref(r))
            o = H.get(_ref(r))
            if o and o.get("entity"):
                add(blk, o, owner=h)
    doc.saveas(out_path)
    log(f"DXF: {stats['written']} entities written, {stats['skipped']} skipped, "
        f"{stats['cyclic_inserts']} cyclic block references dropped -> {out_path}")
    return stats


if __name__ == "__main__":
    convert(load_json(sys.argv[1]), sys.argv[2])
