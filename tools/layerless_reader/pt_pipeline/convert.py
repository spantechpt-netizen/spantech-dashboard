"""تحويل مخطط إنشائي/معماري (DWG/DXF) لملفات DXF نضيفة لـ Auto PT Suite - أمر واحد.

    python -m pt_pipeline.convert INPUT.dwg|dxf -o OUT [--sheets wins.json] [--keep-work]

الخطوات بالترتيب (كل خطوة سكريبت في steps/ وكل القواعد في RULES.md):
  1  DWG -> DXF (LibreDWG)، شيل الليّرات المقفولة وسحب المراجعة، وتحويل الوحدة لمتر (من مقاس الأعمدة).
  2  ذاكرة هندسية: خطوط/نصوص/هاتشات + الأشكال المتقطعة.
  3  الشيتات: عناوين -> فقاعات المحاور -> الرسمة كلها.
  4  لكل شيت: حد البلاطة والفتحات (slab_extractor)، فراغات X الكبيرة والكباري الحديد، السلالم
     (نصوص التسليح)، المنحدر المكتوب عليه RAMP، الكور = فتحة واحدة.
  5  فواصل التمدد -> زونات (أعمدة توأم ≥ 2 أزواج).
  6  الأعمدة/الحوائط/الكمرات (التسميات بالمقاسات، بالعلامة بس، بعرضين، كمرات الحرف، المرسومة
     من غير تسمية بين ركيزتين)، الربط، فحص المنطق.
  7  المنحدر من الخطوط المايلة (لو مفيش نص)، حد المنحدر على الحوائط/الكمرات، وكمرات المنحدر برّه الموديل.
  8  السُمك (ملاحظات + بلوكات)، الدروبات، المناسيب، شرايح الصب.
  9  السلم بين كمراته، الكور، الكمرة بعرضين، حد البلاطة على الكمرات والأعمدة، فحص الزونات.
  10 التصدير (PT-Clean-*، مم) + صور + members.csv + report.json.
الأمر بيطلع بكود ≠ 0 لو فحص الزونات فشل - الملف مابيتسلّمش وفيه غلط معروف.
"""
import argparse, json, math, os, pickle, re, shutil, statistics, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = os.path.join(HERE, "steps")
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def log(*a):
    print("[convert]", *a, flush=True)


def step(script, *args, env=None, cwd=None, check=True):
    e = dict(os.environ); e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(STEPS, script), *map(str, args)], cwd=cwd, env=e,
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    with open(os.path.join(cwd, "pipeline.log"), "a", encoding="utf-8") as f:
        f.write(f"\n===== {script} {' '.join(map(str, args))}\n{out}")
    if check and r.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{out[-3000:]}")
    return out


# ---------------------------------------------------------------- 1) القراءة والوحدة
def to_dxf(src, work):
    if src.lower().endswith(".dxf"):
        dst = os.path.join(work, "src.dxf"); shutil.copy(src, dst); return dst
    exe = os.environ.get("LIBREDWG_DWGREAD") or shutil.which("dwgread")
    if not exe:
        raise RuntimeError("DWG input needs LibreDWG dwgread (set LIBREDWG_DWGREAD)")
    js = os.path.join(work, "src.json")
    subprocess.run([exe, "-O", "JSON", "-o", js, src], check=True, capture_output=True)
    dst = os.path.join(work, "src.dxf")
    subprocess.run([sys.executable, os.path.join(ROOT, "dwg_json_to_dxf.py"), js, dst], check=True, capture_output=True)
    return dst


def detect_scale(dxf):
    """وحدة الرسمة من مقاس الأعمدة (أقصر ضلع لهاتش صغير مدمج): ~0.2-1 -> متر، ~20-100 -> سم، ~200-1000 -> مم."""
    import ezdxf, slab_extractor as SX, layerless_reader as LR
    from shapely.geometry import Polygon
    d = ezdxf.readfile(dxf); sides = []
    for e in SX._explode(list(d.modelspace())):
        if e.dxftype() != "HATCH": continue
        try:
            for r in LR.hatch_rings(e, 0.0):
                if len(r) < 3: continue
                p = Polygon(r).buffer(0)
                if p.is_empty or p.area <= 0: continue
                L, S = SX._rect_dims(p)
                if S > 0 and L / S <= 6 and p.area / max(p.minimum_rotated_rectangle.area, 1e-12) > 0.85: sides.append(S)
        except Exception:
            continue
    if not sides: return 1.0, "no hatches - assumed metres"
    s = statistics.median(sides)
    if s >= 100: return 0.001, f"median column side {s:.0f} -> mm"
    if s >= 10: return 0.01, f"median column side {s:.1f} -> cm"
    return 1.0, f"median column side {s:.2f} -> m"


# ---------------------------------------------------------------- 2) الذاكرة الهندسية
def build_caches(work):
    import ezdxf, slab_extractor as SX, layerless_reader as LR
    from ezdxf import path as P
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    d = ezdxf.readfile(os.path.join(work, "m.dxf"))
    segs, tx, hs = [], [], []; H = collections.defaultdict(list); dashed = []

    def lt(e):
        l = e.dxf.get("linetype", "BYLAYER")
        if l.upper() == "BYLAYER":
            try: l = d.layers.get(e.dxf.layer).dxf.linetype
            except Exception: pass
        return l.upper()
    for e in SX._explode(list(d.modelspace())):
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            r = SX._text_of(e)
            if r: tx.append((r[0][:60], r[1], r[2]))
        elif t == "HATCH":
            pat = "SOLID" if e.dxf.solid_fill else e.dxf.pattern_name
            try:
                for r_ in LR.hatch_rings(e, 0.01):
                    hs.append((r_, pat)); H[pat].append(r_)
            except Exception:
                pass
        elif t in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
            try: pts = [(v.x, v.y) for v in P.make_path(e).flattening(0.02)]
            except Exception: continue
            segs += list(zip(pts, pts[1:]))
            if t == "LWPOLYLINE" and e.closed and ("HID" in lt(e) or "DASH" in lt(e)) and len(pts) >= 3:
                dashed.append(pts)
    pickle.dump((segs, tx, hs), open(os.path.join(work, "cache.pkl"), "wb"))
    U = unary_union([Polygon(r).buffer(0) for v in H.values() for r in v if len(r) >= 3])
    lone = []
    for r in dashed:
        p = Polygon(r).buffer(0)
        if p.area > 0.03 and p.intersection(U).area < 0.3 * p.area: lone.append(list(p.exterior.coords))
    pickle.dump((lone, dict(H)), open(os.path.join(work, "hatch.pkl"), "wb"))
    return tx, H, lone


# ---------------------------------------------------------------- 6) إعدادات قراءة العناصر (تلقائي)
def members_config(work, wins, tx, H, lone):
    import slab_extractor as SX
    from shapely.geometry import Polygon, Point
    RE = re.compile(r"\(\s*(\d{2,4})\s*(?:/\s*\d{2,4}\s*)?[*xX×]\s*(\d{2,5})\s*\)")
    ws = [int(m.group(1)) for t, p, h in tx for m in [RE.search(t)] if m]
    lbl_div = 100 if ws and statistics.median(ws) < 100 else 1000
    # المفتاح المرسوم (نص CONTINUOUS/PLANTED/STOPPED جنب عينة هاتش) له الأولوية
    env = {"DXF": "m.dxf", "WINS": "wins.json"}
    leg = step("members.py", "--legend-only", env=env, cwd=work, check=False)
    m = re.search(r"LEGEND (\{.*\})", leg)
    legmap = json.loads(m.group(1)) if m else {}
    source = "legend"
    extra = []
    inwin = lambda p: any(w[0] <= p.x <= w[2] and w[1] <= p.y <= w[3] for w in wins.values())
    colpat = collections.Counter(); polys = collections.defaultdict(list)
    for pat, rings in H.items():
        for r in rings:
            if len(r) < 3: continue
            g = Polygon(r).buffer(0)
            if g.is_empty or not inwin(g.representative_point()): continue
            L, S = SX._rect_dims(g)
            if 0.03 <= g.area <= 3.0 and S >= 0.12: colpat[pat] += 1; polys[pat].append(g)
    if not legmap:
        source = "derived"
        if colpat:
            main = colpat.most_common(1)[0][0]; legmap[main] = "continuous"
            from shapely.ops import unary_union
            M = unary_union(polys[main])
            planted_pts = [Point(p) for t, p, h in tx if re.search(r"PLANTED", t, re.I)]
            outl = []
            for z in wins:
                try: outl.append(Polygon(json.load(open(os.path.join(work, f"{z}_res.json")))["slabs"][0]["outline"]).buffer(0))
                except Exception: pass
            SL = unary_union(outl) if outl else None
            band = unary_union([o.exterior.buffer(0.6) for o in outl if not o.is_empty]) if outl else None

            def edge_frac(pat):
                if SL is None: return 0.0
                g = unary_union([Polygon(r).buffer(0) for r in H[pat] if len(r) >= 3]).intersection(SL.buffer(0.6))
                return g.intersection(band).area / g.area if g.area > 0.5 else 0.0
            for pat, n in colpat.items():
                if pat == main: continue
                ov = sum(1 for g in polys[pat] if g.intersection(M).area >= 0.8 * g.area) / max(len(polys[pat]), 1)
                # ملاحظات "Planted" جنب هاتش النمط ده = النمط كله مزروع (قبل فحص التراكب: العمود المزروع ممكن
                # يبقى فوق هاتش) - بس لو أغلب عناصر النمط جنبها ملاحظة. ملاحظة جنب حتة واحدة من نمط كبير
                # (حيطة البدروم المحيطة) بتخص العمود اللي بتشاور عليه بس (planted_notes.py)، مش النمط كله.
                near = sum(1 for g in polys[pat] if any(g.distance(q) <= 3.0 for q in planted_pts))
                if planted_pts and near >= 0.6 * len(polys[pat]):
                    legmap[pat] = "planted"
                elif ov >= 0.7: legmap[pat] = "stopped"          # شبكة فوق التعبئة = موقوف تحت السقف
                # نمط تاني ماشي على حد البلاطة (≥ 70% منه في شريط 0.6 م حوالين الحد) وعناصره تخينة (≥ 200 مم)
                # = حيطة خرسانة محيطة (حيطة البدروم): ركيزة. الحوائط المباني جوه البلاطة مش بتتحسب.
                elif ov < 0.3 and len(polys[pat]) >= 3 and edge_frac(pat) >= 0.7 and \
                        statistics.median(SX._rect_dims(g)[1] for g in polys[pat]) >= 0.2:
                    legmap[pat] = "continuous"
            # عمود مزروع مرسوم بو-تاي (مثلثين) من النمط المزروع
            for pat, k in legmap.items():
                if k != "planted": continue
                U = unary_union([Polygon(r).buffer(0.02) for r in H[pat] if len(r) >= 3])
                for g in getattr(U, "geoms", [U]):
                    q = g.buffer(-0.02).minimum_rotated_rectangle
                    if 0.05 <= q.area <= 2.5 and g.buffer(-0.02).area < 0.8 * q.area:
                        extra.append({"poly": list(q.exterior.coords), "type": "planted", "src": "bow-tie"})
    # أعمدة تحت البلاطة مرسومة متقطع من غير هاتش = ركايز موقوفة - بس لو الرسمة مالهاش مفتاح بيعرّف
    # الموقوف (لو فيه مفتاح، الخطوط المتقطعة حاجة تانية: كمرات تحت/إسقاط)
    for r in ([] if (source == "legend" and "stopped" in legmap.values()) else lone):
        p = Polygon(r).buffer(0); L, S = SX._rect_dims(p)
        if p.area / max(p.minimum_rotated_rectangle.area, 1e-9) >= 0.85 and 0.15 <= S and L <= 2.0:
            extra.append({"poly": list(p.exterior.coords), "type": "stopped", "src": "dashed"})
    json.dump(extra, open(os.path.join(work, "extra.json"), "w"))
    cfg = {"DXF": "m.dxf", "WINS": "wins.json", "LBL_DIV": str(lbl_div), "LEGMAP": json.dumps(legmap),
           "OVERLAY": "1", "EXTRA_ELEMS": "extra.json", "UNLABELLED": "1"}
    # تسميات بالعلامة بس (EB1, B10) بتتقري كمرات بس لو الرسمة كمراتها متسمية كده (مفيش قطاعات غالبًا)؛
    # في رسمة كمراتها بقطاعات، نص زي CA1 ده ملاحظة مش كمرة
    MARK = re.compile(r"[A-Z]{1,4}\d{1,3}(-[A-Z])?")
    n_mark = sum(1 for t, p, h in tx if MARK.fullmatch(t.strip()) and inwin(Point(p)))
    if n_mark > len(ws): cfg["MARK_RE"] = MARK.pattern
    return cfg, {"label_unit": "cm" if lbl_div == 100 else "mm", "sized_labels": len(ws), "mark_only_labels": n_mark,
                 "mark_only_used": "MARK_RE" in cfg, "legend": legmap, "legend_source": source,
                 "extra_elements": collections.Counter(x["src"] for x in extra)}


# ---------------------------------------------------------------- مساعدات الشيت
_DOC = None


def extract(work, tag, win, wins=None, grow=True):
    """حد البلاطة جوه إطار الشيت. لو خطوط طويلة كتير بتعدّي ضلع من الإطار (المسقط أكبر من فقاعات
    المحاور) الضلع ده بيتوسع 3 م كل مرة لحد 15 م، ومايعدّيش نص المسافة للشيت اللي جنبه.
    grow=False: الشباك محسوب من الرسم نفسه (صف قسم، أو مبنى منفصل) - مابيكبرش، عشان مايدخلش إطار الموقع."""
    import ezdxf, slab_extractor as SX
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    segs = pickle.load(open(os.path.join(work, "cache.pkl"), "rb"))[0]
    # خطوط المحاور (طرفها عند فقاعة) بتعدّي الإطار دايمًا - مابتتحسبش
    bub = json.load(open(os.path.join(work, "bubbles.json"))) if os.path.exists(os.path.join(work, "bubbles.json")) else []
    from shapely.geometry import MultiPoint
    B = MultiPoint(bub).buffer(1.5) if bub else None
    L = [LineString(s) for s in segs if math.dist(*s) >= 1.0 and not (B is not None and (B.contains(Point(s[0])) or B.contains(Point(s[1]))))]
    tree = STRtree(L)
    win = list(win)
    lim = [15.0] * 4
    for k, w in (wins or {}).items():
        if k == tag: continue
        oy = min(win[3], w[3]) > max(win[1], w[1]); ox = min(win[2], w[2]) > max(win[0], w[0])
        if oy and w[2] <= win[0]: lim[0] = min(lim[0], (win[0] - w[2]) / 2)
        if oy and w[0] >= win[2]: lim[2] = min(lim[2], (w[0] - win[2]) / 2)
        if ox and w[3] <= win[1]: lim[1] = min(lim[1], (win[1] - w[3]) / 2)
        if ox and w[1] >= win[3]: lim[3] = min(lim[3], (w[1] - win[3]) / 2)
    grown = [0.0] * 4
    for _ in range(5 if grow else 0):
        sides = [LineString([(win[0], win[1]), (win[0], win[3])]), LineString([(win[0], win[1]), (win[2], win[1])]),
                 LineString([(win[2], win[1]), (win[2], win[3])]), LineString([(win[0], win[3]), (win[2], win[3])])]
        cross = [sum(1 for k in tree.query(sd) if L[int(k)].intersects(sd)) for sd in sides]
        grew = False
        for k_, sgn in ((0, -1), (1, -1), (2, 1), (3, 1)):
            if cross[k_] >= 6 and grown[k_] + 3.0 <= lim[k_]:
                win[k_] += sgn * 3.0; grown[k_] += 3.0; grew = True
        if not grew: break
    global _DOC
    if _DOC is None or _DOC[0] != work:
        _DOC = (work, ezdxf.readfile(os.path.join(work, "m.dxf")))
    doc = _DOC[1]
    v = SX.PlanView(name=tag, title=tag, window=tuple(win), source="struct")
    r = SX.extract_slab(doc, v, log=lambda *a, **k: None)
    res = {"tag": tag, "window": list(win), "slabs": [{"outline": [tuple(p) for p in r.outline]}],
           "openings": [{"poly": [tuple(p) for p in o.poly], "kind": o.kind, "status": o.status} for o in r.openings],
           "parts": [list(b) for b in r.parts]}
    json.dump(res, open(os.path.join(work, f"{tag}_res.json"), "w"))
    json.dump({"segs": [[list(a), list(b)] for a, b in r.segs]}, open(os.path.join(work, f"{tag}_geo.json"), "w"))
    return r.area


def split_xvoid_parts(work, tag):
    """فراغات X الكبيرة: البلاطة ناقصها؛ كل حتة منفصلة = بلاطة لوحدها، والفراغ اللي جواها = فتحة."""
    from shapely.geometry import Polygon, Point
    X = json.load(open(os.path.join(work, f"{tag}_xvoids.json")))
    R = json.load(open(os.path.join(work, f"{tag}_res.json"))); g = json.load(open(os.path.join(work, f"{tag}_geo.json")))["segs"]
    V = [Polygon(v).buffer(0) for v in X["voids"]]
    parts = sorted([Polygon(p) for p in X["parts"]], key=lambda p: -p.area)
    if not V: return [tag]
    tags = []
    for i, q in enumerate(parts):
        t = tag if len(parts) == 1 else f"{tag}_{chr(65 + i)}"
        ext = q.buffer(0)
        ops = [o for o in R["openings"] if ext.contains(Polygon(o["poly"]).representative_point()) and
               not any(v.contains(Polygon(o["poly"]).representative_point()) for v in V)]
        for v in V:
            if ext.contains(v.representative_point()):
                z = v.intersection(ext); z = max(getattr(z, "geoms", [z]), key=lambda k: k.area)
                ops.append({"poly": list(z.exterior.coords)[:-1], "kind": "X", "status": "ok", "src": "x-void"})
        json.dump({**R, "tag": t, "slabs": [{"outline": list(ext.exterior.coords)[:-1]}], "openings": ops},
                  open(os.path.join(work, f"{t}_res.json"), "w"))
        json.dump({"segs": [s for s in g if ext.buffer(1).contains(Point(s[0]))]}, open(os.path.join(work, f"{t}_geo.json"), "w"))
        tags.append(t)
    return tags


def zone_windows(work, tags, margin=1.0):
    from shapely.geometry import Polygon
    W = {}
    for t in tags:
        b = Polygon(json.load(open(os.path.join(work, f"{t}_res.json")))["slabs"][0]["outline"]).bounds
        W[t] = [b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin]
    return W


# ---------------------------------------------------------------- الصور
def draw(out, tags, title):
    import ezdxf, matplotlib
    matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from shapely.geometry import Polygon
    C = {"PT-Clean-Openings": "#e33", "PT-Clean-Columns": "#b00", "PT-Clean-Walls": "#070", "PT-Clean-Beams": "#23c",
         "PT-Clean-Columns-Above": "m", "PT-Clean-Walls-Above": "m", "PT-Clean-Drops": "orange"}
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    for t in tags:
        d = ezdxf.readfile(os.path.join(out, f"{t}_slab_clean.dxf")); msp = d.modelspace()
        xs_ = [v[0] / 1000 for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "PT-Clean-Boundary" for v in e.get_points()]
        ys_ = [v[1] / 1000 for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "PT-Clean-Boundary" for v in e.get_points()]
        w, h = max(xs_) - min(xs_), max(ys_) - min(ys_); k = 16 / max(w, h, 1)
        fig, ax = plt.subplots(figsize=(max(8, w * k) + 2, max(8, h * k) + 1.5)); area = 0
        for e in msp:
            if e.dxftype() == "LWPOLYLINE":
                L = e.dxf.layer; p = [(v[0] / 1000, v[1] / 1000) for v in e.get_points()]; p.append(p[0])
                xs = [q[0] for q in p]; ys = [q[1] for q in p]
                if L == "PT-Clean-Boundary": ax.fill(xs, ys, color="#eef3fb", zorder=0); ax.plot(xs, ys, "k-", lw=1.6); area = Polygon(p).area
                elif L == "PT-Clean-Loads": ax.plot(xs, ys, color="teal", lw=0.8, ls="--", zorder=1)      # حدود مناطق الأحمال بس
                else: ax.fill(xs, ys, color=C[L], alpha=0.7 if L != "PT-Clean-Openings" else 0.4, lw=0, zorder=2); ax.plot(xs, ys, color=C[L], lw=0.6)
            elif e.dxftype() == "TEXT":
                if e.dxf.layer == "PT-Clean-Beams":
                    ax.text(e.dxf.insert.x / 1000, e.dxf.insert.y / 1000, e.dxf.text, fontsize=6, color="navy", rotation=e.dxf.rotation, zorder=5)
                else:
                    ax.text(e.dxf.insert.x / 1000, e.dxf.insert.y / 1000, e.dxf.text, fontsize=8, color="crimson", zorder=5)
        ax.legend(handles=[Patch(color=c, label=n) for c, n in [("#b00", "columns"), ("m", "above slab (planted)"), ("#070", "walls"),
                                                                   ("#23c", "beams"), ("#e33", "openings"), ("orange", "drops / zones / pour strips")]],
                  loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=10)
        ax.set_title(f"{title} - {t} ({area:.0f} m²)", fontsize=14); ax.set_aspect("equal"); ax.axis("off")
        fig.savefig(os.path.join(out, "images", f"{t}.png"), dpi=70, bbox_inches="tight"); plt.close(fig)



def draw_floors(out, work, tags, sheet_of):
    """صورة الدور كله (كل زوناته فوق خطوط الرسمة نفسها) - الـ checklist قبل التسليم (FLOW 11): بلاطة ناقصة،
    فاصل ماقطعش، مبنى معكوس ناقصه فتحة بيبانوا هنا ومابيبانوش في صورة زون زون."""
    import matplotlib
    matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from shapely.geometry import Polygon
    floors = collections.defaultdict(list)
    for t in tags:
        floors[re.sub(r"-B\d+$", "", sheet_of.get(t, t))].append(t)
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    cm = plt.get_cmap("Pastel1")
    for fl, zs in floors.items():
        fig, ax = plt.subplots(figsize=(22, 12))
        seen = set()
        for t in zs:
            sh = sheet_of.get(t, t)
            gf = os.path.join(work, f"{sh}_geo.json")
            if sh not in seen and os.path.exists(gf):
                seen.add(sh)
                for a, b in json.load(open(gf))["segs"]:
                    ax.plot([a[0], b[0]], [a[1], b[1]], color="#bbb", lw=0.25, zorder=0)
        for i, t in enumerate(zs):
            R = json.load(open(os.path.join(work, f"{t}_res_c.json")))
            g = Polygon(R["slabs"][0]["outline"]).buffer(0)
            if g.is_empty:
                continue
            g = max(getattr(g, "geoms", [g]), key=lambda q: q.area)
            ax.fill(*g.exterior.xy, color=cm(i % 9), alpha=0.75, zorder=1); ax.plot(*g.exterior.xy, "k-", lw=1.1, zorder=3)
            for o in R.get("openings", []):
                q = Polygon(o["poly"])
                ax.fill(*q.exterior.xy, color="w", zorder=2); ax.plot(*q.exterior.xy, color="#e33", lw=0.5, zorder=3)
            for z in R.get("level_zones") or []:
                ax.plot(*Polygon(z["poly"]).exterior.xy, "--", color="purple", lw=0.6, zorder=3)
            mf = os.path.join(work, f"{t}_members_c.json")
            if os.path.exists(mf):
                M = json.load(open(mf))
                for c in M.get("cols", []):
                    ax.fill(*zip(*c["rect"]["corners"]), color="k", zorder=4)
                for b in M.get("beams", []):
                    ax.plot([b["p1"][0], b["p2"][0]], [b["p1"][1], b["p2"][1]], color="#23c", lw=0.5, zorder=3)
            c = g.representative_point(); ml = R.get("main_level_m")
            lab = t[len(fl):].lstrip("-_") or t
            ax.text(c.x, c.y, f"{lab}\n{g.area:.0f} m²" + (f"\n{ml:+.2f}" if ml is not None else ""), fontsize=8,
                    ha="center", weight="bold", zorder=6)
        ax.set_aspect("equal"); ax.axis("off")
        ax.set_title(f"{fl}: {len(zs)} zone(s) over the drawing (grey) - dashed purple = level zones, red = openings", fontsize=13)
        fig.savefig(os.path.join(out, "images", f"_floor_{fl}.png"), dpi=70, bbox_inches="tight"); plt.close(fig)

# ---------------------------------------------------------------- الأمر
def run(src, out, sheets_json=None, keep_work=False, drop_t=None):
    out = os.path.abspath(out); work = os.path.join(out, "work"); os.makedirs(work, exist_ok=True)
    open(os.path.join(work, "pipeline.log"), "w").close()
    report = {"input": os.path.basename(src), "steps": {}, "review": []}
    import ezdxf
    raw = to_dxf(src, work)
    scale, why = detect_scale(raw); report["steps"]["units"] = why; log("units:", why)
    step("prep_dxf.py", raw, os.path.join(work, "m.dxf"), scale, cwd=work)
    tx, H, lone = build_caches(work)
    # 3) الشيتات
    import sheets as SH
    if sheets_json:
        wins = {k: tuple(v) for k, v in json.load(open(sheets_json)).items()}
    else:
        _doc = ezdxf.readfile(os.path.join(work, "m.dxf"))
        wins = dict(SH.detect(_doc, log=log))
        json.dump(SH.grid_bubbles(_doc), open(os.path.join(work, "bubbles.json"), "w"))
    report["steps"]["sheets"] = {k: [round(v, 1) for v in w] for k, w in wins.items()}
    json.dump(wins, open(os.path.join(work, "wins.json"), "w"))
    # 4) البلاطة والفتحات لكل شيت
    tags = []; sheet_of = {}
    # شبابيك المباني المنفصلة (-B1..) محسوبة من الحتة نفسها فمابتكبرش. صفوف الأقسام بتكبر عادي: الأرضي في
    # HDB سقف واحد حده الخطوط الخارجية للموقع كله (المستخدم)، وده برّه عرض الرسم الصغير بنص متر.
    fixed = set()
    section = not sheets_json and getattr(SH, "LAST_SOURCE", None) == "section"
    # إطار فيه كذا مبنى منفصل (أبراج جنب بعض): كل مبنى شيت لوحده (-B1, -B2... من فوق لتحت، شمال ليمين)
    for t, w in list(wins.items()):
        extract(work, t, w, wins, grow=t not in fixed)
        parts = json.load(open(os.path.join(work, f"{t}_res.json"))).get("parts") or []
        if len(parts) >= 2:
            parts.sort(key=lambda b: (-round((b[1] + b[3]) / 2, -1), b[0]))
            del wins[t]
            for k, b in enumerate(parts, 1):
                wins[f"{t}-B{k}"] = (b[0] - 1.5, b[1] - 1.5, b[2] + 1.5, b[3] + 1.5)
                fixed.add(f"{t}-B{k}")
            log(f"sheet {t}: {len(parts)} separate buildings -> {t}-B1..B{len(parts)}")
    # دور فضل سقف واحد (أرضي/بدروم) ودور تاني في نفس القسم اتقسم أبراج: الأبراج مؤشر بس. زونات الأرضي
    # والبدروم بتتحدد من فواصل التمدد (joints.py) - الفاصل ممكن يبقى جوه برج أو بيلم كذا برج، وأعمدة
    # الأرضي أكتر من أعمدة البرج (موقوفة/مكملة) - وأحيانًا السقف كله زون واحدة. مافيش تقسيم بالأبراج.
    if section:
        split_rows = {k.rsplit("-B", 1)[0] for k in wins if re.search(r"-B\d+$", k)}
        for t in [k for k in wins if not re.search(r"-B\d+$", k)]:
            if split_rows:
                n = max(sum(1 for k in wins if k.startswith(r + "-B")) for r in split_rows)
                log(f"sheet {t}: one slab (the floors above have {n} separate buildings) - zones only at expansion joints")
                report["review"].append([t, f"one slab under {n} separate buildings above - zones come only from expansion joints; check the joints"])
    json.dump(wins, open(os.path.join(work, "wins.json"), "w"))
    for t, w in wins.items():
        a = extract(work, t, w, wins, grow=t not in fixed); log(f"sheet {t}: slab {a:.0f} m²")
        step("xvoids.py", t, cwd=work)
        parts = split_xvoid_parts(work, t)
        tags += parts
        for q in parts: sheet_of[q] = t
    json.dump(zone_windows(work, tags), open(os.path.join(work, "wins.json"), "w"))
    for t in tags:
        step("stairs_rebar.py", t, cwd=work)
    step("ramp_label.py", *tags, cwd=work)
    step("core.py", *tags, env={"EXCL": "STEEL"}, cwd=work)
    # 5) الزونات عند فواصل التمدد
    zones = []
    for t in tags:
        o = step("joints.py", t, f"{t}-Z", env={"EXCL": "STEEL"}, cwd=work)
        z = json.load(open(os.path.join(work, f"{t}_zones.json")))
        if len(z) <= 1:
            zones.append(t)
        else:
            zones += z
            for q in z: sheet_of[q] = sheet_of[t]
            report["steps"].setdefault("joints", {})[t] = [l for l in o.splitlines() if l.startswith("joint")]
    wz = zone_windows(work, zones); json.dump(wz, open(os.path.join(work, "wins.json"), "w"))
    log("zones:", zones)
    # 6) العناصر
    cfg, info = members_config(work, wz, tx, H, lone); report["steps"]["members_config"] = info; log("members:", info)
    o = step("members.py", *zones, env=cfg, cwd=work)
    report["steps"]["members"] = [l for l in o.splitlines() if " columns " in l]
    # 7) المنحدر من الخطوط المايلة (لو مفيش منحدر مكتوب)
    # المنحدر من الخطوط المايلة لكل زون (لو لقى منحدر بيضم منحدر النص جواه؛ لو مالقاش، منحدر النص بيفضل)
    step("ramps.py", *zones, cwd=work, check=False)
    step("rescue.py", *zones, cwd=work)
    step("connect.py", *zones, cwd=work)
    step("beam_sanity.py", *zones, env={"SUPPORTS_ONLY": "1"}, cwd=work)
    step("ramp_faces.py", *zones, cwd=work, check=False)
    step("ramp_members.py", *zones, cwd=work, check=False)
    step("planted_notes.py", *zones, cwd=work, check=False)
    # 8) السُمك والدروبات والمناسيب وشرايح الصب
    step("thick_attr.py", raw, scale, *zones, cwd=work, check=False)
    step("thick.py", "m.dxf", *zones, cwd=work, check=False)
    step("drops_notes.py", *zones, env={"DXF": "m.dxf"}, cwd=work, check=False)
    step("drops_dashed.py", *zones, env={"PYTHONPATH": ROOT}, cwd=work, check=False)
    step("drops_boxes.py", *zones, env={"DXF": "m.dxf", **({"DROP_T": str(int(drop_t))} if drop_t else {})}, cwd=work, check=False)
    # سُمك البلاطة المكتوب صراحةً ("PT Slab T=220") بيتكتب مرة للمبنى: الزونات التانية من نفس الشيت
    # اللي مالهاش ملاحظة صريحة بتاخده (بدل أقل T= لقيته جواها) - وبتطلع REVIEW
    # الأول نفس المبنى (الشيت)، وبعدين نفس الدور (صف القسم: كل مباني الدور)
    for level, key in (("building", lambda q: sheet_of.get(q)), ("floor", lambda q: re.sub(r"-B\d+.*$", "", sheet_of.get(q) or q))):
        for sh in set(key(q) for q in zones):
            zs = [q for q in zones if key(q) == sh]
            Rs = {q: json.load(open(os.path.join(work, f"{q}_res_c.json"))) for q in zs}
            ex = {R_.get("slab_t_explicit") for R_ in Rs.values() if R_.get("slab_t_explicit")}
            if len(ex) != 1:
                continue
            v = ex.pop()
            for q, R_ in Rs.items():
                if R_.get("slab_t_explicit"):
                    continue
                if R_.get("slab_thickness_mm") != v:
                    R_.setdefault("review", []).append(["thickness", f"slab thickness {v} mm from the PT slab note of the same {level} "
                                                                      f"(this zone alone would give {R_.get('slab_thickness_mm')})"])
                    R_["slab_thickness_mm"] = v
                R_["slab_t_explicit"] = v
                json.dump(R_, open(os.path.join(work, f"{q}_res_c.json"), "w"))
    step("pourstrips.py", cwd=work, check=False)
    pour = os.path.exists(os.path.join(work, "pourstrips.json")) and json.load(open(os.path.join(work, "pourstrips.json")))
    lvl_env = {"EXCL_POLYS": "pourstrips.json"} if pour else {}
    step("levels.py", "m.dxf", *zones, env=lvl_env, cwd=work, check=False)
    # إعادة بقفل فجوات خطوط حد المنسوب: بس للزون اللي فيها تسميات منسوب مختلفة ومالقتش ولا منطقة
    unres = [t for t in zones if (lambda R: R.get("level_unresolved") and not R.get("level_zones"))(json.load(open(os.path.join(work, f"{t}_res_c.json"))))]
    if unres: step("levels.py", "m.dxf", *unres, env={**lvl_env, "LEVEL_GAP": "1.6"}, cwd=work, check=False)
    # منسوب زون من غير تسمية = منسوب الشيت (لو الشيت كله منسوب واحد)
    for t in zones:
        R = json.load(open(os.path.join(work, f"{t}_res_c.json")))
        if R.get("main_level_m") is None:
            sib = [json.load(open(os.path.join(work, f"{q}_res_c.json"))).get("main_level_m") for q in zones if sheet_of.get(q) == sheet_of.get(t) and q != t]
            sib = {v for v in sib if v is not None}
            if len(sib) == 1:
                R["main_level_m"] = sib.pop(); R.setdefault("review", []).append(["level", f"no level label in this zone - {R['main_level_m']:+.2f} from the rest of the sheet"])
                json.dump(R, open(os.path.join(work, f"{t}_res_c.json"), "w"))
    # 8ب) أنواع الركائز من مقارنة الأدوار (لو الرسمة مالهاش مفتاح وفيه أكتر من دور، زون واحدة لكل دور)
    legmap = info["legend"]
    one_zone = all(sum(1 for q in zones if sheet_of.get(q) == sh) == 1 for sh in set(sheet_of.get(q) for q in zones))
    if info["legend_source"] == "derived" and not ({"stopped", "planted"} & set(legmap.values())) and len(zones) >= 2 and one_zone:
        lv = {t: json.load(open(os.path.join(work, f"{t}_res_c.json"))).get("main_level_m") for t in zones}
        if all(v is not None for v in lv.values()):
            order = sorted(zones, key=lambda t: lv[t])
            report["steps"]["floor_typing"] = step("xtype.py", *order, cwd=work).splitlines()
    # نقطة استئناف: الحالة قبل خطوات التشطيب بتتحفظ، و--resume-from بيكمّل منها (شيت 100+ زون بياخد ساعات)
    st = {"zones": zones, "sheet_of": sheet_of, "wins": {k: list(v) for k, v in wins.items()}, "wz": wz,
          "report": report, "pour": bool(pour)}
    json.dump(st, open(os.path.join(work, "state.json"), "w"), default=str)
    return finish(work, out, st)


FINISH_STEPS = ["stairs_members", "core", "beam_steps", "edge_fit", "beam_merge", "beam_split", "edge_fit2",
                "slab_snap", "region_snap", "loads", "column_gate", "zone_check", "export"]


def finish(work, out, st, start=None):
    """خطوات التشطيب (السلم، الكور، الكمرات، الحد، التلزيق، البوابات، التصدير). start = اسم خطوة من FINISH_STEPS."""
    zones, sheet_of, wins, wz, report = st["zones"], st["sheet_of"], st["wins"], st["wz"], st["report"]
    pour = st.get("pour")
    k0 = FINISH_STEPS.index(start) if start else 0
    # خطوات التشطيب بتعدّل _res_c/_members_c مكانها، فإعادة خطوة على ناتجها بتطبّقها مرتين (HDB/رؤية: الكمرة اللي
    # اتشالت فضلت متشالة بعد تعديل القاعدة). قبل كل خطوة نسخة في work/snap/<step>، و--resume-from بيرجّعها الأول.
    snap_root = os.path.join(work, "snap")

    def _snap_files():
        return [f"{q}{suf}" for q in zones for suf in ("_res_c.json", "_members_c.json")
                if os.path.exists(os.path.join(work, f"{q}{suf}"))]

    if start and k0 > 0:
        d = os.path.join(snap_root, start)
        if os.path.isdir(d):
            for f in os.listdir(d):
                shutil.copy2(os.path.join(d, f), os.path.join(work, f))
            log(f"resume from {start}: zone files restored from the copy taken before that step")
        else:
            log(f"WARNING: no copy from before step {start} (work folder from an older version) - the steps "
                f"run on files the earlier run already changed; for a clean result run the whole conversion")

    def run_(name):
        if FINISH_STEPS.index(name) < k0:
            return False
        d = os.path.join(snap_root, name)
        os.makedirs(d, exist_ok=True)
        for f in _snap_files():
            shutil.copy2(os.path.join(work, f), os.path.join(d, f))
        return True
    _, H = pickle.load(open(os.path.join(work, "hatch.pkl"), "rb"))
    # 9) السلم والكور والكمرة بعرضين وحد البلاطة والفحص
    if run_("stairs_members"): step("stairs_members.py", *zones, env={"PYTHONPATH": ROOT}, cwd=work, check=False)
    if run_("core"): step("core.py", *zones, env={"EXCL": "STEEL", "RES_SUFFIX": "_c"}, cwd=work)
    if run_("beam_steps"): step("beam_steps.py", *zones, cwd=work)
    if run_("edge_fit"): step("edge_fit.py", *zones, cwd=work)
    if run_("beam_merge"): step("beam_merge.py", *zones, cwd=work)
    if run_("beam_split"): step("beam_split.py", *zones, cwd=work)
    # الكمرة الملمومة اتعدلت على المحور (بسنتيمترات): الحد لازم يتظبط على وشها تاني
    if run_("edge_fit2"): step("edge_fit.py", *zones, cwd=work)
    # حد البلاطة على وش الكمرة الطرفية بالظبط (شق الفاصل 3 سم كان بيفضل شريحة) - قبل تلزيق المناطق عليه
    if run_("slab_snap"): step("slab_snap.py", *zones, cwd=work, check=False)
    if run_("region_snap"): step("region_snap.py", *zones, cwd=work)
    # أحمال كل منطقة من مسقط الأحمال (LOADING PLANS) لو موجود - على حد البلاطة النهائي
    if run_("loads"):
        o = step("loads_plan.py", *zones, env={"DXF": "m.dxf"}, cwd=work, check=False)
        report["steps"]["loads"] = [l for l in o.splitlines() if l.strip()][-len(zones) - 2:]
    # بوابة: أعمدة الشيت اللي برّه كل الزونات (مبنى ضاع، جزء اتقص) مابتضيعش في صمت - بتطلع REVIEW
    if run_("column_gate"):
        try:
            from shapely.geometry import Polygon as _P, Point as _Pt
            pts = []
            for rs in H.values():
                for r in rs:
                    if len(r) < 3:
                        continue
                    g = _P(r).buffer(0)
                    if 0.04 <= g.area <= 3.0:
                        b = g.minimum_rotated_rectangle.exterior.coords
                        sides = sorted(math.dist(b[i], b[i + 1]) for i in range(2))
                        if sides[0] >= 0.12 and sides[1] <= 2.5:
                            pts.append((g.centroid.x, g.centroid.y))
            pts = list({(round(x, 2), round(y, 2)) for x, y in pts})
            for sh in sorted(set(sheet_of.values())):
                w = wins.get(sh)
                zs = [q for q in zones if sheet_of.get(q) == sh]
                if not w or not zs:
                    continue
                polys = [_P(json.load(open(os.path.join(work, f"{q}_res_c.json")))["slabs"][0]["outline"]).buffer(0.3) for q in zs]
                # عمود جوه فتحة (كور) أو فراغ X / كوبري حديد (xvoids) مش "بلاطة ناقصة"
                holes = [_P(o["poly"]).buffer(0) for q in zs for o in json.load(open(os.path.join(work, f"{q}_res_c.json"))).get("openings", [])]
                xf = os.path.join(work, f"{sh}_xvoids.json")
                if os.path.exists(xf):
                    holes += [_P(v).buffer(0.5) for v in json.load(open(xf)).get("voids", [])]
                out_ = [p for p in pts if w[0] <= p[0] <= w[2] and w[1] <= p[1] <= w[3] and not any(g.contains(_Pt(p)) for g in polys)
                        and not any(h.contains(_Pt(p)) for h in holes)]
                if out_:
                    msg = (f"{len(out_)} column(s) inside sheet {sh} are outside every zone (e.g. at "
                           f"{', '.join(f'({x:.1f}, {y:.1f})' for x, y in out_[:3])}) - a building or part of the slab may be missing")
                    log("REVIEW: " + msg)
                    report["review"].append([sh, msg])
                    R0 = json.load(open(os.path.join(work, f"{zs[0]}_res_c.json")))
                    R0.setdefault("review", []).append(["columns outside zones", msg])
                    json.dump(R0, open(os.path.join(work, f"{zs[0]}_res_c.json"), "w"))
        except Exception as e:
            log(f"column coverage check skipped: {e}")
    run_("zone_check"); run_("export")          # (نسخة قبلهم برضه، عشان --resume-from zone_check/export)
    chk = step("zone_check.py", *zones, cwd=work, check=False)
    ok = "CHECK OK" in chk
    report["zone_check"] = [l for l in chk.splitlines() if l.strip()]
    # 10) التصدير: كل زونات الشيت بأصل الشيت (الأدوار فوق بعض)
    o_ = {t: [wins[sheet_of[t]][0], wins[sheet_of[t]][1]] if sheet_of.get(t) in wins else [wz[t][0], wz[t][1]] for t in zones}
    json.dump(o_, open(os.path.join(work, "wins_export.json"), "w"))
    exp_env = {"TAGS": " ".join(zones), "ORIGIN": "wins", "WINS_FILE": "wins_export.json", "OUT": out}
    if pour: exp_env["POUR_JSON"] = "pourstrips.json"
    report["steps"]["export"] = step("export_pt.py", env=exp_env, cwd=work).splitlines()
    draw(out, zones, report["input"])
    try:
        draw_floors(out, work, zones, sheet_of)
    except Exception as e:
        log(f"floor images skipped: {e}")
    report["zones"] = zones; report["ok"] = ok
    json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1, ensure_ascii=False, default=str)
    log("DONE", "CHECK OK" if ok else "CHECK FAILED - see report.json")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input"); ap.add_argument("-o", "--out", default="pt_out")
    ap.add_argument("--sheets", help="json {name: [x0,y0,x1,y1]} in metres after unit conversion (skips detection)")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--drop-thickness", type=float, default=None,
                    help="mm - for drop panels drawn with no thickness written (a written thickness always wins)")
    ap.add_argument("--resume-from", choices=FINISH_STEPS,
                    help="continue an earlier run (same -o, --keep-work) from this finishing step")
    a = ap.parse_args(argv)
    if a.resume_from:
        work = os.path.join(os.path.abspath(a.out), "work")
        st = json.load(open(os.path.join(work, "state.json")))
        ok = finish(work, os.path.abspath(a.out), st, a.resume_from)
    else:
        ok = run(a.input, a.out, a.sheets, a.keep_work, a.drop_thickness)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
