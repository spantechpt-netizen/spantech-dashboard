# مولّد التقرير

الملفات دي بتحوّل [`../README.md`](../README.md) لصفحة HTML واحدة فيها الرسومات مدمجة، ومنها بيتطبع الـ PDF.

```bash
pip install markdown playwright
python gen.py                      # ينتج pt-jack-250.html
```

- `shell.html` — القالب: الستايل، الفهرس، حاسبة الضغط/القوة، ستايل الطباعة
- `gen.py` — بيقرا الماركداون، بيحقن رسومات SVG كـ data URI، وبيبني الصفحة

الـ PDF بيتطبع من الصفحة دي بـ Chromium على A4.
