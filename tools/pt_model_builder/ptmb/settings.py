# -*- coding: utf-8 -*-
"""الإعدادات: القيم الافتراضية (سُمك البلاطة والدروب وعمق الكمرة) والأحمال ومسارات RAM.

بتتحفظ في ~/.pt_model_builder.json. أول مرة بتبدأ من إعدادات Auto PT Suite لو موجودة
(~/.auto_pt_suite.json) عشان نفس الأرقام اللي المكتب شغال بيها.
"""
import json
import os

PATH = os.path.join(os.path.expanduser("~"), ".pt_model_builder.json")
AUTOPT_PATH = os.path.join(os.path.expanduser("~"), ".auto_pt_suite.json")

DEFAULTS = {
    # قيم افتراضية - بتتاخد بس لما الرسمة مافيهاش القيمة، ورسالة التأكيد بتقول ده
    "slab_thickness": 250.0,      # mm
    "drop_thickness": 400.0,      # mm
    "beam_depth": 600.0,          # mm - العرض من المخطط دايمًا
    # الأحمال
    "write_area_loads": True,
    "sdl": 2.0,                   # kN/m²
    "live_load": 2.0,             # kN/m²
    "write_wall_loads": False,
    "arch_wall_density": 14.0,    # kN/m³
    "arch_wall_height": 3.0,      # m
    "arch_wall_opening_factor": 1.0,
    "write_edge_load": False,
    "edge_line_load": 0.0,        # kN/m
    # خطوط الركايز وشرايح التصميم
    "write_design_strips": True,
    # RAM
    "template_cpt": "",
    "api_path": "",
    "run_analysis": False,
    "mesh_size": 0.0,             # 0 = اللي في الـ template
    # المرحلة 1
    "reader_dir": "",             # الفولدر اللي فيه pt_pipeline (tools/layerless_reader)
    "dwgread_path": "",
    "python": "",
}

#  المفاتيح اللي بتتاخد من إعدادات Auto PT Suite أول مرة
_FROM_AUTOPT = ("slab_thickness", "drop_thickness", "beam_depth", "sdl", "live_load",
                "write_area_loads", "write_wall_loads", "arch_wall_density", "arch_wall_height",
                "arch_wall_opening_factor", "write_edge_load", "edge_line_load",
                "write_design_strips", "api_path", "dwgread_path")


def load():
    data = dict(DEFAULTS)
    if os.path.isfile(PATH):
        try:
            data.update({k: v for k, v in json.load(open(PATH, encoding="utf-8")).items() if k in DEFAULTS})
            return data
        except Exception:
            pass
    if os.path.isfile(AUTOPT_PATH):
        try:
            a = json.load(open(AUTOPT_PATH, encoding="utf-8"))
            for k in _FROM_AUTOPT:
                if k in a and a[k] not in ("", None):
                    data[k] = type(DEFAULTS[k])(a[k]) if not isinstance(DEFAULTS[k], bool) else \
                        (a[k] if isinstance(a[k], bool) else str(a[k]).lower() in ("1", "true", "yes"))
        except Exception:
            pass
    return data


def save(data):
    try:
        json.dump({k: data.get(k, v) for k, v in DEFAULTS.items()}, open(PATH, "w", encoding="utf-8"), indent=1)
    except Exception:
        pass


def params(data, core):
    """TendonDesignParams بتاع البرنامج من الإعدادات دي (السُمك والعمق والأحمال والشرايح)."""
    kw = {k: data[k] for k in ("slab_thickness", "drop_thickness", "beam_depth", "sdl", "live_load",
                               "write_area_loads", "write_wall_loads", "arch_wall_density",
                               "arch_wall_height", "arch_wall_opening_factor", "write_edge_load",
                               "edge_line_load", "write_design_strips")}
    # السُمك اللي في الـ template مايغلبش السُمك اللي في الرسمة أو الافتراضي اللي هنا
    kw["thickness_from_model"] = False
    return core.TendonDesignParams(**kw)
