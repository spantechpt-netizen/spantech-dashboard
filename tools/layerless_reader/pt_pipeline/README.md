# pt_pipeline: من المخطط لـ RAM Concept بأمر واحد

بياخد مخطط إنشائي أو معماري (DWG أو DXF، شيت واحد أو شيت فيه كذا دور)
ويطلّع ملف DXF نضيف لكل زون، يدخل على **Auto PT Suite** مباشرة.
البرنامج بعدها بيبني الموديل في RAM Concept بالمقاسات المكتوبة.

القواعد كلها، وسبب كل قاعدة، في [`RULES.md`](RULES.md).

## التشغيل

```bash
pip install -r ../requirements.txt          # ezdxf, shapely, matplotlib
export LIBREDWG_DWGREAD=/path/to/dwgread    # لملفات DWG بس (LibreDWG) - على ويندوز: موجود في libredwg\ جوه الـ zip

python -m pt_pipeline.convert project.dwg -o out/
python -m pt_pipeline.convert sheet.dxf -o out/ --keep-work          # يسيب الملفات الوسيطة
python -m pt_pipeline.convert sheet.dxf -o out/ --sheets wins.json    # شبابيك المساقط بإيدك
```

الأمر لازم يتشغّل من فولدر `tools/layerless_reader`.

أو من جوه البرنامج: زرار **"📐 Read a DWG / DXF drawing…"** في صفحة Project، وتفاصيله في `autopt/README.md`.

كود الخروج:

- `0`: كل الزونات عدّت الفحص.
- `2`: فحص الزونات فشل. التفاصيل في `report.json` تحت `zone_check`.

## الناتج

| الملف | المحتوى |
|---|---|
| `<ZONE>_slab_clean.dxf` | لكل زون: `PT-Clean-Boundary`، `-Openings`، `-Columns(-Above)`، `-Walls(-Above)`، `-Beams`، `-Drops`. بالمليمتر. |
| `images/<ZONE>.png` | صورة كل زون لوحدها. |
| `members.csv` | كل عنصر بمقاسه وسبب قبوله، وصفوف `REVIEW` للحاجات اللي محتاجة عين مهندس، والكمرات المشالة وليه. |
| `report.json` | أرقام كل خطوة، الشيتات، الزونات، ونتيجة الفحص. |

النصوص جوه الـ DXF اللي البرنامج بيقراها:

| النص | فين | معناه في RAM |
|---|---|---|
| `t=250` | حد البلاطة | سُمك البلاطة |
| `LEVEL t=240 SE=-300 P=2` | منطقة منسوب | Surface Elevation + أولوية |
| `ZONE t=200 P=2` | منطقة سُمك | سُمك + أولوية |
| `DROP t=400 P=3` | دروب | سُمك + أولوية |
| `POUR STRIP t=250 SE=0 P=4 RELEASE FX FY` | شريحة صب | بلاطة بنفس السُمك، أولوية أعلى، Fx وFy مفكوكين |
| `B4(400X700) P=17 INV SE=-700` | الكمرة | عرض وعمق وأولوية ومنسوب الكمرة المقلوبة |
| `B?(300X?)` | الكمرة | العمق مجهول: البرنامج بيطبق max(البحر/10، 600) |

## الترتيب

كل خطوة سكريبت في `steps/`، و`convert.py` بيشغّلهم بالترتيب ده:

1. `prep_dxf`: تحويل DWG لـ DXF، وتحديد الوحدة من ضلع العمود.
2. `sheets.py`: تحديد المساقط.
3. `slab_extractor` و`xvoids`: حد البلاطة والفتحات.
4. `stairs_rebar`: السلالم.
5. `ramp_label`: المنحدر المكتوب عليه.
6. `core`: الكور.
7. `joints`: فواصل التمدد، ومنها الزونات.
8. `members`: الأعمدة والحوائط والكمرات.
9. `rescue` و`connect` و`beam_sanity`: إكمال العناصر وربطها وفحص منطقها.
10. `ramps` و`ramp_faces` و`ramp_members`: المنحدر.
11. `thick_attr` و`thick` و`drops_*` و`pourstrips` و`levels`: السُمك والدروبات وشرايح الصب والمناسيب.
12. `xtype`: أنواع الأعمدة والحوائط دور بدور.
13. `stairs_members` و`core` و`beam_steps` و`edge_fit`: السلم والكور والكمرة بعرضين وحد البلاطة.
14. `zone_check`: الفحص.
15. `export_pt`: التصدير.

## الاختبارات

```bash
python -m pytest pt_pipeline/tests -q
AUTOPT_SRC=/path/Auto_PT_Suite.py python -m pytest pt_pipeline/tests/test_mesh_doctor.py -q
```

- `test_pipeline.py`: مسقط صناعي (`tests/make_struct_sample.py`) معروف الحقيقة، بيتحوّل من الأول للآخر. الناتج لازم يطابقها في أربع حالات:
  - إحداثيات عادية؛
  - إحداثيات مشروع كبيرة؛
  - وحدة سم؛
  - رسمة ملفوفة 27°.

  وفيه كمان اختبار إن الفحص بيمسك عمود برّه البلاطة وكمرة مكررة.
- `test_mesh_doctor.py`: دكتور الشبكة في البرنامج، على موديل صناعي وجلسة RAM وهمية بترفض الشبكة. بيتأكد من 3 حاجات:
  - الإصلاح بيتعمل؛
  - إعادة البناء مابتكررش العناصر؛
  - لو كل حاجة فشلت، الرسالة بتقول فين.
