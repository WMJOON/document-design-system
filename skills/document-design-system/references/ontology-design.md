# Ontology design notes

## Namespaces

| Prefix | IRI | Role |
|---|---|---|
| `dds:` | `https://example.org/ontology/dds#` | TBox (classes, properties) |
| `ddsh:` | `https://example.org/ontology/dds/shapes#` | SHACL shapes |
| `structure:`, `semantic:`, `presentation:`, `design:` | `{base}structure/` … | reusable type / style individuals and DesignSystems |
| `doc:` | `{base}doc/{docId}` | Document IRIs |
| `component:` | `{base}component/{docId}/{componentId}` | Component IRIs |

`{base}` defaults to `https://example.org/data/` (`--base`). Before publishing your own vocabulary,
replace `https://example.org/ontology/dds#` in `ontology/`, `shapes/`, `instances/` and
`scripts/dds_lib/graph.py` (`DDS`, `DDSH`) with a namespace you control.

## TBox / ABox split (no punning)

`dds:Heading` is a class. `structure:Heading` is an individual of that class. Components point at
individuals (`dds:hasStructure structure:Heading`), never at classes. You can add your own individuals
(e.g. `structure:Callout a dds:Paragraph`) without touching the TBox. SHACL resolves their kind through
`rdf:type/rdfs:subClassOf*`.

## Classes

- Top level: `Document`, `DesignSystem`, `Component`, `Structure`, `Semantic`, `Presentation`,
  `PresentationBinding` (DesignSystem-scoped default Presentation for one Structure).
- Structure: `Section`, `Heading`, `Paragraph`, `List`, `ListItem`, `Table`, `TableRow`, `TableCell`.
- Semantic: `Requirement`, `Policy`, `Constraint`, `Decision`, `Evidence`, `Assumption`, `Description`.
- Presentation: `Typography`, `Layout`, `Style`. Each individual has a `dds:token` that keys into
  `config/presentation-markdown.yaml` (or a CSS / editor token map of your own).

## Hierarchy model

- `Document dds:hasComponent` points to **root** components only. Descendants use `dds:hasChild`.
- Every component has exactly one parent (a Document or a component) and is reachable from a Document.
- `dds:hasOrder` is a 1-based position among siblings (TBox range `xsd:positiveInteger`; SHACL accepts
  `xsd:integer` ≥ 1 because Turtle `1` is `xsd:integer`). the builder and parse normalise orders to 1..n.
- Container policy:

| Parent structure | Allowed children | hasContent |
|---|---|---|
| Section | any | forbidden |
| List (`dds:ordered` true/false) | ListItem | forbidden |
| Table (first row = header) | TableRow | forbidden |
| TableRow | TableCell | forbidden |
| Heading, Paragraph, ListItem, TableCell | none | required, `rdf:langString` |

- Heading level is derived from Section depth when rendering: the document title is `#`, and a heading
  in a Section at depth *d* is `#` × (1 + max(1, d)). Presentation never changes structure.

## Presentation resolution

1. explicit `dds:hasPresentation` on the component
2. else the `PresentationBinding` of the document's DesignSystem whose `dds:forStructure` equals the
   component's structure
3. else none (plain text)

Bindings must reference supported structures and presentations (`ddsh:BindingSupportedShape`).
