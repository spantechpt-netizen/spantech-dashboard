# -*- coding: utf-8 -*-
"""PT Model Builder - الشاشة (بنفس شكل Auto PT Suite: هيدر أزرق، عمود صفحات على اليمين، كونسول غامق، شريط تحت).

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
import time
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, preflight, settings as SET, stage1

try:                                   # الشعار والاسم من Auto PT Suite (ملف متولّد بـ build_core.py، مش في الريبو)
    from . import brand as _BRAND
except Exception:                      # noqa
    _BRAND = None

MODES = {"dxf": "1) Drawing → zone DXFs",
         "both": "2) Drawing → zone DXFs → RAM model",
         "ram": "3) Zone DXFs → RAM model"}

#  ثيم Windows 11 بتاع Auto PT Suite (UI_THEMES["windows11"]) - نفس الألوان بالظبط
P = dict(bg="#f3f5f7", panel="#ffffff", chip="#edf3fb",
         nav="#f5f7fb", nav_active="#e8f1fd", nav_hover="#edf4ff",
         nav_ink="#1f2328", nav_sub="#64748b",
         console="#0f172a", console_ink="#e2e8f0",
         ink="#1c1f23", muted="#5f6f7d", line="#dfe5ed", line_strong="#bfc9d6",
         brand="#0f6cbd", brand_dark="#0b4c8a", accent="#ffb84d",
         ok="#2e7d32", warn="#a86300", err="#c0392b",
         btn="#f1f4f8", btn_hover="#e7edf7", btn_press="#dfe8f3",
         on_brand="#ffffff", on_brand_sub="#dfeeff")
#  ألوان اللوج على الكونسول الغامق
LOG_COL = {"info": "#e2e8f0", "ok": "#86efac", "warn": "#fcd34d", "error": "#fca5a5", "head": "#93c5fd",
           "path": "#5eead4", "time": "#94a3b8"}

#  (المفتاح، العنوان، السطر الصغير، الأيقونة، لونها) - نفس فكرة عمود Auto PT Suite
PAGES = [("project", "Project", "Drawing, output and mode", "🗀", "#4d6484"),
         ("reader", "Drawing reader", "Stage 1: DWG/DXF → zone DXFs", "⌗", "#43706c"),
         ("ram", "RAM Concept", "Template, API, analysis", "▦", "#41628a"),
         ("defaults", "Defaults", "Thickness and depth if not drawn", "⇕", "#6f5a80"),
         ("loads", "Loads", "Loading plan, SDL, LL, walls", "⤓", "#94714c"),
         ("strips", "Support lines", "Design strips", "≡", "#45707e"),
         ("run", "Run", "Log and progress", "▶", "#4f7a5f")]

FONT = "Segoe UI"
MONO = "Consolas"


class _Stop(Exception):
    pass


class Btn(tk.Label):
    """زرار مسطح بنفس شكل أزرار Auto PT Suite (خلفية فاتحة، hover، أو أزرق للأساسي)."""

    def __init__(self, parent, text, command, primary=False, **kw):
        self._bg = P["brand"] if primary else P["btn"]
        self._hv = P["brand_dark"] if primary else P["btn_hover"]
        fg = P["on_brand"] if primary else P["ink"]
        super().__init__(parent, text=text, bg=self._bg, fg=fg, cursor="hand2",
                         font=(FONT, 11 if primary else 10, "bold" if primary else "normal"),
                         padx=kw.pop("padx", 26 if primary else 12), pady=kw.pop("pady", 9 if primary else 6), **kw)
        self._cmd = command
        self._on = True
        self.bind("<Enter>", lambda e: self._on and self.config(bg=self._hv))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg if self._on else P["btn"]))
        self.bind("<Button-1>", lambda e: self._on and self._cmd and self._cmd())

    def enable(self, on=True):
        self._on = on
        self.config(bg=self._bg if on else P["btn"], fg=(self["fg"] if on else "#9aa5b1"),
                    cursor="hand2" if on else "arrow")
        if on and self._bg == P["brand"]:
            self.config(fg=P["on_brand"])
        elif on:
            self.config(fg=P["ink"])


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"PT Model Builder {__version__} — " + (getattr(_BRAND, "COMPANY_NAME", "") or "Span Tech"))
        root.configure(bg=P["bg"])
        root.geometry("1380x900")
        root.minsize(1100, 720)
        self.data = SET.load()
        self.q = queue.Queue()
        self.worker = None
        self.proc = None
        self.job = None
        self.stop_flag = threading.Event()
        self.v = {}
        self.pages = {}
        self.nav = {}
        self.lines = []              # (نص، مستوى) - للفلتر "Important only"
        self.t0 = None
        self._style()
        self._build()
        self.show("project")
        self._keys()
        self.root.after(100, self._pump)
        self.root.after(500, self._tick)

    # ------------------------------------------------------------ الشكل
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Brand.Horizontal.TProgressbar", troughcolor=P["line"], background=P["brand"],
                     bordercolor=P["line"], lightcolor=P["brand"], darkcolor=P["brand"], thickness=8)
        st.configure("TCheckbutton", background=P["panel"], foreground=P["ink"], font=(FONT, 10))
        st.configure("TRadiobutton", background=P["panel"], foreground=P["ink"], font=(FONT, 10))
        st.configure("TEntry", fieldbackground="#ffffff", bordercolor=P["line_strong"], padding=4)

    def _header(self):
        h = tk.Frame(self.root, bg=P["brand"], height=150)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"v{__version__}", bg=P["brand_dark"], fg=P["on_brand"], font=(MONO, 14),
                 padx=20, pady=6).place(x=14, y=48)
        right = tk.Frame(h, bg=P["brand"]); right.pack(side="right", padx=24, pady=14, anchor="ne")
        tk.Label(right, text=getattr(_BRAND, "COMPANY_NAME", "Span Tech") or "Span Tech", bg=P["brand"],
                 fg=P["accent"], font=(FONT, 13, "bold")).pack(anchor="e")
        row = tk.Frame(right, bg=P["brand"]); row.pack(anchor="e", pady=(4, 2))
        self._logo = None
        if _BRAND is not None and getattr(_BRAND, "SPAN_TECH_LOGO_PNG_B64", None):
            try:
                base = tk.PhotoImage(data=_BRAND.SPAN_TECH_LOGO_PNG_B64)
                f = max(1, round(base.height() / 48))
                self._logo = base.subsample(f, f) if f > 1 else base
                tk.Label(row, image=self._logo, bg=P["brand"]).pack(side="left", padx=(0, 10))
            except Exception:
                self._logo = None
        tk.Label(row, text="PT Model Builder", bg=P["brand"], fg=P["on_brand"],
                 font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(right, text="From an AutoCAD drawing to RAM Concept models, zone by zone",
                 bg=P["brand"], fg=P["on_brand_sub"], font=(FONT, 11)).pack(anchor="e")
        tk.Frame(self.root, bg=P["accent"], height=3).pack(fill="x")

    def _sidebar(self, parent):
        side = tk.Frame(parent, bg=P["nav"], width=330)
        side.pack(side="right", fill="y"); side.pack_propagate(False)
        tk.Frame(side, bg=P["nav"], height=10).pack()
        for i, (key, title, sub, icon, col) in enumerate(PAGES, 1):
            it = tk.Frame(side, bg=P["nav"], cursor="hand2", height=86)
            it.pack(fill="x"); it.pack_propagate(False)
            bar = tk.Frame(it, bg=P["nav"], width=4); bar.pack(side="right", fill="y")
            ic = tk.Label(it, text=icon, bg=P["nav"], fg=col, font=(FONT, 22), width=2)
            ic.pack(side="right", padx=(8, 16))
            txt = tk.Frame(it, bg=P["nav"]); txt.pack(side="right", fill="y", pady=16)
            t = tk.Label(txt, text=title, bg=P["nav"], fg=P["nav_ink"], font=(FONT, 12, "bold"), anchor="e")
            t.pack(anchor="e")
            s = tk.Label(txt, text=sub, bg=P["nav"], fg=P["nav_sub"], font=(FONT, 10), anchor="e")
            s.pack(anchor="e")
            n = tk.Label(it, text=f"⌃{i}", bg=P["nav"], fg="#c3cad3", font=(FONT, 8))
            n.pack(side="left", padx=10, anchor="n", pady=10)
            parts = (it, txt, t, s, ic, n)
            self.nav[key] = (parts, bar)
            for w_ in parts:
                w_.bind("<Button-1>", lambda e, k=key: self.show(k))
                w_.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                w_.bind("<Leave>", lambda e, k=key: self._hover(k, False))

    def _hover(self, key, on):
        if key == getattr(self, "_page", None):
            return
        for w_ in self.nav[key][0]:
            w_.config(bg=P["nav_hover"] if on else P["nav"])

    def show(self, key):
        self._page = key
        for k, (parts, bar) in self.nav.items():
            bg = P["nav_active"] if k == key else P["nav"]
            for w_ in parts:
                w_.config(bg=bg)
            bar.config(bg=P["brand"] if k == key else P["nav"])
        for k, f in self.pages.items():
            if k == key:
                f.pack(fill="both", expand=True)
            else:
                f.pack_forget()

    def _card(self, page, title, note=None):
        c = tk.Frame(page, bg=P["panel"], highlightthickness=1, highlightbackground=P["line"])
        c.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(c, text=title, bg=P["panel"], fg=P["ink"], font=(FONT, 12, "bold")).grid(
            row=0, column=0, columnspan=12, sticky="w", padx=14, pady=(12, 2))
        if note:
            tk.Label(c, text=note, bg=P["panel"], fg=P["muted"], font=(FONT, 9), wraplength=880,
                     justify="left").grid(row=1, column=0, columnspan=12, sticky="w", padx=14, pady=(0, 6))
        body = tk.Frame(c, bg=P["panel"]); body.grid(row=2, column=0, columnspan=12, sticky="we", padx=10, pady=(2, 12))
        c.columnconfigure(0, weight=1)
        return body

    def _page(self, key):
        f = tk.Frame(self.main, bg=P["bg"])
        self.pages[key] = f
        return f

    # ------------------------------------------------------------ خانات
    def _var(self, key, kind=tk.StringVar):
        val = self.data.get(key, "")
        v = kind(value=val if kind is not tk.StringVar else ("" if val is None else str(val)))
        self.v[key] = v
        return v

    def _lbl(self, parent, text, r, c, **kw):
        tk.Label(parent, text=text, bg=P["panel"], fg=P["ink"], font=(FONT, 10)).grid(row=r, column=c, sticky="w",
                                                                                      padx=6, pady=4, **kw)

    def _row(self, parent, r, label, key, browse=None, width=70):
        parent.columnconfigure(1, weight=1)
        self._lbl(parent, label, r, 0)
        ttk.Entry(parent, textvariable=self.v.get(key) or self._var(key), width=width, font=(FONT, 10)).grid(
            row=r, column=1, sticky="we", padx=6)
        if browse:
            Btn(parent, "Browse…", browse).grid(row=r, column=2, padx=6)

    def _num(self, parent, r, c, label, key, unit):
        self._lbl(parent, label, r, c)
        ttk.Entry(parent, textvariable=self._var(key), width=9, font=(FONT, 10)).grid(row=r, column=c + 1, sticky="w")
        tk.Label(parent, text=unit, bg=P["panel"], fg=P["muted"], font=(FONT, 9)).grid(row=r, column=c + 2, sticky="w",
                                                                                       padx=(3, 18))

    def _chk(self, parent, r, c, label, key, span=3):
        ttk.Checkbutton(parent, text=label, variable=self._var(key, tk.BooleanVar)).grid(
            row=r, column=c, columnspan=span, sticky="w", padx=6, pady=4)

    # ------------------------------------------------------------ البناء
    def _build(self):
        self._header()
        body = tk.Frame(self.root, bg=P["bg"]); body.pack(fill="both", expand=True)
        self._sidebar(body)
        self.main = tk.Frame(body, bg=P["bg"]); self.main.pack(side="left", fill="both", expand=True)

        # --- Project
        pg = self._page("project")
        b = self._card(pg, "Files", "The office drawing as it is (DWG or DXF, architectural or structural), or zone DXFs "
                                    "already made (mode 3). The output folder gets one DXF per zone, images, the report, "
                                    "and a RAM folder with the models.")
        self.v["input"] = tk.StringVar(); self.v["out"] = tk.StringVar()
        self._row(b, 0, "Drawing (DWG/DXF) or zone DXFs", "input", self._pick_input)
        self._row(b, 1, "Output folder", "out", lambda: self._pick_dir("out"))
        b = self._card(pg, "Mode")
        self.v["mode"] = tk.StringVar(value="dxf")
        for i, (k, t) in enumerate(MODES.items()):
            ttk.Radiobutton(b, text=t, value=k, variable=self.v["mode"]).grid(row=i, column=0, sticky="w", padx=6, pady=3)

        # --- Drawing reader
        pg = self._page("reader")
        b = self._card(pg, "Drawing reader (stage 1)",
                       "pt_pipeline and dwgread come inside the zip and are found on their own. Set them here only if "
                       "they were moved.")
        self._row(b, 0, "Drawing reader folder (has pt_pipeline)", "reader_dir", lambda: self._pick_dir("reader_dir"))
        self._row(b, 1, "LibreDWG dwgread (DWG only)", "dwgread_path",
                  lambda: self._pick_file("dwgread_path", [("dwgread", "dwgread*"), ("All", "*.*")]))
        b = self._card(pg, "What is read from the drawing",
                       "Slab edge, openings, stairs and cores · columns, walls, beams with their sizes · expansion "
                       "joints → zones · thickness (PT Slab T=…) and drops (T=…) · levels (T.O.C / T.O.S / SSL / FFL) "
                       "→ level zones with SE · the LOADING PLAN → load areas with SIDL and LL. Nothing is taken from "
                       "layer names.")

        # --- RAM
        pg = self._page("ram")
        b = self._card(pg, "RAM Concept", "Each zone is built into a copy of the template; the template itself is "
                                          "never touched.")
        self._row(b, 0, "Template model (.cpt)", "template_cpt",
                  lambda: self._pick_file("template_cpt", [("RAM Concept", "*.cpt")]))
        self._row(b, 1, "RAM Concept Python API folder", "api_path", lambda: self._pick_dir("api_path"))
        self._chk(b, 2, 0, "Run the analysis after building (the mesh doctor retries if RAM refuses the mesh)",
                  "run_analysis")

        # --- Defaults
        pg = self._page("defaults")
        b = self._card(pg, "Defaults", "Used only where the drawing has no value. The check before building lists "
                                       "every place a default is used.")
        self._num(b, 0, 0, "Slab thickness", "slab_thickness", "mm")
        self._num(b, 1, 0, "Drop panel thickness", "drop_thickness", "mm")
        self._num(b, 2, 0, "Beam depth (width from the drawing)", "beam_depth", "mm")

        # --- Loads
        pg = self._page("loads")
        b = self._card(pg, "Loads", "The LOADING PLAN in the drawing gives each area its own SIDL and LL (layer "
                                    "PT-Clean-Loads). The values below cover what the loading plan does not.")
        self._chk(b, 0, 0, "Area loads on the slab", "write_area_loads")
        self._num(b, 1, 0, "SDL (default)", "sdl", "kN/m²"); self._num(b, 1, 3, "Live load (default)", "live_load", "kN/m²")
        self._chk(b, 2, 0, "Architectural wall loads", "write_wall_loads")
        self._num(b, 3, 0, "Density", "arch_wall_density", "kN/m³"); self._num(b, 3, 3, "Height", "arch_wall_height", "m")
        self._num(b, 3, 6, "Opening factor", "arch_wall_opening_factor", "")
        self._chk(b, 4, 0, "Edge line load", "write_edge_load")
        self._num(b, 5, 0, "Load", "edge_line_load", "kN/m")

        # --- Strips
        pg = self._page("strips")
        b = self._card(pg, "Support lines and design strips")
        self._chk(b, 0, 0, "Draw support lines and design strips in the model", "write_design_strips")

        # --- Run
        pg = self._page("run")
        top = tk.Frame(pg, bg=P["panel"], highlightthickness=1, highlightbackground=P["line"])
        top.pack(fill="x", padx=14, pady=(12, 0))
        self.timer = tk.Label(top, text="00:00", bg=P["panel"], fg=P["muted"], font=(MONO, 12))
        self.timer.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))
        self.status = tk.Label(top, text="Ready", bg=P["panel"], fg=P["ink"], font=(FONT, 12, "bold"))
        self.status.grid(row=0, column=1, sticky="e", padx=14, pady=(10, 4))
        top.columnconfigure(0, weight=1)
        self.pb = ttk.Progressbar(top, style="Brand.Horizontal.TProgressbar", mode="indeterminate")
        self.pb.grid(row=1, column=0, columnspan=2, sticky="we", padx=14)
        self.info = tk.Label(top, text="", bg=P["panel"], fg=P["brand"], font=(FONT, 10, "bold"), anchor="w")
        self.info.grid(row=2, column=0, columnspan=2, sticky="we", padx=14, pady=(6, 10))

        con = tk.Frame(pg, bg=P["console"]); con.pack(fill="both", expand=True, padx=14, pady=(10, 0))
        self.log_w = tk.Text(con, wrap="word", font=(MONO, 10), bg=P["console"], fg=P["console_ink"],
                             insertbackground=P["console_ink"], relief="flat", padx=10, pady=8, borderwidth=0)
        sb = ttk.Scrollbar(con, command=self.log_w.yview); self.log_w.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.log_w.pack(side="left", fill="both", expand=True)
        for lvl, col in LOG_COL.items():
            self.log_w.tag_configure(lvl, foreground=col)
        self.log_w.tag_configure("hl", background="#6b4f00")

        act = tk.Frame(pg, bg=P["bg"]); act.pack(fill="x", padx=14, pady=(8, 10))
        Btn(act, "🗀  Open the folder", self._open_out).pack(side="left", padx=(0, 6))
        Btn(act, "⧉  Copy log", self._copy_log).pack(side="left", padx=6)
        Btn(act, "⤓  Save log", self._save_log).pack(side="left", padx=6)
        Btn(act, "✕  Clear", self._clear_log).pack(side="left", padx=6)
        self.v_follow = tk.BooleanVar(value=True); self.v_imp = tk.BooleanVar(value=False)
        for t, v, cmd in (("Follow the log", self.v_follow, None), ("Important only", self.v_imp, self._rerender)):
            ttk.Checkbutton(act, text=t, variable=v, command=cmd, style="Bar.TCheckbutton").pack(side="left", padx=10)
        ttk.Style(self.root).configure("Bar.TCheckbutton", background=P["bg"], font=(FONT, 10))

        # --- الشريط اللي تحت
        tk.Frame(self.root, bg=P["line"], height=1).pack(fill="x")
        bar = tk.Frame(self.root, bg=P["panel"]); bar.pack(fill="x")
        self.b_start = Btn(bar, "Start", self.start, primary=True); self.b_start.pack(side="left", padx=(12, 6), pady=10)
        self.b_stop = Btn(bar, "■  Stop", self.stop); self.b_stop.pack(side="left", padx=6, pady=10)
        self.b_stop.enable(False)
        tk.Label(bar, text="F5 Start  ·  Shift+F5 Stop  ·  Ctrl+S Save  ·  Ctrl+1…7 Pages", bg=P["panel"],
                 fg=P["muted"], font=(FONT, 9)).pack(side="left", padx=18)
        for t, cmd in (("⤓  Save settings", self._save_settings), ("⤒  Save as", self._save_as),
                       ("←  Load settings", self._load_settings), ("↺  Defaults", self._defaults)):
            Btn(bar, t, cmd).pack(side="right", padx=6, pady=10)

    def _keys(self):
        self.root.bind("<F5>", lambda e: self.start())
        self.root.bind("<Shift-F5>", lambda e: self.stop())
        self.root.bind("<Control-s>", lambda e: self._save_settings())
        for i, (k, *_r) in enumerate(PAGES, 1):
            self.root.bind(f"<Control-Key-{i}>", lambda e, k=k: self.show(k))

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

    def _apply(self, data):
        self.data = data
        for k, v in self.v.items():
            if k in data:
                try:
                    v.set(data[k] if isinstance(v, tk.BooleanVar) else ("" if data[k] is None else str(data[k])))
                except Exception:
                    pass

    def _save_settings(self):
        try:
            d = self._collect()
        except ValueError as e:
            messagebox.showerror("Settings", str(e)); return
        SET.save(d); self.data = d
        self.info.config(text=f"Settings saved: {SET.PATH}")

    def _save_as(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Settings", "*.json")])
        if p:
            try:
                SET.save(self._collect(), p); self.info.config(text=f"Settings saved: {p}")
            except ValueError as e:
                messagebox.showerror("Settings", str(e))

    def _load_settings(self):
        p = filedialog.askopenfilename(filetypes=[("Settings", "*.json")])
        if p:
            try:
                self._apply(SET.load_from(p)); self.info.config(text=f"Settings loaded: {p}")
            except Exception as e:
                messagebox.showerror("Settings", str(e))

    def _defaults(self):
        if messagebox.askokcancel("Defaults", "Put every value back to the program defaults?"):
            self._apply(dict(SET.DEFAULTS))

    # ------------------------------------------------------------ اللوج (من أي خيط)
    def log(self, msg, level="info"):
        self.q.put(("log", str(msg), level))

    def _imp(self, level):
        return level in ("warn", "error", "head", "ok")

    def _put(self, text, level):
        stamp = time.strftime("%H:%M:%S  ")
        tag = "path" if level == "info" and (":\\" in text or text.startswith("/")) else level
        self.log_w.insert("end", stamp, "time")
        self.log_w.insert("end", text + "\n", (tag, "hl") if "REVIEW" in text or "FAILED" in text else tag)

    def _rerender(self):
        self.log_w.delete("1.0", "end")
        for text, level in self.lines:
            if not self.v_imp.get() or self._imp(level):
                self._put(text, level)
        self.log_w.see("end")

    def _copy_log(self):
        self.root.clipboard_clear(); self.root.clipboard_append("\n".join(t for t, _ in self.lines))

    def _save_log(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if p:
            open(p, "w", encoding="utf-8").write("\n".join(t for t, _ in self.lines))

    def _clear_log(self):
        self.lines = []; self.log_w.delete("1.0", "end")

    def _tick(self):
        if self.t0 is not None:
            s = int(time.time() - self.t0)
            self.timer.config(text=f"{s // 60:02d}:{s % 60:02d}")
        self.root.after(500, self._tick)

    def _pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self.lines.append((item[1], item[2]))
                    if not self.v_imp.get() or self._imp(item[2]):
                        self._put(item[1], item[2])
                        if self.v_follow.get():
                            self.log_w.see("end")
                elif item[0] == "ask":
                    _, fn, box = item
                    try:
                        box["v"] = fn()
                    finally:
                        box["ev"].set()
                elif item[0] == "done":
                    self.b_start.enable(True); self.b_stop.enable(False)
                    self.pb.stop(); self.pb.config(mode="determinate", value=100)
                    self.status.config(text=item[1].capitalize(),
                                       fg=P["err"] if item[1] in ("failed",) else P["ink"])
                    self.t0 = None
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
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            data = self._collect()
        except ValueError as e:
            messagebox.showerror("Settings", str(e)); return
        SET.save(data); self.data = data
        src = self.v["input"].get().strip(); out = self.v["out"].get().strip()
        mode = self.v["mode"].get()
        if not src:
            self.show("project"); messagebox.showerror("Files", "Pick the drawing (or the zone DXFs)."); return
        if not out:
            self.show("project"); messagebox.showerror("Files", "Pick the output folder."); return
        if mode != "dxf":
            bad = [n for k, n in (("slab_thickness", "Slab thickness"), ("drop_thickness", "Drop panel thickness"),
                                  ("beam_depth", "Beam depth")) if float(data.get(k) or 0) <= 0]
            if bad:
                self.show("defaults")
                messagebox.showerror("Defaults", "Enter a value above 0 for: " + ", ".join(bad) +
                                     "\n(it is used only where the drawing has none)."); return
        if mode != "dxf" and not os.path.isfile(data.get("template_cpt") or ""):
            self.show("ram")
            messagebox.showerror("RAM Concept", "Pick the template model (.cpt): each zone is built into a copy of it."); return
        self.stop_flag.clear()
        self.show("run")
        self.b_start.enable(False); self.b_stop.enable(True)
        self.status.config(text="Running…", fg=P["ink"]); self.info.config(text=MODES[mode])
        self.pb.config(mode="indeterminate"); self.pb.start(12)
        self.t0 = time.time()
        self.log(f"PT Model Builder {__version__} - {MODES[mode]}", "head")
        self.worker = threading.Thread(target=self._run, args=(mode, src, out, data), daemon=True)
        self.worker.start()

    def stop(self):
        if self.worker is None or not self.worker.is_alive():
            return
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
                         f"beams {z['beams']}  drops {z['drops']}  levels {len(z['levels'])}  "
                         f"load areas {len(z.get('load_areas') or [])}")
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
        w.configure(bg=P["panel"])
        tk.Label(w, text="Each zone becomes its own RAM model", bg=P["panel"], fg=P["ink"],
                 font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        vs = []
        fr = tk.Frame(w, bg=P["panel"]); fr.pack(fill="both", expand=True, padx=10)
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
                   f"drops {z['drops']}  levels {len(z['levels'])}  loads {len(z.get('load_areas') or [])}"
                   + (f"   ⚠ {', '.join(miss)}" if miss else ""))
            ttk.Checkbutton(fr, text=txt, variable=v).grid(row=i, column=0, sticky="w", pady=1)
        bf = tk.Frame(w, bg=P["panel"]); bf.pack(fill="x", padx=10, pady=10)

        def ok():
            self.result = [n for n, v in vs if v.get()]
            w.destroy()
        Btn(bf, "Build these", ok, primary=True).pack(side="right")
        Btn(bf, "Cancel", w.destroy).pack(side="right", padx=8)
        parent.wait_window(w)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
