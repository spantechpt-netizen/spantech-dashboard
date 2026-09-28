# -*- coding: utf-8 -*-
"""قبل البناء في RAM: إيه اللي مكتوب في الرسمة وإيه اللي هياخد الافتراضي - رسالة التأكيد.

لكل زون (من نصوص ملف الزون النضيف):
  - سُمك البلاطة "t=" على الحد، أو الافتراضي؛
  - الدروب: بسُمك مكتوب "DROP t=" أو من غير سُمك "DROP" -> سُمك الدروب الافتراضي؛
  - الكمرات: "(WxD)" أو من غير عمق "(Wx?)" -> العرض من المخطط والعمق الافتراضي؛
  - المناسيب: "LEVEL ... SE=" - من غيرها السقف كله منسوب واحد (صفر)، مش خطأ.
"""
import os
import re

import ezdxf

T_RE = re.compile(r"\bt\s*=\s*(\d{2,4})", re.I)
LOAD_RE = re.compile(r"LOAD\s+SDL\s*=\s*([\d.]+)\s+LL\s*=\s*([\d.]+)\s*(.*)", re.I)
SE_RE = re.compile(r"\bSE\s*=\s*([+\-]?\d+)", re.I)
BEAM_RE = re.compile(r"\((\d{2,4})\s*[xX]\s*(\d{2,4}|\?)\)")


def inspect_zone(path):
    msp = ezdxf.readfile(path).modelspace()
    z = {"zone": os.path.basename(path).replace("_slab_clean.dxf", ""), "slab_t": None,
         "drops": 0, "drops_no_t": 0, "zones_t": 0, "levels": [], "beams": 0, "beams_no_d": 0,
         "columns": 0, "walls": 0, "openings": 0, "pour_strips": 0, "load_areas": []}
    lpolys, ltexts = [], []
    for e in msp:
        lay = e.dxf.layer
        if e.dxftype() == "LWPOLYLINE":
            if lay in ("PT-Clean-Columns", "PT-Clean-Columns-Above"):
                z["columns"] += 1
            elif lay in ("PT-Clean-Walls", "PT-Clean-Walls-Above"):
                z["walls"] += 1
            elif lay == "PT-Clean-Openings":
                z["openings"] += 1
            elif lay == "PT-Clean-Loads":
                lpolys.append([(p[0] / 1000.0, p[1] / 1000.0) for p in e.get_points()])
            continue
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        t = e.dxf.text if e.dxftype() == "TEXT" else e.text
        up = t.upper().strip()
        if lay == "PT-Clean-Boundary":
            m = T_RE.search(t)
            if m:
                z["slab_t"] = int(m.group(1))
        elif lay == "PT-Clean-Drops":
            if up.startswith("DROP"):
                z["drops"] += 1
                z["drops_no_t"] += 0 if T_RE.search(t) else 1
            elif up.startswith("LEVEL"):
                m = SE_RE.search(t)
                if m:
                    z["levels"].append(int(m.group(1)))
            elif up.startswith("ZONE"):
                z["zones_t"] += 1
            elif up.startswith("POUR"):
                z["pour_strips"] += 1
        elif lay == "PT-Clean-Loads":
            m = LOAD_RE.search(t)
            if m:
                ltexts.append(((e.dxf.insert.x / 1000.0, e.dxf.insert.y / 1000.0), float(m.group(1)), float(m.group(2)), m.group(3).strip()))
        elif lay == "PT-Clean-Beams":
            m = BEAM_RE.search(t)
            if m:
                z["beams"] += 1
                z["beams_no_d"] += 1 if m.group(2) == "?" else 0
    # كل مضلع حمل بياخد النص اللي جواه (مسقط الأحمال)
    if lpolys:
        from shapely.geometry import Polygon, Point
        # النص لأصغر مضلع حواليه (زي RAM): مضلع كبير فيه مناطق تانية مابياخدش نصوصها
        G = [(pts, Polygon(pts).buffer(0)) for pts in lpolys]
        for t in ltexts:
            own = [(g.area, pts, g) for pts, g in G if g.area > 0 and g.buffer(0.01).contains(Point(t[0]))]
            if own:
                a, pts, g = min(own, key=lambda q: q[0])
                if not any(x["poly"] is pts for x in z["load_areas"]):
                    z["load_areas"].append({"poly": pts, "sdl": t[1], "ll": t[2], "usage": t[3], "area": a})
    return z


def _dflt(v):
    v = float(v or 0)
    return f"default {v:.0f} mm" if v > 0 else "NO default set - enter one in Defaults"


def summary(zones, data, stage2=True):
    """سطور رسالة التأكيد (زي رسالة Auto PT Suite قبل البناء)."""
    L = []
    miss_t = [z["zone"] for z in zones if not z["slab_t"]]
    have_t = sorted({z["slab_t"] for z in zones if z["slab_t"]})
    L.append("THICKNESS / DEPTH")
    if have_t:
        L.append(f"  Slab thickness from the drawing: {', '.join(f'{t} mm' for t in have_t)}"
                 f" ({len(zones) - len(miss_t)} of {len(zones)} zone(s))")
    if miss_t:
        L.append(f"  ⚠ Slab thickness NOT in the drawing for {len(miss_t)} zone(s) "
                 f"({', '.join(miss_t[:6])}{'...' if len(miss_t) > 6 else ''}) "
                 f"-> {_dflt(data['slab_thickness'])}")
    nd = sum(z["drops"] for z in zones); nd0 = sum(z["drops_no_t"] for z in zones)
    if nd:
        L.append(f"  Drop panels: {nd}" + (f" - ⚠ {nd0} with no thickness written -> {_dflt(data['drop_thickness'])}"
                                          if nd0 else " - thickness from the drawing"))
    nb = sum(z["beams"] for z in zones); nb0 = sum(z["beams_no_d"] for z in zones)
    if nb:
        L.append(f"  Beams: {nb}" + (f" - ⚠ {nb0} with no depth written -> width from the drawing, depth = "
                                    f"{_dflt(data['beam_depth'])}" if nb0 else " - width and depth from the drawing"))
    L.append("")
    L.append("LEVELS")
    lv = [z for z in zones if z["levels"]]
    for z in lv:
        L.append(f"  {z['zone']}: {len(z['levels'])} level zone(s) SE "
                 + ", ".join(f"{v:+d}" for v in sorted(set(z["levels"]))) + " mm (main slab = 0)")
    flat = [z["zone"] for z in zones if not z["levels"]]
    if flat:
        L.append(f"  {len(flat)} zone(s) with no level difference in the drawing -> the whole slab at one level")
    L.append("")
    L.append("LOADS")
    la = [a for z in zones for a in z.get("load_areas", [])]
    if not la:
        L.append("  No loading plan in the drawing" + (" -> the defaults below on the whole slab" if stage2 else ""))
    if la or stage2:
        if la:
            by = {}
            for a in la:
                k = (a["usage"], a["sdl"], a["ll"]); by[k] = by.get(k, 0.0) + a["area"]
            L.append("  From the drawing's LOADING PLAN (each area with its own loads):")
            for (u, sd, ll), ar in sorted(by.items(), key=lambda q: -q[1]):
                L.append(f"    {u}: SIDL {sd:g} + LL {ll:g} kN/m²  ({ar:.0f} m²)")
            nz = [z["zone"] for z in zones if not z.get("load_areas")]
            if nz:
                L.append(f"  ⚠ {len(nz)} zone(s) not covered by the loading plan -> defaults below")
            if stage2:
                L.append("  The defaults below go on the whole slab; each loading-plan area adds the difference (+ or -):")
    if stage2:
        if data.get("write_area_loads"):
            L.append(f"  SDL {float(data['sdl']):.2f} kN/m²  ·  Live load {float(data['live_load']):.2f} kN/m² (on the slab area)")
        else:
            L.append("  SDL / live load: NOT written - self weight only")
        if data.get("write_wall_loads"):
            L.append(f"  Arch. walls: {float(data['arch_wall_density']):g} kN/m³ × {float(data['arch_wall_height']):.2f} m "
                     f"× {float(data['arch_wall_opening_factor']):.2f}")
        else:
            L.append("  Arch. walls: none")
        if data.get("write_edge_load") and float(data.get("edge_line_load") or 0) > 0:
            L.append(f"  Edge line load: {float(data['edge_line_load']):.2f} kN/m on the outer slab edge")
        else:
            L.append("  Edge line load: none")
        L.append("")
        L.append("SUPPORT LINES / DESIGN STRIPS: " + ("drawn" if data.get("write_design_strips") else "not drawn"))
    return L


def missing_count(zones):
    return (sum(1 for z in zones if not z["slab_t"]) + sum(z["drops_no_t"] for z in zones)
            + sum(z["beams_no_d"] for z in zones))
