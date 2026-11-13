# Compose spec (YAML)

```yaml
base: https://example.org/data/      # optional ABox base (CLI --base wins)
lang: ko                             # default content language (CLI --lang wins)
document:
  id: my-doc                         # required; anchors every component IRI
  title: 문서 제목                    # skos:prefLabel
  design_system: PlanningSystem      # local name, design:Name, or full IRI
  components:                        # root components, in order
    - id: intro                      # stable id -> {base}component/my-doc/intro
      structure: Section             # local name, structure:Name or IRI
      children:
        - {id: intro-title, structure: Heading, content: 소개}
        - id: REQ001
          structure: Paragraph
          semantic: [Requirement, Evidence]   # 0..n
          presentation: Callout               # 0..1 (else DS default binding)
          content: 본문                        # or {text: "...", lang: en}
        - id: steps
          structure: List
          ordered: true
          items:                               # shorthand -> ListItem children
            - 첫째                              # id = steps-i1 (positional)
            - {id: step-b, content: 둘째, semantic: Constraint}
        - id: matrix
          structure: Table
          rows:                                # shorthand -> TableRow/TableCell; first row = header
            - [항목, 값]                        # ids matrix-r1, matrix-r1-c1 ...
            - {id: row-x, cells: [A, {content: B, semantic: Evidence}]}
```

- Order is the list position (normalised 1..n).
- Components without `id` get a random `c-xxxxxxxx` id and a warning. Use `--write-ids` to save
  them back into the spec. The rewrite drops YAML comments, so prefer explicit ids.
- Shorthand item/row/cell ids are positional. Give an explicit `id` to any item that must keep its IRI when reordered.
- Duplicate ids are rejected (exit 2).
