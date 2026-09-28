# -*- coding: utf-8 -*-
"""المرحلة 2: DXF الزون النضيف -> موديل RAM Concept.

نفس خطوات Auto PT Suite (نفس الكود، من ram_core.py) من غير كابلات:
  قراءة الـ DXF (السُمك والمنسوب والأولوية والمقاسات المكتوبة) -> تنضيف الهندسة -> فتح الـ template
  -> دكتور الشبكة + بناء المنشأ -> الأحمال (SDL/LL، حوائط، حمل الحرف) -> خطوط الركايز وشرايح
  التصميم -> حفظ نسخة جديدة (الـ template مابيتلمسش) -> (اختياري) تحليل + إعادة المحاولة لو RAM رفض الشبكة.
اللي مش مكتوب في الرسمة بياخد الافتراضي (settings)، والمنسوب اللي مش موجود = السقف كله منسوب واحد.
"""
import datetime
import os

from . import preflight, settings as SET


def core():
    try:
        from . import ram_core
    except ImportError as e:
        raise RuntimeError("ram_core.py is missing - run build_core.py on the Auto PT Suite file once "
                           "(it comes ready inside the delivered zip).") from e
    return ram_core


def _pieces(g):
    """مضلعات من غير خروم (RAM بياخد الحد الخارجي بس)."""
    from shapely.geometry import LineString
    from shapely.ops import split
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.geom_type != "Polygon" or p.area < 0.5:
            continue
        if not p.interiors:
            out.append(p); continue
        cx = p.interiors[0].centroid.x
        for q in split(p, LineString([(cx, p.bounds[1] - 1), (cx, p.bounds[3] + 1)])).geoms:
            out += _pieces(q)
    return out


def write_load_areas(C, session, site, params, job, areas):
    """
    أحمال مسقط الأحمال (اقتراح المستخدم، HDB): الحمل الافتراضي على السقف كله (حدود البلاطة، نفس
    write_area_loads_to_ram)، وكل منطقة في المسقط بياخد **الفرق** بس: موجب لو حملها أكبر، سالب لو أصغر.
    كده مافيش حتة في السقف من غير حمل، ومافيش تقطيع للباقي. لو الأحمال الافتراضية مش متعلّمة: كل منطقة
    بحملها كامل والباقي من غير حمل (زي ما المهندس اختار).
    """
    from shapely.geometry import Polygon
    P2, Poly2 = session.api["Point2D"], session.api["Polygon2D"]
    sign = C.down_sign(session, job)
    base = (float(params.sdl), float(params.live_load)) if params.write_area_loads else (0.0, 0.0)
    if params.write_area_loads:
        C.write_area_loads_to_ram(session, site, params, job)
    todo = [(Polygon(a["poly"]).buffer(0), a["sdl"], a["ll"], a["usage"]) for a in areas]
    n = {"sdl": 0, "live": 0}
    for key, causes, what, idx in (("sdl", C.DEAD_CAUSE_NAMES, "Superimposed dead load", 0),
                                   ("live", C.LIVE_CAUSE_NAMES, "Live load", 1)):
        layer = C.pick_loading_layer(session, causes, job, what)
        if layer is None:
            continue
        for g, sd, ll, use in todo:
            v = (sd, ll)[idx] - base[idx]
            if abs(v) < 0.005:
                continue                          # نفس الافتراضي: الحمل اللي على السقف كفاية
            for piece in _pieces(g):
                try:
                    elem = layer.add_area_load(Poly2([P2(x, y) for x, y in list(piece.exterior.coords)[:-1]]))
                except Exception as e:
                    job.error(f"{what} ({use}): could not add the area load: {e}"); continue
                first = [None]
                # _set_area_load بتاخد القيمة المطلقة: الفرق السالب = الإشارة معكوسة
                if elem is not None and C._set_area_load(elem, abs(v), job, first, sign if v > 0 else -sign):
                    n[key] += 1
                else:
                    job.error(f"{what} ({use}): the value {v:+g} was rejected ({first[0] or 'no reason given'}).")
    by = {}
    for g, sd, ll, use in todo:
        k = (use, sd, ll); by[k] = by.get(k, 0.0) + g.area
    if params.write_area_loads:
        job.ok(f"Loads: SIDL {base[0]:g} + LL {base[1]:g} kN/m² on the whole slab, and the loading-plan "
               f"areas carry the difference ({n['sdl']} SIDL and {n['live']} LL area load(s), + or -):")
    else:
        job.ok(f"Loads from the loading plan: {n['sdl']} SIDL and {n['live']} LL area load(s) "
               f"(default area loads are off - the rest of the slab has none):")
    for (use, sd, ll), ar in by.items():
        job.info(f"    {use}: SIDL {sd:g} + LL {ll:g} kN/m² over {ar:.0f} m²"
                 + (f"  (written as {sd - base[0]:+g} / {ll - base[1]:+g} on top of the slab load)" if params.write_area_loads else ""))
    return n


def build_zone(dxf, data, job, out_dir, session_cls=None):
    """زون واحدة -> ملف .cpt. بترجّع المسار أو None."""
    C = core()
    params = SET.params(data, C)
    errs = params.validate() if hasattr(params, "validate") else []
    if errs:
        for e in errs:
            job.error(str(e))
        return None
    zone = os.path.basename(dxf).replace("_slab_clean.dxf", "").replace(".dxf", "")
    job.log("═" * 60, "head"); job.log(f"  RAM model: {zone}", "head"); job.log("═" * 60, "head")
    layers, _ = C.scan_dxf_layers(dxf)
    if not layers:
        job.error("The file has no entities."); return None
    roles = {l["name"]: l["role"] for l in layers}
    # ليّر الأحمال مش شكل إنشائي: مضلعاتها لو اتقرت "auto" بتبقى بلاطات، ونص المنسوب (LEVEL SE=) بيروح لأصغر
    # مضلع حواليه = مضلع الحمل مش منطقة المنسوب. الأحمال بتتقري لوحدها (preflight.inspect_zone -> write_load_areas).
    for n in roles:
        if n.upper() == "PT-CLEAN-LOADS":
            roles[n] = "ignore"
    site = C.parse_dxf(dxf, roles, list(C.UNIT_CHOICES)[0], job)
    if not site.get("boundary"):
        job.error("No valid slab boundary."); return None
    C.wall_udl_check(site, params, job)
    C.sanitize_site(site, job)
    C.mark_band_beams(site, params, job)
    template = data.get("template_cpt") or ""
    if not os.path.isfile(template):
        job.error("Set the RAM Concept template (.cpt) - the model is built into a copy of it."); return None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(out_dir, f"{zone}_{stamp}.cpt")
    Session = session_cls or C.RamSession
    with Session(job, api_path=data.get("api_path") or None) as s:
        s.open(template)
        C.build_structure_in_ram(s, site, params, job)
        areas = preflight.inspect_zone(dxf).get("load_areas") or []
        if areas:
            write_load_areas(C, s, site, params, job, areas)
        elif params.write_area_loads:
            C.write_area_loads_to_ram(s, site, params, job)
        if params.write_area_loads and site.get("line_loads"):
            C.write_adm_line_loads_to_ram(s, site, params, job)
        if params.write_wall_loads:
            C.write_wall_loads_to_ram(s, site, params, job)
        if params.write_edge_load and float(params.edge_line_load or 0) > 0:
            C.write_edge_loads_to_ram(s, site, params, job)
        if params.write_design_strips:
            C.write_design_strips_to_ram(s, site, params, job, template)
        if not C.safe_save(s, out, job):
            job.error("The model could not be saved."); return None
        if data.get("run_analysis"):
            r = C.run_model_analysis(s, job, mesh_size=float(data.get("mesh_size") or 0) or None)
            if isinstance(r, dict) and not r.get("ok", True):
                job.warn("The analysis did not finish - the model is saved without results; the log says where.")
            C.safe_save(s, out, job)
    job.ok(f"Saved: {out}")
    return out


def run(dxfs, data, job, out_dir, session_cls=None):
    os.makedirs(out_dir, exist_ok=True)
    done, failed = [], []
    for d in dxfs:
        try:
            r = build_zone(d, data, job, out_dir, session_cls)
            (done if r else failed).append(r or d)
        except core().CancelledError:
            job.warn("Stopped."); break
        except Exception as e:
            failed.append(d); job.error(f"{os.path.basename(d)}: {type(e).__name__}: {e}")
    job.log(f"RAM: {len(done)} model(s) saved, {len(failed)} failed.", "ok" if not failed else "warn")
    return done, failed
