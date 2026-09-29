# Span Tech skill for Claude

`SKILL.md` teaches Claude (in any chat) the Span Tech way of working: office rules, the drawing → RAM
pipeline, how to check results and how to deliver. The uploadable skill zip is built from this file plus
`layerless_reader/pt_pipeline/RULES.md`, `FLOW.md` (as `references/`) and the pipeline code (as `scripts/`):

    mkdir -p spantech-pt/references spantech-pt/scripts
    cp tools/claude_skill/SKILL.md spantech-pt/
    cp tools/layerless_reader/pt_pipeline/{RULES,FLOW}.md spantech-pt/references/
    cp -r tools/layerless_reader/{pt_pipeline,layerless_reader.py,slab_extractor.py,dwg_json_to_dxf.py,requirements.txt} spantech-pt/scripts/
    zip -r spantech-pt.zip spantech-pt

Claude.ai: Settings → Capabilities → Skills → upload `spantech-pt.zip`. Or paste `SKILL.md` into a
Project's instructions.
