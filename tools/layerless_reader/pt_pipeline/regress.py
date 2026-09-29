"""Regression: كل المشاريع القديمة بالكود الحالي، ومقارنة بالمرجع (FLOW جزء 8 و11).

    python -m pt_pipeline.regress projects.json -o reg_out [--baseline pt_pipeline/tests/baseline.json]
                                               [--ref-dir old_reg_out] [--only hdb roya] [-j 3] [--write-baseline]

projects.json (عندك، مش في الريبو - المسارات محلية):
    [{"name": "roya", "input": "D:/dwg/roya.dwg", "args": ["--drop-thickness", "400"]}, ...]

لكل مشروع: CHECK، عدد الزونات، عدد العناصر في كل ليّر (مجموع كل الملفات)، أعمدة برّه الزونات، عدد REVIEW.
- `--baseline`: الأرقام دي لازم تطابق المرجع. أي فرق بيتطبع بالمشروع والليّر.
- `--ref-dir`: فولدر regression قديم - المقارنة ملف ملف بمحتوى الرسمة (مش بالتاريخ)، والعناصر اللي اتغيرت بإحداثياتها.
- `--write-baseline`: يكتب الأرقام الحالية كمرجع جديد (بعد ما تتأكد إن كل فرق مفهوم).
الكود بيطلع 1 لو أي مشروع CHECK FAILED أو اختلف عن المرجع.
"""
import argparse, collections, concurrent.futures as cf, glob, json, os, subprocess, sys


def run_one(p, out, env):
    dst = os.path.join(out, p["name"])
    cmd = [sys.executable, "-m", "pt_pipeline.convert", p["input"], "-o", dst, "--keep-work"] + list(p.get("args", []))
    with open(os.path.join(out, p["name"] + ".log"), "w") as lf:
        rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env,
                            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).returncode
    return p["name"], rc


def entities(fn):
    import ezdxf
    out = []
    for e in ezdxf.readfile(fn).modelspace():
        t, L = e.dxftype(), e.dxf.layer
        if t == "LWPOLYLINE":
            out.append((L, t, tuple(round(c, 0) for q in e.get_points() for c in q[:2])))
        elif t == "LINE":
            out.append((L, t, tuple(round(c, 0) for c in (e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))))
        elif t in ("TEXT", "MTEXT"):
            out.append((L, t, e.dxf.text if t == "TEXT" else e.text, round(e.dxf.insert.x, 0), round(e.dxf.insert.y, 0)))
        else:
            out.append((L, t))
    return out


def summary(d):
    rp = os.path.join(d, "report.json")
    if not os.path.exists(rp):
        return {"ok": False, "error": "no report.json"}
    r = json.load(open(rp))
    layers = collections.Counter()
    for f in glob.glob(os.path.join(d, "*.dxf")):
        layers.update(L for L, *_ in entities(f))
    gate = sum(int(m.split()[0]) for _, m in r.get("review", []) if "outside every zone" in m)
    return {"ok": bool(r.get("ok")), "zones": len(r.get("zones", [])), "layers": dict(sorted(layers.items())),
            "columns_outside_zones": gate, "review": len(r.get("review", []))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects"); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--baseline"); ap.add_argument("--ref-dir"); ap.add_argument("--only", nargs="*")
    ap.add_argument("-j", "--jobs", type=int, default=2); ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--no-run", action="store_true", help="compare an existing -o folder without converting")
    a = ap.parse_args(argv)
    P = [p for p in json.load(open(a.projects)) if not a.only or p["name"] in a.only]
    os.makedirs(a.out, exist_ok=True)
    if not a.no_run:
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            for name, rc in ex.map(lambda p: run_one(p, a.out, dict(os.environ)), P):
                print(f"[regress] {name}: exit {rc}", flush=True)
    cur = {p["name"]: summary(os.path.join(a.out, p["name"])) for p in P}
    bad = 0
    base = json.load(open(a.baseline)) if a.baseline and os.path.exists(a.baseline) else {}
    print(f"\n{'project':12s} {'CHECK':6s} {'zones':>5s} {'cols out':>8s} {'review':>6s}  vs baseline")
    for n, s in cur.items():
        diffs = []
        if not s.get("ok"):
            bad += 1
        b = base.get(n)
        if b:
            for k in ("ok", "zones", "columns_outside_zones"):
                if b.get(k) != s.get(k):
                    diffs.append(f"{k} {b.get(k)} -> {s.get(k)}")
            for L in sorted(set(b.get("layers", {})) | set(s.get("layers", {}))):
                x, y = b.get("layers", {}).get(L, 0), s.get("layers", {}).get(L, 0)
                if x != y:
                    diffs.append(f"{L} {x} -> {y}")
            bad += bool(diffs)
        print(f"{n:12s} {'OK' if s.get('ok') else 'FAIL':6s} {s.get('zones', 0):5d} {s.get('columns_outside_zones', 0):8d} "
              f"{s.get('review', 0):6d}  {'; '.join(diffs) if diffs else ('same' if b else '(no baseline)')}")
    if a.ref_dir:
        print("\nfile by file against", a.ref_dir)
        for n in cur:
            for f in sorted(glob.glob(os.path.join(a.out, n, "*.dxf"))):
                g = os.path.join(a.ref_dir, n, os.path.basename(f))
                if not os.path.exists(g):
                    print(f"  {n}/{os.path.basename(f)}: new file"); bad += 1; continue
                A, B = collections.Counter(entities(g)), collections.Counter(entities(f))
                if A != B:
                    bad += 1
                    gone, new = list((A - B).elements()), list((B - A).elements())
                    print(f"  {n}/{os.path.basename(f)}: {len(gone)} gone, {len(new)} new")
                    for e in (gone[:4] + new[:4]):
                        print(f"      {'-' if e in gone else '+'} {str(e)[:150]}")
            for g in sorted(glob.glob(os.path.join(a.ref_dir, n, "*.dxf"))):
                if not os.path.exists(os.path.join(a.out, n, os.path.basename(g))):
                    print(f"  {n}/{os.path.basename(g)}: missing now"); bad += 1
    if a.write_baseline and a.baseline:
        base.update(cur)
        json.dump(base, open(a.baseline, "w"), indent=1, ensure_ascii=False)
        print(f"\nbaseline written: {a.baseline}")
    print("\nREGRESSION", "OK" if bad == 0 else f"FAILED ({bad})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
