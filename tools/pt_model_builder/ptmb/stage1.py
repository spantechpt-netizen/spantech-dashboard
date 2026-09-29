# -*- coding: utf-8 -*-
"""المرحلة 1: المخطط (DWG/DXF) -> DXF نضيف لكل زون (pt_pipeline).

بيشغّل `python -m pt_pipeline.convert` في process لوحده (اللوج بيطلع سطر سطر، والإيقاف بيقتله).
الناتج: فولدر فيه <ZONE>_slab_clean.dxf + members.csv + report.json + images/.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_reader_dir(configured=""):
    """الفولدر اللي فيه pt_pipeline/convert.py: الإعداد، ثم جنب البرنامج (الـ zip)، ثم الريبو."""
    cands = [configured, os.environ.get("PTMB_READER_DIR", ""),
             os.path.join(HERE, "..", "layerless_reader"),
             os.path.join(HERE, "..", "..", "layerless_reader")]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "pt_pipeline", "convert.py")):
            return os.path.abspath(c)
    return None


def find_dwgread(configured="", reader_dir=None):
    names = ("dwgread.exe", "dwgread")
    cands = [configured, os.environ.get("LIBREDWG_DWGREAD", ""), shutil.which("dwgread") or ""]
    for base in [reader_dir, os.path.join(HERE, "..")]:
        if base:
            for sub in ("", "libredwg", os.path.join("libredwg", "bin")):
                cands += [os.path.join(base, sub, n) for n in names]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def run(src, out_dir, data, log=print, proc_cb=None):
    """
    بترجّع (كود الخروج، [ملفات الزونات]، report). كود 2 = فحص الزونات فشل (الملفات موجودة
    بس فيها غلط معروف - بيتقال في اللوج). proc_cb(p) بياخد الـ process عشان زرار الإيقاف.
    """
    rdir = find_reader_dir(data.get("reader_dir", ""))
    if not rdir:
        raise RuntimeError("pt_pipeline not found - set 'Drawing reader folder' (the folder that has pt_pipeline in it).")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if src.lower().endswith(".dwg"):
        dw = find_dwgread(data.get("dwgread_path", ""), rdir)
        if not dw:
            raise RuntimeError("A DWG needs LibreDWG dwgread - it comes in libredwg\\ inside the zip, "
                               "or set its path in the settings.")
        env["LIBREDWG_DWGREAD"] = dw
    py = data.get("python") or sys.executable
    cmd = [py, "-u", "-m", "pt_pipeline.convert", src, "-o", out_dir]
    if data.get("drop_thickness"):
        cmd += ["--drop-thickness", str(int(float(data["drop_thickness"])))]
    log(f"Stage 1: {os.path.basename(src)} -> zone DXFs in {out_dir}", "head")
    p = subprocess.Popen(cmd, cwd=rdir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    if proc_cb:
        proc_cb(p)
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        if not line or line.startswith("====="):
            continue
        tail = (tail + [line])[-40:]
        if line.startswith("[convert]"):
            log("   " + line[len("[convert]"):].strip(), "info")
    rc = p.wait()
    files = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith("_slab_clean.dxf")) \
        if os.path.isdir(out_dir) else []
    rep = {}
    try:
        rep = json.load(open(os.path.join(out_dir, "report.json"), encoding="utf-8"))
    except Exception:
        pass
    if rc not in (0, 2) or not files:
        for ln in tail[-15:]:
            log("    " + ln, "error")
        raise RuntimeError(f"Stage 1 stopped (code {rc}).")
    if rc == 2:
        log("Zone check FAILED - an element from another zone, an element outside its slab, or a "
            "duplicated beam. Check these before building in RAM:", "warn")
        for ln in rep.get("zone_check") or []:
            if "CHECK" not in ln:
                log("    " + ln, "warn")
    log(f"Stage 1 done: {len(files)} zone file(s).", "ok")
    return rc, files, rep
