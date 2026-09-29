"""كمرات اتقرت من نمط متكرر (دربزين/لوفر/جريلات) - مش كمرات.

BHN PO1: ألواح الدربزين في البلكونات (A-ELSC-PN02 جوه xref البلاطة) مستطيلات 0.25 × 1.9 م ورا بعض كل
30-40 سم، وتسمية ELB1/EB1 جنبها خلّت القارئ ياخدها كمرات قصيرة لازقة في بعض (توأم) - 16 ELB1 و37 EB1.
النمط: مستطيل مقفول وجنبه (بالعرض، مش فوقه ومش ورا على الطول) ≥ 3 مستطيلات بنفس المقاس (± 2 سم) ونفس
الاتجاه (± 2°) مراكزهم على 0.9 عرض - 1.5 م منه.
أي كمرة ≥ 60% منها فوق مستطيلات نمط بتتشال وبتتسجل REVIEW. الكمرة الحقيقية مابتتكررش كده.
usage: python pattern_beams.py TAG...   (m.dxf + wins.json + {tag}_members_c.json + {tag}_res_c.json)"""
import json, math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import ezdxf
import layerless_reader as LR
import slab_extractor as SX
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree


def rects(doc, win, m=2.0):
    out = []
    for e in SX._explode(list(doc.modelspace())):
        if e.dxftype() != "LWPOLYLINE":
            continue
        try:
            p = [tuple(map(float, q[:2])) for q in e.get_points()]
        except Exception:
            continue
        if len(p) >= 5 and math.dist(p[0], p[-1]) < 1e-6:
            p = p[:-1]
        if len(p) != 4 or not (e.closed or len(p) == 4):
            continue
        cx, cy = sum(q[0] for q in p) / 4, sum(q[1] for q in p) / 4
        if not (win[0] - m < cx < win[2] + m and win[1] - m < cy < win[3] + m):
            continue
        g = Polygon(p).buffer(0)
        if g.is_empty or g.area <= 0:
            continue
        r = g.minimum_rotated_rectangle
        if g.area < 0.95 * r.area:
            continue
        xy = list(r.exterior.coords)
        a, b = math.dist(xy[0], xy[1]), math.dist(xy[1], xy[2])
        w, l = min(a, b), max(a, b)
        if not (0.05 <= w <= 0.8 and 0.5 <= l <= 6.0):
            continue
        i = 0 if a >= b else 1
        ang = math.degrees(math.atan2(xy[i + 1][1] - xy[i][1], xy[i + 1][0] - xy[i][0])) % 180.0
        out.append({"g": g, "c": (cx, cy), "w": w, "l": l, "ang": ang})
    return out


def pattern_polys(R):
    if not R:
        return []
    tree = STRtree([r["g"].centroid for r in R])
    pat = []
    for r in R:
        n = 0
        for j in tree.query(r["g"].centroid.buffer(1.5)):
            o = R[j]
            d = math.dist(o["c"], r["c"])
            # جنب بعض: مش نفس المكان (العمود مرسوم مرتين - S-COLUMN و HIDDEN) ومش ورا بعض على الطول
            if o is r or d > 1.5 or d < 0.9 * r["w"]:
                continue
            ux, uy = math.cos(math.radians(r["ang"])), math.sin(math.radians(r["ang"]))
            if abs((o["c"][0] - r["c"][0]) * ux + (o["c"][1] - r["c"][1]) * uy) > 0.2 * r["l"]:
                continue
            da = abs(o["ang"] - r["ang"]) % 180.0
            if abs(o["w"] - r["w"]) <= 0.02 and abs(o["l"] - r["l"]) <= 0.02 and min(da, 180.0 - da) <= 2.0:
                n += 1
        if n >= 3:
            pat.append(r)
    return pat


def pour_strip_beams(tag, M):
    """كمرة جوه شريحة صب (≥ 80%) وعرضها قريب من عرض الشريحة (± 25%) = الشريحة نفسها اتقرت كمرة (BHN PO1:
    شريحة 0.98 م اتقرت EB1 عرضها 1.0 م وطولها 34 م)."""
    if not os.path.exists("pourstrips.json") or not M.get("beams"):
        return 0
    try:
        ps = [Polygon(q).buffer(0) for q in json.load(open("pourstrips.json")) if len(q) >= 3]
    except Exception:
        return 0
    ps = [g for g in ps if not g.is_empty and g.area > 0]
    if not ps:
        return 0
    keep, gone = [], []
    for b in M["beams"]:
        g = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
        hit = False
        for q in ps:
            if g.area > 0 and g.intersection(q).area >= 0.8 * g.area:
                r = q.minimum_rotated_rectangle; xy = list(r.exterior.coords)
                qw = min(math.dist(xy[0], xy[1]), math.dist(xy[1], xy[2]))
                if abs(b["w"] - qw) <= 0.25 * qw:
                    hit = True; break
        (gone if hit else keep).append(b)
    if gone:
        M["beams"] = keep
        M.setdefault("dropped_beams", []).extend([dict(b, why="the pour strip itself read as a beam") for b in gone])
        R = json.load(open(f"{tag}_res_c.json"))
        R.setdefault("review", []).append(["beams", f"{len(gone)} beam(s) {', '.join(sorted({b.get('mark', '?') for b in gone}))} lay on a pour strip "
                                                    f"with its width - the pour strip read as a beam, removed"])
        json.dump(R, open(f"{tag}_res_c.json", "w"))
        print(tag, f"pour strip read as beam: {len(gone)} removed")
    return len(gone)


def main(tags):
    W = json.load(open("wins.json"))
    doc = ezdxf.readfile("m.dxf")
    for tag in tags:
        M = json.load(open(f"{tag}_members_c.json"))
        if pour_strip_beams(tag, M):
            json.dump(M, open(f"{tag}_members_c.json", "w"))
        win = W.get(tag) or W.get(tag.rsplit("-Z", 1)[0])
        if not win or not M.get("beams"):
            continue
        P = pattern_polys(rects(doc, win))
        if not P:
            continue
        # الصف كله شريط واحد (الكمرة الوهمية بتطلع من الفراغ بين لوحين، مش من اللوح نفسه)
        U = unary_union([r["g"].buffer(0.25, join_style=2) for r in P]).buffer(-0.2, join_style=2)
        keep, gone = [], []
        for b in M["beams"]:
            g = LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
            L = math.dist(b["p1"], b["p2"])
            ab = math.degrees(math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0])) % 180.0
            # موازية للألواح ومش أطول منها بكتير: الكمرة الطرفية اللي ماشية على طول الصف (عمودية على الألواح) بتفضل
            par = [r for r in P if min(abs(ab - r["ang"]) % 180.0, 180.0 - abs(ab - r["ang"]) % 180.0) <= 5.0 and L <= 1.3 * r["l"]]
            (gone if par and g.area > 0 and g.intersection(U).area >= 0.6 * g.area else keep).append(b)
        if not gone:
            continue
        M["beams"] = keep
        M.setdefault("dropped_beams", []).extend(
            [dict(b, why="drawn on a repeated pattern of identical rectangles (railing / louvre / grating), not a beam") for b in gone])
        json.dump(M, open(f"{tag}_members_c.json", "w"))
        R = json.load(open(f"{tag}_res_c.json"))
        marks = sorted({b.get("mark", "?") for b in gone})
        R.setdefault("review", []).append(["beams", f"{len(gone)} beam(s) {', '.join(marks)} were on a repeated pattern of {len(P)} identical rectangles "
                                                    f"(railing / louvre panels) and were removed - check the edge beams there"])
        json.dump(R, open(f"{tag}_res_c.json", "w"))
        print(tag, f"pattern: {len(P)} rectangles in rows; {len(gone)} beam(s) removed ({', '.join(marks)})")


if __name__ == "__main__":
    main(sys.argv[1:])
