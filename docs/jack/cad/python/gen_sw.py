#!/usr/bin/env python3
"""
PT-JACK-250 — generates the SolidWorks-facing deliverables from the same
parameter set used by pt_jack_250.py:

    ../dxf/*.dxf              2D profiles, import straight into a SW sketch
    ../macros/*.bas           VBA macros that rebuild each part inside SW
    ../equations/*.txt        global variables for SW Equations > Import

Run after pt_jack_250.py:   python gen_sw.py
"""
import os, math, ezdxf
from pt_jack_250 import P, S, CZ

HERE = os.path.dirname(os.path.abspath(__file__))
DXF  = os.path.normpath(os.path.join(HERE, "..", "dxf"))
BAS  = os.path.normpath(os.path.join(HERE, "..", "macros"))
EQN  = os.path.normpath(os.path.join(HERE, "..", "equations"))
for d in (DXF, BAS, EQN):
    os.makedirs(d, exist_ok=True)

TAPER_H = math.tan(math.radians(P["TAPER_INC"] / 2.0))
D_LARGE = P["WEDGE_SMALL"] + 2 * P["WEDGE_L"] * TAPER_H

# ==========================================================================
# profiles — every profile is a closed list of (x, y) points in mm
# ==========================================================================
def yoke_outline():
    W, TOP, BB, BOT = P["YOKE_W"] / 2, P["YOKE_TOP"], P["BRIDGE_BOT"], P["YOKE_BOT"]
    sw, ch = P["SLOT_W"] / 2, 20.0
    lz0, lz1 = P["PAD_OFFSET"] - P["PAD_Z"] / 2, P["PAD_OFFSET"] + P["PAD_Z"] / 2
    return ([(-W, TOP - ch), (-W + ch, TOP), (W - ch, TOP), (W, TOP - ch),
             (W, BB), (lz1, BB), (lz1, BOT), (lz0, BOT), (lz0, BB), (sw, BB), (sw, 0)],
            [(-sw, 0), (-sw, BB), (-lz0, BB), (-lz0, BOT), (-lz1, BOT), (-lz1, BB), (-W, BB)])

def beam_outline():
    W, H = P["BEAM_W"] / 2, P["BEAM_H"] / 2
    return [(-W, -H), (W, -H), (W, H), (-W, H)]

def tube_profile():
    L, ri, ro = P["TUBE_L"], P["BORE"] / 2, P["TUBE_OD"] / 2
    return [(0, ri), (L, ri), (L, ro), (0, ro)]

def rod_profile():
    L  = S["rod1"] - S["rod0"]
    rn = (P["ROD_NOSE_TH"] - 1.6) / 2
    rs, rb = P["ROD_SHLD_D"] / 2, P["ROD"] / 2
    a, b = P["ROD_NOSE_ENG"], P["ROD_NOSE_ENG"] + P["ROD_SHLD_L"]
    c = L - P["PISTON_L"]
    return [(0, 0), (0, rn), (a, rn), (a, rs), (b, rs), (b, rb),
            (c, rb), (c, rn), (L, rn), (L, 0)]

def piston_profile():
    L, ro = P["PISTON_L"], (P["BORE"] - 0.2) / 2
    ri = (P["ROD_NOSE_TH"] - 1.5) / 2
    g1, g2 = 45.0 / 2, 38.7 / 2
    pts = [(0, ri), (L, ri), (L, ro)]
    for x0, x1, r in ((L - 11.7, L - 2.0, g1), (19.6, 15.4, g2), (11.7, 2.0, g1)):
        pts += [(x0, ro), (x0, r), (x1, r), (x1, ro)]
    pts += [(0, ro)]
    return pts

def gland_profile():
    L, ro, rb = P["GLAND_L"], P["GLAND_OD"] / 2, P["ROD"] / 2
    thr = L - P["THREAD_ENG"]
    rt = P["TUBE_OD"] / 2
    pts = [(0, rb)]
    for off, wid, dia in ((1.0, 7.0, 40.0), (11.0, 9.7, 37.0),
                          (23.0, 6.3, 41.5), (32.0, 6.3, 42.5)):
        pts += [(off, rb), (off, dia / 2), (off + wid, dia / 2), (off + wid, rb)]
    pts += [(thr, rb), (thr, 26.6), (thr + 2.2, 26.6), (thr + 2.2, 28.5), (thr, 28.5),
            (thr, rt), (L, rt), (L, ro), (0, ro)]
    return pts

def gripper_profile():
    sp, bl = P["GRIP_THREAD_L"], P["GRIP_L"]
    L = sp + bl
    rs, rb = (P["GRIP_THREAD_D"] - 2.0) / 2, P["GRIP_OD"] / 2
    return [(0, P["WEDGE_SMALL"] / 2), (P["WEDGE_L"], D_LARGE / 2),
            (P["WEDGE_L"], D_LARGE / 2 + 1.25), (L - 18, D_LARGE / 2 + 1.25),
            (L - 18, 26.0), (L, 26.0), (L, rb), (sp, rb), (sp, rs), (0, rs)]

def stopring_profile():
    return [(0, (P["ROD"] + 2) / 2), (40, (P["ROD"] + 2) / 2),
            (40, (P["BORE"] - 0.2) / 2), (0, (P["BORE"] - 0.2) / 2)]

def pad_outline():
    z, y = P["PAD_Z"] / 2, P["PAD_Y"] / 2
    return [(-z, -y), (z, -y), (z, y), (-z, y)]

REVOLVES = [
    ("P3-cylinder-tube",  tube_profile(),     "Cylinder tube Ø50/Ø70 x 310"),
    ("P4-piston-rod",     rod_profile(),      "Piston rod Ø32"),
    ("P5-piston",         piston_profile(),   "Piston Ø49.8 with seal grooves"),
    ("P6-gland-cap",      gland_profile(),    "Gland cap Ø86 with seal stack"),
    ("P8-gripper-barrel", gripper_profile(),  "Gripper barrel Ø65 x 75, 7 deg taper"),
    ("P10-stop-ring",     stopring_profile(), "Stroke stop spacer ring"),
]

# ==========================================================================
# DXF
# ==========================================================================
def rounded_rect(msp, x0, x1, y0, y1, r, layer):
    msp.add_line((x0 + r, y0), (x1 - r, y0), dxfattribs={"layer": layer})
    msp.add_line((x1, y0 + r), (x1, y1 - r), dxfattribs={"layer": layer})
    msp.add_line((x1 - r, y1), (x0 + r, y1), dxfattribs={"layer": layer})
    msp.add_line((x0, y1 - r), (x0, y0 + r), dxfattribs={"layer": layer})
    for cx, cy, a0, a1 in ((x1 - r, y0 + r, 270, 360), (x1 - r, y1 - r, 0, 90),
                           (x0 + r, y1 - r, 90, 180), (x0 + r, y0 + r, 180, 270)):
        msp.add_arc((cx, cy), r, a0, a1, dxfattribs={"layer": layer})

def new_doc():
    doc = ezdxf.new("R2000", setup=True)
    for name, col in (("OUTLINE", 7), ("HOLES", 1), ("POCKETS", 3), ("AXIS", 5), ("NOTE", 8)):
        if name not in doc.layers:
            doc.layers.add(name, color=col)
    return doc

def poly(msp, pts, layer="OUTLINE", closed=True):
    msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})

def write_dxf():
    # --- P1 nose yoke, front view (x = Z, y = Y) --------------------------
    doc = new_doc(); msp = doc.modelspace()
    right, left = yoke_outline()
    sw = P["SLOT_W"] / 2
    for a, b in zip(right, right[1:]):
        if a != b:
            msp.add_line(a, b, dxfattribs={"layer": "OUTLINE"})
    msp.add_arc((0, 0), sw, 0, 180, dxfattribs={"layer": "OUTLINE"})
    for a, b in zip(left, left[1:]):
        if a != b:
            msp.add_line(a, b, dxfattribs={"layer": "OUTLINE"})
    msp.add_line(left[-1], right[0], dxfattribs={"layer": "OUTLINE"})
    for z in (-CZ, CZ):
        msp.add_circle((z, 0), 22.5 / 2, dxfattribs={"layer": "HOLES"})
    for z in (-P["PAD_OFFSET"], P["PAD_OFFSET"]):
        for y in (-18, 18):
            msp.add_circle((z, y), 6.8 / 2, dxfattribs={"layer": "HOLES"})
    for z0, z1 in ((48, 115), (-115, -48)):
        rounded_rect(msp, z0, z1, 14, 78, 8, "POCKETS")
    msp.add_text("P1 NOSE YOKE - extrude 75 mm - pockets 50 deep from rear face",
                 height=6, dxfattribs={"layer": "NOTE"}).set_placement((-P["YOKE_W"] / 2, 105))
    doc.saveas(os.path.join(DXF, "P1-nose-yoke-profile.dxf"))

    # --- P2 crossbeam, front view ----------------------------------------
    doc = new_doc(); msp = doc.modelspace()
    poly(msp, beam_outline())
    for z in (-CZ, CZ):
        msp.add_circle((z, 0), P["TUBE_OD"] / 2, dxfattribs={"layer": "HOLES"})
        msp.add_circle((z, 0), P["BORE"] / 2, dxfattribs={"layer": "HOLES"})
    msp.add_circle((0, 0), 26.0 / 2, dxfattribs={"layer": "HOLES"})
    msp.add_circle((0, 0), (P["GRIP_THREAD_D"] - 1.5) / 2, dxfattribs={"layer": "HOLES"})
    for z0, z1 in ((38, 116), (-116, -38)):
        rounded_rect(msp, z0, z1, -66, 66, 8, "POCKETS")
    msp.add_text("P2 CROSSBEAM - extrude 80 mm - M70x2 bores 30 deep - pockets 35 deep from rear",
                 height=6, dxfattribs={"layer": "NOTE"}).set_placement((-P["BEAM_W"] / 2, 100))
    doc.saveas(os.path.join(DXF, "P2-crossbeam-profile.dxf"))

    # --- P7 bearing pad ---------------------------------------------------
    doc = new_doc(); msp = doc.modelspace()
    poly(msp, pad_outline())
    for y in (-18, 18):
        msp.add_circle((0, y), 4.5, dxfattribs={"layer": "HOLES"})
        msp.add_circle((0, y), 7.0, dxfattribs={"layer": "HOLES"})
    msp.add_text("P7 BEARING PAD - extrude 12 mm - 16MnCr5 case hardened HRC 55-58",
                 height=3, dxfattribs={"layer": "NOTE"}).set_placement((-15, 30))
    doc.saveas(os.path.join(DXF, "P7-bearing-pad.dxf"))

    # --- revolve half-profiles -------------------------------------------
    for name, pts, note in REVOLVES:
        doc = new_doc(); msp = doc.modelspace()
        poly(msp, pts)
        xmax = max(p[0] for p in pts)
        msp.add_line((-10, 0), (xmax + 10, 0), dxfattribs={"layer": "AXIS"})
        msp.add_text(note + "  -  REVOLVE 360 deg about the AXIS layer line",
                     height=3, dxfattribs={"layer": "NOTE"}).set_placement((0, -12))
        doc.saveas(os.path.join(DXF, name + "-revolve.dxf"))

# ==========================================================================
# SolidWorks global variables
# ==========================================================================
def write_equations():
    lines = ['\'PT-JACK-250 global variables — SolidWorks: Tools > Equations > Import',
             '\'Every dimension in the macros and drawings derives from these.']
    for k, v in P.items():
        lines.append(f'"{k}"= {v}')
    lines += [f'"CYL_HALF"= "CYL_CC" / 2',
              f'"D_TAPER_LARGE"= "WEDGE_SMALL" + 2 * "WEDGE_L" * tan(("TAPER_INC"/2) * pi/180)',
              f'"L_RETRACTED"= {S["L_retracted"]}',
              f'"L_EXTENDED"= {S["L_extended"]}']
    with open(os.path.join(EQN, "PT-JACK-250-globals.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

# ==========================================================================
# VBA macros
# ==========================================================================
HEADER = '''Attribute VB_Name = "{mod}"
'==========================================================================
' PT-JACK-250  —  {title}
'
' Generated from docs/jack/cad/python/gen_sw.py. Units in the API are METRES.
'
' HOW TO RUN
'   1. SolidWorks > Tools > Macro > New...  (save as {mod}.swp)
'   2. In the VBA editor: File > Import File... and pick this .bas
'   3. Run Sub main
'
' The macro creates a NEW part and builds the feature tree. Late binding is
' used throughout so no type-library reference is required, and reference
' planes are picked by position rather than by name, so it works on any
' language template.
'
' NOT TESTED AGAINST A LIVE SOLIDWORKS INSTALL — see cad/README.md. If a
' call fails, the STEP file of the same part is the fallback.
'==========================================================================
Option Explicit

Dim swApp As Object
Dim swModel As Object

Private Function NewPartDoc() As Object
    Dim tpl As String
    tpl = swApp.GetUserPreferenceStringValue(8)      'swDefaultTemplatePart
    Set NewPartDoc = swApp.NewDocument(tpl, 0, 0, 0)
End Function

Private Function SelectPlane(ByVal idx As Integer) As Boolean
    'idx 1 = Front, 2 = Top, 3 = Right (order is template-independent)
    Dim swFeat As Object, n As Integer
    Set swFeat = swModel.FirstFeature
    n = 0
    Do While Not swFeat Is Nothing
        If swFeat.GetTypeName2 = "RefPlane" Then
            n = n + 1
            If n = idx Then
                SelectPlane = swFeat.Select2(False, 0)
                Exit Function
            End If
        End If
        Set swFeat = swFeat.GetNextFeature
    Loop
    SelectPlane = False
End Function

Private Sub SelectLastFeature()
    Dim swFeat As Object
    Set swFeat = swModel.FeatureByPositionReverse(0)
    swFeat.Select2 False, -1
End Sub
'''

REVOLVE_BODY = '''
Sub main()
    Set swApp = Application.SldWorks
    Set swModel = NewPartDoc()
    If swModel Is Nothing Then
        MsgBox "No part template found. Set one in Tools > Options > File Locations."
        Exit Sub
    End If

    swModel.ClearSelection2 True
    SelectPlane 1                                  'Front plane
    swModel.SketchManager.InsertSketch True
    swModel.SketchManager.CreateCenterLine {cl0}, 0#, 0#, {cl1}, 0#, 0#
{lines}
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature

    swModel.FeatureManager.FeatureRevolve2 True, True, False, False, False, False, _
        0, 0, 6.28318530717959, 0, False, False, 0, 0, 0, 0, 0, False, True, True

    swModel.ViewZoomtofit2
    swModel.ClearSelection2 True
    MsgBox "{title} built. Save as {mod}.SLDPRT."
End Sub
'''

def m(v):      # mm -> metres, VBA literal
    return f"{v/1000.0:.6f}"

def revolve_macro(mod, pts, title):
    segs = []
    closed = pts + [pts[0]]
    for a, b in zip(closed, closed[1:]):
        if abs(a[0]-b[0]) < 1e-9 and abs(a[1]-b[1]) < 1e-9:
            continue
        segs.append(f"    swModel.SketchManager.CreateLine {m(a[0])}, {m(a[1])}, 0#, "
                    f"{m(b[0])}, {m(b[1])}, 0#")
    xmax = max(p[0] for p in pts)
    body = REVOLVE_BODY.format(cl0=m(-10), cl1=m(xmax + 10),
                               lines="\n".join(segs), title=title, mod=mod)
    return HEADER.format(mod=mod, title=title) + body

PLATE_BODY = '''
Sub main()
    Dim i As Integer
    Set swApp = Application.SldWorks
    Set swModel = NewPartDoc()
    If swModel Is Nothing Then
        MsgBox "No part template found. Set one in Tools > Options > File Locations."
        Exit Sub
    End If

    '--- base profile, extruded {depth} mm -------------------------------------
    swModel.ClearSelection2 True
    SelectPlane 1
    swModel.SketchManager.InsertSketch True
{outline}
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature
    swModel.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, {depth_m}, 0.01, _
        False, False, False, False, 0.0174532925199433, 0.0174532925199433, _
        False, False, False, False, True, True, True, 0, 0, False

{cuts}
    swModel.ViewZoomtofit2
    swModel.ClearSelection2 True
    MsgBox "{title} built." & vbCrLf & _
           "Still to add by hand: tapped-thread callouts, the lightening pockets," & vbCrLf & _
           "and R8 fillets on internal corners (see cad/README.md)."
End Sub
'''

def cut_block(comment, sketch_lines, through=True, depth_m=None):
    out = [f"    '--- {comment} " + "-" * max(0, 60 - len(comment)),
           "    swModel.ClearSelection2 True",
           "    SelectPlane 1",
           "    swModel.SketchManager.InsertSketch True"]
    out += sketch_lines
    out += ["    swModel.SketchManager.InsertSketch True",
            "    swModel.ClearSelection2 True",
            "    SelectLastFeature"]
    if through:
        out.append("    swModel.FeatureManager.FeatureCut4 False, False, True, 1, 1, 0.01, 0.01, _")
    else:
        out.append(f"    swModel.FeatureManager.FeatureCut4 True, False, False, 0, 0, {depth_m}, 0.01, _")
    out += ["        False, False, False, False, 0.0174532925199433, 0.0174532925199433, _",
            "        False, False, False, False, False, True, True, True, True, True, _",
            "        False, 0, 0, False",
            ""]
    return "\n".join(out)

def circle_line(cx, cy, d):
    return (f"    swModel.SketchManager.CreateCircleByRadius {m(cx)}, {m(cy)}, 0#, {m(d/2)}")

def yoke_macro():
    right, left = yoke_outline()
    sw = P["SLOT_W"] / 2
    L = []
    seq = right
    for a, b in zip(seq, seq[1:]):
        if a != b:
            L.append(f"    swModel.SketchManager.CreateLine {m(a[0])}, {m(a[1])}, 0#, {m(b[0])}, {m(b[1])}, 0#")
    L.append(f"    swModel.SketchManager.CreateArc 0#, 0#, 0#, {m(sw)}, 0#, 0#, {m(-sw)}, 0#, 0#, 1")
    for a, b in zip(left, left[1:]):
        if a != b:
            L.append(f"    swModel.SketchManager.CreateLine {m(a[0])}, {m(a[1])}, 0#, {m(b[0])}, {m(b[1])}, 0#")
    L.append(f"    swModel.SketchManager.CreateLine {m(left[-1][0])}, {m(left[-1][1])}, 0#, {m(right[0][0])}, {m(right[0][1])}, 0#")

    cuts = cut_block("rod seats M24x1.5 - tapping drill 22.5, THROUGH (tap 45 deep)",
                     [circle_line(-CZ, 0, 22.5), circle_line(CZ, 0, 22.5)])
    pad = [circle_line(z, y, 6.8) for z in (-P["PAD_OFFSET"], P["PAD_OFFSET"]) for y in (-18, 18)]
    cuts += cut_block("bearing-pad fixing holes M8 - tapping drill 6.8, 18 deep",
                      pad, through=False, depth_m=m(18))
    return HEADER.format(mod="P1_NoseYoke", title="P1 nose yoke") + \
        PLATE_BODY.format(outline="\n".join(L), depth=P["YOKE_D"], depth_m=m(P["YOKE_D"]),
                          cuts=cuts, title="P1 nose yoke")

def beam_macro():
    W, H = P["BEAM_W"] / 2, P["BEAM_H"] / 2
    pts = beam_outline() + [beam_outline()[0]]
    L = [f"    swModel.SketchManager.CreateLine {m(a[0])}, {m(a[1])}, 0#, {m(b[0])}, {m(b[1])}, 0#"
         for a, b in zip(pts, pts[1:])]
    cuts = cut_block("cylinder bosses M70x2 - 30 deep",
                     [circle_line(-CZ, 0, P["TUBE_OD"]), circle_line(CZ, 0, P["TUBE_OD"])],
                     through=False, depth_m=m(P["THREAD_ENG"]))
    cuts += cut_block("chamber ends Ø50 - a further 10 deep",
                      [circle_line(-CZ, 0, P["BORE"]), circle_line(CZ, 0, P["BORE"])],
                      through=False, depth_m=m(P["THREAD_ENG"] + 10))
    cuts += cut_block("release-tube guide Ø26 - 45 deep from the front face",
                      [circle_line(0, 0, 26.0)], through=False, depth_m=m(45))
    cuts += cut_block("gripper thread M60x1.5 - THROUGH (change to 35 deep from the rear)",
                      [circle_line(0, 0, P["GRIP_THREAD_D"] - 1.5)])
    return HEADER.format(mod="P2_Crossbeam", title="P2 rear crossbeam / manifold") + \
        PLATE_BODY.format(outline="\n".join(L), depth=P["BEAM_D"], depth_m=m(P["BEAM_D"]),
                          cuts=cuts, title="P2 rear crossbeam")

ASM = '''Attribute VB_Name = "PT_JACK_Assembly"
'==========================================================================
' PT-JACK-250 — assembly helper
'
' Inserts the eight saved parts into a new assembly AT THE ORIGIN. It does
' NOT position or mate them: each part macro builds its part in its own
' natural orientation (turned parts revolve about X, plate parts extrude
' along Z), so a blind coordinate insert would place them inconsistently.
'
' For a CORRECTLY POSITIONED assembly, open instead:
'     cad/step/PT-JACK-250-assembly.step
' which carries every part at its retracted station. Use this macro only if
' you want to mate the macro-built parts yourself.
'
' Station table for manual positioning (mm along the jack axis, 0 = front
' face of the nose yoke, retracted):
{stationtbl}
'
' Edit PARTS_DIR below, then run main.
'==========================================================================
Option Explicit

Const PARTS_DIR As String = "C:\\PT-JACK-250\\parts\\"

Dim swApp As Object
Dim swAsm As Object

Private Sub Ins(ByVal fname As String)
    Dim swComp As Object
    swApp.OpenDoc6 PARTS_DIR & fname, 1, 32, "", 0, 0
    Set swComp = swAsm.AddComponent5(PARTS_DIR & fname, 0, "", False, "", 0#, 0#, 0#)
    If swComp Is Nothing Then MsgBox "Could not insert " & fname
End Sub

Sub main()
    Dim tpl As String
    Set swApp = Application.SldWorks
    tpl = swApp.GetUserPreferenceStringValue(10)     'swDefaultTemplateAssembly
    Set swAsm = swApp.NewDocument(tpl, 0, 0, 0)
    If swAsm Is Nothing Then
        MsgBox "No assembly template found."
        Exit Sub
    End If

{inserts}
    swAsm.ForceRebuild3 True
    swAsm.ViewZoomtofit2
    MsgBox "Parts inserted at the origin — mate them using the station table" & vbCrLf & _
           "in this macro's header, or open cad/step/PT-JACK-250-assembly.step" & vbCrLf & _
           "for the positioned assembly." & vbCrLf & vbCrLf & _
           "Overall length: retracted {Lr} mm, extended {Le} mm."
End Sub
'''

def asm_macro():
    files = ["P1-nose-yoke", "P2-crossbeam", "P3-cylinder-tube", "P4-piston-rod",
             "P5-piston", "P6-gland-cap", "P7-bearing-pad", "P8-gripper-barrel",
             "P10-stop-ring"]
    ins = "\n".join(f'    Ins "{n}.SLDPRT"' for n in files)
    keys = ["yoke0", "yoke1", "gland0", "gland1", "tube0", "stop0", "stop1",
            "pist0", "pist1", "tube1", "beam0", "beam1", "grip0", "grip1",
            "rod0", "rod1"]
    tbl = "\n".join(f"'   {k:10s} X = {S[k]:7.1f}" for k in keys)
    tbl += f"\n'   cylinder axes at Z = +/- {CZ:.0f}"
    return ASM.format(inserts=ins, Lr=S["L_retracted"], Le=S["L_extended"], stationtbl=tbl)

def write_macros():
    for mod, pts, title in REVOLVES:
        name = mod.replace("-", "_")
        with open(os.path.join(BAS, mod + ".bas"), "w") as f:
            f.write(revolve_macro(name, pts, title))
    with open(os.path.join(BAS, "P1-nose-yoke.bas"), "w") as f:
        f.write(yoke_macro())
    with open(os.path.join(BAS, "P2-crossbeam.bas"), "w") as f:
        f.write(beam_macro())
    with open(os.path.join(BAS, "PT-JACK-250-assembly.bas"), "w") as f:
        f.write(asm_macro())

if __name__ == "__main__":
    write_dxf(); write_equations(); write_macros()
    print("DXF  ->", DXF)
    for f in sorted(os.listdir(DXF)):  print("   ", f)
    print("BAS  ->", BAS)
    for f in sorted(os.listdir(BAS)):  print("   ", f)
    print("EQN  ->", EQN)
    for f in sorted(os.listdir(EQN)):  print("   ", f)
