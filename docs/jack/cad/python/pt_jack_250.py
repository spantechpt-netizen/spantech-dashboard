#!/usr/bin/env python3
"""
PT-JACK-250 — parametric solid model
Mono-strand post-tensioning stressing jack, 250 kN, twin cylinder.

This script IS the parametric master. Change a value in PARAMS, re-run,
and every STEP / DXF file is regenerated consistently.

    pip install cadquery
    python pt_jack_250.py

Coordinate system (global, millimetres):
    X  jack axis, 0 = front face of the nose yoke, +X rearward
    Y  vertical (the side-entry slot opens towards -Y)
    Z  across the jack; the two cylinder axes lie at Z = +/- CYL_CC/2

All parts are modelled in their RETRACTED position.
"""
import os, json
import cadquery as cq

# --------------------------------------------------------------------------
# PARAMETERS — edit here
# --------------------------------------------------------------------------
P = dict(
    # --- hydraulics -------------------------------------------------------
    BORE          = 50.0,    # cylinder bore
    ROD           = 32.0,    # piston rod
    STROKE        = 200.0,
    TUBE_OD       = 70.0,
    TUBE_L        = 310.0,
    PISTON_L      = 35.0,
    CYL_CC        = 160.0,   # centre distance between the two cylinders
    THREAD_ENG    = 30.0,    # M70x2 engagement, both tube ends
    # --- structure --------------------------------------------------------
    YOKE_D        = 75.0,    # yoke depth along X
    YOKE_W        = 250.0,
    YOKE_TOP      = 85.0,    # bridge extends to +Y
    YOKE_BOT      = -85.0,   # pad legs reach -Y
    BRIDGE_BOT    = -20.0,   # bottom of the full-width bridge
    SLOT_W        = 22.0,    # side-entry slot for the strand
    BEAM_D        = 80.0,    # crossbeam depth along X
    BEAM_W        = 250.0,
    BEAM_H        = 170.0,
    # --- gripper ----------------------------------------------------------
    GRIP_OD       = 65.0,
    GRIP_L        = 75.0,
    GRIP_THREAD_D = 60.0,
    GRIP_THREAD_L = 35.0,
    TAPER_INC     = 7.0,     # included cone angle, degrees
    WEDGE_SMALL   = 25.0,    # taper small end diameter (front)
    WEDGE_L       = 70.0,
    # --- misc -------------------------------------------------------------
    GLAND_L       = 75.0,
    GLAND_OD      = 86.0,
    ROD_NOSE_TH   = 24.0,    # M24x1.5
    ROD_NOSE_ENG  = 45.0,
    ROD_SHLD_D    = 44.0,
    ROD_SHLD_L    = 8.0,
    PAD_Z         = 30.0,    # bearing pad, across
    PAD_Y         = 50.0,
    PAD_T         = 12.0,
    PAD_OFFSET    = 26.0,    # pad centre from the jack axis
    STRAND_D      = 15.24,
    GALLERY_D     = 6.0,
    YOKE_GAP      = 20.0,    # clearance yoke rear face -> gland cap front face
)

RHO = dict(al7075=2.81e-6, steel=7.85e-6)   # kg/mm^3

# --------------------------------------------------------------------------
# derived station coordinates along X
# --------------------------------------------------------------------------
def stations(p):
    s = {}
    s["yoke0"], s["yoke1"] = 0.0, p["YOKE_D"]
    s["gland0"] = s["yoke1"] + p["YOKE_GAP"]
    s["gland1"] = s["gland0"] + p["GLAND_L"]
    s["tube0"]  = s["gland1"] - p["THREAD_ENG"]
    s["tube1"]  = s["tube0"] + p["TUBE_L"]
    s["beam0"]  = s["tube1"] - p["THREAD_ENG"]
    s["beam1"]  = s["beam0"] + p["BEAM_D"]
    s["pist1"]  = s["tube1"]                       # retracted: piston at the rear
    s["pist0"]  = s["pist1"] - p["PISTON_L"]
    s["stop1"]  = s["pist0"] - p["STROKE"]         # hard stop for the extended position
    s["stop0"]  = s["stop1"] - 40.0
    s["grip0"]  = s["beam1"] - p["GRIP_THREAD_L"]
    s["grip1"]  = s["beam1"] + p["GRIP_L"]
    s["gcap1"]  = s["grip1"] + 18.0
    s["rod0"]   = s["yoke1"] - p["ROD_NOSE_ENG"]
    s["rod1"]   = s["pist1"]
    s["L_retracted"] = s["gcap1"]
    s["L_extended"]  = s["gcap1"] + p["STROKE"]
    return s

S = stations(P)
CZ = P["CYL_CC"] / 2.0

# --------------------------------------------------------------------------
# primitive helpers — solids generated along +X
# --------------------------------------------------------------------------
def cylX(x0, x1, d, y=0.0, z=0.0):
    """Cylinder along X from x0 to x1, diameter d, axis at (y, z)."""
    return (cq.Workplane("YZ").workplane(offset=x0).center(y, z)
            .circle(d / 2.0).extrude(x1 - x0))

def coneX(x0, x1, d0, d1, y=0.0, z=0.0):
    """Truncated cone along X (d0 at x0, d1 at x1)."""
    return (cq.Workplane("YZ").workplane(offset=x0).center(y, z)
            .circle(d0 / 2.0).workplane(offset=x1 - x0).circle(d1 / 2.0)
            .loft(ruled=True))

def boxX(x0, x1, y0, y1, z0, z1):
    """Rectangular prism along X."""
    return (cq.Workplane("YZ").workplane(offset=x0)
            .moveTo(y0, z0).lineTo(y1, z0).lineTo(y1, z1).lineTo(y0, z1)
            .close().extrude(x1 - x0))

def cylY(y0, y1, d, x=0.0, z=0.0):
    """Cylinder along Y (used for the hydraulic galleries)."""
    return (cq.Workplane("XZ").workplane(offset=-y0).center(x, z)
            .circle(d / 2.0).extrude(-(y1 - y0)))

def cylZ(z0, z1, d, x=0.0, y=0.0):
    return (cq.Workplane("XY").workplane(offset=z0).center(x, y)
            .circle(d / 2.0).extrude(z1 - z0))

def roundedBoxX(x0, x1, y0, y1, z0, z1, r=8.0):
    """Prism along X with the four longitudinal edges filleted (fatigue rule R>=8)."""
    b = boxX(x0, x1, y0, y1, z0, z1)
    try:
        return b.edges("|X").fillet(r)
    except Exception:
        return b

def profile_zy(pts):
    """Feed a list of (z, y) points to a YZ workplane (local x = Y, local y = Z)."""
    return [(y, z) for (z, y) in pts]

# ==========================================================================
# P1 — NOSE YOKE
# ==========================================================================
def nose_yoke(p=P, s=S):
    W, TOP, BOT, BB = p["YOKE_W"] / 2, p["YOKE_TOP"], p["YOKE_BOT"], p["BRIDGE_BOT"]
    sw, ch = p["SLOT_W"] / 2, 20.0
    pz = p["PAD_OFFSET"]
    lz0, lz1 = pz - p["PAD_Z"] / 2, pz + p["PAD_Z"] / 2   # pad-leg extent in Z

    right = [(-W, TOP - ch), (-W + ch, TOP), (W - ch, TOP), (W, TOP - ch),
             (W, BB), (lz1, BB), (lz1, BOT), (lz0, BOT), (lz0, BB), (sw, BB), (sw, 0)]
    left  = [(-sw, BB), (-lz0, BB), (-lz0, BOT), (-lz1, BOT), (-lz1, BB), (-W, BB)]

    def dedupe(seq):
        out = []
        for q in seq:
            if not out or (abs(q[0] - out[-1][0]) > 1e-6 or abs(q[1] - out[-1][1]) > 1e-6):
                out.append(q)
        return out

    right, left = dedupe(right), dedupe(left)
    wp = cq.Workplane("YZ").workplane(offset=0)
    part = wp.moveTo(*profile_zy([right[0]])[0])
    for pt in profile_zy(right[1:]):
        part = part.lineTo(*pt)
    # semicircular strand pocket at the top of the side-entry slot
    part = part.threePointArc(profile_zy([(0, sw)])[0], profile_zy([(-sw, 0)])[0])
    for pt in profile_zy(left):
        part = part.lineTo(*pt)
    part = part.close().extrude(p["YOKE_D"])

    # rod seats: M24x1.5 tapped, modelled at tapping-drill diameter
    for z in (-CZ, CZ):
        part = part.cut(cylX(-1, p["YOKE_D"] + 1, 22.5, 0, z))
    # bearing-pad fixing holes, M8 (tapping drill 6.8), 18 deep from the front face
    for z in (-pz, pz):
        for y in (-18, 18):
            part = part.cut(cylX(-1, 18, 6.8, y, z))
    # lightening pockets, 45 deep from the rear face, R8 corners
    for z0, z1 in ((48, 115), (-115, -48)):
        part = part.cut(roundedBoxX(p["YOKE_D"] - 50, p["YOKE_D"] + 1, 14, 78, z0, z1))
    return part


# ==========================================================================
# P2 — REAR CROSSBEAM / MANIFOLD
# ==========================================================================
def crossbeam(p=P, s=S):
    x0, x1 = s["beam0"], s["beam1"]
    W, H = p["BEAM_W"] / 2, p["BEAM_H"] / 2
    part = boxX(x0, x1, -H, H, -W, W)

    # cylinder bosses: M70x2 tapped 30 deep, then the bore end 10 deep
    for z in (-CZ, CZ):
        part = part.cut(cylX(x0 - 1, x0 + p["THREAD_ENG"], p["TUBE_OD"], 0, z))
        part = part.cut(cylX(x0 + p["THREAD_ENG"], x0 + p["THREAD_ENG"] + 10, p["BORE"], 0, z))
    # centre: release-tube guide from the front, gripper thread from the rear
    part = part.cut(cylX(x0 - 1, x0 + 45, 26.0))
    part = part.cut(cylX(x0 + 45, x1 + 1, p["GRIP_THREAD_D"] - 1.5))

    # hydraulic galleries, all Ø6
    ch_x = x0 + p["THREAD_ENG"] + 5          # X of the cap-side chamber
    g = p["GALLERY_D"]
    part = part.cut(cylY(H + 1, 55, g, x=ch_x, z=0))            # port A drop
    part = part.cut(cylZ(-CZ, CZ, g, x=ch_x, y=55))             # port A cross-drill
    for z in (-CZ, CZ):
        part = part.cut(cylY(56, 20, g, x=ch_x, z=z))           # into each chamber
    rb_x = x1 - 20
    part = part.cut(cylY(H + 1, 70, g, x=rb_x, z=0))            # port B drop
    part = part.cut(cylZ(-110, 110, g, x=rb_x, y=70))           # port B cross-drill
    for z in (-110, 110):
        part = part.cut(cylX(x0 - 1, rb_x + 1, g, y=70, z=z))   # forward to the side outlets
    # lightening pockets, 25 deep from the rear face
    for z0, z1 in ((38, 116), (-116, -38)):
        part = part.cut(roundedBoxX(x1 - 35, x1 + 1, -66, 66, z0, z1))
    return part

# ==========================================================================
# P3 — CYLINDER TUBE
# ==========================================================================
def cylinder_tube(p=P, s=S):
    t = cylX(s["tube0"], s["tube1"], p["TUBE_OD"], 0, CZ)
    t = t.cut(cylX(s["tube0"] - 1, s["tube1"] + 1, p["BORE"], 0, CZ))
    # thread reliefs mark the M70x2 zones at both ends
    for a, b in ((s["tube0"], s["tube0"] + p["THREAD_ENG"]),
                 (s["tube1"] - p["THREAD_ENG"], s["tube1"])):
        t = t.cut(cylX(a, b, p["TUBE_OD"] + 2, 0, CZ)
                  .cut(cylX(a - 1, b + 1, p["TUBE_OD"] - 0.8, 0, CZ)))
    return t

# ==========================================================================
# P4 — PISTON ROD
# ==========================================================================
def piston_rod(p=P, s=S):
    a, b = s["rod0"], s["rod1"]
    th, sh = p["ROD_NOSE_TH"], p["ROD_SHLD_D"]
    x1 = a + p["ROD_NOSE_ENG"]
    x2 = x1 + p["ROD_SHLD_L"]
    x3 = b - p["PISTON_L"]
    r = cylX(a, x1, th - 1.6, 0, CZ)               # M24x1.5 nose thread (minor dia)
    r = r.union(cylX(x1, x2, sh, 0, CZ))           # shoulder flange
    r = r.union(cylX(x2, x3, p["ROD"], 0, CZ))     # Ø32 chromed body
    r = r.union(cylX(x3, b, th - 1.6, 0, CZ))      # M24x1.5 piston thread (minor dia)
    return r

# ==========================================================================
# P5 — PISTON
# ==========================================================================
def piston(p=P, s=S):
    a, b = s["pist0"], s["pist1"]
    pi = cylX(a, b, p["BORE"] - 0.2, 0, CZ)
    pi = pi.cut(cylX(a - 1, b + 1, p["ROD_NOSE_TH"] - 1.5, 0, CZ))   # M24x1.5 bore
    # seal grooves: guide / Glyd ring / guide
    pi = pi.cut(cylX(a + 2, a + 11.7, p["BORE"] + 2, 0, CZ)
                .cut(cylX(a + 1, a + 12.7, 45.0, 0, CZ)))
    pi = pi.cut(cylX(a + 15.4, a + 19.6, p["BORE"] + 2, 0, CZ)
                .cut(cylX(a + 14.4, a + 20.6, 38.7, 0, CZ)))
    pi = pi.cut(cylX(b - 11.7, b - 2, p["BORE"] + 2, 0, CZ)
                .cut(cylX(b - 12.7, b - 1, 45.0, 0, CZ)))
    return pi

# ==========================================================================
# P6 — GLAND CAP
# ==========================================================================
def gland_cap(p=P, s=S):
    a, b = s["gland0"], s["gland1"]
    thr = b - p["THREAD_ENG"]
    g = cylX(a, b, p["GLAND_OD"], 0, CZ)
    g = g.cut(cylX(thr, b + 1, p["TUBE_OD"], 0, CZ))       # M70x2 over the tube OD
    g = g.cut(cylX(a - 1, thr, p["ROD"], 0, CZ))           # rod bore
    # seal stack, front to back: wiper / guide / rod seal / buffer
    for off, wid, dia in ((1.0, 7.0, 40.0), (11.0, 9.7, 37.0),
                          (23.0, 6.3, 41.5), (32.0, 6.3, 42.5)):
        g = g.cut(cylX(a + off, a + off + wid, dia, 0, CZ)
                  .cut(cylX(a + off - 1, a + off + wid + 1, p["ROD"], 0, CZ)))
    # face O-ring groove on the shoulder the tube end butts against
    g = g.cut(cylX(thr, thr + 2.2, 57.0, 0, CZ)
              .cut(cylX(thr - 1, thr + 3.2, 53.2, 0, CZ)))
    # retract port, Ø6 radial, on the pressure side of the buffer seal
    port = cylY(p["GLAND_OD"], p["ROD"] / 2 - 2, p["GALLERY_D"], x=thr - 3.5, z=CZ)
    return g.cut(port)

# ==========================================================================
# P7 — BEARING PAD
# ==========================================================================
def bearing_pad(p=P):
    pad = boxX(-p["PAD_T"], 0, -p["PAD_Y"] / 2, p["PAD_Y"] / 2,
               p["PAD_OFFSET"] - p["PAD_Z"] / 2, p["PAD_OFFSET"] + p["PAD_Z"] / 2)
    for y in (-18, 18):
        pad = pad.cut(cylX(-p["PAD_T"] - 1, 1, 9.0, y, p["PAD_OFFSET"]))
        pad = pad.cut(cylX(-p["PAD_T"] - 1, -p["PAD_T"] + 6, 14.0, y, p["PAD_OFFSET"]))
    return pad

# ==========================================================================
# P8 — GRIPPER BARREL
# ==========================================================================
def gripper_barrel(p=P, s=S):
    a, b = s["grip0"], s["grip1"]
    body0 = s["beam1"]
    g = cylX(a, body0, p["GRIP_THREAD_D"] - 2.0)          # M60x1.5 spigot (minor dia)
    g = g.union(cylX(body0, b, p["GRIP_OD"]))
    import math
    d_large = p["WEDGE_SMALL"] + 2 * p["WEDGE_L"] * math.tan(math.radians(p["TAPER_INC"] / 2))
    g = g.cut(coneX(a, a + p["WEDGE_L"], p["WEDGE_SMALL"], d_large))
    g = g.cut(cylX(a + p["WEDGE_L"], b - 18, d_large + 2.5))
    g = g.cut(cylX(b - 18, b + 1, 52.0))                  # M52x1.5 end-cap thread
    return g

# ==========================================================================
# P10 — STOP SPACER RING
# ==========================================================================
def stop_ring(p=P, s=S):
    r = cylX(s["stop0"], s["stop1"], p["BORE"] - 0.2, 0, CZ)
    return r.cut(cylX(s["stop0"] - 1, s["stop1"] + 1, p["ROD"] + 2, 0, CZ))

# ==========================================================================
# build, report, export
# ==========================================================================
def mirror_z(part):
    return part.mirror(mirrorPlane="XY", basePointVector=(0, 0, 0))

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_STEP = os.path.normpath(os.path.join(HERE, "..", "step"))
OUT_DXF  = os.path.normpath(os.path.join(HERE, "..", "dxf"))

PARTS = [
    ("P1-nose-yoke",       nose_yoke(),      "al7075", 1),
    ("P2-crossbeam",       crossbeam(),      "al7075", 1),
    ("P3-cylinder-tube",   cylinder_tube(),  "steel",  2),
    ("P4-piston-rod",      piston_rod(),     "steel",  2),
    ("P5-piston",          piston(),         "steel",  2),
    ("P6-gland-cap",       gland_cap(),      "al7075", 2),
    ("P7-bearing-pad",     bearing_pad(),    "steel",  2),
    ("P8-gripper-barrel",  gripper_barrel(), "steel",  1),
    ("P10-stop-ring",      stop_ring(),      "steel",  2),
]

def main():
    os.makedirs(OUT_STEP, exist_ok=True)
    os.makedirs(OUT_DXF, exist_ok=True)
    report, total = [], 0.0
    asm = cq.Assembly()
    for name, wp, mat, qty in PARTS:
        solid = wp.val()
        vol = solid.Volume()
        mass = vol * RHO[mat] * qty
        total += mass
        report.append(dict(part=name, qty=qty, material=mat,
                           volume_mm3=round(vol, 1), mass_kg=round(mass, 3)))
        cq.exporters.export(wp, os.path.join(OUT_STEP, name + ".step"))
        asm.add(wp, name=name)
        if qty == 2 and abs(wp.val().Center().z) > 1:      # mirror the paired parts
            asm.add(mirror_z(wp), name=name + "-mirror")
    asm.save(os.path.join(OUT_STEP, "PT-JACK-250-assembly.step"))

    print(f"{'part':22s} {'qty':>3s} {'material':9s} {'volume mm3':>12s} {'mass kg':>8s}")
    for r in report:
        print(f"{r['part']:22s} {r['qty']:3d} {r['material']:9s} "
              f"{r['volume_mm3']:12.1f} {r['mass_kg']:8.3f}")
    print(f"{'MODELLED SUBTOTAL':22s} {'':3s} {'':9s} {'':12s} {total:8.3f}")
    print()
    print("stations (mm along X):")
    for k in sorted(S):
        print(f"   {k:14s} {S[k]:8.1f}")
    with open(os.path.join(HERE, "mass_report.json"), "w") as f:
        json.dump(dict(parts=report, subtotal_kg=round(total, 3),
                       stations={k: round(v, 1) for k, v in S.items()},
                       params=P), f, indent=2)

if __name__ == "__main__":
    main()
