# -*- coding: utf-8 -*-
"""سطر الأوامر:

    python -m ptmb plan.dwg -o out --stage dxf            # المرحلة 1 بس: DXF لكل زون
    python -m ptmb plan.dwg -o out --stage both --cpt template.cpt
    python -m ptmb out/ --stage ram --cpt template.cpt   # DXFs جاهزة (فولدر أو ملفات) -> RAM
    python -m ptmb --gui                                  # الشاشة

قبل البناء في RAM بيطبع رسالة التأكيد (السُمك/العمق/المناسيب/الأحمال) وبيسأل - أو --yes.
"""
import argparse
import os
import sys

from . import preflight, settings as SET, stage1


class _PrintJob:
    def log(self, msg, level="info"):
        icons = {"ok": "✔ ", "warn": "⚠ ", "error": "✖ ", "head": ""}
        print(icons.get(level, "  ") + str(msg), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ptmb", description="Drawing -> zone DXFs -> RAM Concept model")
    ap.add_argument("input", nargs="*", help="DWG/DXF drawing, or zone DXFs / their folder for --stage ram")
    ap.add_argument("-o", "--out", help="output folder (default: <drawing>_PT beside it)")
    ap.add_argument("--stage", choices=("dxf", "both", "ram"), default="dxf")
    ap.add_argument("--cpt", help="RAM Concept template (.cpt)")
    ap.add_argument("--api", help="RAM Concept Python API folder")
    ap.add_argument("--slab-t", type=float); ap.add_argument("--drop-t", type=float); ap.add_argument("--beam-d", type=float)
    ap.add_argument("--sdl", type=float); ap.add_argument("--ll", type=float)
    ap.add_argument("--no-loads", action="store_true"); ap.add_argument("--no-strips", action="store_true")
    ap.add_argument("--run", action="store_true", help="analyse after building")
    ap.add_argument("--yes", action="store_true", help="do not ask before building in RAM")
    ap.add_argument("--gui", action="store_true")
    a = ap.parse_args(argv)
    if a.gui or not a.input:
        from . import app
        return app.main()
    data = SET.load()
    for k, v in (("template_cpt", a.cpt), ("api_path", a.api), ("slab_thickness", a.slab_t),
                 ("drop_thickness", a.drop_t), ("beam_depth", a.beam_d), ("sdl", a.sdl), ("live_load", a.ll)):
        if v not in (None, ""):
            data[k] = v
    if a.no_loads:
        data["write_area_loads"] = False
    if a.no_strips:
        data["write_design_strips"] = False
    data["run_analysis"] = bool(a.run)
    job = _PrintJob()
    src = a.input[0]
    out = a.out or (os.path.splitext(src)[0] + "_PT" if os.path.isfile(src) else src)
    if a.stage in ("dxf", "both"):
        rc, zones, _ = stage1.run(src, out, data, log=job.log)
    else:
        zones = []
        for p in a.input:
            zones += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".dxf")] if os.path.isdir(p) else [p]
    info = [preflight.inspect_zone(z) for z in zones]
    lines = preflight.summary(info, data, stage2=a.stage != "dxf")
    print("\n" + "\n".join(lines) + "\n")
    if a.stage == "dxf":
        return 0
    if not a.yes:
        if input("Build the RAM model(s) with these? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled."); return 1
    from . import stage2
    C = stage2.core()
    cj = C.ConsoleJob()
    done, failed = stage2.run(zones, data, cj, os.path.join(out, "RAM"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
