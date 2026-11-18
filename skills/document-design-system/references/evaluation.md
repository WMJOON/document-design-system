# Evaluation and Frame evolution (v0.3.0)

`scripts/evaluate.py` answers "what do we know about this document, and how do we know it?", one
criterion at a time. It never computes an overall score.

## Statuses

| Status | EARL outcome | Meaning |
|---|---|---|
| Pass | `earl:passed` | a stated, checkable condition holds (SHACL, deterministic check, or a human assessment) |
| Fail | `earl:failed` | a checkable condition is violated |
| NeedsReview | `earl:cantTell` | a deterministic pre-check flagged something it cannot decide, or only an AI opinion exists |
| NotEvaluated | `earl:untested` | nothing checked it |

## Criteria (`instances/evaluation.ttl`)

| Criterion | Dimension | Decided by | Pre-check that can raise NeedsReview |
|---|---|---|---|
| structure-hierarchy | Structure | SHACL (v0.2 rules, relation targets, critique completeness) | — |
| structure-depth | Structure | `ElaborationDepthShape` (overview links point into a sub-Section) | — |
| structure-order | Structure | `PremiseOrderShape`, `RevisionOrderShape` | a component `basedOn` a premise that a later component revises (`wasRevisionOf`): re-review the dependent |
| frame-contract | Structure | Frame shapes (requirements, DS compatibility, mappings); NotEvaluated without a Frame | — |
| fidelity | Semantic | human assessment only | — |
| coverage | Semantic | human assessment only (must state `dds:evaluationScope`) | no Scope component in the document |
| counterargument | Semantic | `CounterTargetShape`, `DeferredCritiqueShape` (Fail); otherwise human | an overview (`elaboratedBy`) that does not lead to a Counterargument / UnresolvedIssue |
| perspective-bias | Semantic | human assessment only | exactly one Perspective recorded |
| traceability | Semantic | `TraceabilityShape` when the Frame requires it (Fail); Pass when every Claim / Decision links to grounds | Claims / Decisions without `supportedBy` |
| concept-consistency | Semantic | human assessment only | — |
| presentation-consistency | Presentation | same semantic(s) → same effective presentation | otherwise NeedsReview |
| presentation-distinguishability | Presentation | key meanings (Decision, Evidence, Counterargument, Critique, UnresolvedIssue) look different | shared presentation, or one component with conflicting mapped semantics |
| presentation-predictability | Presentation | Frame maps every key meaning present; NotEvaluated without a Frame | unmapped key meaning |

Traceability Pass means *links exist*. Whether the evidence is sufficient is a semantic question.

## Assessment records (EARL)

Human or AI reviewers add `earl:Assertion`s; pass them with `--assessments`. Shapes in
`shapes/evaluation.shacl.ttl` reject incomplete records (they are listed as invalid and ignored):

```turtle
[] a earl:Assertion ;
    earl:subject doc:my-doc ; earl:test criterion:coverage ;
    earl:assertedBy <https://example.org/agents/reviewer> ; earl:mode earl:semiAuto ;
    dds:assessorModel "model-id" ;                         # required unless earl:mode earl:manual
    dds:uncertainty "What could not be checked."@en ;      # required unless earl:mode earl:manual
    dds:evaluationScope "Source set / decision scope."@en ; # required for coverage
    earl:result [ a earl:TestResult ; earl:outcome earl:passed ; earl:info "Basis."@en ] .
```

Folding rules:
- A semantic item becomes Pass / Fail only through a human record (`earl:mode earl:manual`) whose
  `earl:subject` is the document. Records about one component (e.g. one Section overview) are listed
  per component and never close the document item.
- An AI record never closes an item: the item is NeedsReview and the reasons show the model, basis,
  scope and uncertainty.
- Disagreeing human records → NeedsReview.
- A human record cannot turn a SHACL Fail into Pass; the conflict is reported.

## History and comparison

`evaluate.py --earl result.ttl` writes one assertion per criterion (`earl:assertedBy dds:evaluate`,
`dds:frameVersion`, `dcterms:date`). Keep results per document, e.g.
`evaluations/<doc-id>/<date>.ttl`, and compare:

```bash
python3 scripts/compare.py evaluations/my-doc/2026-11-18.ttl evaluations/my-doc/2026-11-19.ttl
python3 scripts/compare.py --history evaluations/my-doc/
```

The comparison lists every criterion before → after. It does not call a change an improvement.
A lower count of issues, higher agreement or a shorter document is not quality by itself.

## Frame evolution loop

Frame definition → document generation → structure validation → semantic evaluation →
presentation evaluation → independent critique → revision proposal (a DeliberationRevision document)
→ **new Frame version** (`frame:X-v2`, `prov:wasRevisionOf frame:X-v1`) → regression evaluation of the
fixtures → comparison.

- Never edit a published Frame. Documents pin a version with `dds:usesFrame`, so loading v2 does not
  change the results of v1 documents (`tests/test_evolution.py`).
- Re-pinning a document to v2 is a document change; compare its results per criterion.
- Example: `examples/frame-evolution/` (DecisionRecord v2 adds Scope and Criterion requirements; the
  proposal keeps the deferred "require counterarguments" critique as an UnresolvedIssue).

## Limits (not claimed)

Complete meaning preservation, discovery of every alternative, absolute MECE, real stakeholder
agreement, the reader's final judgment, objective AI evaluation. Coverage and MECE are only meaningful
within a stated Scope and evidence boundary.
