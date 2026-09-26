"""سُمك البلاطة من بلوكات سُمك (attribute THK) - حتى لو على ليّر مقفول (بيتعلّم hidden).
القطع = البلاطة بين خطوط الرسمة (فجوات ≤ GAP مقفولة، خطوط شرايح الصب مستبعدة).
كل ملاحظة -> القطعة اللي هي فيها. السُمك الأساسي = الأكبر مساحة، والباقي thick_zones.
usage: python thick_attr.py <dxf> <scale> TAG...  env GAP, EXCL_POLYS"""
import json, sys, os
import ezdxf
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union
dxf, sc = sys.argv[1], float(sys.argv[2])
d = ezdxf.readfile(dxf)
hidden = {L.dxf.name for L in d.layers if L.is_off() or L.is_frozen()}
notes = []
for e in d.modelspace().query("INSERT"):
    at = {a.dxf.tag.upper(): a.dxf.text for a in e.attribs}
    if "THK" in at and at["THK"].strip().isdigit():
        kind = "PT" if "PT" in at else "RC" if "RC" in at else ""
        notes.append((int(at["THK"]), Point(e.dxf.insert.x * sc, e.dxf.insert.y * sc), kind, e.dxf.layer in hidden))
gap = float(os.environ.get("GAP", "1.6"))
ex = unary_union([Polygon(p).exterior for p in json.load(open(os.environ["EXCL_POLYS"]))]).buffer(0.05) if os.environ.get("EXCL_POLYS") else None
for tag in sys.argv[3:]:
    R = json.load(open(f"{tag}_res_c.json")); g = json.load(open(f"{tag}_geo.json"))["segs"]
    slab = Polygon(R["slabs"][0]["outline"]); ops = unary_union([Polygon(o["poly"]) for o in R["openings"]])
    if ex is not None: g = [s for s in g if not ex.contains(LineString(s))]
    cut = slab.difference(unary_union([LineString(s) for s in g if LineString(s).length >= 2.0]).buffer(gap / 2, cap_style=2))
    pieces = [Polygon(q.exterior).buffer(gap / 2, join_style=2).intersection(slab) for q in getattr(cut, "geoms", [cut]) if q.area >= 2.0]
    mine = [n for n in notes if slab.contains(n[1]) and not ops.contains(n[1])]
    per = {}
    for v, p, k, hid in mine:
        fs = [q for q in pieces if q.buffer(0.3).contains(p)]
        if not fs: continue
        f = min(fs, key=lambda q: q.area)
        key = round(f.centroid.x, 2), round(f.centroid.y, 2)
        per.setdefault(key, [f, set(), hid])[1].add(v)
    area = {}
    for f, vs, hid in per.values():
        if len(vs) == 1: v = next(iter(vs)); area[v] = area.get(v, 0) + f.area
    st = max(area, key=area.get) if area else None
    if st is not None and R.get("slab_thickness_mm") is None: R["slab_thickness_mm"] = st   # الملاحظة المكتوبة بتكسب البلوك
    R["thickness_source"] = "hidden layer" if mine and all(n[3] for n in mine) else "drawing"
    R["thick_zones"] = []; R["thickness_conflicts"] = []
    for f, vs, hid in per.values():
        if len(vs) > 1: R["thickness_conflicts"].append({"at": list(f.centroid.coords[0]), "values": sorted(vs)}); continue
        v = next(iter(vs))
        if v == st or f.area > 0.85 * slab.area: continue
        z = f.difference(ops); z = max(getattr(z, "geoms", [z]), key=lambda q: q.area)
        R["thick_zones"].append({"poly": list(z.exterior.coords)[:-1], "thickness_mm": v, "note": f"THK {v}" + (" (hidden layer)" if hid else "")})
    json.dump(R, open(f"{tag}_res_c.json", "w"))
    print(tag, "notes", len(mine), "slab t", st, R["thickness_source"], "zones", [(z["thickness_mm"], round(Polygon(z["poly"]).area)) for z in R["thick_zones"]],
          "conflicts", R["thickness_conflicts"], "area by t", {k: round(v) for k, v in area.items()})
