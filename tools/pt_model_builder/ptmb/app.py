# -*- coding: utf-8 -*-
"""PT Model Builder - الشاشة.

  1) Drawing -> zone DXFs            المرحلة 1 بس
  2) Drawing -> zone DXFs -> RAM     المرحلتين ورا بعض (اختيار الزونات + رسالة التأكيد في النص)
  3) Zone DXFs -> RAM                DXFs جاهزة من قبل

قبل أي بناء في RAM: رسالة تأكيد بالسُمك/العمق اللي مش مكتوب والافتراضي اللي هياخده، والمناسيب
(أو "السقف كله منسوب واحد")، والأحمال، وشرايح التصميم.
"""
import os
import queue
import subprocess
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, preflight, settings as SET, stage1

MODES = {"dxf": "1) Drawing → zone DXFs",
         "both": "2) Drawing → zone DXFs → RAM model",
         "ram": "3) Zone DXFs → RAM model"}


class _Stop(Exception):
    pass


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"PT Model Builder {__version__}")
        self.data = SET.load()
        self.q = queue.Queue()
        self.worker = None
        self.proc = None
        self.job = None
        self.stop_flag = threading.Event()
        self.v = {}
        self._build()
        self.root.after(100, self._pump)

    # ------------------------------------------------------------ الشاشة
    def _var(self, key, kind=tk.StringVar):
        val = self.data.get(key, "")
        v = kind(value=val if kind is not tk.StringVar else ("" if val is None else str(val)))
        self.v[key] = v
        return v

    def _row(self, parent, r, label, key, browse=None, width=46):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(parent, textvariable=self._var(key), width=width).grid(row=r, column=1, sticky="we", padx=4)
        if browse:
            ttk.Button(parent, text="…", width=3, command=browse).grid(row=r, column=2, padx=2)

    def _num(self, parent, r, c, label, key, unit):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=4, pady=2)
        ttk.Entry(parent, textvariable=self._var(key), width=8).grid(row=r, column=c + 1, sticky="w")
        ttk.Label(parent, text=unit).grid(row=r, column=c + 2, sticky="w", padx=(2, 10))

    def _chk(self, parent, r, c, label, key, span=3):
        ttk.Checkbutton(parent, text=label, variable=self._var(key, tk.BooleanVar)).grid(
            row=r, column=c, columnspan=span, sticky="w", padx=4, pady=2)

    def _build(self):
        f = ttk.Frame(self.root, padding=8); f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        io = ttk.LabelFrame(f, text="Files", padding=6); io.grid(row=0, column=0, sticky="we")
        io.columnconfigure(1, weight=1)
        self.v["input"] = tk.StringVar(); self.v["out"] = tk.StringVar()
        ttk.Label(io, text="Drawing (DWG/DXF) or zone DXFs").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Entry(io, textvariable=self.v["input"], width=60).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(io, text="…", width=3, command=self._pick_input).grid(row=0, column=2)
        ttk.Label(io, text="Output folder").grid(row=1, column=0, sticky="w", padx=4)
        ttk.Entry(io, textvariable=self.v["out"], width=60).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Button(io, text="…", width=3, command=lambda: self._pick_dir("out")).grid(row=1, column=2)
        self.v["mode"] = tk.StringVar(value="dxf")
        mf = ttk.Frame(io); mf.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for k, t in MODES.items():
            ttk.Radiobutton(mf, text=t, value=k, variable=self.v["mode"]).pack(side="left", padx=6)

        ram = ttk.LabelFrame(f, text="RAM Concept", padding=6); ram.grid(row=1, column=0, sticky="we", pady=4)
        ram.columnconfigure(1, weight=1)
        self._row(ram, 0, "Template model (.cpt)", "template_cpt",
                  lambda: self._pick_file("template_cpt", [("RAM Concept", "*.cpt")]))
        self._row(ram, 1, "RAM Concept Python API folder", "api_path", lambda: self._pick_dir("api_path"))
        self._chk(ram, 2, 0, "Run the analysis after building (the mesh doctor retries if RAM refuses the mesh)", "run_analysis")

        df = ttk.LabelFrame(f, text="Defaults - used only where the drawing has no value (the check before building lists them)",
                            padding=6)
        df.grid(row=2, column=0, sticky="we", pady=4)
        self._num(df, 0, 0, "Slab thickness", "slab_thickness", "mm")
        self._num(df, 0, 3, "Drop panel thickness", "drop_thickness", "mm")
        self._num(df, 0, 6, "Beam depth (width from the drawing)", "beam_depth", "mm")

        lf = ttk.LabelFrame(f, text="Loads", padding=6); lf.grid(row=3, column=0, sticky="we", pady=4)
        self._chk(lf, 0, 0, "Area loads on the slab", "write_area_loads")
        self._num(lf, 0, 3, "SDL", "sdl", "kN/m²"); self._num(lf, 0, 6, "Live load", "live_load", "kN/m²")
        self._chk(lf, 1, 0, "Architectural wall loads", "write_wall_loads")
        self._num(lf, 1, 3, "Density", "arch_wall_density", "kN/m³"); self._num(lf, 1, 6, "Height", "arch_wall_height", "m")
        self._num(lf, 1, 9, "Opening factor", "arch_wall_opening_factor", "")
        self._chk(lf, 2, 0, "Edge line load", "write_edge_load")
        self._num(lf, 2, 3, "Load", "edge_line_load", "kN/m")

        sf = ttk.LabelFrame(f, text="Support lines / design strips", padding=6); sf.grid(row=4, column=0, sticky="we", pady=4)
        self._chk(sf, 0, 0, "Draw support lines and design strips in the model", "write_design_strips")

        ad = ttk.LabelFrame(f, text="Drawing reader (stage 1)", padding=6); ad.grid(row=5, column=0, sticky="we", pady=4)
        ad.columnconfigure(1, weight=1)
        self._row(ad, 0, "Drawing reader folder (has pt_pipeline)", "reader_dir", lambda: self._pick_dir("reader_dir"))
        self._row(ad, 1, "LibreDWG dwgread (DWG only)", "dwgread_path",
                  lambda: self._pick_file("dwgread_path", [("dwgread", "dwgread*"), ("All", "*.*")]))

        bf = ttk.Frame(f); bf.grid(row=6, column=0, sticky="we", pady=4)
        self.b_start = ttk.Button(bf, text="Start", command=self.start); self.b_start.pack(side="left")
        self.b_stop = ttk.Button(bf, text="Stop", command=self.stop, state="disabled"); self.b_stop.pack(side="left", padx=6)
        ttk.Button(bf, text="Open output folder", command=self._open_out).pack(side="left")
        self.status = ttk.Label(bf, text=""); self.status.pack(side="right")

        self.log_w = tk.Text(f, height=16, wrap="word", font=("Consolas", 9))
        self.log_w.grid(row=7, column=0, sticky="nsew"); f.rowconfigure(7, weight=1)
        for lvl, col in (("ok", "#127a2e"), ("warn", "#9a6700"), ("error", "#b00020"), ("head", "#1f3a93")):
            self.log_w.tag_configure(lvl, foreground=col)

    # ------------------------------------------------------------ اختيار الملفات
    def _pick_input(self):
        if self.v["mode"].get() == "ram":
            ps = filedialog.askopenfilenames(title="Zone DXF files", filetypes=[("DXF", "*.dxf")])
            if ps:
                self.v["input"].set("; ".join(ps))
                self.v["out"].set(self.v["out"].get() or os.path.dirname(ps[0]))
        else:
            p = filedialog.askopenfilename(title="Drawing", filetypes=[("CAD drawing", "*.dwg *.dxf"), ("All", "*.*")])
            if p:
                self.v["input"].set(p)
                self.v["out"].set(os.path.splitext(p)[0] + "_PT")

    def _pick_dir(self, key):
        p = filedialog.askdirectory()
        if p:
            self.v[key].set(p)

    def _pick_file(self, key, types):
        p = filedialog.askopenfilename(filetypes=types)
        if p:
            self.v[key].set(p)

    def _open_out(self):
        p = self.v["out"].get()
        if p and os.path.isdir(p):
            if sys.platform.startswith("win"):
                os.startfile(p)          # noqa
            else:
                subprocess.Popen(["xdg-open", p])

    # ------------------------------------------------------------ الإعدادات
    def _collect(self):
        d = dict(self.data)
        for k, dv in SET.DEFAULTS.items():
            if k not in self.v:
                continue
            raw = self.v[k].get()
            if isinstance(dv, bool):
                d[k] = bool(raw)
            elif isinstance(dv, float):
                try:
                    d[k] = float(raw)
                except ValueError:
                    raise ValueError(f"'{raw}' is not a number ({k})")
            else:
                d[k] = str(raw).strip()
        return d

    # ------------------------------------------------------------ اللوج (من أي خيط)
    def log(self, msg, level="info"):
        self.q.put(("log", str(msg), level))

    def _pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self.log_w.insert("end", item[1] + "\n", item[2]); self.log_w.see("end")
                elif item[0] == "ask":
                    _, fn, box = item
                    try:
                        box["v"] = fn()
                    finally:
                        box["ev"].set()
                elif item[0] == "done":
                    self.b_start.config(state="normal"); self.b_stop.config(state="disabled")
                    self.status.config(text=item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def ask(self, fn):
        """سؤال من خيط الشغل للشاشة (رسالة/اختيار زونات) - بيستنى الرد."""
        box = {"ev": threading.Event(), "v": None}
        self.q.put(("ask", fn, box))
        box["ev"].wait()
        return box["v"]

    # ------------------------------------------------------------ التشغيل
    def start(self):
        try:
            data = self._collect()
        except ValueError as e:
            messagebox.showerror("Settings", str(e)); return
        SET.save(data); self.data = data
        src = self.v["input"].get().strip(); out = self.v["out"].get().strip()
        mode = self.v["mode"].get()
        if not src:
            messagebox.showerror("Files", "Pick the drawing (or the zone DXFs)."); return
        if not out:
            messagebox.showerror("Files", "Pick the output folder."); return
        if mode != "dxf":
            bad = [n for k, n in (("slab_thickness", "Slab thickness"), ("drop_thickness", "Drop panel thickness"),
                                  ("beam_depth", "Beam depth")) if float(data.get(k) or 0) <= 0]
            if bad:
                messagebox.showerror("Defaults", "Enter a value above 0 for: " + ", ".join(bad) +
                                     "\n(it is used only where the drawing has none)."); return
        if mode != "dxf" and not os.path.isfile(data.get("template_cpt") or ""):
            messagebox.showerror("RAM Concept", "Pick the template model (.cpt): each zone is built into a copy of it."); return
        self.stop_flag.clear()
        self.b_start.config(state="disabled"); self.b_stop.config(state="normal"); self.status.config(text="running…")
        self.worker = threading.Thread(target=self._run, args=(mode, src, out, data), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_flag.set()
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        if self.job is not None:
            try:
                self.job.cancel_event.set()
            except Exception:
                pass
        self.log("Stopping…", "warn")

    def _run(self, mode, src, out, data):
        status = "done"
        try:
            if mode == "ram":
                zones = [p.strip() for p in src.split(";") if p.strip()]
            else:
                rc, zones, rep = stage1.run(src, out, data, log=self.log, proc_cb=lambda p: setattr(self, "proc", p))
                if self.stop_flag.is_set():
                    raise _Stop()
            info = [preflight.inspect_zone(z) for z in zones]
            for z in info:
                self.log(f"   {z['zone']}: t={z['slab_t'] or '?'}  columns {z['columns']}  walls {z['walls']}  "
                         f"beams {z['beams']}  drops {z['drops']}  levels {len(z['levels'])}")
            if mode == "dxf":
                for ln in preflight.summary(info, data, stage2=False):
                    self.log(ln)
                status = f"{len(zones)} zone DXF(s)"
                return
            if mode == "both":
                chosen = self.ask(lambda: ZoneDialog(self.root, info).result)
                if not chosen:
                    raise _Stop()
                keep = [z for z, i in zip(zones, info) if i["zone"] in chosen]
                info = [i for i in info if i["zone"] in chosen]
                zones = keep
            lines = preflight.summary(info, data, stage2=True)
            ok = self.ask(lambda: messagebox.askokcancel(
                "Check before building the RAM model",
                "\n".join(lines) + "\n\nOK builds the model(s) with these. Cancel goes back to the settings.",
                parent=self.root))
            if not ok:
                raise _Stop()
            from . import stage2
            C = stage2.core()
            self.job = C.Job(log_cb=self.log, progress_cb=lambda f, t="": None)
            done, failed = stage2.run(zones, data, self.job, os.path.join(out, "RAM"))
            status = f"{len(done)} model(s) saved" + (f", {len(failed)} failed" if failed else "")
        except _Stop:
            status = "stopped"; self.log("Stopped.", "warn")
        except Exception as e:
            status = "failed"
            self.log(f"{type(e).__name__}: {e}", "error")
            self.log(traceback.format_exc(), "error")
        finally:
            self.proc = None; self.job = None
            self.q.put(("done", status))


class ZoneDialog:
    """اختيار الزونات اللي هتتبني في RAM (كلها متعلّمة)، بأعدادها."""

    def __init__(self, parent, info):
        self.result = None
        w = tk.Toplevel(parent); w.title("Zones to build in RAM"); w.transient(parent); w.grab_set()
        ttk.Label(w, text="Each zone becomes its own RAM model:", padding=6).pack(anchor="w")
        vs = []
        fr = ttk.Frame(w, padding=6); fr.pack(fill="both", expand=True)
        for i, z in enumerate(info):
            v = tk.BooleanVar(value=True); vs.append((z["zone"], v))
            miss = []
            if not z["slab_t"]:
                miss.append("no slab t")
            if z["drops_no_t"]:
                miss.append(f"{z['drops_no_t']} drops no t")
            if z["beams_no_d"]:
                miss.append(f"{z['beams_no_d']} beams no depth")
            txt = (f"{z['zone']}   t={z['slab_t'] or '?'}  cols {z['columns']}  beams {z['beams']}  "
                   f"drops {z['drops']}  levels {len(z['levels'])}" + (f"   ⚠ {', '.join(miss)}" if miss else ""))
            ttk.Checkbutton(fr, text=txt, variable=v).grid(row=i, column=0, sticky="w")
        bf = ttk.Frame(w, padding=6); bf.pack(fill="x")

        def ok():
            self.result = [n for n, v in vs if v.get()]
            w.destroy()
        ttk.Button(bf, text="Build these", command=ok).pack(side="right")
        ttk.Button(bf, text="Cancel", command=w.destroy).pack(side="right", padx=6)
        parent.wait_window(w)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
