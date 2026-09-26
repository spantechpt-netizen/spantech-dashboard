"""اختبارات دكتور الشبكة (Auto PT Suite) على موديل صناعي وجلسة RAM وهمية - من غير RAM.

    AUTOPT_SRC=Auto_PT_Suite_v397_CAD_Reader_AI_patched.py python -m pytest pt_pipeline/tests/test_mesh_doctor.py -q
"""
import importlib.util, os, sys, types, copy
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
#  البرنامج نفسه مش في الريبو: AUTOPT_SRC=path/to/Auto_PT_Suite.py python -m pytest ...
SRC = os.environ.get("AUTOPT_SRC", "")
if not os.path.isfile(SRC):
    pytest.skip("set AUTOPT_SRC to the Auto PT Suite .py file", allow_module_level=True)


def _load():
    class _Any(types.ModuleType):
        def __getattr__(self, k):
            if k.startswith("__"):
                raise AttributeError(k)
            return type(k, (), {"__init__": lambda self, *a, **kw: None})
    for name in ("tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"):
        sys.modules.setdefault(name, _Any(name))
    tk = sys.modules["tkinter"]
    for n in ("ttk", "filedialog", "messagebox"):
        setattr(tk, n, sys.modules["tkinter." + n])
    spec = importlib.util.spec_from_file_location("autopt", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A = _load()


class Job:
    def __init__(self): self.log = []
    def __getattr__(self, k):
        if k in ("ok", "warn", "info", "error", "step"):
            return lambda *a, **kw: self.log.append((k, " ".join(map(str, a))))
        if k == "check":
            return lambda *a, **kw: None
        raise AttributeError(k)


def site():
    # بلاطة 10×8، الحد التحتاني مرسوم على y=0.04 والكمرة وشها الخارجي على y=0
    return {
        "boundary": [(0, 0.04), (10, 0.04), (10, 8), (0, 8)],
        "slabs": [{"points": [(0, 0.04), (10, 0.04), (10, 8), (0, 8)], "is_drop": False,
                   "thickness": 250, "priority": 1},
                  {"points": [(4, 4), (5, 4), (5, 5), (4, 5)], "is_drop": True,
                   "thickness": 400, "priority": 1}],
        "openings": [[(8.97, 3), (9.97, 3), (9.97, 4), (8.97, 4)],       # 3 سم من الحد
                     [(2, 2), (3, 2), (3, 3), (2, 3)],
                     [(2.5, 2.5), (3.5, 2.5), (3.5, 3.5), (2.5, 3.5)],  # متداخلة
                     [(20, 20), (21, 20), (21, 21), (20, 21)]],         # برّه
        "columns": [{"center": (0.2, 0.2), "b": 400, "d": 400},
                    {"center": (9.8, 0.2), "b": 400, "d": 400},
                    {"center": (5, 7.8), "b": 400, "d": 400}],
        "walls": [],
        "beams": [{"p1": (0, 0.15), "p2": (10, 0.15), "width": 300, "depth": 700},
                  {"p1": (5, 0.15), "p2": (5, 9.5), "width": 300, "depth": 600},     # طالعة برّه
                  {"p1": (30, 30), "p2": (35, 30), "width": 300, "depth": 600},      # برّه خالص
                  {"p1": (7, 0.35), "p2": (7, 5), "width": 250, "depth": 600},       # بتقف قبل الكمرة بـ 20 سم؟ لا: 0.35-0.15=0.2
                  {"p1": (2, 0.2), "p2": (2, 5), "width": 250, "depth": 600}],      # 5 سم بعد المحور
        "pour_strips": [],
    }


def test_edge_snaps_to_beam_outer_face():
    s = site(); A.mesh_doctor(s, Job())
    ys = sorted(set(round(p[1], 4) for p in s["boundary"]))
    assert ys[0] == 0.0, s["boundary"]


def test_opening_near_edge_becomes_notch_and_overlaps_merge():
    s = site(); A.mesh_doctor(s, Job())
    P = A._md_geom()[0]
    assert len(s["openings"]) == 1                       # المتداخلتين بقوا واحدة، والقريبة بقت تجويف، واللي برّه اتشالت
    assert abs(P(s["openings"][0]).area - 1.75) < 1e-6
    assert P(s["boundary"]).area < 10 * 8 - 0.99


def test_beams_trimmed_and_dropped():
    s = site(); A.mesh_doctor(s, Job())
    ends = [(tuple(map(lambda v: round(v, 3), b["p1"])), tuple(map(lambda v: round(v, 3), b["p2"]))) for b in s["beams"]]
    assert all(max(p[1] for p in e) <= 8.0 + 1e-6 for e in ends)       # مفيش كمرة برّه
    assert not any(e[0][0] >= 30 for e in ends)
    assert len(s["mesh_doctor_dropped"]) == 1
    b2 = [b for b in s["beams"] if abs(b["p1"][0] - 2) < 1e-6][0]
    assert abs(b2["p1"][1] - 0.15) < 1e-6                           # الطرف اتقص على محور الكمرة


def test_drop_is_not_snapped_and_idempotent():
    s = site(); A.mesh_doctor(s, Job()); s1 = copy.deepcopy(s)
    drop = [x for x in s["slabs"] if x["is_drop"]][0]
    assert sorted(drop["points"]) == sorted([(4, 4), (5, 4), (5, 5), (4, 5)])
    rep = A.mesh_doctor(s, Job())
    assert s["boundary"] == s1["boundary"] and s["openings"] == s1["openings"], rep


def test_same_priority_overlap_gets_higher_priority():
    s = site(); A.mesh_doctor(s, Job())
    drop = [x for x in s["slabs"] if x["is_drop"]][0]
    assert drop["priority"] == 2


def test_diagnose():
    assert A.diagnose_ram_error("An entity has become misshaped")[0] == "geometry"
    assert A.diagnose_ram_error("There is no structure to analyze; did you forget to generate the mesh?")[0] == "no_mesh"
    assert A.diagnose_ram_error("Structure is unstable")[0] == "stability"
    assert A.diagnose_ram_error("???")[0] == "unknown"


# ---------------- جلسة RAM وهمية ----------------
class Elem:
    def __init__(self, store): self.store = store; store.append(self)
    def delete(self): self.store.remove(self)


class Layer:
    def __init__(self): self.items = []
    def add_slab_area(self, poly): return Elem(self.items)
    def add_slab_opening(self, poly): return Elem(self.items)
    def add_column_below(self, *a): return Elem(self.items)
    def add_column(self, *a): return Elem(self.items)
    def add_wall_below(self, *a): return Elem(self.items)
    def add_wall(self, *a): return Elem(self.items)
    def add_beam(self, *a): return Elem(self.items)


class Model:
    def __init__(self, fail_times):
        self.cad_manager = types.SimpleNamespace(structure_layer=Layer())
        self.fail = fail_times; self.mesh_calls = 0
    def generate_mesh(self, *a):
        self.mesh_calls += 1
        if self.fail > 0:
            self.fail -= 1
            raise RuntimeError("An entity has become misshaped")
    def calc_all(self): pass


class Sess:
    def __init__(self, fail):
        self.model = Model(fail); self.concept = types.SimpleNamespace()
        P2 = lambda x, y: (x, y)
        self.api = {"Point2D": P2, "Polygon2D": lambda pts: pts, "LineSegment2D": lambda a, b: (a, b)}


def _params():
    return A.TendonDesignParams()


def test_retry_rebuilds_and_succeeds(monkeypatch):
    monkeypatch.setattr(A, "_run_with_heartbeat", lambda fn, job, label: fn(), raising=False)
    s = Sess(fail=2); job = Job()
    A.build_structure_in_ram(s, site(), _params(), job)
    n0 = len(s.model.cad_manager.structure_layer.items)
    r = A.run_model_analysis(s, job)
    assert r["ok"], job.log[-15:]
    assert "fixed_by" in r
    assert len(s.model.cad_manager.structure_layer.items) == n0     # اتمسح واترسم، مش اتكرر


def test_retry_reports_places_when_nothing_works(monkeypatch):
    monkeypatch.setattr(A, "_run_with_heartbeat", lambda fn, job, label: fn(), raising=False)
    s = Sess(fail=10 ** 6); job = Job()
    A.build_structure_in_ram(s, site(), _params(), job)
    r = A.run_model_analysis(s, job)
    assert not r["ok"] and r["diagnosis"]["kind"] == "geometry"
    assert any("still refuses" in t for k, t in job.log if k == "error")


def test_findings_point_at_beam_off_the_edge():
    s = site()
    s["beams"].append({"p1": (0, 7.8), "p2": (10, 7.8), "width": 300, "depth": 600})   # وشها 5 سم من الحد
    f = A.mesh_doctor_findings(s)
    assert len([x for x in f if "outer face" in x]) == 1 and "50 mm" in f[0], f
