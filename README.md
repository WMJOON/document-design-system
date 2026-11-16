# Document Design System (DDS)

An Agent Skill that models documents — plans, policies, requirement specs, technical specs — as an
**RDF/OWL ontology**, validates them with **SHACL**, and renders them to **Markdown**.

A document is the combination of three independent dimensions:

| Dimension | Answers | Examples |
|---|---|---|
| **Structure** | What kind of block is it? | Section, Heading, Paragraph, List/ListItem, Table/TableRow/TableCell |
| **Semantic** | What role does the content play? | Requirement, Policy, Constraint, Decision, Evidence, Assumption, Description |
| **Presentation** | How does it look? | Typography, Layout, Style (mapped to design tokens) |

A `Document` uses exactly one reusable `DesignSystem` that declares which Structures, Semantics and
Presentations are allowed, plus default Presentations per Structure.

## Quick start

```bash
pip install -r requirements.txt
cd skills/document-design-system

# Author: copy a blank TTL skeleton (or build from the component library, see below)
sed 's#new-doc#my-id#g' templates/default-planning.ttl > /tmp/doc.ttl
python3 scripts/validate.py /tmp/doc.ttl                                      # PASS / FAIL with causes
python3 scripts/render.py /tmp/doc.ttl -o /tmp/doc.md                         # Turtle -> Markdown
python3 scripts/parse.py /tmp/doc.md -o /tmp/back.ttl                         # Markdown -> Turtle (round trip)
python3 scripts/export.py /tmp/doc.ttl -f json-ld                             # Turtle / JSON-LD / N-Triples

python3 -m pytest -q tests
```

### Component library and generated builder

Turtle is the canonical authoring format. Reusable components are defined first as prototypes in
`library/planning-components.ttl` (itself SHACL-valid). `scripts/gen_builder.py` turns each prototype
into a method of a generated builder, so a document is a short Python call sequence and the builder
fills ids, `hasChild` and `hasOrder`:

```bash
python3 scripts/gen_builder.py library/planning-components.ttl -o generated/build_planning.py
```

```python
from build_planning import Doc          # generated/
d = Doc("my-id", "Title", lang="en")
d.add(d.section("overview", d.heading("overview-title", "Overview"),
                d.requirement("REQ001", "The system must ...")))
d.write("my.ttl")                       # then validate.py / render.py
```

A failing document reports each violation with the shape, focus node and cause:

```text
$ python3 scripts/validate.py tests/fixtures/invalid/duplicate-order.ttl
FAIL  2 SHACL violation(s)
  - [ddsh:UniqueSiblingOrderShape] c:h = 1
      Duplicate hasOrder 1 among siblings of https://example.org/data/component/t/s1 (also used by …/t/p).
```

## What is validated

- Document → exactly one existing DesignSystem, at least one root Component
- Component → exactly one Structure, 0..n Semantics, 0..1 Presentation, a positive `hasOrder`,
  language-tagged content where required
- Hierarchy → no cycles, single parent, no orphans, unique sibling order, container policy
  (Section → any; List → ListItem; Table → TableRow; TableRow → TableCell)
- DesignSystem support → every Structure / Semantic / Presentation used, including default bindings,
  is supported by the document's DesignSystem

The rules use SHACL Core plus SHACL-SPARQL (pyshacl) and run **without inference**, so `rdfs:domain` and
`rdfs:range` cannot hide missing data. See
[`references/validation-rules.md`](skills/document-design-system/references/validation-rules.md).

## Layout

```
skills/document-design-system/
├── SKILL.md            # agent instructions
├── ontology/           # TBox (core, structure, semantic, presentation, relations)
├── shapes/             # SHACL shapes
├── instances/          # default DesignSystems + example document (ABox)
├── library/            # component prototypes (source of the builder)
├── generated/          # generated document builder (do not hand-edit)
├── config/             # Presentation token -> Markdown mapping
├── scripts/            # gen_builder / validate / render / parse / export (+ dds_lib)
├── templates/          # blank TTL skeletons (default-*.ttl)
├── references/         # design notes, validation rules
└── tests/              # pytest + SHACL fixtures (one violation per invalid fixture)
```

## Install as a skill

Copy or symlink `skills/document-design-system` into your agent's skills directory (for example
`~/.claude/skills/document-design-system`).

## Namespaces

The TBox uses the placeholder `https://example.org/ontology/dds#`, and instance data defaults to
`https://example.org/data/` (`--base`). Replace them with namespaces you control before publishing
your own vocabulary.

## 한국어 요약

DDS는 기획안·정책서·요구사항 정의서 같은 문서를 Structure / Semantic / Presentation 세 축의
RDF/OWL 온톨로지로 구조화합니다. SHACL(Core + SPARQL)로 정합성을 검증하고 Markdown으로 렌더링합니다.
문서는 하나의 DesignSystem을 참조하며, 그 DesignSystem이 지원하지 않는 유형이나 스타일은 검증에서 걸립니다.
컴포넌트를 TTL 라이브러리로 먼저 정의하고 생성기로 문서 빌더를 만들어 쓸 수 있으며, 빈 TTL 골격(`templates/default-*.ttl`)도 제공합니다. YAML 입구(`compose.py`)는 제거되었습니다.
Markdown 렌더링 결과에는 `<!-- dds … -->` 주석이 들어가므로, 다시 Turtle로 파싱해도 IRI·계층·순서·Semantic이 보존됩니다.

## License

MIT
