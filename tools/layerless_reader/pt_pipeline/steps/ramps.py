"""منحدر العربيات (بدون ليّرات): خطوط مايلة (شعاعية حوالين القوس + شيفرونات) جوه البلاطة
ومش في فتحة. المنطقة = نطاق الخطوط المايلة (متنعّم)، ممدود لحد الحيطان الخارجية، ومقصوص
من جوه عند الكمرة المنحنية (دايرة القوس) وعند الـ cores والفتحات. بتتضاف فتحة "ramp" (المنحدر دايمًا فتحة في شغلنا)."""
import json, math, sys
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR
def ramps(tag, min_area=30):     # منحدر عربيات ≥ 30 م²
    g=json.load(open(f"{tag}_geo.json"))["segs"]; R=json.load(open(f"{tag}_res.json"))
    M=json.load(open(f"{tag}_members.json"))
    slab=Polygon(R["slabs"][0]["outline"])
    ops=unary_union([Polygon(o["poly"]) for o in R["openings"] if o.get("kind")!="ramp"]) if R["openings"] else Polygon()
    # اتجاه شبكة المسقط (المسقط ممكن يبقى مايل): أكتر زاوية (mod 90) بالطول
    hist={}
    for a,b in g:
        L=math.dist(a,b)
        if L>=1.0:
            k=round(math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))%90); hist[k]=hist.get(k,0)+L
    # اتجاهات الشبكة = اتجاهات الأعمدة والحوائط نفسها (دهان المنحدر عمره ما بيبقى موازي للأعمدة):
    # كل اتجاه (mod 90) عليه ≥ 3 عناصر. من غير عناصر مدمجة -> أطول اتجاهات الخطوط.
    import collections as _C
    cnt=_C.Counter()
    for c in M["cols"]:
        if not c.get("round"): cnt[round(c["rect"].get("angle_deg",0))%90]+=1
    for w in M["walls"]:
        cnt[round(math.degrees(math.atan2(w["p2"][1]-w["p1"][1],w["p2"][0]-w["p1"][0])))%90]+=1
    peaks=[k for k,v in cnt.items() if v>=3]
    if not peaks:
        mx=max(hist.values()) if hist else 0
        peaks=[k for k,v in hist.items() if v>=0.35*mx] or [0]
    def off_grid(a_):
        return min(min(abs(a_-p)%90,90-abs(a_-p)%90) for p in peaks)
    obl=[]
    for a,b in g:
        L=math.dist(a,b)
        if L<0.5: continue
        ang=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))%90
        if off_grid(ang)>8:
            ln=LineString([a,b])
            if ln.intersection(ops).length<0.5*L and slab.buffer(0.1).contains(ln): obl.append(ln)
    if len(obl)<12: return []
    Z=unary_union([l.buffer(0.9) for l in obl]).buffer(-0.6)
    blobs=[p for p in getattr(Z,"geoms",[Z]) if p.area>min_area and sum(1 for l in obl if l.intersects(p))>=12]
    walls=unary_union([LR._wall_poly(w) for w in M["walls"]]+[Polygon(c["rect"]["corners"]) for c in M["cols"]])
    # دواير الكمرات المنحنية (من جوه): المنحدر برّه القوس
    import numpy as np
    arcs=[]
    for b in M["beams"]+M.get("ramp_beams",[]):
        if b.get("curved"): arcs.append(b)
    out=[]
    for bl in blobs:
        U=bl.buffer(1.2).buffer(-0.4)                     # تنعيم + يوصل للحيطة
        U=U.intersection(slab)
        # قص بدايرة القوس القريب (نص قطر أوسط - نص العرض)
        near=[b for b in arcs if LineString([b["p1"],b["p2"]]).distance(bl)<1.5]
        if len(near)>=2:
            P=np.array([p for b in near for p in (b["p1"],b["p2"])])
            A=np.c_[2*P[:,0],2*P[:,1],np.ones(len(P))]; cx,cy,c=np.linalg.lstsq(A,(P**2).sum(1),rcond=None)[0]
            Rm=math.sqrt(c+cx*cx+cy*cy)
            U=U.difference(Point(cx,cy).buffer(Rm,256))       # لحد آكس الكمرة المنحنية
        U=U.difference(walls).difference(ops)
        parts=[p for p in getattr(U,"geoms",[U]) if p.geom_type=="Polygon" and p.area>min_area]
        out+=parts
    return out
if __name__=="__main__":
    for tag in sys.argv[1:]:
        R=json.load(open(f"{tag}_res.json"))
        rs=ramps(tag)
        if not rs: print(tag,"no ramp"); continue          # منحدر مكتوب عليه RAMP (لو فيه) بيفضل زي ما هو
        U=unary_union(rs)
        # منحدر النص اللي جوه منحدر الخطوط بيتضم؛ غير كده بيفضل
        R["openings"]=[o for o in R["openings"] if Polygon(o["poly"]).buffer(0).intersection(U).area<0.5*Polygon(o["poly"]).buffer(0).area]
        import pickle, re as _re
        try: _tx=pickle.load(open("cache.pkl","rb"))[1]
        except Exception: _tx=[]
        for r in rs:
            has_txt=any(_re.search(r"\bRAMP\b|منحدر|\bSLOPE\b|^\s*(UP|DN)\s*$",t_,_re.I) and r.buffer(3).contains(Point(p_)) for t_,p_,h_ in _tx)
            R["openings"].append({"poly":list(r.exterior.coords)[:-1],"kind":"ramp","status":"ok" if has_txt else "review","src":"diagonal lines"})
            if not has_txt:
                R.setdefault("review",[]).append(["ramp",f"opening of {r.area:.0f} m² read as a ramp from its diagonal lines (no RAMP text near it) - confirm it is a ramp"])
        json.dump(R,open(f"{tag}_res.json","w"))
        print(tag,"ramps",[round(r.area,1) for r in rs])
