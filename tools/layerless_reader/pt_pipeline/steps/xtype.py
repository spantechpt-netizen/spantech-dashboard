"""أنواع الركائز من غير مفتاح هاتش: من مقارنة كل دور باللي فوقه.
عنصر مرسوم في مسقط N (تحت بلاطة N):
  موجود كمان تحت بلاطة N+1  -> مستمر
  مش موجود فوق               -> موقوف (بيخلص تحت بلاطة N)
عنصر تحت بلاطة N+1 ومش تحت N -> بيتضاف لـ N كـ "مزروع" (واقف عليها)."""
import json, math, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import xfloor as X
from shapely import affinity
ORDER=sys.argv[1:]
MS={t:json.load(open(f"{t}_members_c.json")) for t in ORDER}
for t in ORDER:
    for c in MS[t]["cols"]: c["type"]="continuous"
    for w in MS[t]["walls"]: w["type"]="continuous"
rep={}
for lo,hi in zip(ORDER,ORDER[1:]):
    A=X.elems(MS[lo],{"continuous"}); B=X.elems(MS[hi],{"continuous"})
    t,n,na,nb=X.best_shift(A,B)
    UB=X.unary_union([e["poly"] for e in B]); UA=X.unary_union([affinity.translate(e["poly"],*t) for e in A])
    stopped=0; planted=0
    # نوقف اللي مالوش كمالة فوق
    objs=[("col",c,X.Polygon(c["rect"]["corners"])) for c in MS[lo]["cols"] if c["type"]!="planted"]+\
         [("wall",w,X.LR._wall_poly(w)) for w in MS[lo]["walls"] if w["type"]!="planted"]
    for k,o,p in objs:
        pt=affinity.translate(p,*t)
        if pt.intersection(UB).area<0.6*p.area: o["type"]="stopped"; stopped+=1
    # اللي فوق ومالوش أساس تحت -> مزروع على lo
    for c in MS[hi]["cols"]:
        p=X.Polygon(c["rect"]["corners"])
        if c.get("added_from") or p.intersection(UA).area>=0.6*p.area: continue
        r=dict(c["rect"]); r["center"]=(r["center"][0]-t[0],r["center"][1]-t[1]); r["corners"]=[(q[0]-t[0],q[1]-t[1]) for q in r["corners"]]
        MS[lo]["cols"].append({"type":"planted","rect":r,"b":c["b"],"d":c["d"],"added_from":hi}); planted+=1
    for w in MS[hi]["walls"]:
        p=X.LR._wall_poly(w)
        if w.get("added_from") or p.intersection(UA).area>=0.6*p.area: continue
        MS[lo]["walls"].append({"type":"planted","p1":(w["p1"][0]-t[0],w["p1"][1]-t[1]),"p2":(w["p2"][0]-t[0],w["p2"][1]-t[1]),"t":w["t"],"added_from":hi}); planted+=1
    rep[f"{lo}->{hi}"]={"shift":t,"cols_matched":n,"of":[na,nb],"stopped_on_lo":stopped,"planted_on_lo":planted}
    print(f"{lo} -> {hi}: shift ({t[0]:.2f},{t[1]:.2f}) cols matched {n}/{na}/{nb}, stopped under {lo}: {stopped}, planted on {lo}: {planted}")
# السقف الأخير: مفيش فوقه
for c in MS[ORDER[-1]]["cols"]:
    if c["type"]!="planted": c["type"]="stopped"
for w in MS[ORDER[-1]]["walls"]:
    if w["type"]!="planted": w["type"]="stopped"
for t,M in MS.items(): json.dump(M,open(f"{t}_members_c.json","w"))
json.dump(rep,open("xtype_report.json","w"),indent=1,default=list)
