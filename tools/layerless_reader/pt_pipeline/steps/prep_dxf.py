"""نسخة نضيفة للقراءة: شيل الليّرات المقفولة/المطفية (مش باينة في الأوتوكاد)،
وسحب المراجعة (revision clouds)، وحوّل مم -> م."""
import ezdxf, math, sys
from ezdxf.math import Matrix44
src,dst,scale=sys.argv[1],sys.argv[2],float(sys.argv[3])
d=ezdxf.readfile(src); m=d.modelspace()
hidden={L.dxf.name for L in d.layers if L.is_off() or L.is_frozen()}
def is_cloud(e):
    if e.dxftype()!="LWPOLYLINE": return False
    try: pts=e.get_points("xyb")
    except Exception: return False
    if len(pts)<8: return False
    segs=list(zip(pts,pts[1:]+([pts[0]] if e.closed else [])))
    arcs=[p[2] for p,_ in segs if abs(p[2])>0.2]
    if len(arcs)<0.8*len(segs): return False
    if not (all(b>0 for b in arcs) or all(b<0 for b in arcs)): return False
    L=[math.dist(p[:2],q[:2]) for p,q in segs]
    # سحابة: قواس قصيرة كتير في نفس الاتجاه، وطولها الكلي كبير (مش تفصيلة صغيرة زي قطاع ألومنيوم)
    return max(L)<1.5*(1/scale if scale<1 else 1)*1 and sum(L)>=4.0/scale*(1 if scale<1 else 1)
n_h=n_c=0
for lay in [m]+list(d.blocks):
    for e in list(lay):
        if e.dxf.get("layer") in hidden: lay.delete_entity(e); n_h+=1
        elif is_cloud(e): lay.delete_entity(e); n_c+=1
M=Matrix44.scale(scale,scale,scale)
for e in list(m):
    try: e.transform(M)
    except Exception: m.delete_entity(e)
d.header["$INSUNITS"]=6
d.saveas(dst); print("hidden removed",n_h,"clouds removed",n_c)
