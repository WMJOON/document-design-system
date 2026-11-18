# Validation rules

`scripts/validate.py` merges TBox + `instances/design-system.ttl` + your files, then runs pyshacl
with `inference="none"`. Without inference, `rdfs:range` cannot make a dangling
`usesDesignSystem` target into a DesignSystem.

| Shape | Kind | Rule | Typical fix |
|---|---|---|---|
| `ddsh:Document-designSystem` | Core | exactly one `usesDesignSystem`, typed `dds:DesignSystem` | fix the IRI or load the DS file with `--extra` |
| `ddsh:Document-component` | Core | ≥ 1 root `hasComponent`, typed `dds:Component` | add a root component |
| `ddsh:DesignSystem-*`, `ddsh:Binding-*` | Core | DS supports ≥ 1 Structure; values have the right class; binding has 1 structure + 1 presentation | fix the DS definition |
| `ddsh:ComponentShape` | Core | anything used as a component is typed `dds:Component` | add `a dds:Component` |
| `ddsh:Component-structure` | Core | exactly one `hasStructure` (a Structure individual) | add / dedupe structure |
| `ddsh:Component-semantic` | Core | `hasSemantic` values are Semantic individuals (0..n) | |
| `ddsh:Component-presentation` | Core | 0..1 `hasPresentation` | |
| `ddsh:Component-order` | Core | exactly one `hasOrder`, integer ≥ 1 | |
| `ddsh:Component-content` | Core | ≤ 1 `hasContent`, language-tagged | add `@ko` / `@en` |
| `ddsh:Component-ordered` | Core | `dds:ordered` is one boolean | |
| `ddsh:NoCycleShape` | SPARQL | no `hasChild+` cycle | break the cycle |
| `ddsh:SingleParentShape` | SPARQL | at most one parent (Document or component) | remove the extra link |
| `ddsh:ReachableShape` | SPARQL | reachable from a Document via `hasComponent/hasChild*` | attach or delete the orphan |
| `ddsh:UniqueSiblingOrderShape` | SPARQL | no duplicate `hasOrder` among siblings / roots | renumber |
| `ddsh:ContainerPolicyShape` | SPARQL | parent/child structures follow the container policy | move the child |
| `ddsh:ItemParentShape` | SPARQL | ListItem ⊂ List, TableRow ⊂ Table, TableCell ⊂ TableRow | wrap in the right container |
| `ddsh:ContentRequiredShape` | SPARQL | Heading/Paragraph/ListItem/TableCell have content | |
| `ddsh:ContentForbiddenShape` | SPARQL | Section/List/Table/TableRow have no content | move text to a child |
| `ddsh:OrderedOnlyOnListShape` | SPARQL | `dds:ordered` only on List | |
| `ddsh:SupportedStructureShape` | SPARQL | structure ∈ DS `supportsStructure` | use a supported type or extend the DS |
| `ddsh:SupportedSemanticShape` | SPARQL | semantic ∈ DS `supportsSemantic` | |
| `ddsh:SupportedPresentationShape` | SPARQL | explicit presentation ∈ DS `supportsPresentation` | |
| `ddsh:BindingSupportedShape` | SPARQL | default bindings use supported structure + presentation | |
| `ddsh:UniqueBindingShape` | SPARQL | ≤ 1 default binding per structure | |

| v0.3.0 | | | |
| `ddsh:Document-frame` | Core | ≤ 1 `usesFrame`, typed `dds:DocumentFrame` | pin one Frame version |
| `ddsh:Document-provenance`, `ddsh:Component-provenance` | Core | PROV links are IRIs | |
| `ddsh:Frame-*`, `ddsh:Requirement-*`, `ddsh:SemanticBinding-*` | Core | Frame needs ≥ 1 requirement; requirement = 1 semantic + `minOccurs` ≥ 1; binding = 1 semantic + 1 presentation | fix the Frame definition |
| `ddsh:Component-relation` | Core | relation targets are `dds:Component`s | |
| `ddsh:Component-resolution` | Core | ≤ 1 resolution, a `skos:Concept` | use `resolution:accepted/rejected/deferred` |
| `ddsh:FrameContractShape` | SPARQL | each Frame requirement met (count of components with the semantic ≥ `minOccurs`) | add the missing component |
| `ddsh:FrameDesignSystemShape` | SPARQL | DS ∈ Frame `compatibleDesignSystem` (if stated) | |
| `ddsh:MappingSupportedShape`, `ddsh:UniqueMappingShape` | SPARQL | Frame mappings use supported semantics / presentations; ≤ 1 per semantic | |
| `ddsh:RelationTargetShape` | SPARQL | relation target in the same Document | |
| `ddsh:ElaborationDepthShape` | SPARQL | `elaboratedBy` points into a sub-Section (depth) | move the detail under the overview's Section |
| `ddsh:PremiseOrderShape` | SPARQL | `basedOn` premise precedes the dependent (order) | move the premise earlier |
| `ddsh:RevisionOrderShape` | SPARQL | `wasRevisionOf` follows the revised premise | |
| `ddsh:CounterTargetShape` | SPARQL | Counterargument has `counters` | |
| `ddsh:CritiqueShape` | SPARQL | Critique has `targets` and `resolution` | |
| `ddsh:DeferredCritiqueShape` | SPARQL | deferred critique carried by an UnresolvedIssue | add the issue, `wasDerivedFrom` the critique |
| `ddsh:TraceabilityShape` | SPARQL | Frame `requiresTraceability`: Claim and Decision have `supportedBy` | link the grounds |
| `ddsh:Assessment-*`, `ddsh:AIAssessmentShape`, `ddsh:CoverageScopeShape` | Core / SPARQL | assessment records complete (see evaluation.md) | |

These rules check structure and explicit links only. Meaning (is the evidence sufficient, is the
overview faithful, is a premise used consistently) is evaluated by `evaluate.py`, not by SHACL.

Notes:
- A cycle reachable from a Document also triggers `SingleParentShape`, because the entry node has
  two parents.
- SPARQL constraints follow the SHACL spec: no `VALUES`/`MINUS`; prefixes are declared on the shapes
  ontology node via `sh:declare`.
- Messages exist in English and Korean (`--lang ko`).

JSON output (`--json`):

```json
{"conforms": false,
 "violations": [{"focus": "c:p", "shape": "ddsh:UniqueSiblingOrderShape", "path": null,
                 "value": "1", "severity": "Violation", "message": "Duplicate hasOrder 1 among siblings of …"}]}
```
