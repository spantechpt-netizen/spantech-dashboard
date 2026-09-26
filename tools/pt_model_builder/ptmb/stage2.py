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

from . import settings as SET


def core():
    try:
        from . import ram_core
    except ImportError as e:
        raise RuntimeError("ram_core.py is missing - run build_core.py on the Auto PT Suite file once "
                           "(it comes ready inside the delivered zip).") from e
    return ram_core


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
        if params.write_area_loads:
            C.write_area_loads_to_ram(s, site, params, job)
            if site.get("line_loads"):
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
