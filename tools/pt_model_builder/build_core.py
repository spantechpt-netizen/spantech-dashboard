# -*- coding: utf-8 -*-
"""
بيطلّع من Auto PT Suite الجزء اللي المرحلة التانية محتاجاه بس (قراءة الـ DXF، بناء المنشأ في
RAM، دكتور الشبكة، الأحمال، خطوط الركايز وشرايح التصميم) في ملف واحد مستقل:
`ptmb/ram_core.py`. مافيهوش واجهة ولا كابلات ولا تصميم.

    python build_core.py path/to/Auto_PT_Suite_v397_CAD_Reader_AI_patched.py

الطريقة: شجرة الكود (ast) - من الدوال اللي تحت (ENTRIES) بيمشي على كل اسم عام بتستخدمه
(مش المتغيرات المحلية) لحد ما يقفل، وبيكتب التعريفات دي بترتيبها في الملف الأصلي + الـ imports.
لو البرنامج اتحدث، شغّل الأمر ده تاني - مافيش حاجة بتتنسخ بالإيد.

ram_core.py مش في الريبو (الريبو عام، والبرنامج مرخّص): بيتولد عندك وبيتحط في الـ zip.
"""
import ast
import builtins
import datetime
import hashlib
import os
import sys

ENTRIES = [
    # قراءة الـ DXF النضيف
    "scan_dxf_layers", "guess_role", "parse_dxf", "UNIT_CHOICES", "ROLE_LABELS",
    "wall_udl_check", "sanitize_site", "mark_band_beams",
    # الشبكة
    "mesh_doctor", "mesh_doctor_findings", "diagnose_ram_error",
    # RAM
    "RamSession", "find_ram_api_path", "build_structure_in_ram", "safe_save",
    "run_model_analysis",
    # الأحمال
    "write_area_loads_to_ram", "write_adm_line_loads_to_ram",
    "write_wall_loads_to_ram", "write_edge_loads_to_ram",
    # خطوط الركايز وشرايح التصميم
    "write_design_strips_to_ram", "build_support_lines",
    # الإعدادات والتشغيل
    "TendonDesignParams", "Job", "ConsoleJob", "CancelledError",
]


def top_defs(tree):
    defs = {}
    for n in tree.body:
        names = []
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [n.name]
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                names += [x.id for x in ast.walk(t) if isinstance(x, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names = [n.target.id]
        for nm in names:
            defs.setdefault(nm, []).append(n)
    return defs


class Refs(ast.NodeVisitor):
    """الأسامي العامة المستخدمة - من غير المتغيرات المحلية (args، تخصيصات، except as، import جوه دالة)."""

    def __init__(self):
        self.used, self.scopes = set(), [set()]

    @staticmethod
    def _locals(fn):
        a = fn.args
        L = {x.arg for x in a.args + a.kwonlyargs + getattr(a, "posonlyargs", [])}
        L |= {x.arg for x in (a.vararg, a.kwarg) if x}
        glob = set()
        for x in ast.walk(fn):
            if isinstance(x, ast.Global):
                glob |= set(x.names)
        for x in ast.walk(fn):
            if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
                L.add(x.id)
            elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x is not fn:
                L.add(x.name)
            elif isinstance(x, ast.ExceptHandler) and x.name:
                L.add(x.name)
            elif isinstance(x, (ast.Import, ast.ImportFrom)):
                L |= {(n.asname or n.name).split(".")[0] for n in x.names}
            elif isinstance(x, ast.arg):
                L.add(x.arg)
        return L - glob

    def visit_FunctionDef(self, n):
        for d in n.decorator_list + n.args.defaults + [d for d in n.args.kw_defaults if d]:
            self.visit(d)
        self.scopes.append(self._locals(n))
        for b in n.body:
            self.visit(b)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, n):
        self.scopes.append({a.arg for a in n.args.args})
        self.visit(n.body)
        self.scopes.pop()

    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Load) and not any(n.id in s for s in self.scopes[1:]):
            self.used.add(n.id)


def closure(tree, entries):
    defs = top_defs(tree)
    need, todo = set(), list(entries)
    while todo:
        k = todo.pop()
        if k in need or k not in defs:
            continue
        need.add(k)
        r = Refs()
        for n in defs[k]:
            r.visit(n)
        todo += [u for u in r.used if u in defs and u not in need]
    missing = [e for e in entries if e not in defs]
    return need, defs, missing


def build(src_path, out_path):
    src = open(src_path, encoding="utf-8").read()
    tree = ast.parse(src)
    need, defs, missing = closure(tree, ENTRIES)
    if missing:
        raise SystemExit(f"not in this version of the program: {missing}")
    keep = {id(n) for k in need for n in defs[k]}
    lines = src.splitlines()

    def segment(n):
        # الـ decorators قبل السطر بتاع def
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        return "\n".join(lines[start - 1:n.end_lineno])

    parts = []
    for n in tree.body:
        if not (isinstance(n, (ast.Import, ast.ImportFrom, ast.Try)) or id(n) in keep):
            continue
        seg = segment(n)
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = {(a.asname or a.name).split(".")[0] for a in n.names}
            if isinstance(n, ast.ImportFrom) and n.module == "__future__":
                parts.insert(0, seg)
            else:
                # كل import في try: الواجهة (tkinter) وأي مكتبة مش موجودة عند المستخدم مابتوقفش الموديول
                parts.append("try:\n    " + seg.replace("\n", "\n    ") + "\nexcept Exception:\n    pass")
        elif isinstance(n, ast.Try) and all(isinstance(b, (ast.Import, ast.ImportFrom, ast.Assign)) for b in n.body):
            parts.append(seg)                                    # try: import shapely ... except: HAS_SHAPELY = False
        elif id(n) in keep:
            parts.append(seg)
    digest = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
    head = (f'# -*- coding: utf-8 -*-\n"""\nram_core - generated by build_core.py from {os.path.basename(src_path)}\n'
            f"(sha256 {digest}, {datetime.date.today()}). {len(need)} definitions.\nDo not edit by hand: "
            f'run build_core.py again when the program changes.\n"""\n')
    fut = [p for p in parts if p.startswith("from __future__")]
    body = [p for p in parts if not p.startswith("from __future__")]
    code = head + "\n".join(fut) + "\n" + "\n\n".join(body) + "\n"
    compile(code, out_path, "exec")
    # كل اسم عام مستخدم لازم يبقى متعرّف
    t2 = ast.parse(code)
    d2 = top_defs(t2)
    r = Refs()
    for k in need:
        for n in d2.get(k, []):
            r.visit(n)
    imported = set()
    for n in t2.body:                      # try: import shapely ... HAS_SHAPELY = True
        if isinstance(n, ast.Try):
            imported |= {x.id for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
    for n in ast.walk(t2):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            imported |= {(a.asname or a.name).split(".")[0] for a in n.names}
    undefined = sorted(u for u in r.used if u not in d2 and u not in imported and not hasattr(builtins, u))
    open(out_path, "w", encoding="utf-8").write(code)
    return len(need), code.count("\n"), undefined


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptmb", "ram_core.py")
    n, lines, undefined = build(sys.argv[1], out)
    print(f"ram_core.py: {n} definitions, {lines} lines -> {out}")
    if undefined:
        print("WARNING - names used but not defined (check them):", undefined)
    # شعار Span Tech والاسم وثيم الألوان من البرنامج نفسه (الشاشة بنفس شكل Auto PT Suite) - في ملف متولّد
    # زي ram_core (مش في الريبو)
    tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
    keep = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and \
                n.targets[0].id in ("SPAN_TECH_LOGO_PNG_B64", "COMPANY_NAME", "APP_VERSION"):
            try:
                keep[n.targets[0].id] = ast.literal_eval(n.value)
            except Exception:
                pass
    bp = os.path.join(os.path.dirname(out), "brand.py")
    with open(bp, "w", encoding="utf-8") as f:
        f.write("# generated by build_core.py from the Auto PT Suite file - not in the repo\n")
        for k, v in keep.items():
            f.write(f"{k} = {v!r}\n")
    print(f"brand.py: {sorted(keep)} -> {bp}")
