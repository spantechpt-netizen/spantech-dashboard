# -*- coding: utf-8 -*-
"""PT Model Builder - برنامج مستقل: مخطط (DWG/DXF، معماري أو إنشائي) -> DXF لكل زون -> موديل RAM Concept.

المرحلة 1 (stage1): pt_pipeline (tools/layerless_reader) - تحويل وتقسيم زونات، سُمك ومناسيب وكمرات.
المرحلة 2 (stage2): DXF الزون -> RAM: المنشأ + دكتور الشبكة + الأحمال + خطوط الركايز وشرايح التصميم.
الكود بتاع المرحلة 2 جاي من Auto PT Suite نفسه (ram_core.py، بيتولد بـ build_core.py) من غير واجهته.
"""
__version__ = "1.0"
