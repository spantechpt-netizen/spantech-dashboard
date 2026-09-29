"""فحص منطقية الكمرات المشكوك فيها (المرسومة من غير تسمية) بعد الربط.
الكمرة (أو السلسلة: حتت متسامتة لازقة في بعض) بتتقبل بس لو طرفيها الاتنين واقفين على:
  عمود أو حائط (ركيزة)، أو كمرة موثوقة (متسمية، أو اتقبلت قبل كده في نفس الفحص).
غير كده (طرف سايب، واقفة على حرف بلاطة، بين كمرتين مشكوك فيهم) -> بتتشال وتتسجل.
usage: python beam_sanity.py TAG...   ({tag}_members_c.json)"""
import json, math, sys
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
TOL = 0.3


def ang(b):
    return math.degrees(math.atan2(b["p2"][1] - b["p1"][1], b["p2"][0] - b["p1"][0])) % 180


for tag in sys.argv[1:]:
    M = json.load(open(f"{tag}_members_c.json"))
    sup = unary_union([Polygon(c["rect"]["corners"]) for c in M["cols"] if c["type"] != "planted"] +
                      [LR._wall_poly(w) for w in M["walls"] if w["type"] != "planted"])
    doubt = [b for b in M["beams"] if b.get("review") or str(b.get("label", "")).startswith("unlabelled")]
    trusted = [b for b in M["beams"] if b not in doubt]
    # سلاسل: حتت مشكوك فيها متوازية (≤ 10°) وطرف لازق في طرف
    parent = list(range(len(doubt)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, a in enumerate(doubt):
        for j in range(i + 1, len(doubt)):
            b = doubt[j]; da = abs(ang(a) - ang(b)); da = min(da, 180 - da)
            if da <= 10:
                pq = min(((p, q) for p in (a["p1"], a["p2"]) for q in (b["p1"], b["p2"])), key=lambda z: math.dist(*z))
                # السلسلة بتتقطع عند الركيزة: كل بحر بين عمودين بيتحكم عليه لوحده
                if math.dist(*pq) <= TOL and sup.distance(Point(pq[0])) > TOL:
                    parent[find(i)] = find(j)
    chains = {}
    for i, b in enumerate(doubt): chains.setdefault(find(i), []).append(b)
    def ends(ch):
        pts = [p for b in ch for p in (b["p1"], b["p2"])]
        a0 = math.radians(ang(ch[0])); u = (math.cos(a0), math.sin(a0))
        pr = sorted(pts, key=lambda p: p[0] * u[0] + p[1] * u[1])
        return pr[0], pr[-1]
    band = lambda b: LR._wall_poly({"p1": b["p1"], "p2": b["p2"], "t": b["w"]})
    accepted, pending = [], list(chains.values())
    changed = True
    while changed:
        changed = False
        tb = unary_union([band(b) for b in trusted + [x for ch in accepted for x in ch]]) if (trusted or accepted) else Polygon()
        for ch in list(pending):
            own = unary_union([band(b) for b in ch])
            other = tb.difference(own.buffer(0.01))
            # SUPPORTS_ONLY=1: الكمرة المشكوك فيها لازم تبقى بين ركيزتين (عمود/حائط) بالظبط
            only = __import__("os").environ.get("SUPPORTS_ONLY") == "1"
            ok = all(sup.distance(Point(e)) <= TOL or (not only and not other.is_empty and other.distance(Point(e)) <= TOL) for e in ends(ch))
            if ok:
                accepted.append(ch); pending.remove(ch); changed = True
    dropped = [b for ch in pending for b in ch]
    M["beams"] = [b for b in M["beams"] if b not in dropped]
    M["dropped_beams"] = [{**b, "why": "drawn-only beam not spanning between supports"} for b in dropped]
    json.dump(M, open(f"{tag}_members_c.json", "w"))
    print(tag, "doubtful", len(doubt), "chains", len(chains), "kept", sum(len(c) for c in accepted), "dropped", len(dropped))
