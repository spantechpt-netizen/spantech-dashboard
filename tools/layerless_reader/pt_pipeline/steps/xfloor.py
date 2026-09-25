"""مطابقة الركائز بين الأدوار.

فوق السقف N  = مستمر(N) + مزروع(N)
تحت السقف N+1 = مستمر(N+1) + موقوف(N+1)
الاتنين لازم يبقوا نفس العناصر بالظبط (نفس المكان والمقاس)، بعد محاذاة الشيتين.
"""
import json, math, sys
from collections import Counter
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely import affinity
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR

ORDER = ["S3", "S4", "S5", "S6"]


def elems(M, kinds):
    out = []
    for c in M["cols"]:
        if c["type"] in kinds:
            out.append({"kind": "col", "type": c["type"], "poly": Polygon(c["rect"]["corners"]),
                        "size": (round(c["rect"]["long"], 2), round(c["rect"]["short"], 2))})
    for w in M["walls"]:
        if w["type"] in kinds:
            p = LR._wall_poly(w)
            out.append({"kind": "wall", "type": w["type"], "poly": p,
                        "size": (round(math.dist(w["p1"], w["p2"]), 2), round(w["t"], 2))})
    return out


def best_shift(A, B, tol=0.12):
    """الإزاحة اللي بتطابق أكبر عدد مراكز أعمدة (كل زوج عمود-عمود مرشح)."""
    ca = [e["poly"].centroid for e in A if e["kind"] == "col"]
    cb = [e["poly"].centroid for e in B if e["kind"] == "col"]
    best = (0, (0, 0))
    seen = set()
    for a in ca:
        for b in cb:
            t = (round(b.x - a.x, 2), round(b.y - a.y, 2))
            if t in seen: continue
            seen.add(t)
            n = sum(1 for p in ca if any(abs(p.x + t[0] - q.x) < tol and abs(p.y + t[1] - q.y) < tol for q in cb))
            if n > best[0]: best = (n, t)
    # تنعيم: متوسط فروق الأزواج المتطابقة
    n, t = best
    d = [(q.x - p.x, q.y - p.y) for p in ca for q in cb
         if abs(p.x + t[0] - q.x) < tol and abs(p.y + t[1] - q.y) < tol]
    if d: t = (sum(x for x, _ in d) / len(d), sum(y for _, y in d) / len(d))
    return t, n, len(ca), len(cb)


def compare(A, B, t, cover=0.6):
    UA = unary_union([affinity.translate(e["poly"], *t) for e in A]) if A else None
    UB = unary_union([e["poly"] for e in B]) if B else None
    miss_b = [e for e in A if UB is None or affinity.translate(e["poly"], *t).intersection(UB).area < cover * e["poly"].area]
    miss_a = [e for e in B if UA is None or e["poly"].intersection(UA).area < cover * e["poly"].area]
    return miss_b, miss_a, UA, UB


if __name__ == "__main__":
    MS = {t: json.load(open(f"{t}_members_c.json")) for t in ORDER}
    report = {}
    for lo, hi in zip(ORDER, ORDER[1:]):
        A = elems(MS[lo], {"continuous", "planted"})          # فوق السقف lo
        B = elems(MS[hi], {"continuous", "stopped"})          # تحت السقف hi
        t, n, na, nb = best_shift(A, B)
        ma, mb, UA, UB = compare(A, B, t)
        W0 = min(p[0] for e in B for p in e["poly"].exterior.coords), min(p[1] for e in B for p in e["poly"].exterior.coords)
        print(f"\n{lo} (فوق) -> {hi} (تحت): إزاحة ({t[0]:.2f}, {t[1]:.2f}), أعمدة متطابقة {n} من {na}/{nb}")
        print(f"  فوق {lo}: {Counter(e['kind']+'-'+e['type'] for e in A)}")
        print(f"  تحت {hi}: {Counter(e['kind']+'-'+e['type'] for e in B)}")
        print(f"  مساحة الركائز: فوق {UA.area:.2f} م²، تحت {UB.area:.2f} م²، المشترك {UA.intersection(UB).area:.2f}")
        for e in ma:
            c = affinity.translate(e["poly"], *t).centroid
            print(f"   موجود فوق {lo} ومش تحت {hi}: {e['kind']} {e['type']} {e['size']} عند ({c.x:.2f}, {c.y:.2f})")
        for e in mb:
            c = e["poly"].centroid
            print(f"   موجود تحت {hi} ومش فوق {lo}: {e['kind']} {e['type']} {e['size']} عند ({c.x:.2f}, {c.y:.2f})")
        report[f"{lo}->{hi}"] = {"shift": t, "matched_cols": n,
                                 "only_above_lo": [dict(kind=e["kind"], type=e["type"], size=e["size"], at=list(affinity.translate(e["poly"], *t).centroid.coords[0])) for e in ma],
                                 "only_below_hi": [dict(kind=e["kind"], type=e["type"], size=e["size"], at=list(e["poly"].centroid.coords[0])) for e in mb]}
    json.dump(report, open("xfloor_report.json", "w"), indent=1, default=list)
