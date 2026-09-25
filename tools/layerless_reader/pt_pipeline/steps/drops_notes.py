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
    faces=[f for f in polygonize(unary_union([LineString(s) for s in g])) if 0.5<f.area<60]
    cols=[Polygon(c["rect"]["corners"]) for c in M["cols"]]
    st=min(slab_explicit) if slab_explicit else min(slab_t) if slab_t else (min(v for v,_ in thick) if thick else None)
    R.pop("thickness_review",None)
    thin=[v for v,_ in thick if st and v<st]
    if thin: R["thickness_review"]=f"notes T={sorted(set(thin))} thinner than slab {st} - ignored"
    drops=[]
    for v,p in thick:
        if st is None or v<=st: continue
        # العمود بيعمل "فتحة" في الوش، فنقارن بالحد الخارجي للوش
        cand=[Polygon(f.exterior) for f in faces if f.buffer(0.05).contains(p)]
        cand=[f for f in cand if any(f.contains(c.centroid) for c in cols)]
        if not cand: continue
        f=min(cand,key=lambda f:f.area)
        if f.area>=0.9*f.minimum_rotated_rectangle.area and not any(f.equals(d["poly_g"]) for d in drops):
            drops.append({"poly_g":f,"t":v})
    R["drops"]=R.get("drops",[])+[{"poly":list(d["poly_g"].exterior.coords)[:-1],"thickness_mm":d["t"]} for d in drops]
    if st is not None: R["slab_thickness_mm"]=st
    json.dump(R,open(f"{tag}_res_c.json","w"))
    print(tag,"slab t",st,R.get("thickness_review",""),"drops",[(round(d["poly_g"].area,1),d["t"]) for d in drops])
