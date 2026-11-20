---
name: document-design-system
description: Model, validate and render documents (PRDs, policies, requirement specs, technical specs) as an RDF/OWL ontology with SHACL validation. Separates Structure (Section/Heading/Paragraph/List/Table), Semantic (Requirement/Policy/Constraint/Decision/Evidence/Assumption/Description) and Presentation (Typography/Layout/Style), and binds every Document to one reusable DesignSystem. Use when the user wants to compose a document from components, check a document's structural integrity with SHACL, render RDF to Markdown, parse Markdown into Turtle, or export Turtle/JSON-LD. Triggers include "DDS", "document design system", "문서 온톨로지", "문서 구조화", "SHACL 검증", "기획안을 RDF로", "문서 컴포넌트", "디자인 시스템 적용 문서", "Markdown을 Turtle로".
---

# DDS — Document Design System

A Document **uses exactly one DesignSystem** and **contains Components**. Each Component has
exactly one Structure, zero or more Semantics, and zero or one Presentation (falling back to the
DesignSystem's default binding). TBox = `ontology/`, ABox = `instances/` + your files,
validation = `shapes/` (SHACL Core + SHACL-SPARQL).

Version: 0.3.1. Requirements: Python ≥ 3.9, `pip install -r requirements.txt` (rdflib, pyshacl, pyoxigraph, PyYAML).

SHACL engine: Core shapes run in pyshacl; SHACL-SPARQL constraints (`sh:sparql`) run in pyoxigraph
(much faster on document-sized graphs). Set `DDS_SHACL_ENGINE=pyshacl` to run everything in pyshacl.
Without pyoxigraph installed, validation falls back to pyshacl automatically.
All commands run from this skill directory.

## Operations

| Operation | Command | Notes |
|---|---|---|
| **build** | `python3 scripts/build.py doc.ttl --extra data.ttl -o doc.md` | **Main command.** Source TTL → materialise → SHACL → Markdown in one process. `--emit full.ttl` for debugging |
| compose (legacy) | `python3 scripts/compose.py SPEC.yaml -o doc.ttl` | YAML → ABox. Kept for compatibility; write source TTL instead |
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
3. **Write the source TTL** (see "Source TTL" below). Give every component a stable IRI.
   (Legacy: a YAML compose spec, [references/compose-spec.md](references/compose-spec.md).)
4. **Build.** Run `build.py`. A successful Turtle serialisation is NOT validation.
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

## Source TTL (v0.4): the document source

Write documents directly in Turtle. Keep only what a person decides; build derives the rest
(hasOrder, header rows and cells from the glossary, kinded-section headings) in memory.

```turtle
doc:v1 a dds:Document ; skos:prefLabel "결제 수단"@ko ;
    dds:usesDesignSystem design:PlanningSystem ;
    dds:children ( c:summary c:payment-method ) .                 # order = list order
c:summary a dds:Component ; dds:hasStructure structure:Paragraph ;
    dds:hasContent "> 이 문서에서 알 수 있는 것"@ko .
c:payment-method a dds:Component ; dds:hasStructure structure:Section ;
    dds:sectionKind design:ConceptSection ; dds:about kw:PaymentMethod ;   # heading from the concept
    dds:children ( c:payment-method-table ) .
c:payment-method-table a dds:Component ; dds:hasStructure structure:Table ;
    dds:tableKind design:ConceptTable ;
    dds:rows ( kw:Card [ dds:about kw:Deposit ; dds:cells [ design:col-definition "직접 쓴 정의"@ko ] ] ) .
```

- `dds:children` (Document/Section/List), `dds:items` (List literals), `dds:rows` (typed Table) are rdf:Lists.
- Component IRIs live under `<base>component/<doc id>/`; derived ids are deterministic (`{table}-r0-c1`).
- The expanded form (hasChild + hasOrder) is still accepted; do not mix both on one node.
- `validate.py` / `render.py` expand source files automatically.

## Typed tables and sections (v0.2–v0.3)

Content and presentation stay apart: a component says WHAT it shows (kind, row subjects, explicit
cell values); WHICH columns are shown, their order and their header text are presentation, defined
once outside documents.

- **Column**: which property of the row subject fills the cell (`dds:valueProperty`). Header text =
  Column `skos:prefLabel`, renamed only DesignSystem-wide (`dds:hasColumnLabel`). Never per table.
- **TableKind**: rowClass + all allowed Columns in a fixed order. Default `design:ConceptTable`
  (rowClass `skos:Concept`): label | code | definition | description | example | source.
- **TableView**: a named subset of a kind's columns, in the kind's order (`dds:viewColumns`).
  DesignSystem default per kind via `dds:hasDefaultView`; a table may pick a named view with `view:`.
- **SectionKind**: heading pattern + ordered Slots. Default `design:ConceptSection`, one per class:
  `## {label}` → description Paragraph (only when given) → ConceptTable (rows = members) → notes List (only when given).

```yaml
- id: payment-method
  structure: Section
  kind: ConceptSection
  about: payment_method              # concept the section is about (notation, curie or IRI)
  table:
    view: InputView                  # optional named TableView; else the DesignSystem default
    rows:
      - card                         # row subject
      - {about: deposit, cells: {definition: 직접 쓴 정의}}   # explicit cell value
  notes: [주석 한 줄]
```

- `columns:` / `headers:` on a component are rejected.
- Pass data, kinds and views with `--extra` to compose / validate / render.
- SHACL checks: one header row first, equal cell counts, every cell has a column, row subjects typed
  with the rowClass, no untyped tables when `dds:requiresTypedTables true`, section slots present,
  in order, with the right structure and table kind.

## Key files

- `ontology/*.ttl`: TBox (core, structure, semantic, presentation, relations). Design notes: [references/ontology-design.md](references/ontology-design.md)
- `shapes/*.shacl.ttl`: document/DS shapes, component shapes, hierarchy and DS-support SPARQL rules
- `instances/design-system.ttl`: reusable type/style individuals and the default DesignSystems
- `instances/table-kinds.ttl`, `ontology/table.ttl`, `shapes/table.shacl.ttl`: typed tables (Column, TableKind, ColumnLabel)
- `instances/example-document.ttl`: example planning document (ABox)
- `config/presentation-markdown.yaml`: Presentation token → Markdown rule (`wrap`, `prefix`)
- `templates/planning-document.{yaml,md}`: compose spec and its rendered output
- `tests/`: `python3 -m pytest -q tests`
