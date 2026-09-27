"""الـ drop panels: مستطيل مقفول جواه عمود ونص "T= nnn" أكبر من سُمك البلاطة."""
import json, re, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import ezdxf, slab_extractor as SX
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union, polygonize
doc=ezdxf.readfile(__import__("os").environ.get("DXF","m.dxf")); msp=doc.modelspace()
W=json.load(open("wins.json"))
ENT=list(SX._explode(list(msp)))
def texts(win):
    out=[]
    for e in ENT:
        if e.dxftype() not in ("TEXT","MTEXT"): continue
        r=SX._text_of(e)
        if r and win[0]<r[1][0]<win[2] and win[1]<r[1][1]<win[3]: out.append((r[0].strip(),Point(r[1])))
    # قيم الـ attributes في كل البلوكات حتى المتداخلة (زي CSTH جوه FRAMING-BS)
    def walk(es,depth=0):
        for e in es:
            if e.dxftype()!="INSERT": continue
            p=e.dxf.insert
            if win[0]<p.x<win[2] and win[1]<p.y<win[3]:
                # بلوك سُمك: جواه نص "T=" أو "TH=" وقيمته في attribute رقمي
                try: isth=any(x.dxftype()=="TEXT" and re.match(r"\s*TH?\s*=",x.dxf.text) for x in doc.blocks.get(e.dxf.name))
                except Exception: isth=False
                for a in e.attribs: out.append((a.dxf.text.strip(),Point(p.x,p.y),"THK" if isth else e.dxf.name))
            if depth<4:
                try: walk(list(e.virtual_entities()),depth+1)
                except Exception: pass
    walk(list(msp.query("INSERT")))
    return out
for tag in sys.argv[1:]:
    win=W[tag]; g=json.load(open(f"{tag}_geo.json"))["segs"]; M=json.load(open(f"{tag}_members_c.json")); R=json.load(open(f"{tag}_res_c.json"))
    T=texts(win)
    slab_t=[int(t[0]) for t in T if len(t)==3 and t[2]=="THK" and t[0].isdigit()]
    thick=[(int(m.group(1)),t[1]) for t in T for m in [re.search(r"\bTH?\s*=\s*(\d{3,4})",t[0])] if m]
    # "PT Slab" + "T=220" (نصين جنب بعض ≤ 1.5 م، أو نص واحد): ده سُمك البلاطة نفسها صراحةً (HDB)
    ptl=[t[1] for t in T if re.search(r"\bP\.?\s*T\.?\s*SLAB\b|POST.?TENSION",t[0],re.I)]
    pt_explicit=[v for v,p in thick if any(p.distance(q)<=1.5 for q in ptl)]
    thick+=[(int(t[0]),t[1]) for t in T if len(t)==3 and t[2]=="THK" and t[0].isdigit()]
    # "T=" و"400" نصين منفصلين: الرقم الأقرب على بعد ≤ 1.2 م
    slab_explicit=[]
    nums=[(int(t[0]),t[1]) for t in T if re.fullmatch(r"\d{3,4}",t[0])]
    for t in T:
        if re.fullmatch(r"(P\.)?T\s*=",t[0]) and nums:
            v,p=min(nums,key=lambda q:q[1].distance(t[1]))
            if p.distance(t[1])<=1.2:
                # "P.T=220" = سُمك البلاطة البوست تنشن نفسها (مش drop)
                if t[0].startswith("P"): slab_explicit.append(v)
                else: thick.append((v,t[1]))
    _U=unary_union([LineString(s) for s in g]); _UB=_U.buffer(0.03)
    allf=list(polygonize(_U))
    def _drawn_rect(f):
        import math
        from shapely import affinity
        # المستطيل الأصغر ممكن يطلع مايل (شق العمود بيطلع برّه الإطار)؛ فبنجرب كمان الغلاف في اتجاه أطول ضلع في الوش
        ex=list(f.exterior.coords); e=max(zip(ex,ex[1:]),key=lambda ab:math.dist(*ab))
        ang=math.degrees(math.atan2(e[1][1]-e[0][1],e[1][0]-e[0][0]))
        env=affinity.rotate(affinity.rotate(f,-ang,origin=f.centroid).envelope,ang,origin=f.centroid)
        for r in (f.minimum_rotated_rectangle,env):
            c=list(r.exterior.coords)
            if all(LineString([c[i],c[i+1]]).intersection(_UB).length>=0.9*LineString([c[i],c[i+1]]).length for i in range(4)): return r
        # ضلع مش على خط (سن من طرف خط سايب طالع من الوش): بيتزحلق ≤ 0.35 م لأقرب خط موازي مرسوم
        o=f.centroid; x0,y0,x1,y1=affinity.rotate(f,-ang,origin=o).bounds
        UR=affinity.rotate(_UB,-ang,origin=o)
        def cov(a,b): L=LineString([a,b]); return L.intersection(UR).length>=0.9*L.length
        def slide(v,mk):
            for d in sorted([k/100 for k in range(-35,36)],key=abs):
                if cov(*mk(v+d)): return v+d
            return None
        nx0=slide(x0,lambda v:((v,y0),(v,y1))); nx1=slide(x1,lambda v:((v,y0),(v,y1)))
        ny0=slide(y0,lambda v:((x0,v),(x1,v))); ny1=slide(y1,lambda v:((x0,v),(x1,v)))
        if None in (nx0,nx1,ny0,ny1) or nx1-nx0<0.5 or ny1-ny0<0.5: return None
        from shapely.geometry import box as _box
        r=affinity.rotate(_box(nx0,ny0,nx1,ny1),ang,origin=o)
        c=list(r.exterior.coords)
        return r if all(LineString([c[i],c[i+1]]).intersection(_UB).length>=0.9*LineString([c[i],c[i+1]]).length for i in range(4)) else None
    faces=[f for f in allf if 0.5<f.area<60]
    cols=[Polygon(c["rect"]["corners"]) for c in M["cols"]]
    # العمود ممكن يبقى مرسوم مستطيل من غير هاتش (HDB: T=550 جوه مستطيل 3×3 حوالين عمود مش مهاشر):
    # أي وش صغير مستطيل (0.05–2.5 م²، ضلعه ≥ 0.2) بيتحسب عمود هنا
    cols+=[f for f in allf if 0.05<=f.area<=2.5 and f.area>=0.9*f.minimum_rotated_rectangle.area
           and min(SX._rect_dims(f))>=0.2]
    slab_explicit+=pt_explicit
    st=min(slab_explicit) if slab_explicit else min(slab_t) if slab_t else (min(v for v,_ in thick) if thick else None)
    if slab_explicit: R["slab_t_explicit"]=min(slab_explicit)
    else: R.pop("slab_t_explicit",None)
    R.pop("thickness_review",None)
    thin=[v for v,_ in thick if st and v<st]
    if thin: R["thickness_review"]=f"notes T={sorted(set(thin))} thinner than slab {st} - ignored"
    drops=[]
    for v,p in thick:
        if st is None or v<=st: continue
        # العمود بيعمل "فتحة" في الوش، فنقارن بالحد الخارجي للوش
        # بالحد الخارجي: إطار الملاحظة نفسها (مستطيل صغير حوالين "T=550") بيعمل خرم في وش الدروب، والنقطة بتقع فيه
        cand=[Polygon(f.exterior) for f in faces if Polygon(f.exterior).buffer(0.05).contains(p)]
        # الوش مش مستطيل لأن خطوط تانية (عمود/كمرة) قاطعة إطار الدروب، والإطار نفسه مرسوم كامل:
        # المستطيل المحيط بيتاخد لو كل ضلع فيه مرسوم ≥ 90% (HDB الأرضي: 67 دروب T=550 من 252 كانوا بيضيعوا)
        cand=[f if f.area>=0.9*f.minimum_rotated_rectangle.area else _drawn_rect(f) for f in cand]
        cand=[f for f in cand if f is not None and any(f.buffer(0.02).contains(c.centroid) for c in cols)]
        if not cand: continue
        f=min(cand,key=lambda f:f.area)
        if f.area>=0.9*f.minimum_rotated_rectangle.area and not any(f.equals(d["poly_g"]) for d in drops):
            drops.append({"poly_g":f,"t":v})
    R["drops"]=R.get("drops",[])+[{"poly":list(d["poly_g"].exterior.coords)[:-1],"thickness_mm":d["t"]} for d in drops]
    # دروب مكتوب (T= في إطار مرسوم كامل) من غير عمود/حيطة حقيقية تحته: بيتاخد (الرسمة صريحة) + REVIEW
    _real=[Polygon(c["rect"]["corners"]) for c in M["cols"]]
    import layerless_reader as _LR
    _real+=[_LR._wall_poly(w) for w in M["walls"]]
    _bare=[d for d in drops if not any(d["poly_g"].buffer(0.05).intersects(q) for q in _real)]
    if _bare:
        R.setdefault("review",[]).append(["drop",f"{len(_bare)} drop(s) with an explicit T= in a fully drawn box but no column or wall under them "
                                                f"(e.g. at ({_bare[0]['poly_g'].centroid.x:.1f}, {_bare[0]['poly_g'].centroid.y:.1f})) - check the support"])
    # منطقة سُمك (thick.py) ملاحظتها وقعت جوه دروب = هي الدروب نفسه، مش منطقة
    if drops and R.get("thick_zones"):
        DG=unary_union([d["poly_g"] for d in drops])
        R["thick_zones"]=[z for z in R["thick_zones"] if not (z.get("at") and DG.buffer(0.3).contains(Point(z["at"])))]
    if st is not None: R["slab_thickness_mm"]=st
    json.dump(R,open(f"{tag}_res_c.json","w"))
    print(tag,"slab t",st,R.get("thickness_review",""),"drops",[(round(d["poly_g"].area,1),d["t"]) for d in drops])
