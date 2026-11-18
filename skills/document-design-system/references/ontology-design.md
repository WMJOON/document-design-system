# Ontology design notes

## Namespaces

| Prefix | IRI | Role |
|---|---|---|
| `dds:` | `https://example.org/ontology/dds#` | TBox (classes, properties) |
| `ddsh:` | `https://example.org/ontology/dds/shapes#` | SHACL shapes |
| `structure:`, `semantic:`, `presentation:`, `design:` | `{base}structure/` … | reusable type / style individuals and DesignSystems |
| `frame:`, `resolution:`, `criterion:` | `{base}frame/` … | DocumentFrames (versioned), critique resolution scheme, evaluation criteria |
| `prov:`, `earl:` | W3C PROV-O, EARL | provenance; evaluation results and assessment records |
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
  `PresentationBinding` (DesignSystem-scoped default Presentation for one Structure); v0.3.0 (approved):
  `DocumentFrame`, `FrameRequirement` (required semantic + `minOccurs`), `SemanticBinding`
  (Frame-scoped semantic → presentation).
- Structure: `Section`, `Heading`, `Paragraph`, `List`, `ListItem`, `Table`, `TableRow`, `TableCell`.
- Semantic: `Requirement`, `Policy`, `Constraint`, `Decision`, `Evidence`, `Assumption`, `Description`;
  v0.3.0: `Problem`, `Goal`, `Scope`, `DecisionQuestion`, `Criterion`, `Alternative`, `Claim`,
  `Counterargument`, `Perspective`, `Risk`, `Rationale`, `Critique`, `UnresolvedIssue`.
  Not semantics: *overview / summary* (a position, see below) and *agreement / disagreement / hold*
  (`dds:resolution` values `accepted` / `rejected` / `deferred` on a Critique).
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

## Structure principles (v0.3.0)

| Property | Encoded by | Checked by SHACL | Left to evaluation |
|---|---|---|---|
| **Depth = abstraction** | Section nesting (`hasChild`) | `elaboratedBy` points into a sub-Section of the overview's parent | does the overview faithfully cover its details? |
| **Order = logical progression** | sibling `hasOrder` | `basedOn` premise precedes the dependent; `prov:wasRevisionOf` follows its premise | consistent use of concepts; impact of a revised premise |

- *Overview* is relative: the leading content of a Section (before its sub-Sections), and root
  paragraphs for the whole document. No Overview / Summary semantic exists.
- Order alone proves no dependency; only explicit `basedOn` links are checked. Not every earlier
  Section is a premise.
- "Precedes" = ancestor, or the ancestor-or-self branches are siblings and the premise's branch has
  the smaller `hasOrder`.

## Relations (v0.3.0)

| Property | From → to | Rule |
|---|---|---|
| `dds:elaboratedBy` | overview content → detail | must point down (depth) |
| `dds:supportedBy` | Claim / Decision / Alternative → Evidence / Rationale | grounds; no order constraint |
| `dds:basedOn` | component → premise (Scope, Criterion, Assumption, …) | premise comes first (order) |
| `dds:counters` | Counterargument → what it argues against | required on a Counterargument |
| `dds:targets` + `dds:resolution` | Critique → reviewed component | both required; `deferred` must be carried by an UnresolvedIssue `prov:wasDerivedFrom` the critique |
| `prov:wasRevisionOf` | later component → premise it revises; Frame v2 → v1 | revision comes after its premise |
| `prov:wasDerivedFrom` | Document → deliberation record; component → component | IRI |
| `prov:hadPrimarySource` | Evidence → external source | IRI |

All `dds:` relations are sub-properties of `dds:relatesTo`, stay inside one Document, and never
change the hierarchy (`hasChild` is still the only tree edge). Markdown annotations carry them as
`"rel"`, `"prov"`, `"res"` keys and the document header carries `"frame"` and document `"prov"`.

## Frames and presentation resolution (v0.3.0)

Presentation resolution order: explicit `hasPresentation` → the document Frame's `SemanticBinding`
for one of the component's semantics (first by semantic IRI) → DesignSystem `PresentationBinding`
→ none. Documents without `usesFrame` render exactly as in v0.2.0. Frames are versioned by IRI and
never edited in place (see [evaluation.md](evaluation.md)).
