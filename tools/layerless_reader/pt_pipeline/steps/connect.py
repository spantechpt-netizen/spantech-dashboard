"""ربط العناصر ببعض عشان شبكة العناصر المحددة في RAM Concept:
نهايات الكمرات على آكس العمود / خط الحائط / خط الكمرة التانية، تقسيم الكمرة
عند عمود في النص، وحد البلاطة/الفتحات ينطبق على وش الكمرة لو قريب."""
import json, math, sys
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import nearest_points
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import layerless_reader as LR

def unit(p1,p2):
    L=math.dist(p1,p2) or 1.0
    return ((p2[0]-p1[0])/L,(p2[1]-p1[1])/L)

def line_x(p1,p2,q1,q2):
    """تقاطع خطين لا نهائيين (أو None لو متوازيين)."""
    d=(p1[0]-p2[0])*(q1[1]-q2[1])-(p1[1]-p2[1])*(q1[0]-q2[0])
    if abs(d)<1e-9: return None
    a=p1[0]*p2[1]-p1[1]*p2[0]; b=q1[0]*q2[1]-q1[1]*q2[0]
    return ((a*(q1[0]-q2[0])-(p1[0]-p2[0])*b)/d, (a*(q1[1]-q2[1])-(p1[1]-p2[1])*b)/d)

def proj(P,a,b):
    """إسقاط P على الخط (a,b) اللا نهائي - الكمرة/الحائط يفضلوا مستقيمين."""
    u=unit(a,b); t=(P[0]-a[0])*u[0]+(P[1]-a[1])*u[1]
    return (a[0]+u[0]*t, a[1]+u[1]*t)

def lateral(P,a,b):
    q=proj(P,a,b); return math.dist(P,q)

def angle_between(u,v):
    c=abs(u[0]*v[0]+u[1]*v[1]); return math.degrees(math.acos(min(1,c)))

def connect(M, R, reach=0.8):
    sup_cols=[c for c in M["cols"] if c["type"]!="planted"]
    sup_walls=[w for w in M["walls"] if w["type"]!="planted"]
    cpoly=[Polygon(c["rect"]["corners"]) for c in sup_cols]
    ccen=[tuple(c["rect"]["center"]) for c in sup_cols]
    log={"beam_end_to_column":0,"beam_end_to_wall":0,"beam_end_to_beam":0,"beam_split_at_column":0,
         "wall_end_to_column":0,"wall_end_to_wall":0,"slab_edges_snapped":0,"opening_edges_snapped":0,"free_beam_ends":[]}

    # ---- 1) الحوائط: أطراف على مركز عمود أو على خط حائط تاني ----
    for w in sup_walls:
        for end in ("p1","p2"):
            P=w[end]; other=w["p2" if end=="p1" else "p1"]; u=unit(other,P)
            best=None
            for c,col,cc in zip(cpoly,sup_cols,ccen):
                d=c.distance(Point(P))
                if d<=0.3+w["t"]/2 and lateral(cc,w["p1"],w["p2"])<=w["t"]/2+col["b"]/2 and (best is None or d<best[0]): best=(d,cc)
            if best: w[end]=proj(best[1],w["p1"],w["p2"]); log["wall_end_to_column"]+=1; continue
            for w2 in sup_walls:
                if w2 is w: continue
                u2=unit(w2["p1"],w2["p2"])
                if angle_between(u,u2)<30: continue
                X=line_x(w["p1"],w["p2"],w2["p1"],w2["p2"])
                if not X or math.dist(X,P)>w2["t"]/2+0.35: continue
                if LineString([w2["p1"],w2["p2"]]).distance(Point(X))>w["t"]/2+0.35: continue
                w[end]=X; log["wall_end_to_wall"]+=1; break

    # ---- 2) الكمرات: كل طرف على آكس عمود > خط حائط > خط كمرة ----
    beams=M["beams"]
    carried=[]      # (المحمولة، الشايلة)
    def snap_end(b,end):
        P=b[end]; other=b["p2" if end=="p1" else "p1"]; u=unit(other,P)
        # عمود: الطرف جوه العمود أو قريب منه
        best=None
        for c,col,cc in zip(cpoly,sup_cols,ccen):
            d=c.distance(Point(P))
            if d<=reach+b["w"]/2 and lateral(cc,b["p1"],b["p2"])<=b["w"]/2+col["b"]/2 and (best is None or d<best[0]): best=(d,cc)
        if best:
            # على آكس العمود: إسقاط مركزه على خط الكمرة (الكمرة تفضل مستقيمة ووشها على حد البلاطة)
            b[end]=proj(best[1],b["p1"],b["p2"]); log["beam_end_to_column"]+=1; return True
        # حائط: تقاطع خط الكمرة مع خط الحائط، أو أقرب طرف للحائط
        best=None
        for w in sup_walls:
            wl=LineString([w["p1"],w["p2"]]); wp=LR._wall_poly(w)
            d=wp.distance(Point(P))
            if d>reach+b["w"]/2: continue
            uw=unit(w["p1"],w["p2"])
            cand=None
            if angle_between(u,uw)>=20:
                X=line_x(b["p1"],b["p2"],w["p1"],w["p2"])
                if X and wl.distance(Point(X))<=0.05 and math.dist(X,P)<=reach+w["t"]:
                    cand=X
            if cand is None:
                # بداية الحائط - بس لو واقعة جوه عرض الكمرة، ونسقطها على آكس الكمرة (من غير ميل)
                ek=min(("p1","p2"),key=lambda k_:math.dist(w[k_],P)); e_=w[ek]
                if angle_between(u,uw)<20 and lateral(e_,b["p1"],b["p2"])<=0.05:
                    cand=(tuple(e_),None,None)      # على امتداد الحائط: نفس النقطة بالظبط
                elif angle_between(u,uw)<20 and lateral(e_,b["p1"],b["p2"])<=max(b["w"],w["t"])/2+1e-6:
                    # موازي بس مزاح عن آكس الكمرة: الكمرة تفضل مستقيمة وطرفها على إسقاط بداية الحائط
                    cand=(proj(e_,b["p1"],b["p2"]),None,None)
                elif lateral(e_,b["p1"],b["p2"])<=b["w"]/2+w["t"]/2+0.05:
                    cand=proj(e_,b["p1"],b["p2"])
                    # الحائط كمان يتمد على آكسه لنفس النقطة، عشان الخطين يتقابلوا بالظبط
                    if lateral(cand,w["p1"],w["p2"])>0.02:
                        X=line_x(b["p1"],b["p2"],w["p1"],w["p2"])
                        if X and math.dist(X,e_)<=b["w"]/2+0.3: cand=X
                    cand=(cand,w,ek)
            if cand is None: continue
            if not isinstance(cand[0],(tuple,list)): cand=(cand,None,None)
            if best is None or d<best[0]: best=(d,cand)
        if best:
            pt,w_,ek=best[1]
            b[end]=pt
            if w_ is not None and lateral(pt,w_["p1"],w_["p2"])<=0.02: w_[ek]=pt
            log["beam_end_to_wall"]+=1; return True
        # كمرة تانية
        best=None
        for b2 in beams:
            if b2 is b: continue
            u2=unit(b2["p1"],b2["p2"])
            if angle_between(u,u2)<20: continue
            X=line_x(b["p1"],b["p2"],b2["p1"],b2["p2"])
            if not X: continue
            if math.dist(X,P)>reach+b2["w"]/2: continue
            if LineString([b2["p1"],b2["p2"]]).distance(Point(X))>reach: continue
            if best is None or math.dist(X,P)<best[0]: best=(math.dist(X,P),X,b2)
        if best:
            b[end]=best[1]; log["beam_end_to_beam"]+=1
            carried.append((b.get("id"),best[2].get("id")))
            # لو الكمرة التانية طرفها قريب من نقطة الالتقاء (ركن L) نوصلها هي كمان
            b2=best[2]
            for e2 in ("p1","p2"):
                if math.dist(b2[e2],best[1])<=reach+b["w"]/2: b2[e2]=best[1]
            return True
        return False
    def extend_free(b,end,R=4.0,col_lat=1.0,back=1.0):
        """طرف سايب: نمد الكمرة على آكسها لقدام (لحد R) - أو نقصّها لورا (لحد back) لو
        الطرف فات خط العنصر - لحد أقرب خط كمرة/حائط أو آكس عمود."""
        P=b[end]; other=b["p2" if end=="p1" else "p1"]; u=unit(other,P)
        L0=math.dist(P,other)
        back=min(back,0.5*L0)
        A=(P[0]-u[0]*back,P[1]-u[1]*back); B_=(P[0]+u[0]*R,P[1]+u[1]*R)
        ray=LineString([A,B_])
        def tpos(X): return (X[0]-P[0])*u[0]+(X[1]-P[1])*u[1]
        best=None
        def consider(t,X,carrier,kind):
            nonlocal best
            if abs(t)<1e-3: return
            key=t if t>0 else -t*1.5          # لقدام أولى شوية من القص
            if best is None or key<best[0]: best=(key,X,carrier,kind,t)
        for b2 in beams:
            if b2 is b or math.dist(b2["p1"],b2["p2"])<0.1: continue
            if angle_between(u,unit(b2["p1"],b2["p2"]))<8: continue
            u2=unit(b2["p1"],b2["p2"]); e2=b2["w"]/2+0.3
            X=ray.intersection(LineString([(b2["p1"][0]-u2[0]*e2,b2["p1"][1]-u2[1]*e2),(b2["p2"][0]+u2[0]*e2,b2["p2"][1]+u2[1]*e2)]))
            if X.is_empty or X.geom_type!="Point": continue
            consider(tpos((X.x,X.y)),(X.x,X.y),b2,"beam")
        for w in sup_walls:
            if angle_between(u,unit(w["p1"],w["p2"]))<8: continue
            a_,c_=w["p1"],w["p2"]; uw=unit(a_,c_); e=w["t"]/2+0.2
            X=ray.intersection(LineString([(a_[0]-uw[0]*e,a_[1]-uw[1]*e),(c_[0]+uw[0]*e,c_[1]+uw[1]*e)]))
            if X.is_empty or X.geom_type!="Point": continue
            consider(tpos((X.x,X.y)),(X.x,X.y),None,"wall")
        # عنصر على نفس الخط قدامها (حائط أو كمرة ماشية على امتدادها): لبدايته بالظبط
        for m_,kind_,half in [(w,"wall",w["t"]/2) for w in sup_walls]+[(o,"beam",o["w"]/2) for o in beams if o is not b]:
            if angle_between(u,unit(m_["p1"],m_["p2"]))>=8: continue
            for k_ in ("p1","p2"):
                q=m_[k_]; t=tpos(q)
                if 1e-3<t<=R and lateral(q,P,(P[0]+u[0],P[1]+u[1]))<=max(b["w"]/2,half)+0.02:
                    consider(t,tuple(q),m_ if kind_=="beam" else None,kind_+"_in_line")
        for col,cc in zip(sup_cols,ccen):
            t=tpos(cc)
            if not (-back<t<=R): continue
            if lateral(cc,P,(P[0]+u[0],P[1]+u[1]))>max(b["w"]/2+col["b"]/2,col_lat): continue
            consider(t,(P[0]+u[0]*t,P[1]+u[1]*t),None,"column")
        if not best: return False
        _,X,carrier,kind,t=best
        b[end]=X
        if carrier is not None and LineString([carrier["p1"],carrier["p2"]]).distance(Point(X))>0.005:
            k2=min(("p1","p2"),key=lambda k_:math.dist(carrier[k_],X))
            carrier[k2]=proj(X,carrier["p1"],carrier["p2"]) if lateral(X,carrier["p1"],carrier["p2"])>1e-6 else X
        k="free_end_"+("extended" if t>0 else "trimmed")+"_to_"+kind
        log[k]=log.get(k,0)+1
        log.setdefault("extended_m",[]).append(round(t,2))
        if carrier is not None: carried.append((b.get("id"),carrier.get("id")))
        b["extended"]=True
        return True
    pending=[]
    for b in beams:
        if b.get("curved"): continue
        for end in ("p1","p2"):
            if not snap_end(b,end): pending.append((b,end))
    # "متصل" = الطرف جوه عمود ركيزة، أو واقع على خط كمرة/حائط تاني (± 1 سم)
    def is_connected(b,end):
        P=Point(b[end])
        if any(c.buffer(0.01).contains(P) for c in cpoly): return True
        # عمود مركزه جوه عرض الكمرة عند طرفها = متصل في الـ mesh
        u_=unit(b["p2" if end=="p1" else "p1"],b[end])
        # نهاية الكمرة (خط بعرضها) بتقطع العمود = متصل
        cap=LineString([(b[end][0]-u_[1]*b["w"]/2,b[end][1]+u_[0]*b["w"]/2),(b[end][0]+u_[1]*b["w"]/2,b[end][1]-u_[0]*b["w"]/2)])
        if any(c.buffer(0.01).intersects(cap) for c in cpoly): return True
        # حائط موازي مزاح (الكمرة على امتداده): طرفها فوق بدايته = متصل
        if any(angle_between(u_,unit(w["p1"],w["p2"]))<20 and LR._wall_poly(w).buffer(0.01).intersects(cap) for w in sup_walls): return True
        for o in beams:
            if o is not b and LineString([o["p1"],o["p2"]]).distance(P)<0.01: return True
        for w in sup_walls:
            if LineString([w["p1"],w["p2"]]).distance(P)<0.01: return True
        return False
    # لحام: طرف على بعد ≤ 5 سم من خط عنصر تاني -> عليه بالظبط
    for b in beams:
        for end in ("p1","p2"):
            P=Point(b[end]); bestw=None
            for o in [x for x in beams if x is not b]+sup_walls:
                ln=LineString([o["p1"],o["p2"]]); d=ln.distance(P)
                if 1e-6<d<=0.05 and (bestw is None or d<bestw[0]): bestw=(d,ln)
            if bestw:
                q=nearest_points(bestw[1],P)[0]; b[end]=(q.x,q.y)
    for b in beams:
        for end in ("p1","p2"):
            if is_connected(b,end): continue
            if b.get("curved") and any(o is not b and o.get("curved") and min(math.dist(b[end],o["p1"]),math.dist(b[end],o["p2"]))<0.01 for o in beams):
                continue
            if not extend_free(b,end):
                log["free_beam_ends"].append(b[end])
    # الكمرات المنحنية: قطعها متصلة ببعض أصلًا، نربط أول/آخر قطعة بس
    for b in beams:
        if b.get("curved"):
            for end in ("p1","p2"):
                P=b[end]
                if sum(1 for o in beams if o is not b and o.get("curved") and min(math.dist(P,o["p1"]),math.dist(P,o["p2"]))<0.01): continue
                snap_end(b,end)
                if not is_connected(b,end):
                    # طرف القوس: لأقرب نقطة على آكس حائط/عمود في حدود 0.5 م (من غير ما نمد القوس)
                    Pp=Point(b[end]); cands=[]
                    for w in sup_walls:
                        ln=LineString([w["p1"],w["p2"]]); d_=ln.distance(Pp)
                        if d_<=0.5+w["t"]/2: q=nearest_points(ln,Pp)[0]; cands.append((d_,(q.x,q.y)))
                    for cc in ccen:
                        d_=math.dist(cc,b[end])
                        if d_<=0.5: cands.append((d_,tuple(cc)))
                    if cands:
                        b[end]=min(cands)[1]; log["curved_end_to_support"]=log.get("curved_end_to_support",0)+1

    # ---- 3) تقسيم الكمرة عند عمود واقع على خطها ----
    out=[]
    for b in beams:
        pts=[b["p1"],b["p2"]]; ln=LineString(pts)
        mids=[]
        for c,cc in zip(cpoly,ccen):
            if min(math.dist(proj(cc,b["p1"],b["p2"]),b["p1"]),math.dist(proj(cc,b["p1"],b["p2"]),b["p2"]))<0.05: continue
            if ln.distance(Point(cc))<=max(0.35,b["w"]/2) and 0.05<ln.project(Point(cc))<ln.length-0.05:
                mids.append((ln.project(Point(cc)),proj(cc,b["p1"],b["p2"])))
        mids.sort()
        chain=[b["p1"]]+[cc for _,cc in mids]+[b["p2"]]
        if mids: log["beam_split_at_column"]+=len(mids)
        for k in range(len(chain)-1):
            nb=dict(b); nb["p1"]=chain[k]; nb["p2"]=chain[k+1]; out.append(nb)
    out=[b for b in out if math.dist(b["p1"],b["p2"])>=0.1]      # قطع اتقسمت لطول صفر
    M["beams"]=out

    # ---- الأولوية: الأعمق أعلى، والشايلة أعلى من المحمولة عليها ----
    # عمق كمرة مش مكتوب (تسمية من غير قطاع / كمرة من غير تسمية): max(البحر/10، DEPTH_MIN)
    # البحر = طول الحتة بين الركايز بعد التقسيم عند الأعمدة
    import os
    _dmin=float(os.environ.get("DEPTH_MIN","0.6"))
    for b in out:
        if not b.get("d"):
            L_=math.dist(b["p1"],b["p2"]); b["d"]=max(math.ceil(L_/10/0.05-1e-9)*0.05,_dmin); b["depth_rule"]=True
    pr={}
    for b in out: pr[b["id"]]=10+int(round((b["d"] or 0)*10))      # عمق مش معروف (تسمية من غير قطاع) -> الأولوية من الشايل/المتشال بس
    for _ in range(5):
        for c_,s_ in carried:
            if c_ in pr and s_ in pr and pr[s_]<=pr[c_]: pr[s_]=pr[c_]+1
    for b in out: b["priority"]=pr[b["id"]]
    # ---- 4) حد البلاطة والفتحات على وش الكمرة الخارجي ----
    faces=[]
    for b in out:
        u=unit(b["p1"],b["p2"]); n=(-u[1],u[0]); h=b["w"]/2
        for s in (1,-1):
            faces.append(LineString([(b["p1"][0]+s*n[0]*h,b["p1"][1]+s*n[1]*h),(b["p2"][0]+s*n[0]*h,b["p2"][1]+s*n[1]*h)]))
    def snap_poly(pts,key,tol=0.20):
        """كل ضلع موازي لوش كمرة وقريب منه (≤ 20 سم) ومتداخل معاه ≥ نصه
        بيبقى على خط الوش نفسه، والرؤوس = تقاطع الضلعين الجداد."""
        n=len(pts); lines=[]; moved=0
        for i in range(n):
            a,b=pts[i],pts[(i+1)%n]; L=math.dist(a,b)
            tgt=None
            if L>0.05:
                ue=unit(a,b); seg=LineString([a,b])
                best=None
                for f in faces:
                    fc=list(f.coords)
                    if angle_between(ue,unit(fc[0],fc[1]))>5: continue
                    d=max(lateral(a,fc[0],fc[1]),lateral(b,fc[0],fc[1]))
                    if d>tol: continue
                    ov=seg.intersection(f.buffer(tol+0.01)).length
                    if ov<0.5*L: continue
                    if d<1e-4: best=(0,None); break
                    if best is None or d<best[0]: best=(d,fc)
                if best and best[1] is not None: tgt=best[1]
            lines.append((tgt[0],tgt[1]) if tgt else (a,b))
            if tgt: moved+=1
        if not moved: return [tuple(p) for p in pts]
        new=[]
        for i in range(n):
            l0=lines[i-1]; l1=lines[i]
            X=line_x(l0[0],l0[1],l1[0],l1[1])
            if X is None or math.dist(X,pts[i])>0.5:
                X=proj(pts[i],*l1) if lines[i]!=(pts[i],pts[(i+1)%n]) else tuple(pts[i])
            new.append(X)
        # رؤوس مكررة + تأكد إن الشكل سليم؛ لو اتبوظ نصلحه أو نرجع للأصل
        clean=[]
        for p in new:
            if not clean or math.dist(clean[-1],p)>0.005: clean.append(p)
        if len(clean)>3 and math.dist(clean[0],clean[-1])<=0.005: clean.pop()
        pg=Polygon(clean); orig=Polygon(pts)
        if not pg.is_valid:
            fx=pg.buffer(0)
            fx=max(getattr(fx,"geoms",[fx]),key=lambda g:g.area) if not fx.is_empty else None
            if fx is None or abs(fx.area-orig.area)>0.005*orig.area:
                return [tuple(p) for p in pts]
            clean=list(fx.exterior.coords)[:-1]
        log[key]+=moved
        return clean
    R["slabs"][0]["outline"]=snap_poly(R["slabs"][0]["outline"],"slab_edges_snapped")
    for o in R["openings"]:
        o["poly"]=snap_poly(o["poly"],"opening_edges_snapped")
    return M,R,log

if __name__=="__main__":
    for tag in sys.argv[1:]:
        import os; M=json.load(open(f"{tag}_members_r.json" if os.path.exists(f"{tag}_members_r.json") else f"{tag}_members.json")); R=json.load(open(f"{tag}_res.json"))
        M,R,log=connect(M,R)
        json.dump(M,open(f"{tag}_members_c.json","w")); json.dump(R,open(f"{tag}_res_c.json","w"))
        fe=log.pop("free_beam_ends"); ex=log.pop("extended_m",[])
        M["free"]=[list(f) if isinstance(f,(list,tuple)) and len(f)==2 and not isinstance(f[0],(list,tuple)) else f for f in fe]
        json.dump(M,open(f"{tag}_members_c.json","w"))
        print(tag, {k:v for k,v in log.items() if k.startswith("free_end")}, "extensions (m):", ex, "still free:", len(fe))
