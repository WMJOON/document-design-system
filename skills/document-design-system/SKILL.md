---
name: document-design-system
description: Model, validate and render documents (PRDs, policies, requirement specs, technical specs) as an RDF/OWL ontology with SHACL validation. Separates Structure (Section/Heading/Paragraph/List/Table), Semantic (Requirement/Policy/Constraint/Decision/Evidence/Assumption/Description) and Presentation (Typography/Layout/Style), and binds every Document to one reusable DesignSystem. Use when the user wants to compose a document from components, check a document's structural integrity with SHACL, render RDF to Markdown, parse Markdown into Turtle, or export Turtle/JSON-LD. Triggers include "DDS", "document design system", "문서 온톨로지", "문서 구조화", "SHACL 검증", "기획안을 RDF로", "문서 컴포넌트", "디자인 시스템 적용 문서", "Markdown을 Turtle로".
---

# DDS — Document Design System

A Document **uses exactly one DesignSystem** and **contains Components**. Each Component has
exactly one Structure, zero or more Semantics, and zero or one Presentation (falling back to the
DesignSystem's default binding). TBox = `ontology/`, ABox = `instances/` + your files,
validation = `shapes/` (SHACL Core + SHACL-SPARQL).

Requirements: Python ≥ 3.9, `pip install -r requirements.txt` (rdflib, pyshacl, PyYAML).
All commands run from this skill directory.

## Operations

| Operation | Command | Notes |
|---|---|---|
| compose | `python3 scripts/compose.py SPEC.yaml -o doc.ttl` | YAML → ABox; validates afterwards. `--write-ids` persists generated ids |
| validate | `python3 scripts/validate.py doc.ttl [--json] [--lang ko]` | exit 0 pass / 1 violations / 2 error |
| render | `python3 scripts/render.py doc.ttl -o doc.md [--no-annotate]` | refuses invalid input unless `--force` |
| parse | `python3 scripts/parse.py doc.md -o doc.ttl [--design-system X]` | annotated MD → exact graph; plain MD → structural |
| export | `python3 scripts/export.py doc.ttl -f json-ld [--with-tbox]` | turtle, json-ld, nt, xml |
| define | edit `instances/design-system.ttl` or pass your own TTL with `--extra` | new DesignSystems, presentations, bindings |
| update | edit SPEC.yaml (keep `id`s) and re-run compose | IRIs stay stable |

`diff` is not implemented yet (roadmap). Use `rdflib.compare.graph_diff` on two composed graphs.

## Workflow

1. **Survey first.** If the project already has an ontology or document system, read it and report
   conflicts before adding anything.
2. **Pick a DesignSystem.** Read `instances/design-system.ttl` (`PlanningSystem`, `MemoSystem`).
   A new one goes in a separate TTL passed via `--extra`. Never apply a Structure / Semantic /
   Presentation the DesignSystem does not support.
3. **Write a compose spec.** Start from `templates/planning-document.yaml`. Give every component an
   explicit, stable `id`. See [references/compose-spec.md](references/compose-spec.md).
4. **Compose → validate.** Run `compose.py`. A successful Turtle serialisation is NOT validation.
   Only a `PASS` from SHACL counts. On failure, read the `[ddsh:…Shape]` code and fix the cause
   (see [references/validation-rules.md](references/validation-rules.md)).
5. **Render** with `render.py`. Keep annotations (default) when the Markdown may be parsed back.
6. **Report** changed components (by id), structural vs content changes, and the validation result.

## Agent rules

1. Keep TBox (`ontology/`) and ABox (instances, documents) in separate files.
2. Do not add new top-level classes without user approval. Subclasses of Structure/Semantic/Presentation are fine when the user asks.
3. When editing, keep existing component ids/IRIs. Change content in place, never by delete+recreate.
4. Report structural changes (hierarchy, order, structure type) separately from content changes.
5. Preserve titles, paragraphs, lists, tables, hierarchy and order when converting.
6. Always run SHACL validation, never stop at "it parsed".
7. The renderer reads structure as stored. Do not reorganise hierarchy while rendering.
8. Container policy: Section → any child; List → ListItem; Table → TableRow; TableRow → TableCell; everything else → no children. `Document hasComponent` points to root components only.
9. Validation runs without RDFS/OWL inference on purpose. Domain/range are inference rules, not checks.

## Key files

- `ontology/*.ttl`: TBox (core, structure, semantic, presentation, relations). Design notes: [references/ontology-design.md](references/ontology-design.md)
- `shapes/*.shacl.ttl`: document/DS shapes, component shapes, hierarchy and DS-support SPARQL rules
- `instances/design-system.ttl`: reusable type/style individuals and the default DesignSystems
- `instances/example-document.ttl`: example planning document (ABox)
- `config/presentation-markdown.yaml`: Presentation token → Markdown rule (`wrap`, `prefix`)
- `templates/planning-document.{yaml,md}`: compose spec and its rendered output
- `tests/`: `python3 -m pytest -q tests`
