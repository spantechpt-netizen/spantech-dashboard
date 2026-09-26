"""DXF نضيف لـ Auto PT Suite (مم، $INSUNITS=4) - موحّد لكل المشاريع.

طبقات:
  PT-Clean-Boundary      حد البلاطة + نص "t=240" و "T.O.S +0.30" جوه البلاطة
  PT-Clean-Openings      فتحات (سلالم/أسانسير/شفتات/منحدر)
  PT-Clean-Drops         كل منطقة بسُمك أو منسوب غير البلاطة:
                           drop:           "DROP t=400"            (+ " SE=..." لو جوه منطقة منسوب)
                           منطقة منسوب:    "LEVEL t=240 SE=-300"
  PT-Clean-Beams         "MARK(WxD) P=n" + للمقلوبة " INV SE=+460" (SE = عمق - سُمك البلاطة، بالمم)
  PT-Clean-Columns/Walls[-Above]  ركائز تحت / مزروعة فوق
SE = Surface Elevation في رام: فرق منسوب سطح العنصر عن سطح البلاطة الأساسية (مم).
env: TAGS="A B C", ORIGIN=wins|coreb, OUT=out
"""
import json, math, csv, os, sys, collections
import ezdxf
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR

TAGS = os.environ["TAGS"].split(); OUT = os.environ.get("OUT", "out"); ORIGIN = os.environ.get("ORIGIN", "wins")
os.makedirs(OUT, exist_ok=True)


def core_b(res, REF=(30.0, 20.0)):
    st = [o for o in res["openings"] if o["kind"] == "stair"]; lf = [o for o in res["openings"] if o["kind"] in ("lift?", "lift")]
    for s in st:
        c = Polygon(s["poly"]).centroid
        for l in lf:
            d = Polygon(l["poly"]).centroid
            if abs(d.x - c.x + 2.22) < 0.3 and abs(d.y - c.y - 1.17) < 0.3:
                return (c.x - REF[0], c.y - REF[1])


def interior_point(poly, avoid):
    """نقطة جوه البلاطة وبعيدة عن الدروب/المناطق/الفتحات (عشان الملاحظة تروح للبلاطة نفسها)."""
    free = poly.difference(avoid.buffer(0.5)) if not avoid.is_empty else poly
    free = max(getattr(free, "geoms", [free]), key=lambda g: g.area) if not free.is_empty else poly
    return free.representative_point()


rows = []; summ = []
for tag in TAGS:
    res = json.load(open(f"{tag}_res_c.json")); M = json.load(open(f"{tag}_members_c.json"))
    if ORIGIN == "wins":
        W = json.load(open(os.environ.get("WINS_FILE", "wins.json"))); ox, oy = W[tag][0], W[tag][1]
    else:
        ox, oy = core_b(res)
    T = lambda p, ox=ox, oy=oy: ((p[0] - ox) * 1000, (p[1] - oy) * 1000)
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4; msp = doc.modelspace()
    for n, c in {"PT-Clean-Boundary": 7, "PT-Clean-Openings": 2, "PT-Clean-Columns": 1, "PT-Clean-Walls": 3, "PT-Clean-Beams": 5,
                 "PT-Clean-Columns-Above": 6, "PT-Clean-Walls-Above": 6, "PT-Clean-Drops": 4}.items():
        doc.layers.add(n, color=c)
    slab = Polygon(res["slabs"][0]["outline"])
    t_slab = res.get("slab_thickness_mm"); main = res.get("main_level_m")
    zones = [(Polygon(z["poly"]), z) for z in res.get("level_zones", [])]
    drops = [(Polygon(d["poly"]), d) for d in res.get("drops", [])]
    tz = [(Polygon(z["poly"]).buffer(0), z) for z in res.get("thick_zones", [])]
    # منطقة المنسوب ومنطقة السُمك بنفس الأولوية (2): لو اتداخلوا RAM مايعرفش مين يغلب.
    # فمنطقة المنسوب بتتكتب من غير أجزاء السُمك، وكل جزء من منطقة السُمك بياخد SE المنطقة اللي هو فيها.
    def _no_holes(g):
        """مضلع فيه خرم بيتقسم لقطع من غير خرم (RAM بياخد حد خارجي بس)."""
        if not g.interiors:
            return [g]
        from shapely.ops import split
        from shapely.geometry import LineString
        cx = g.interiors[0].centroid.x; y0, y1 = g.bounds[1] - 1, g.bounds[3] + 1
        out = []
        for q in split(g, LineString([(cx, y0), (cx, y1)])).geoms:
            out += _no_holes(q)
        return out

    if tz and zones:
        TZ = unary_union([p for p, _ in tz])
        zz = []
        for zp, z in zones:
            q = zp.buffer(0).difference(TZ)
            zz += [(h, z) for g in getattr(q, "geoms", [q]) if g.geom_type == "Polygon" for h in _no_holes(g) if h.area >= 0.5]
        tt = []
        for tp, t in tz:
            rest = tp
            for zp, z in zones:
                q = tp.intersection(zp.buffer(0))
                tt += [(g, dict(t, se_fixed=z["se_mm"])) for g in getattr(q, "geoms", [q]) if g.geom_type == "Polygon" and g.area >= 0.5]
                rest = rest.difference(zp.buffer(0))
            tt += [(g, dict(t, se_fixed=0)) for g in getattr(rest, "geoms", [rest]) if g.geom_type == "Polygon" and g.area >= 0.5]
        zones, tz = zz, tt
    ops = [Polygon(o["poly"]) for o in res["openings"]]
    # شرايح الصب (pour strips): بلاطة بنفس سُمك ومنسوب اللي ماشية فيه، أولوية أعلى، Fx/Fy مفكوكين
    strips = []
    if os.environ.get("POUR_JSON"):
        for ring in json.load(open(os.environ["POUR_JSON"])):
            q = Polygon(ring).buffer(0).intersection(slab).difference(unary_union(ops) if ops else Polygon())
            strips += [g for g in getattr(q, "geoms", [q]) if g.geom_type == "Polygon" and g.area >= 0.5]
    # الأولويات: منطقة منسوب/سُمك 2، دروب 3، شريحة الصب 4 (بتغلب الدروب: متقطّعة عنده وبسُمكه)
    P_Z, P_D, P_S = (2, 3, 4) if strips else (None, None, None)

    def zone_se(pt):
        for zp, z in zones:
            if zp.contains(pt):
                return z["se_mm"]
        return 0

    msp.add_lwpolyline([T(p) for p in res["slabs"][0]["outline"]], close=True, dxfattribs={"layer": "PT-Clean-Boundary"})
    ip = interior_point(slab, unary_union([p for p, _ in zones] + [p for p, _ in drops] + [p for p, _ in tz] + ops))
    if t_slab:
        msp.add_text(f"t={t_slab}", dxfattribs={"layer": "PT-Clean-Boundary", "height": 400, "insert": T((ip.x, ip.y))})
    if main is not None:
        msp.add_text("T.O.S", dxfattribs={"layer": "PT-Clean-Boundary", "height": 300, "insert": T((ip.x, ip.y - 0.7))})
        msp.add_text(f"{main:+.2f}", dxfattribs={"layer": "PT-Clean-Boundary", "height": 300, "insert": T((ip.x + 1.6, ip.y - 0.7))})
    for o in res["openings"]:
        msp.add_lwpolyline([T(p) for p in o["poly"]], close=True, dxfattribs={"layer": "PT-Clean-Openings"})
        if o.get("kind") == "ramp":
            rows.append([tag, "opening", "ramp", "", "", round(Polygon(o["poly"]).area, 2), "car ramp = opening (office rule)"])
    for zp, z in zones:
        msp.add_lwpolyline([T(p) for p in list(zp.exterior.coords)[:-1]], close=True, dxfattribs={"layer": "PT-Clean-Drops"})
        c = zp.representative_point()
        zt = None if z.get("t_unknown") else z.get("thickness_mm", t_slab)
        txt = (f"LEVEL t={zt} " if zt else "LEVEL ") + f"SE={z['se_mm']:+d}" + (f" P={P_Z}" if P_Z else "")
        msp.add_text(txt, dxfattribs={"layer": "PT-Clean-Drops", "height": 250, "insert": T((c.x, c.y))})
        rows.append([tag, "level zone", f"{z['level_m']:+.2f}", t_slab or "", "", round(zp.area, 2), f"SE={z['se_mm']:+d} mm vs main {main:+.2f}"])
    if res.get("thickness_review"):
        rows.append([tag, "REVIEW", "thickness", "", "", "", res["thickness_review"]])
    if not t_slab:
        rows.append([tag, "REVIEW", "thickness", "", "", "", "no slab thickness value in the drawing - program default used"])
    for rv in res.get("review", []):
        rows.append([tag, "REVIEW", rv[0], "", "", "", rv[1]])
    for v in res.get("level_unresolved", []):
        rows.append([tag, "REVIEW", "level", v, "", "", "level label with no closed zone around it - not exported"])
    for zp, z in tz:
        msp.add_lwpolyline([T(p) for p in list(zp.exterior.coords)[:-1]], close=True, dxfattribs={"layer": "PT-Clean-Drops"})
        c = zp.representative_point(); se = z["se_fixed"] if "se_fixed" in z else zone_se(c)
        msp.add_text(f"ZONE t={z['thickness_mm']}" + (f" SE={se:+d}" if se else "") + (f" P={P_Z}" if P_Z else ""),
                     dxfattribs={"layer": "PT-Clean-Drops", "height": 250, "insert": T((c.x, c.y))})
        rows.append([tag, "thickness zone", "", z["thickness_mm"], "", round(zp.area, 2), f"slab {t_slab}; note '{z.get('note','')}'"])
    for dp, d in drops:
        msp.add_lwpolyline([T(p) for p in d["poly"]], close=True, dxfattribs={"layer": "PT-Clean-Drops"})
        c = dp.representative_point(); se = zone_se(c)
        # سُمك مش مكتوب: "DROP" من غير t= والبرنامج بياخد سُمك الدروب الافتراضي من صفحة Project
        txt = ("DROP" if d.get("thickness_mm") is None else f"DROP t={d['thickness_mm']}") + \
            (f" SE={se:+d}" if se else "") + (f" P={P_D}" if P_D else "")
        msp.add_text(txt, dxfattribs={"layer": "PT-Clean-Drops", "height": 250, "insert": T((c.x, c.y))})
        rows.append([tag, "drop panel", d.get("src", ""), d["thickness_mm"] if d.get("thickness_mm") is not None else "?", "",
                     round(dp.area, 2), f"slab {t_slab}" + (f" SE={se:+d}" if se else "")])
    n_tu = sum(1 for _, d in drops if d.get("thickness_mm") is None)
    if n_tu:
        rows.append([tag, "REVIEW", "drop thickness", "", "", n_tu,
                     f"{n_tu} drop panel(s) drawn with no thickness written - the program's default drop thickness is used"])
    # كل شريحة بتتقسم على المناطق اللي بتعدّي فيها: كل حتة بسُمك ومنسوب المنطقة دي
    n_strip = 0
    for sp in strips:
        hosts = [(zp, z.get("thickness_mm", t_slab) if not z.get("t_unknown") else None, z["se_mm"]) for zp, z in zones] + \
                [(zp, z["thickness_mm"], zone_se(zp.representative_point())) for zp, z in tz]
        rest = sp
        pieces = []
        # جوه الدروب: حتة لوحدها بسُمك الدروب، والشريحة أولويتها أعلى منه
        for dp, d in drops:
            q = rest.intersection(dp)
            for g in getattr(q, "geoms", [q]):
                if g.geom_type == "Polygon" and g.area >= 0.05: pieces.append((g, d.get("thickness_mm"), zone_se(g.representative_point()), "in drop"))
            rest = rest.difference(dp)
        for hp, ht, hse in hosts:
            q = rest.intersection(hp)
            for g in getattr(q, "geoms", [q]):
                if g.geom_type == "Polygon" and g.area >= 0.05: pieces.append((g, ht, hse, ""))
            rest = rest.difference(hp)
        pieces += [(g, t_slab, 0, "") for g in getattr(rest, "geoms", [rest]) if g.geom_type == "Polygon" and g.area >= 0.05]
        for g, ht, hse, where in pieces:
            msp.add_lwpolyline([T(p) for p in list(g.exterior.coords)[:-1]], close=True, dxfattribs={"layer": "PT-Clean-Drops"})
            c = g.representative_point()
            msp.add_text("POUR STRIP" + (f" t={ht}" if ht else "") + (f" SE={hse:+d}" if hse else "") + f" P={P_S} RELEASE FX FY",
                         dxfattribs={"layer": "PT-Clean-Drops", "height": 250, "insert": T((c.x, c.y))})
            n_strip += 1
            rows.append([tag, "pour strip", where, ht or "", "", round(g.area, 2), f"release Fx Fy, priority {P_S} (over drops {P_D})" + (f", SE={hse:+d}" if hse else "")])
    n_inv = 0
    # كمرة متسمية واقعة بالكامل على حائط (التسمية لقت وشين الحائط): الحائط هو الركيزة؛
    # لو اتكتبت كمرة البرنامج بينقل الحائط نفسه لكمرات ويضيع الركيزة
    _W = unary_union([LR._wall_poly(w) for w in M["walls"]]) if M["walls"] else Polygon()
    _keep = []
    for b in M["beams"]:
        bp = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        if bp.area > 0 and bp.intersection(_W).area >= 0.9 * bp.area:
            rows.append([tag, "beam on wall (not exported)", b["mark"], round(b["w"] * 1000), "", round(math.dist(b["p1"], b["p2"]), 2), "label sits on a wall - the wall is the support"])
            continue
        _keep.append(b)
    M["beams"] = _keep
    for b in M["beams"]:
        msp.add_lwpolyline([T(p) for p in LR._rect_pts(b["p1"], b["p2"], b["w"])], close=True, dxfattribs={"layer": "PT-Clean-Beams"})
        mx = ((b["p1"][0] + b["p2"][0]) / 2, (b["p1"][1] + b["p2"][1]) / 2)
        mark = b["mark"].replace("?", "X")
        if b.get("depth_unknown") and not b.get("depth_rule"): rows.append([tag, "REVIEW", "beam depth", b["mark"], "", "", f"{b['mark']} width {b['w']*1000:.0f} measured, depth not in the drawing"])
        se = zone_se(Point(mx))
        extra = ""
        if b.get("inverted"):
            ts = t_slab or 0
            se += int(round(b["d"] * 1000 - ts)) if (ts and b.get("d")) else 0
            extra = f" INV SE={se:+d}" if ts else " INV"
            n_inv += 1
        elif se:
            extra = f" SE={se:+d}"
        sec = f'({b["w"]*1000:.0f}X{b["d"]*1000:.0f})' if b.get("d") else f'({b["w"]*1000:.0f}X?)'
        msp.add_text(f'{mark}{sec} P={b.get("priority",10)}{extra}',
                     dxfattribs={"layer": "PT-Clean-Beams", "height": 300, "insert": T(mx),
                                 "rotation": math.degrees(math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0]))})
        note = ("curved " if b.get("curved") else "") + ("INVERTED " if b.get("inverted") else "") + \
               ("axis-drawn " if b.get("axis_beam") else "") + ("opening-edge " if b.get("opening_edge_beam") else "") + \
               ("depth typo /10 " if b.get("depth_typo") else "") + ("depth=max(span/10, 600) " if b.get("depth_rule") else "") + ("UNLABELLED (drawn only) - review " if b.get("review") else "") + ("width measured " if b.get("width_measured") else "") + f'P={b.get("priority")}' + extra
        rows.append([tag, "beam", b["mark"], round(b["w"] * 1000), round(b["d"] * 1000) if b.get("d") else "?", round(math.dist(b["p1"], b["p2"]), 2), note.strip()])
    for b in M.get("dropped_beams", []):
        rows.append([tag, "beam dropped (not logical)", b["mark"], round(b["w"] * 1000), "", round(math.dist(b["p1"], b["p2"]), 2), b["why"]])
    for b in M.get("ramp_beams", []):
        rows.append([tag, "beam (ramp, not exported)", b["mark"], round(b["w"] * 1000) if b.get("w") else "?", round(b["d"] * 1000) if b.get("d") else "?",
                     round(math.dist(b["p1"], b["p2"]), 2), b["label"]])
    for c in M["cols"]:
        lay = "PT-Clean-Columns-Above" if c["type"] == "planted" else "PT-Clean-Columns"
        msp.add_lwpolyline([T(p) for p in c["rect"]["corners"]], close=True, dxfattribs={"layer": lay})
        rows.append([tag, "column" + (" (round)" if c.get("round") else ""), c["type"], round(c["b"] * 1000), round(c["d"] * 1000), "",
                     "top (above slab)" if c["type"] == "planted" else "bottom (support)"])
    for w in M["walls"]:
        lay = "PT-Clean-Walls-Above" if w["type"] == "planted" else "PT-Clean-Walls"
        msp.add_lwpolyline([T(p) for p in LR._rect_pts(w["p1"], w["p2"], w["t"])], close=True, dxfattribs={"layer": lay})
        rows.append([tag, "wall", w["type"], round(w["t"] * 1000), "", round(math.dist(w["p1"], w["p2"]), 2),
                     "top (above slab)" if w["type"] == "planted" else "bottom (support)"])
    for l in M.get("miss", []):
        rows.append([tag, "UNMATCHED LABEL", l, "", "", "", "no beam faces found - review"])
    doc.saveas(f"{OUT}/{tag}_slab_clean.dxf")
    cc = collections.Counter(c["type"] for c in M["cols"])
    summ.append((tag, f"t={t_slab}", f"main={main}", f"zones={len(zones)}+{len(tz)}", f"drops={len(drops)}", f"pour strip pieces={n_strip}", f"cols={dict(cc)}",
                 f"beams={len(M['beams'])}", f"inv={n_inv}"))
with open(f"{OUT}/members.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["sheet", "element", "type/mark", "b_or_t_mm", "d_mm", "length_or_area", "note"]); w.writerows(rows)
for s in summ: print(*s)
