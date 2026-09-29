---
name: spantech-pt
description: Span Tech post-tensioned slab workflow. Use whenever the user (Span Tech, PT design office) sends AutoCAD DWG/DXF slab drawings to convert into clean per-zone DXFs or RAM Concept models, asks about PT Suite (Auto PT Suite), PT Model Builder, the drawing reader, design strips, tendons, pour strips, levels, drops or loads, or asks to change those programs. Covers the office rules, the conversion pipeline, how to check results and how to talk and deliver.
---

# Span Tech — PT drawings → RAM Concept

You work with the Span Tech structural office (post-tensioned slabs). The work is:

1. **Drawing → clean zone DXFs**: the architect's/structural AutoCAD drawing (DWG or DXF, any layer names) is read and turned into one clean DXF per zone, all in mm, on fixed layers (`PT-Clean-*`).
2. **Zone DXFs → RAM Concept models** with *PT Model Builder* (stand-alone) or with *Auto PT Suite* ("PT Suite", the main program: structure + tendons + design).
3. Changing / fixing those programs when the engineer finds something wrong in RAM.

The pipeline code is in `scripts/` (Python, see "Running the pipeline"). The full rules are in `references/RULES.md`, the step-by-step flow in `references/FLOW.md`. Read the relevant section before changing a rule, and add the new rule there with its reason (the project where it came from).

---

## 1. How to talk and work with the user

- **Reply in Egyptian Arabic, simple and short.** Technical names (DXF, RAM, KFr, SE, P=…) stay in English. Questions to the user go in plain Arabic in the chat, one at a time, with the options spelled out.
- **Never guess.** If the drawing does not say it (thickness, depth, level, load, which beam), use the program default and write a **REVIEW** line, or ask. A wrong number in a model is worse than a missing one.
- **Be honest about what was tested.** Say exactly what you checked (image, numbers, offline test) and what you could not (e.g. "RAM is not installed here, I could not build the model"). Never say "fixed" without a check.
- **Find the real cause before fixing.** When the user sends a RAM screenshot saying something is wrong, reproduce it on the file, find where in the code it comes from, fix it for every project (not only this one), and show before/after numbers.
- **Every fix must keep the old projects working** (see §6 regression).
- **Deliverables:**
  - After a program change: send **only the programs**: `Auto_PT_Suite_…_patched.py`, `PT_Model_Builder.zip`, and `drawing_reader_tools.zip` if the reader changed.
  - Project output files (zone DXF zips) only when the user asks for them or for a new drawing.
  - For a new drawing: the zip of the zone DXFs + images + `report.json`/`members.csv`, plus a short Arabic summary: zones, CHECK OK/FAILED, what is REVIEW, questions.
- End every answer with what you need from the user (if anything).

---

## 2. Office rules (what the engineer asked for — do not break them)

### Reading the drawing
- **No reliance on layer names.** Everything is recognised from shape + text (labels, hatches, blocks, mirrored blocks included: hatches inside blocks with extrusion (0,0,-1) must be transformed OCS→WCS).
- Units detected from the median column side. All output in mm.
- Sheets (plans) found from their titles; each sheet split into zones at expansion joints.
- Beams from their labels `B9(400X900)`: label width wins unless the drawn width differs → drawn width + REVIEW. Short beams (e.g. 40×90 in HDB ground floor) are kept when an end sits on a support. A beam without depth gets `(WX?)` → program default depth.
- An "X" void must be real diagonals of a rectangle (or have drawn sides); a "+" is not a void.
- **Drops**: the drop is the closed rectangle around its `T=` note, drawn at its **full rectangular size**, even if a beam runs over it. A drop without a column/wall under it → REVIEW.
- **`T=250` inside/next to a stair = the stair slab** → part of the stair opening, not a slab zone.

### Levels
- The **dominant level of the roof = 0** (main slab). Only areas with a different level are drawn, as `LEVEL t=… SE=±… P=2`.
- **A level written on the roof covers the drops and beams inside its area** (they take its SE). A drop in a notch/corner of a level zone belongs to that zone.
- Never two slabs on top of each other at the same level unless the thickness differs.
- Main slab note: `SLAB t=300 SE=+0 P=1` + `T.O.S` value.
- Priorities always written: slab 1, level/thickness zone 2, drop 3, pour strip 4; crossing beams of equal priority: the wider/longer +1.

### Meshing (RAM rejects bad meshes)
- No overlapping slabs on the same layer; beam priorities so beams and slabs don't fight.
- No small slab slivers (especially near cores).
- Lines of structural elements that are close must be **exactly on top of each other** (slab edge on the beam/wall face, openings on beam faces, collinear beams flush, jogs ≤ 5 cm straightened).

### Loads
- From the drawing's LOADING PLAN table (SIDL / LL / usage) → layer `PT-Clean-Loads`, text `LOAD SDL=… LL=… usage`.
- **Default SDL/LL go on the whole slab; each loading-plan area carries only the difference (+ or −).** No part of the roof without load. Areas outside the plan drawn as `LOAD DEFAULT (program SDL/LL)`.
- The loads layer is **not** structural geometry (never read it as slabs).

### Design strips (support lines)
- **RAM does not accept a strip crossing from one level to another**: spans are cut at the level-step line, a splitter runs along the step.
- **Each level region is designed like a separate slab** (supports on the step line count for both sides); a region with no strip in a direction gets one through its middle.
- Strip ends stop on the centre line of a wall/column/beam, never inside it.

### Tendons
- **Tendon crossing two levels**: put it at the top cover (50 or 70 mm per settings) below the top of the lower slab at the step; check that point in the higher slab — if it is **below mid-depth** of the higher slab, **split the tendons** and design each slab separately.
- **Pour strips**: a slab area **0.8–1.2 m wide** with **KFr and KFs ≤ 0.1** (usually 0.001) is a pour strip → tendons stop at it (every layout method: sweep, field, added, guided). A new pour strip is drawn Custom with KFr = KFs = 0.001.

---

## 3. Running the pipeline (drawing → zone DXFs)

Needs Python 3.10+, `pip install ezdxf shapely matplotlib numpy`. DWG needs `dwgread` (LibreDWG; the Windows build is in `drawing_reader_tools.zip`). If you cannot read DWG here, ask the user for a DXF (AutoCAD: SAVEAS → DXF).

```bash
cd scripts
python -m pt_pipeline.convert INPUT.dwg|dxf -o OUT_DIR --keep-work
#   --drop-thickness 400       drop thickness when the drawing has none
#   --sheets sheets.json       only some plans: {"NAME": [x0, y0, x1, y1]}
#   --resume-from STEP         re-run the finish steps only (snapshots in work/snap)
```

Output in `OUT_DIR`: `<SHEET>-Z<n>_slab_clean.dxf` per zone, `images/`, `report.json` (CHECK, zones, REVIEW rows), `members.csv`.

Clean DXF layers: `PT-Clean-Boundary` (slab + `SLAB t= SE= P=`), `PT-Clean-Openings`, `PT-Clean-Columns(-Above)`, `PT-Clean-Walls(-Above)`, `PT-Clean-Beams` (`MARK(WxD) P=n [SE=…]`), `PT-Clean-Drops` (drops `DROP t= P=3`, `LEVEL t= SE= P=2`, `ZONE t=`, `POUR STRIP … RELEASE FX FY`), `PT-Clean-Loads`.

Regression over the old projects: `python -m pt_pipeline.regress projects.json -o out --baseline baseline.json` (CHECK, zone count, element counts per layer must not change without a reason).

---

## 4. Checking a result (do this before sending anything)

1. `report.json` → `ok: true` (CHECK OK). Read every REVIEW row; each one is either explained to the user or fixed.
2. Look at the zone images (`images/`) and draw your own check images (matplotlib) of the zone: boundary, openings, columns, beams, drops, level zones, loads. Compare with the original drawing around the same window.
3. Count: columns, beams per label, drops (all `T=` found?), level zones and their SE, load areas and their areas.
4. For RAM questions: parse the zone DXF the way the program does (text goes to the **smallest** polygon around it) and check every element gets the right thickness / SE / priority.
5. Say in the summary what you checked and what you could not.

---

## 5. The programs

- **Auto PT Suite** (`Auto_PT_Suite_v397_CAD_Reader_AI_patched.py`, one big Python/Tk file, licensed — never publish it). Reads DXF or an existing RAM model (`site_from_cpt`: thickness, priority, TOC, KFr/KFs), builds structure, tendons, design strips, runs RAM. Changes are kept as a patch (`auto_pt_suite_patch.diff`) on the original.
- **PT Model Builder** (`PT_Model_Builder.zip`): stand-alone, same look as PT Suite. Stage 1 runs the pipeline, stage 2 builds RAM models from zone DXFs using `ram_core.py` generated from PT Suite by `build_core.py` (so PT Suite fixes reach it after re-running `build_core.py`).
- When you change reading/strips/loads logic, change it in PT Suite (the patch), regenerate `ram_core.py`, rebuild both packages, and send both.

## 6. Before delivering a program change

- Reproduce the problem first, then show it fixed (numbers or an image).
- Run the tests (`pytest scripts/pt_pipeline/tests`, PT Model Builder `tests/`).
- Old projects: regression must stay the same or every difference must be explained.
- Update `references/RULES.md` (rule + reason) and the README of the changed program.
