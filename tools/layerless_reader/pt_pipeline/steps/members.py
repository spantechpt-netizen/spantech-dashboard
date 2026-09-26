import re
import ezdxf, sys, re, math, json, collections, os
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", ".."))
import slab_extractor as SX, layerless_reader as LR
from ezdxf import path as ezpath
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
DXF=os.environ.get("DXF","plan.dxf")
LBL_DIV=float(os.environ.get("LBL_DIV","100"))   # تسمية الكمرة: سم (100) أو مم (1000)
d=ezdxf.readfile(DXF); m=d.modelspace()
RE=re.compile(r"(?:\b\d\s*[xX]\s*|\b)([A-Z]{1,3}\d{0,2})\*?\s*-?\s*\(\s*(\d{2,4})\s*[*xX×]\s*(\d{2,5})\s*\)")
# كمرة متغيرة العرض "(350/200x700)": بتتقري بالعرض الأكبر وبتتعلّم tapered
TAPER=re.compile(r"\(\s*(\d{2,4})\s*/\s*(\d{2,4})\s*([*xX×])")

def legend(win_sheet=None):
    """نمط التعبئة -> النوع، من جدول المفتاح المرسوم نفسه."""
    out={}
    for e in m.query("TEXT MTEXT"):
        r=SX._text_of(e)
        if not r: continue
        t=r[0].upper()
        kind="continuous" if "CONTINUOUS" in t else "planted" if "PLANTED" in t else "stopped" if "STOPPED" in t else None
        if not kind or "COLUMN" not in t: continue
        x,y=r[1]; h=r[2]
        best=None
        for h_ in m.query("HATCH"):
            b=SX._bbox(h_)
            if not b: continue
            if b[2]<=x+0.3 and b[2]>=x-6*h and b[1]<=y+1.5*h and b[3]>=y-1.0*h:
                pat="SOLID" if h_.dxf.solid_fill else h_.dxf.pattern_name
                dist=x-b[2]
                if best is None or dist<best[0]: best=(dist,pat)
        if best: out.setdefault(best[1],collections.Counter())[kind]+=1
    res={p:c.most_common(1)[0][0] for p,c in out.items()}
    # جدول مفتاح حقيقي بيعرّف نوعين على الأقل (مستمر + مزروع مثلًا). ملاحظة "Planted Column"
    # لوحدها جنب عمود في المسقط مش مفتاح - دي بتخص العمود ده بس (planted_notes.py)
    return res if len(set(res.values()))>=2 else {}




REBAR_TXT=re.compile(r"\d+\s*T\s*\d+|T\d+\s*@|T\s*&\s*B|L\s*=\s*\d+(\.\d+)?\s*m|ADD\b",re.I)
def _drop_rebar(segs,m,W):
    """شيل خطوط التسليح من الخطوط اللي بتدخل في مزاوجة وشوش الكمرات:
    خط ≥ 0.8 م في طرفه هوك (خط قصير مايل 20-70° طرفه التاني حر)، والهوك نفسه."""
    def un(a,b):
        L=math.dist(a,b) or 1; return ((b[0]-a[0])/L,(b[1]-a[1])/L)
    def an(u,v): return math.degrees(math.acos(min(1,abs(u[0]*v[0]+u[1]*v[1]))))
    ends={}
    for i,(a,b) in enumerate(segs):
        for P in (a,b): ends.setdefault((round(P[0],2),round(P[1],2)),[]).append(i)
    def touching(P,skip):
        return [j for j in ends.get((round(P[0],2),round(P[1],2)),[]) if j not in skip]
    texts=[]
    for e in m.query("TEXT MTEXT"):
        r=SX._text_of(e)
        if not r or not REBAR_TXT.search(r[0]): continue
        x,y=r[1]
        if not(W[0]-1.5<x<W[2]+1.5 and W[1]-1.5<y<W[3]+1.5): continue
        rot=e.dxf.get("rotation",0.0) if e.dxftype()=="TEXT" else math.degrees(math.atan2(e.dxf.text_direction[1],e.dxf.text_direction[0]))
        tu=(math.cos(math.radians(rot)),math.sin(math.radians(rot))); n_=len(r[0]); h=r[2]
        texts.append(((x+tu[0]*n_*h*0.45-tu[1]*h*0.5, y+tu[1]*n_*h*0.45+tu[0]*h*0.5),tu,h))
    drop=set()
    for i,(a,b) in enumerate(segs):
        if math.dist(a,b)<0.8: continue
        u=un(a,b); hook=False
        for P in (a,b):
            for j in touching(P,{i}):
                s_=segs[j]
                if 0.04<=math.dist(*s_)<=0.45 and 20<=an(u,un(*s_))<=70:
                    far=s_[1] if math.dist(P,s_[0])<0.01 else s_[0]
                    if not touching(far,{j}): hook=True; drop.add(j)
        free=not touching(a,{i}) and not touching(b,{i})
        near_txt=free and any(an(u,tu)<=5 and LineString([a,b]).distance(Point(c))<=max(0.6,2*h) for c,tu,h in texts)
        # نص التسليح لوحده مش كفاية (وش كمرة حر جنب ملاحظة تسليح البلاطة اتشال غلط)؛ الهوك بس
        if hook: drop.add(i)
    return [s_ for k,s_ in enumerate(segs) if k not in drop]



def _split_masses(segs,beams,cols,walls,ops):
    from shapely.ops import polygonize
    from shapely import affinity
    from shapely.geometry import box as _box
    faces=[f for f in polygonize(unary_union([LineString(s_) for s_ in segs])) if 1.0<f.area<120]
    sup=[Polygon(c["rect"]["corners"]) for c in cols if c["type"]!="planted"]+[LR._wall_poly(w) for w in walls if w["type"]!="planted"]
    SUP=unary_union(sup) if sup else None
    allsolid=unary_union([Polygon(c["rect"]["corners"]) for c in cols]+[LR._wall_poly(w) for w in walls]) if (cols or walls) else None
    bands=[(b,LR._wall_poly({"p1":b["p1"],"p2":b["p2"],"t":b["w"]})) for b in beams if not b.get("curved")]
    OPS=unary_union(ops) if ops else None
    out=[]
    for F in faces:
        pieces=[]
        if F.area>=0.92*F.minimum_rotated_rectangle.area: continue          # مستطيل = كمرة عادية
        inside=[(b,bp) for b,bp in bands if bp.intersection(F).area>=0.5*bp.area]
        if not inside: continue
        if OPS is not None and F.intersection(OPS).area>0.2*F.area: continue
        R=F.difference(unary_union([bp.buffer(0.02) for _,bp in inside]))
        if allsolid is not None: R=R.difference(allsolid.buffer(0.01))
        lab_area=sum(bp.area for _,bp in inside)
        if R.area<0.5 or R.area>1.5*lab_area: continue
        if not R.buffer(-1.8).is_empty: continue                               # فيه حتة أعرض من 3.6 م = بلاطة مش كمرة
        ref=max(inside,key=lambda t:t[1].area)[0]
        ang=math.degrees(math.atan2(ref["p2"][1]-ref["p1"][1],ref["p2"][0]-ref["p1"][0]))
        org=F.centroid
        Rr=affinity.rotate(R,-ang,origin=org)
        def snap(vals):
            vals=sorted(vals); out_=[]
            for v in vals:
                if not out_ or v-out_[-1]>0.04: out_.append(v)
            return out_
        pts=[c for g in getattr(Rr,"geoms",[Rr]) if g.geom_type=="Polygon" for c in g.exterior.coords]
        xs=snap([p[0] for p in pts]); ys=snap([p[1] for p in pts])
        if len(xs)>24 or len(ys)>24: continue
        depth=max(b["d"] for b,_ in inside); names=" + ".join(sorted({b["label"] for b,_ in inside}))
        def nsup(rc):
            x0,y0,x1,y1=rc.bounds
            ends=[LineString([(x0,y0),(x0,y1)]),LineString([(x1,y0),(x1,y1)])] if x1-x0>=y1-y0 else \
                 [LineString([(x0,y0),(x1,y0)]),LineString([(x0,y1),(x1,y1)])]
            k=0
            for e_ in ends:
                ew=affinity.rotate(e_,ang,origin=org)
                if SUP is not None and ew.intersection(SUP.buffer(0.08)).length>=0.5*e_.length: k+=1
            return k
        for _ in range(6):
            if Rr.area<0.3: break
            best=None; P_=Rr.buffer(0.02)
            for i in range(len(xs)):
                for j in range(i+1,len(xs)):
                    for k in range(len(ys)):
                        for l in range(k+1,len(ys)):
                            w_,h_=xs[j]-xs[i],ys[l]-ys[k]; sh,lg=min(w_,h_),max(w_,h_)
                            if sh<0.25 or sh>3.6 or lg<max(0.8,sh): continue
                            rc=_box(xs[i],ys[k],xs[j],ys[l])
                            if rc.difference(P_).area>0.02*rc.area: continue
                            key=(nsup(rc),lg,rc.area)
                            if best is None or key>best[0]: best=(key,rc)
            if best is None: break
            rc=best[1]; x0,y0,x1,y1=rc.bounds
            if x1-x0>=y1-y0: a_,b_,w_=((x0,(y0+y1)/2),(x1,(y0+y1)/2),y1-y0)
            else: a_,b_,w_=(((x0+x1)/2,y0),((x0+x1)/2,y1),x1-x0)
            pa=affinity.rotate(Point(a_),ang,origin=org); pb=affinity.rotate(Point(b_),ang,origin=org)
            pieces.append({"mark":"PBM","w":round(w_,3),"d":depth,"p1":(pa.x,pa.y),"p2":(pb.x,pb.y),
                           "label":f"mass with {names}","mass":True,"supported_ends":best[0][0]})
            Rr=Rr.difference(rc.buffer(0.01))
        # كتلة حقيقية = فيها كمرة شايلة (طرفيها على ركائز)؛ غير كده غالبًا بلاطة بين كمرات
        if any(p["supported_ends"]==2 for p in pieces):
            out+=[p for p in pieces if p["supported_ends"]>=1]
    return out


def hatch_area(e):
    """مساحة الـ hatch من أضلاع الحدود نفسها: كل ضلع لوحده (خط/قوس/إهليلج/spline)
    وبعدين polygonize - ماتفرقش معاها ترتيب الأضلاع ولا اتجاه الأقواس."""
    from ezdxf.math import ConstructionArc
    from shapely.ops import polygonize, unary_union
    import shapely
    acc=None
    for bp in e.paths:
        if hasattr(bp,"vertices"):                      # polyline path
            p=ezpath.from_hatch_polyline_path(bp)
            pp=[(v.x,v.y) for v in p.flattening(0.01)]
            rings=[Polygon(pp).buffer(0)] if len(pp)>=3 else []
        else:
            lines=[]
            for ed in bp.edges:
                tn=type(ed).__name__
                try:
                    if tn=="LineEdge": pts=[ed.start,ed.end]
                    elif tn=="ArcEdge":
                        pts=list(ConstructionArc(ed.center,ed.radius,ed.start_angle,ed.end_angle).flattening(0.01))
                    elif tn=="EllipseEdge": pts=list(ed.construction_tool().flattening(0.01))
                    elif tn=="SplineEdge": pts=list(ed.construction_tool().flattening(0.01))
                    else: continue
                except Exception: continue
                pts=[(float(q[0]),float(q[1])) for q in pts]
                if len(pts)>=2: lines.append(LineString(pts))
            if not lines: continue
            net=shapely.set_precision(unary_union(lines),0.002)
            rings=[pg for pg in polygonize(net) if pg.area>1e-6]
        for hp in rings:
            acc=hp if acc is None else acc.symmetric_difference(hp)
    return acc


def _arc_band(g):
    """شكل على هيئة شريط منحني (بين قوسين متحدين المركز)؟ يرجّع
    (المركز، نصف القطر الأوسط، السُمك، زاوية البداية، زاوية النهاية) أو None."""
    import numpy as np
    if g.interiors: return None
    pts=np.array(g.exterior.coords[:-1])
    if len(pts)<8: return None
    t=2*g.area/max(g.length,1e-9)*1.0            # سُمك تقريبي لشريط طويل
    if not 0.1<=t<=0.8: return None
    A=np.c_[2*pts[:,0],2*pts[:,1],np.ones(len(pts))]; b=(pts**2).sum(1)
    cx,cy,c=np.linalg.lstsq(A,b,rcond=None)[0]; R=math.sqrt(max(c+cx*cx+cy*cy,0))
    if not 1.0<R<80: return None
    r=np.hypot(pts[:,0]-cx,pts[:,1]-cy)
    ri,ro=r.min(),r.max(); th=ro-ri
    if not 0.1<=th<=0.8 or abs(th-t)>0.35*th: return None
    # كل النقط لازم تبقى على القوس الجوّاني أو البرّاني
    if (np.minimum(abs(r-ri),abs(r-ro))>0.03).mean()>0.1: return None
    ang=np.unwrap(np.arctan2(pts[:,1]-cy,pts[:,0]-cx))
    a0,a1=float(ang.min()),float(ang.max())
    if (a1-a0)*R<2*th: return None                 # قصير جدًا: عنصر عادي
    return (float(cx),float(cy)),float((ri+ro)/2),float(th),a0,a1


# كمرات مرسومة من غير تسمية: مقفولة افتراضيًا (خطوط تسليح/حدود كانت بتتقري كمرات)،
# وبتتفتح بـ env UNLABELLED=1 لمشروع كمراته مرسومة ومش متسمية - وبتتعلّم للمراجعة
GUESS_UNLABELLED=os.environ.get("UNLABELLED")=="1"

MARK_RE=re.compile(os.environ["MARK_RE"]) if os.environ.get("MARK_RE") else None
def run(tag, W, legmap):
    global _CLIP
    try: _CLIP=Polygon(json.load(open(f"{tag}_res.json"))["slabs"][0]["outline"]).buffer(0)
    except Exception: _CLIP=box(-1e9,-1e9,1e9,1e9)
    # كل الكيانات جوه إطار المسقط، بعد فك البلوكات (بعض الملفات حاطة الهاتش والتسميات جوه بلوكات)
    _mg=1.6
    EX=[]
    for e_ in m:
        b_=SX._bbox(e_)
        if not b_ or b_[2]<W[0]-_mg or b_[0]>W[2]+_mg or b_[3]<W[1]-_mg or b_[1]>W[3]+_mg: continue
        EX+=list(SX._explode([e_]))
    def Q(types):
        ts=set(types.split())
        return [x for x in EX if x.dxftype() in ts]
    # ---- عناصر رأسية: hatch بنمط من المفتاح ----
    elems=[]
    for e in Q("HATCH"):
        b=SX._bbox(e)
        if not b or not (W[0]<=b[0] and b[2]<=W[2] and W[1]<=b[1] and b[3]<=W[3]): continue
        pat="SOLID" if e.dxf.solid_fill else e.dxf.pattern_name
        if pat not in legmap: continue
        acc=hatch_area(e)
        if acc is None: continue
        for g in getattr(acc,"geoms",[acc]):
            if g.geom_type!="Polygon" or g.area<0.02: continue
            elems.append((g, legmap[pat]))
    # عناصر زيادة من برّه (زي أعمدة تحت البلاطة مرسومة متقطع من غير هاتش)
    if os.environ.get("EXTRA_ELEMS"):
        for x_ in json.load(open(os.environ["EXTRA_ELEMS"])):
            g_=Polygon(x_["poly"]).buffer(0)
            if W[0]<=g_.bounds[0] and g_.bounds[2]<=W[2] and W[1]<=g_.bounds[1] and g_.bounds[3]<=W[3]: elems.append((g_,x_["type"]))
    # البلاطة نفسها: الإطار ممكن يلم عناصر بلاطة جنبها (بلاطتين مقسومين بفاصل وواحدة مايلة)
    elems=[(g_,k_) for g_,k_ in elems if _CLIP.buffer(0.6).contains(g_.representative_point())]
    if os.environ.get("DBG_TYPES"): print("elems",collections.Counter(k_ for _,k_ in elems))
    # نفس الشكل متهاشر مرتين
    # نفس المكان متهاشر مرتين (أحيانًا بنمطين مختلفين): الـ SOLID (مستمر) هو اللي
    # باين في الرسمة فبيكسب، والتاني بياخد بس الجزء اللي برّه منه
    # (عمود مزروع فوق حائط موقوف: الاتنين حقيقيين ومتداخلين، فمابيتقصّش غير على الـ SOLID)
    uniq=[]; solid_=None
    # OVERLAY=1: نمط تاني مرسوم فوق الـ SOLID بالظبط (عمود متهاشر SOLID + شبكة) = النوع التاني
    # هو الصح (الشبكة علامة "موقوف" فوق التعبئة العادية)
    _ov=os.environ.get("OVERLAY")=="1"
    for g,k in sorted(elems,key=lambda t:(0 if t[1]=="continuous" else 1,-t[0].area)):
        hit=[i_ for i_,(u,_) in enumerate(uniq) if g.intersection(u).area>0.8*g.area]
        if hit:
            if _ov and k!="continuous":
                for i_ in hit:
                    if uniq[i_][0].intersection(g).area>0.8*uniq[i_][0].area: uniq[i_]=(uniq[i_][0],k)
            continue
        g2=g if (solid_ is None or k=="continuous") else g.difference(solid_)
        if g2.area<0.2*g.area: continue
        for gg in getattr(g2,"geoms",[g2]):
            if gg.geom_type=="Polygon" and gg.area>=0.02: uniq.append((gg,k))
        if k=="continuous": solid_=g if solid_ is None else solid_.union(g)
    ops=[]
    try:
        ops=[Polygon(o["poly"]).buffer(-0.05) for o in json.load(open(f"{tag}_res.json"))["openings"]]
    except Exception: pass
    cols=[]; walls=[]
    for g,k in uniq:
        if g.area<0.6 and any(o.contains(g.representative_point()) for o in ops): continue   # معدات جوه فتحة
        L,S=SX._rect_dims(g)
        fill=g.area/max(g.minimum_rotated_rectangle.area,1e-9)
        if S<0.15: continue                        # حاجات صغيرة (sleeves) مش عناصر
        circ=4*math.pi*g.area/max(g.length**2,1e-9)
        if circ>=0.88 and L<=2.0 and L/S<=1.15:
            # عمود دايري: نفس المركز والقطر (البرنامج بيقراه دايري لو الشكل مضلع ≥ 8 نقط)
            dia=2*math.sqrt(g.area/math.pi); c0=g.centroid
            corners=[(c0.x+dia/2*math.cos(2*math.pi*i/32),c0.y+dia/2*math.sin(2*math.pi*i/32)) for i in range(32)]
            r={"center":(c0.x,c0.y),"long":dia,"short":dia,"angle_deg":0.0,"corners":corners}
            cols.append({"type":k,"rect":r,"b":round(dia,3),"d":round(dia,3),"round":True})
            continue
        if fill>=0.85 and L<=2.0 and L/S<=3.98:     # البرنامج بيرفض العمود لو النسبة > 4
            r=LR.min_area_rect(list(g.exterior.coords)[:-1])
            if 0.145<=r["short"]<0.1505:
                # مرسوم 15 سم بالظبط والتقريب نزّله تحت حد البرنامج (150 مم) فبيترفض
                a_=math.radians(r["angle_deg"]); ux_,uy_=math.cos(a_),math.sin(a_); nx_,ny_=-uy_,ux_
                hl,hs=r["long"]/2,0.1505/2; cx_,cy_=r["center"]
                r["short"]=0.1505
                r["corners"]=[(cx_+sx*hl*ux_+sy*hs*nx_, cy_+sx*hl*uy_+sy*hs*ny_) for sx,sy in ((-1,-1),(1,-1),(1,1),(-1,1))]
            cols.append({"type":k,"rect":r,"b":round(r["long"],3),"d":round(r["short"],3)})
        elif fill>=0.85:
            r=LR.min_area_rect(list(g.exterior.coords)[:-1])
            a=math.radians(r["angle_deg"]); ux,uy=math.cos(a),math.sin(a)
            cx,cy=r["center"]; h=r["long"]/2
            walls.append({"type":k,"p1":(cx-ux*h,cy-uy*h),"p2":(cx+ux*h,cy+uy*h),"t":r["short"]})
        elif _arc_band(g) is not None:
            # حائط/عمود منحني: قوسين متحدين المركز -> قطع مستقيمة ≈ 1 م على القوس الأوسط
            (cx,cy),Rm,t_,a0,a1=_arc_band(g)
            nseg=max(1,int(round((a1-a0)*Rm/1.0)))
            for i_ in range(nseg):
                u0=a0+(a1-a0)*i_/nseg; u1=a0+(a1-a0)*(i_+1)/nseg
                walls.append({"type":k,"p1":(cx+Rm*math.cos(u0),cy+Rm*math.sin(u0)),
                              "p2":(cx+Rm*math.cos(u1),cy+Rm*math.sin(u1)),"t":t_,"curved":True})
        else:
            # L / T / حلقة: وشوش متوازية جوه الشكل نفسه
            cs=list(g.exterior.coords)+[c for i in g.interiors for c in i.coords]
            ring_segs=[]
            for ring in [g.exterior]+list(g.interiors):
                c_=list(ring.coords)
                ring_segs+=[(c_[i],c_[i+1],{}) for i in range(len(c_)-1) if math.dist(c_[i],c_[i+1])>0.05]
            cfg=LR.Config(wall_min_t=0.1,wall_max_t=0.6,wall_min_len=0.3)
            for w in LR.merge_pieces(LR.pair_faces(ring_segs,cfg)):
                if math.dist(w["p1"],w["p2"])>=0.3:
                    walls.append({"type":k,"p1":w["p1"],"p2":w["p2"],"t":w["t"]})
    supports=unary_union([Polygon(c["rect"]["corners"]) for c in cols]+[LR._wall_poly(w) for w in walls]) if (cols or walls) else None
    # ---- الكمرات: تسمية MARK(W*D) + وشين متوازيين بنفس العرض ----
    segs=[]
    for e in Q("LINE LWPOLYLINE"):
        b=SX._bbox(e)
        if not b or not (W[0]<=b[0] and b[2]<=W[2] and W[1]<=b[1] and b[3]<=W[3]): continue
        try: pts=[(v.x,v.y) for v in ezpath.make_path(e).flattening(0.01)]
        except Exception: continue
        if e.dxftype()=="LWPOLYLINE" and e.closed: pts.append(pts[0])
        segs+=[(pts[i],pts[i+1]) for i in range(len(pts)-1) if math.dist(pts[i],pts[i+1])>0.3]
    seen=set(); S_=[]
    for s in segs:
        k_=tuple(sorted([(round(s[0][0],3),round(s[0][1],3)),(round(s[1][0],3),round(s[1][1],3))]))
        if k_ not in seen: seen.add(k_); S_.append(s)
    if os.environ.get('DBG_SEG'):
        yy=float(os.environ['DBG_SEG'])
        _k=_drop_rebar(S_,m,W)
        print('DBGSEG before',[ [round(v,2) for v in (*a,*b)] for a,b in S_ if abs(a[1]-yy)<0.05 and abs(b[1]-yy)<0.05],'after',[ [round(v,2) for v in (*a,*b)] for a,b in _k if abs(a[1]-yy)<0.05 and abs(b[1]-yy)<0.05])
    segs=_drop_rebar(S_,m,W); L_=[LineString(s) for s in segs]; tree=STRtree(L_)
    labels=[]
    for e in Q("TEXT MTEXT"):
        r=SX._text_of(e)
        if not r: continue
        x,y=r[1]
        # التسمية ممكن تبقى برّه حدود المسقط بشوية (جنب الكمرة الطرفية)
        if not(W[0]-1.5<x<W[2]+1.5 and W[1]-1.5<y<W[3]+1.5): continue
        _txt=r[0]; _tap=TAPER.search(_txt)
        if _tap: _txt=TAPER.sub(lambda m_: "(%d%s"%(max(int(m_.group(1)),int(m_.group(2))),m_.group(3)),_txt)
        mm=RE.search(_txt)
        if not mm:
            # تسمية بالعلامة بس (EB1 / B10 / SB3-A) من غير قطاع: العرض من الرسمة والعمق مش معروف
            if MARK_RE and MARK_RE.fullmatch(r[0].strip()) and _CLIP.buffer(1.5).contains(Point(x,y)):
                rot=e.dxf.get("rotation",0.0) if e.dxftype()=="TEXT" else math.degrees(math.atan2(e.dxf.text_direction[1],e.dxf.text_direction[0]))
                h=r[2]; n=len(r[0]); a=math.radians(rot)
                cx=x+math.cos(a)*n*h*0.45-math.sin(a)*h*0.5; cy=y+math.sin(a)*n*h*0.45+math.cos(a)*h*0.5
                labels.append({"mark":r[0].strip(),"w":None,"dpt":None,"at":(cx,cy),"rot":rot%180,"text":r[0].strip(),"depth_typo":False})
            continue
        if not _CLIP.buffer(1.5).contains(Point(x,y)): continue
        rot=e.dxf.get("rotation",0.0) if e.dxftype()=="TEXT" else math.degrees(math.atan2(e.dxf.text_direction[1],e.dxf.text_direction[0]))
        # نقطة وسط النص تقريبًا
        h=r[2]; n=len(r[0]); a=math.radians(rot)
        cx=x+math.cos(a)*n*h*0.45-math.sin(a)*h*0.5; cy=y+math.sin(a)*n*h*0.45+math.cos(a)*h*0.5
        dpt=int(mm.group(3))/LBL_DIV; typo=False
        if dpt>3.0: dpt/=10; typo=True      # عمق فوق 3 م = غلطة كتابة (7000 بدل 700)
        labels.append({"mark":mm.group(1),"w":int(mm.group(2))/LBL_DIV,"dpt":dpt,"at":(cx,cy),"rot":rot%180,"text":r[0],"depth_typo":typo,**({"tapered":_tap.group(0)} if _tap else {})})
    beams=[]; miss=[]
    # تسمية بعرضين: مابتدخلش المطابقة العادية (بتلقط حتة غلط جنب العمود) - beam_steps.py بيبنيها من الوشوش
    tapered=[dict(mark=lb["mark"],label=lb["text"],label_at=list(lb["at"]),label_rot=lb["rot"],d=lb["dpt"],w=lb["w"]) for lb in labels if lb.get("tapered")]
    labels=[lb for lb in labels if not lb.get("tapered")]
    for lb in labels:
        px,py=lb["at"]; W_=lb["w"] if lb["w"] is not None else 0.3; _unk=lb["w"] is None
        near=[segs[int(k)] for k in tree.query(Point(px,py).buffer(W_+2.5))
              if LineString(segs[int(k)]).distance(Point(px,py))<=W_+2.5]
        cands=[]
        if os.environ.get("DBG_LBL") and abs(px-float(os.environ["DBG_LBL"].split(",")[0]))<1.5 and abs(py-float(os.environ["DBG_LBL"].split(",")[1]))<1.5:
            print("DBGNEAR",lb["text"],round(px,2),round(py,2),lb["rot"],[[round(v,2) for v in (*a,*b)] for a,b in near if abs(a[1]-b[1])<0.05 and 550<a[1]<556])
        for i in range(len(near)):
            si=near[i]; ai=SX._ang(si)
            for j in range(i+1,len(near)):
                sj=near[j]; aj=SX._ang(sj)
                dd=abs(ai-aj); dd=min(dd,180-dd)
                if dd>1.5: continue
                th=math.radians(ai); ux,uy=math.cos(th),math.sin(th); nx,ny=-uy,ux
                oi=(si[0][0]+si[1][0])/2*nx+(si[0][1]+si[1][1])/2*ny
                oj=(sj[0][0]+sj[1][0])/2*nx+(sj[0][1]+sj[1][1])/2*ny
                # المسافة بالقيمة المطلقة: خطين بميل 0.1° و179.9° متوازيين، بس العمودي
                # بتاع كل واحد في اتجاه عكس التاني، فالفرق كان بيطلع سالب في الترتيبين
                sp=abs(oj-oi)
                if _unk:
                    if not (0.15<=sp<=1.0): continue
                    loose=False
                elif sp<1e-6 or abs(sp-W_)>max(0.05,0.30*W_): continue
                else: loose=abs(sp-W_)>max(0.06,0.15*W_)      # 300 مكتوبة و350 مرسومة = نفس الكمرة (فرق رسم ≤ 6 سم)     # مرسومة أعرض/أضيق من التسمية بأكتر من 15%
                li=sorted([si[0][0]*ux+si[0][1]*uy, si[1][0]*ux+si[1][1]*uy])
                lj=sorted([sj[0][0]*ux+sj[0][1]*uy, sj[1][0]*ux+sj[1][1]*uy])
                lo,hi=max(li[0],lj[0]),min(li[1],lj[1])
                if hi-lo<0.4: continue
                pp=px*ux+py*uy
                along=0 if lo-1.0<=pp<=hi+1.0 else min(abs(pp-lo),abs(pp-hi))
                perp=abs(px*nx+py*ny-(oi+oj)/2)
                if perp>W_/2+1.5: continue
                da=abs(ai-lb["rot"]); da=min(da,180-da)
                inside=perp<=W_/2 and along==0
                # التسمية جوه الكمرة نفسها: ممكن تبقى مكتوبة بالعرض (كمرة قصيرة عريضة)
                # التسمية بالعرض على الكمرة مقبولة بس لكمرة قصيرة عريضة (طول ≤ 2× العرض، زي PB5 2.0×2.47)؛
                # غير كده ده زوج خطوط تاني (خطوط سلم/درج) بيعدّي تحت التسمية
                if da>12 and not (inside and hi-lo<=2.0*max(W_,0.3)): continue
                if loose and not inside: continue       # المسموح الواسع بس لو التسمية جوه الشريط نفسه
                score=perp+along+(0.005 if inside else 0.05)*da+(0 if _unk else 2.0*abs(sp-W_))+(5.0 if loose else 0)   # العرض الأقرب للمكتوب أولى
                cands.append((score,ai,oi,oj,lo,hi))
        cands.sort(key=lambda c_:c_[0])
        # أقل طول مقبول لكمرة بالعرض ده: وشين أقصر من كده = مش كمرة (نهايات حوائط،
        # حرف بسطة سلم...) فالتسمية تروح للمرشح اللي بعده، أو تتعلّم "مش متربطة"
        min_len=max(1.0,W_)          # الكمرة الشايلة العريضة ممكن تبقى قصيرة (PB5 2.0 × 2.46)
        found=None; valid=[]
        for sc_,ai,o1,o2,lo,hi in cands[:12]:
            _sp=abs(o2-o1)
            th=math.radians(ai); ux,uy=math.cos(th),math.sin(th); nx,ny=-uy,ux
            mid=(o1+o2)/2
            def run_ext(off):
                parts=[]
                for s in segs:
                    dd=abs(SX._ang(s)-ai); dd=min(dd,180-dd)
                    if dd>1.5: continue
                    o=(s[0][0]+s[1][0])/2*nx+(s[0][1]+s[1][1])/2*ny
                    if abs(o-off)>0.03: continue
                    s0=s[0][0]*ux+s[0][1]*uy; s1=s[1][0]*ux+s[1][1]*uy
                    parts.append((min(s0,s1),max(s0,s1)))
                parts.sort(); runs=[]
                for a_,b_ in parts:
                    if runs and a_<=runs[-1][1]+0.1: runs[-1][1]=max(runs[-1][1],b_)
                    else: runs.append([a_,b_])
                return runs
            def pick(runs):
                for a_,b_ in runs:
                    if a_-0.05<=(lo+hi)/2<=b_+0.05: return a_,b_
                return lo,hi
            a1,b1=pick(run_ext(o1)); a2,b2=pick(run_ext(o2))
            s0,s1=max(a1,a2),min(b1,b2)
            if s1-s0<0.4: s0,s1=lo,hi
            p1=(s0*ux+mid*nx, s0*uy+mid*ny); p2=(s1*ux+mid*nx, s1*uy+mid*ny)
            # زوج وشوش أغلبه حائط/عمود (وش حيطة المصعد مثلًا) مش كمرة
            if supports is not None:
                _bp=LR._wall_poly({"p1":p1,"p2":p2,"t":_sp if _unk else W_})
                if _bp.area>0 and _bp.intersection(supports).area>=0.5*_bp.area: continue
            if s1-s0>=min_len-0.05: valid.append((sc_,p1,p2,_sp))
        if not valid: miss.append(lb); continue
        # من المرشحين القريبين في السكور: اللي طرفيه على ركائز أولى
        # (التسمية ممكن تبقى مكتوبة بالعرض على كمرة قصيرة عريضة)
        def nsup(p1_,p2_):
            if supports is None: return 0
            u_=((p2_[0]-p1_[0]),(p2_[1]-p1_[1])); L_=math.hypot(*u_) or 1; u_=(u_[0]/L_,u_[1]/L_); n_=(-u_[1],u_[0])
            k_=0
            for P_ in (p1_,p2_):
                cap=LineString([(P_[0]-n_[0]*W_/2,P_[1]-n_[1]*W_/2),(P_[0]+n_[0]*W_/2,P_[1]+n_[1]*W_/2)])
                if cap.intersection(supports.buffer(0.08)).length>=0.5*W_: k_+=1
            return k_
        b0=valid[0][0]
        near_=[v for v in valid if v[0]<=b0+max(0.1,0.6*W_)]
        sc_best,p1,p2,_spb=max(near_,key=lambda v:(nsup(v[1],v[2]),-v[0]))
        if os.environ.get("DBG_LBL") and abs(lb["at"][0]-float(os.environ["DBG_LBL"].split(",")[0]))<1.5 and abs(lb["at"][1]-float(os.environ["DBG_LBL"].split(",")[1]))<1.5:
            print("DBG",lb["text"],[(round(v[0],2),[round(q,2) for q in (*v[1],*v[2])],nsup(v[1],v[2])) for v in valid[:6]], "cands",[(round(c_[0],2),round(c_[1])) for c_ in cands[:6]])
        beams.append({"mark":lb["mark"],"w":round(_spb,3) if _unk else W_,"d":lb["dpt"],"p1":p1,"p2":p2,"label":lb["text"],"label_at":list(lb["at"]),"label_rot":lb["rot"],**({"depth_typo":True} if lb.get("depth_typo") else {}),
                      **({"width_mismatch":True} if sc_best>=5 else {}),**({"depth_unknown":True,"width_measured":True} if _unk else {})})
    # ---- كمرة مرسومة على محور بس (من غير وشين): التسمية موازية لخط محور وقريبة منه ----
    # الكمرة على المحور ده من أقرب ركيزة على ناحية لأقرب ركيزة على الناحية التانية
    _sup=[Polygon(c["rect"]["corners"]) for c in cols]+[LR._wall_poly(w) for w in walls]
    try: ops_raw=[Polygon(o_["poly"]) for o_ in json.load(open(f"{tag}_res.json"))["openings"] if o_.get("kind") not in ("ramp","stair")]
    except Exception: ops_raw=[]
    for lb in list(miss):
        if lb["w"] is None: continue
        px,py=lb["at"]; best=None
        for s_ in segs:
            L_=math.dist(*s_)
            if L_<4.0: continue
            a_=math.degrees(math.atan2(s_[1][1]-s_[0][1],s_[1][0]-s_[0][0]))%180
            da=abs(a_-lb["rot"]); da=min(da,180-da)
            if da>5: continue
            d_=LineString(s_).distance(Point(px,py))
            if d_<=0.6 and (best is None or d_<best[0]): best=(d_,s_)
        # حرف فتحة (تسمية موازية لضلع فتحة وقريبة منه): الكمرة بطول الضلع، برّه الفتحة ولازقة فيها
        edge=None
        for op_ in ops_raw:
            ring=list(op_.exterior.coords)
            for q0,q1 in zip(ring,ring[1:]):
                if math.dist(q0,q1)<1.0: continue
                a_=math.degrees(math.atan2(q1[1]-q0[1],q1[0]-q0[0]))%180
                da=abs(a_-lb["rot"]); da=min(da,180-da)
                d_=LineString([q0,q1]).distance(Point(px,py))
                if da<=5 and d_<=lb["w"]+0.8 and (edge is None or d_<edge[0]): edge=(d_,q0,q1,op_)
        if edge:
            _,q0,q1,op_=edge; L_=math.dist(q0,q1); u=((q1[0]-q0[0])/L_,(q1[1]-q0[1])/L_); nrm=(-u[1],u[0])
            cen=op_.centroid; sgn=1 if (px-cen.x)*nrm[0]+(py-cen.y)*nrm[1]>0 else -1
            off=lb["w"]/2*sgn; ext=lb["w"]/2
            p1=(q0[0]+nrm[0]*off-u[0]*ext,q0[1]+nrm[1]*off-u[1]*ext); p2=(q1[0]+nrm[0]*off+u[0]*ext,q1[1]+nrm[1]*off+u[1]*ext)
            beams.append({"mark":lb["mark"],"w":lb["w"],"d":lb["dpt"],"p1":p1,"p2":p2,"label":lb["text"],"label_at":list(lb["at"]),"label_rot":lb["rot"],"opening_edge_beam":True,
                          **({"depth_typo":True} if lb.get("depth_typo") else {})})
            miss[:]=[x for x in miss if x is not lb]; continue
        if not best: continue
        (a,b)=best[1]; u=((b[0]-a[0])/math.dist(a,b),(b[1]-a[1])/math.dist(a,b))
        t0=(px-a[0])*u[0]+(py-a[1])*u[1]; P0=(a[0]+u[0]*t0,a[1]+u[1]*t0)
        def hit(sign):
            ray=LineString([P0,(P0[0]+sign*u[0]*14,P0[1]+sign*u[1]*14)])
            ts=[]
            for sp in _sup:
                X=ray.intersection(sp)
                if not X.is_empty: ts.append(Point(P0).distance(X))
            return min(ts) if ts else None
        t1=hit(1); t2=hit(-1)
        if t1 is None or t2 is None or t1+t2<1.0: continue
        p1=(P0[0]-u[0]*t2,P0[1]-u[1]*t2); p2=(P0[0]+u[0]*t1,P0[1]+u[1]*t1)
        beams.append({"mark":lb["mark"],"w":lb["w"],"d":lb["dpt"],"p1":p1,"p2":p2,"label":lb["text"],"label_at":list(lb["at"]),"label_rot":lb["rot"],"axis_beam":True,
                      **({"depth_typo":True} if lb.get("depth_typo") else {})})
        miss[:]=[x for x in miss if x is not lb]
    # ---- كمرة طرفية متسمية ومش مرسومة بوشين (الواجهة مرسومة شبابيك بس): التسمية موازية لحرف
    # البلاطة وقريبة منه (≤ 1 م) -> كمرة على الحرف (وشها الخارجي = الحرف) من ركيزة لركيزة ----
    try:
        _ring=list(_CLIP.exterior.coords)
    except Exception: _ring=[]
    for lb in list(miss):
        if lb["w"] is None or not _ring: continue
        px,py=lb["at"]; best=None
        for q0,q1 in zip(_ring,_ring[1:]):
            if math.dist(q0,q1)<2.0: continue
            a_=math.degrees(math.atan2(q1[1]-q0[1],q1[0]-q0[0]))%180
            da=abs(a_-lb["rot"]); da=min(da,180-da)
            d_=LineString([q0,q1]).distance(Point(px,py))
            if da<=5 and d_<=1.0 and (best is None or d_<best[0]): best=(d_,q0,q1)
        if not best: continue
        _,q0,q1=best; L_=math.dist(q0,q1); u=((q1[0]-q0[0])/L_,(q1[1]-q0[1])/L_); nrm=(-u[1],u[0])
        mid=((q0[0]+q1[0])/2,(q0[1]+q1[1])/2)
        if not _CLIP.contains(Point(mid[0]+nrm[0]*0.1,mid[1]+nrm[1]*0.1)): nrm=(-nrm[0],-nrm[1])     # لجوه البلاطة
        t0=(px-q0[0])*u[0]+(py-q0[1])*u[1]; W_=lb["w"]
        P0=(q0[0]+u[0]*t0+nrm[0]*W_/2,q0[1]+u[1]*t0+nrm[1]*W_/2)
        def hit_(sign):
            ray=LineString([P0,(P0[0]+sign*u[0]*14,P0[1]+sign*u[1]*14)]); ts=[]
            for sp in _sup:
                X=ray.intersection(sp)
                if not X.is_empty: ts.append(Point(P0).distance(X))
            return min(ts) if ts else None
        t1=hit_(1); t2=hit_(-1)
        if t1 is None or t2 is None or t1+t2<1.0: continue
        beams.append({"mark":lb["mark"],"w":W_,"d":lb["dpt"],"p1":(P0[0]-u[0]*t2,P0[1]-u[1]*t2),"p2":(P0[0]+u[0]*t1,P0[1]+u[1]*t1),
                      "label":lb["text"],"label_at":list(lb["at"]),"label_rot":lb["rot"],"slab_edge_beam":True})
        miss[:]=[x for x in miss if x is not lb]
    # ---- كمرات منحنية: قوسين متحدين المركز وفرق نصف القطر = العرض المكتوب ----
    import numpy as np
    arcs=[]
    for e in Q("ARC LWPOLYLINE POLYLINE"):
        b=SX._bbox(e)
        if not b or not (W[0]<=b[0] and b[2]<=W[2] and W[1]<=b[1] and b[3]<=W[3]): continue
        if e.dxftype()!="ARC":
            try:
                if not any(abs(v[4])>1e-6 for v in e.get_points("xyseb")): continue
            except Exception: continue
        pts=np.array([(v.x,v.y) for v in ezpath.make_path(e).flattening(0.005)])
        if len(pts)<5: continue
        A=np.c_[2*pts[:,0],2*pts[:,1],np.ones(len(pts))]; bb=(pts**2).sum(1)
        cx,cy,c=np.linalg.lstsq(A,bb,rcond=None)[0]; R=math.sqrt(c+cx*cx+cy*cy)
        if R>60 or np.abs(np.hypot(pts[:,0]-cx,pts[:,1]-cy)-R).max()>0.03: continue
        arcs.append({"c":(cx,cy),"R":R,"pts":pts})
    matched_lbl=set(id(b_) for b_ in beams)
    done_arcs=set()
    for lb in list(labels):
        if lb["w"] is None: continue
        px,py=lb["at"]; W_=lb["w"]
        got=None
        for i,a1 in enumerate(arcs):
            for a2 in arcs[i+1:]:
                if math.dist(a1["c"],a2["c"])>0.1: continue
                dr=abs(a1["R"]-a2["R"])
                if abs(dr-W_)>max(0.04,0.15*W_): continue
                Rm=(a1["R"]+a2["R"])/2
                if abs(math.dist((px,py),a1["c"])-Rm)>W_/2+1.2: continue
                # الجزء المشترك من الزاوية
                def angs(a): return np.unwrap(np.arctan2(a["pts"][:,1]-a["c"][1],a["pts"][:,0]-a["c"][0]))
                t1,t2=angs(a1),angs(a2)
                lo=max(min(t1),min(t2)); hi=min(max(t1),max(t2))
                if hi-lo<0.05:   # نجرب لف 2π
                    t2=t2+2*math.pi*round((np.mean(t1)-np.mean(t2))/(2*math.pi)); lo=max(min(t1),min(t2)); hi=min(max(t1),max(t2))
                if hi-lo<0.05: continue
                tl=math.atan2(py-a1["c"][1],px-a1["c"][0])
                tl+=2*math.pi*round(((lo+hi)/2-tl)/(2*math.pi))
                if not(lo-0.3<=tl<=hi+0.3): continue
                # الأقرب للتسمية (جوه مداه الزاوي وعلى نصف قطره)، مش أول واحد: القوس
                # ممكن يبقى مقسوم حتتين عند عمود وعلى كل حتة تسمية
                key_=max(0,lo-tl,tl-hi)*Rm+abs(math.dist((px,py),a1["c"])-Rm)
                if got is None or key_<got[0]: got=(key_,a1["c"],Rm,lo,hi)
        if os.environ.get("DBG_ARC"): print("DBGARC",lb["text"],[round(v,2) for v in lb["at"]],"->",None if not got else (round(got[0],2),round(got[2],2),round(got[3],2),round(got[4],2)))
        if not got: continue
        got=got[1:]
        (cx,cy),Rm,lo,hi=got
        akey=(round(cx,1),round(cy,1),round(Rm,1),round(lo,2),round(hi,2),lb["text"])
        if akey in done_arcs: miss[:]=[x for x in miss if x is not lb]; continue   # نفس القوس بتسمية تانية مكررة
        done_arcs.add(akey)
        n=max(2,int((hi-lo)*Rm/1.0)+1)     # قطع ≈ 1 م
        ts=np.linspace(lo,hi,n+1)
        # شيل أي كمرة مستقيمة صغيرة اتربطت غلط بنفس التسمية
        beams[:]=[b_ for b_ in beams if not (not b_.get("curved") and b_["label"]==lb["text"] and math.dist(b_["p1"],b_["p2"])<2.0
                                             and abs(math.dist(((b_["p1"][0]+b_["p2"][0])/2,(b_["p1"][1]+b_["p2"][1])/2),(cx,cy))-Rm)<W_+0.5)]
        miss[:]=[x for x in miss if x is not lb]
        for k in range(n):
            p1=(cx+Rm*math.cos(ts[k]),cy+Rm*math.sin(ts[k])); p2=(cx+Rm*math.cos(ts[k+1]),cy+Rm*math.sin(ts[k+1]))
            beams.append({"mark":lb["mark"],"w":W_,"d":lb["dpt"],"p1":p1,"p2":p2,"label":lb["text"],"label_at":list(lb["at"]),"label_rot":lb["rot"],**({"depth_typo":True} if lb.get("depth_typo") else {}),"curved":True})
    # ---- كتلة: شكل مقفول فيه كمرة متسمية ومش مستطيل -> نقسمه مستطيلات ----
    # المستطيل اللي طرفيه على ركائز = الكمرة الشايلة، والباقي بيقع عليه (المتشالة)
    beams+=_split_masses(segs,beams,cols,walls,ops)
    # ---- كمرة متسمية بتلف (L / U): نكمل رجليها بنفس العرض ونفس التسمية ----
    pcfg=LR.Config(wall_min_t=0.12,wall_max_t=2.6,wall_min_len=0.3)
    pieces=LR.merge_pieces(LR.pair_faces([(s_[0],s_[1],{}) for s_ in segs],pcfg))
    solid=[LR._wall_poly(w) for w in walls]+[Polygon(c["rect"]["corners"]) for c in cols]
    def _u(a,b):
        L=math.dist(a,b) or 1; return ((b[0]-a[0])/L,(b[1]-a[1])/L)
    # بس للكمرات العادية (≤ 60 سم): الكمرات الشايلة العريضة كل حتة فيها متسمية لوحدها
    stack=[(b,e,0) for b in beams if not b.get("curved") and b["w"]<=0.6 for e in ("p1","p2")]
    while stack:
        b,e,depth=stack.pop()
        if depth>=4: continue
        E_=b[e]; ub_=_u(b["p1"],b["p2"])
        # الطرف واقف على عمود/حائط = الكمرة خلصت هنا، مفيش رجل تانية
        if any(sp.distance(Point(E_))<=b["w"] for sp in solid): continue
        for pc in pieces:
            if abs(pc["t"]-b["w"])>max(0.05,0.15*b["w"]): continue
            up=_u(pc["p1"],pc["p2"])
            if abs(ub_[0]*up[0]+ub_[1]*up[1])>0.87: continue          # لازم يلف (≥ 30°)
            k=min(("p1","p2"),key=lambda k_:math.dist(pc[k_],E_))
            if math.dist(pc[k],E_)>b["w"]+0.1: continue
            if math.dist(pc["p1"],pc["p2"])<max(0.5,2*b["w"]): continue
            band=LR._wall_poly(pc)
            if any(band.intersection(sp).area>0.3*band.area for sp in solid): continue
            if any(LineString([x["p1"],x["p2"]]).distance(LineString([pc["p1"],pc["p2"]]))<b["w"]/2 and
                   abs(_u(x["p1"],x["p2"])[0]*up[0]+_u(x["p1"],x["p2"])[1]*up[1])>0.97 for x in beams): continue
            nb={"mark":b["mark"],"w":b["w"],"d":b["d"],"p1":pc["p1"],"p2":pc["p2"],"label":b["label"],"leg_of":b["label"]}
            beams.append(nb)
            stack.append((nb,"p2" if k=="p1" else "p1",depth+1))
    # دمج الكمرات المكررة (تسميتين لنفس الكمرة)
    ub=[]
    for b in beams:
        pb=LR._wall_poly({"p1":b["p1"],"p2":b["p2"],"t":b["w"]})
        if not b.get("curved") and any(pb.intersection(LR._wall_poly({"p1":u["p1"],"p2":u["p2"],"t":u["w"]})).area>0.6*pb.area for u in ub): continue
        ub.append(b)
    # ---- كمرات من غير تسمية: وشين متوازيين، والطرفين على ركيزة/كمرة ----
    from collections import Counter
    taken=unary_union([LR._wall_poly({"p1":b["p1"],"p2":b["p2"],"t":b["w"]}) for b in ub]+
                      [LR._wall_poly(w) for w in walls]+[Polygon(c["rect"]["corners"]) for c in cols]+ops) if (ub or walls or cols) else None
    anchors=[LR._wall_poly({"p1":b["p1"],"p2":b["p2"],"t":b["w"]}) for b in ub]+[LR._wall_poly(w) for w in walls if w["type"]!="planted"]+[Polygon(c["rect"]["corners"]) for c in cols if c["type"]!="planted"]
    long_segs=[(s[0],s[1],{}) for s in segs if math.dist(*s)>=1.0]
    cfg=LR.Config(wall_min_t=0.18,wall_max_t=0.6,wall_min_len=0.8)
    # طرف كمرة متسمية = مرساة كمان: القطع القصيرة (0.8-1.5 م) مقبولة بس لو بتوصّل طرف كمرة بركيزة/كمرة
    lab_ends=[Point(p) for b in ub for p in (b["p1"],b["p2"])]
    wall_polys=[LR._wall_poly(w) for w in walls]
    extra=[]
    # كمرات من غير تسمية: متوقفة (بتتلخبط مع خطوط التسليح وحد البلاطة)
    for pc in ([] if not GUESS_UNLABELLED else LR.merge_pieces(LR.pair_faces(long_segs,cfg))):
        L=math.dist(pc["p1"],pc["p2"])
        if L<0.8: continue
        band=LR._wall_poly(pc)
        # جنب حائط/عمود بطوله = خط الحائط اتزاوج مع خط جنبه، مش كمرة
        side=band.buffer(0.12,cap_style=2).difference(band)
        if any(side.intersection(wp).area>0.3*0.12*L for wp in wall_polys): continue
        # لازقة بطولها في كمرة (متسمية أو اتقبلت): الوش ده وش الكمرة التانية + خط جنبها (حرف سلم...)، مش كمرة
        _bp=[LR._wall_poly({"p1":b_["p1"],"p2":b_["p2"],"t":b_["w"]}) for b_ in ub+extra]
        if any(side.intersection(bp_).area>0.3*0.12*L for bp_ in _bp): continue
        if taken is not None and band.intersection(taken).area>0.3*band.area: continue
        e1=Point(pc["p1"]).buffer(0.8); e2=Point(pc["p2"]).buffer(0.8)
        # كمرة طرفية: وش منها على حد البلاطة بطولها -> مقبولة من غير ركايز على طرفيها
        edge=_CLIP.exterior.buffer(0.06).intersection(band.buffer(0.02).exterior).length>=0.8*L
        if not edge and not (any(a.intersects(e1) for a in anchors) and any(a.intersects(e2) for a in anchors)): continue
        # جوه فتحة (كور/منحدر/شفت) مش كمرة البلاطة دي
        if any(o.buffer(0.1).contains(band.representative_point()) for o in ops): continue
        if L<1.5 and not any(q.distance(Point(pc["p1"]))<=0.5 or q.distance(Point(pc["p2"]))<=0.5 for q in lab_ends): continue
        # العمق: كمرات متسمية قريبة بنفس العرض وطول قريب، وإلا عُشر البحر
        near=[b for b in ub if b.get("d") and abs(b["w"]-pc["t"])<=0.05 and
              LineString([b["p1"],b["p2"]]).distance(LineString([pc["p1"],pc["p2"]]))<=8.0]
        similar=[b for b in near if abs(math.dist(b["p1"],b["p2"])-L)<=0.3*L]
        pool=similar or near
        if pool:
            dpt=Counter(round(b["d"],2) for b in pool).most_common(1)[0][0]; src="nearby beams"
        else:
            dpt=None; src="depth rule"          # العمق بيتحط بعد الربط: max(البحر/10، الحد الأدنى)
        extra.append({"mark":"B?","w":round(pc["t"],3),"d":dpt,"p1":pc["p1"],"p2":pc["p2"],
                      "label":f"unlabelled ({src})","review":True,**({"edge_beam":True} if edge else {}),**({"depth_unknown":True} if dpt is None else {})})
    ub+=extra
    for i,b in enumerate(ub): b["id"]=i
    # كمرة مكتوب عليها RAMP (زي DB4(400X700)W/RAMP) شايلة المنحدر على منسوب تاني، مش البلاطة دي
    ramp_b=[b for b in ub if re.search(r"RAMP",b.get("label",""),re.I)]
    # وكمان أي كمرة (أو تسمية مالقتش وشوش) واقعة جوه المنحدر: المنحدر فتحة، فكمراته مش من البلاطة دي
    try: _rp=[Polygon(o_["poly"]).buffer(0.3) for o_ in json.load(open(f"{tag}_res.json"))["openings"] if o_.get("kind")=="ramp"]
    except Exception: _rp=[]
    if _rp:
        _R=unary_union(_rp)
        for b in ub:
            bp=LR._wall_poly({"p1":b["p1"],"p2":b["p2"],"t":b["w"]})
            if b not in ramp_b and bp.intersection(_R).area>=0.7*bp.area: ramp_b.append(b)
        for l_ in list(miss):
            if _R.contains(Point(l_["at"])):
                ramp_b.append({"label":l_["text"],"mark":l_["mark"],"w":l_["w"],"d":l_["dpt"],"p1":l_["at"],"p2":l_["at"],"label_only":True}); miss.remove(l_)
    ub=[b for b in ub if b not in ramp_b]
    # كمرة مقلوبة: مكتوب على تسميتها INV أو INVERTED
    for b in ub:
        if re.search(r"\bINV(?:ERTED)?\b",b.get("label",""),re.I): b["inverted"]=True
    res={"tapered_labels":tapered,"ramp_beams":ramp_b,"cols":cols,"walls":walls,"beams":ub,"miss":[l["text"]+" @(%.1f,%.1f)"%(l["at"][0]-W[0],l["at"][1]-W[1]) for l in miss],
         "miss_pts":[[l["text"],l["mark"],l["w"],l["dpt"],l["at"][0],l["at"][1]] for l in miss]}
    json.dump(res,open(f"{tag}_members.json","w"),default=lambda o: o)
    cc=collections.Counter(c["type"] for c in cols); wc=collections.Counter(w["type"] for w in walls)
    print(tag,"columns",dict(cc),"walls",dict(wc),"beams",len(ub),"(unlabelled %d)"%len(extra),"labels",len(labels),"unmatched",len(miss))
    for x in res["miss"][:10]: print("   miss",x)
    return res

if __name__=="__main__":
    if sys.argv[1:2]==["--legend-only"]:
        print("LEGEND",json.dumps(legend())); sys.exit(0)
    lm=json.loads(os.environ["LEGMAP"]) if os.environ.get("LEGMAP") else legend(); print("legend:",lm)
    W=json.load(open(os.environ["WINS"])) if os.environ.get("WINS") else {"S3":(1086.1,542.7,1124.5,594.9),"S4":(1083.4,412.4,1121.9,457.4),"S5":(1080.1,269.3,1118.5,314.3),"S6":(1082.9,129.2,1121.3,174.2)}
    for t in sys.argv[1:]: run(t,W[t],lm)
