---
name: document-design-system
description: Model, validate, render and evaluate documents (PRDs, policies, requirement specs, technical specs, decision records and other deliberation documents) as an RDF/OWL ontology with SHACL validation. Separates Structure (Section/Heading/Paragraph/List/Table), Semantic (Requirement/Policy/Constraint/Decision/Evidence/Assumption/Description, plus deliberation roles such as Problem/Scope/Criterion/Alternative/Claim/Counterargument/Rationale/Critique/UnresolvedIssue) and Presentation (Typography/Layout/Style), and binds every Document to one reusable DesignSystem. Supports versioned DocumentFrames (problem framing, decision question, alternative comparison, independent critique, deliberation revision, decision record), argument/premise relations, PROV-O provenance, per-criterion evaluation (Pass / Fail / NeedsReview / NotEvaluated) and cost-aware semantic checks by a local model (oMLX, LM Studio, Ollama, vLLM, SGLang) or a light-model subagent. Use when the user wants to compose a document from components, check a document's structural integrity with SHACL, review or evaluate a document's meaning, render RDF to Markdown, parse Markdown into Turtle, or export Turtle/JSON-LD. Triggers include "DDS", "document design system", "문서 온톨로지", "문서 구조화", "SHACL 검증", "기획안을 RDF로", "문서 컴포넌트", "디자인 시스템 적용 문서", "Markdown을 Turtle로", "DocumentFrame", "결정 기록", "숙의 문서", "대안 비교 문서", "문서 평가", "문서 검토", "evaluate document".
---

# DDS — Document Design System

A Document uses exactly one **DesignSystem** (allowed types and styles) and contains **Components**.
Each Component has one Structure, 0..n Semantics and 0..1 Presentation. Deliberation documents also
pin one versioned **DocumentFrame** (which meanings they must contain). Turtle (TTL) is canonical;
Markdown is a rendering that round-trips through `<!-- dds … -->` annotations.

Setup: Python ≥ 3.9, `pip install -r requirements.txt` (rdflib, pyshacl, PyYAML). Run commands from
this skill directory; pass the user's files by absolute path.

## 1. Choose the path

| The user wants… | Do |
|---|---|
| a plain document (plan, policy, spec, memo) | **A** build → validate → render |
| a document that supports a decision (problem, options, critique, decision record) | **B** pick a Frame → build → validate → evaluate (L0) → render |
| to know whether an existing document is sound | **C** validate → evaluate; add semantic checks (§3) only if they ask for a review of meaning |
| to re-check a document after edits | **D** validate → `semantic_eval.py --prev old.ttl --cache …` (only affected parts) |
| Markdown → TTL, or another format | `parse.py` / `export.py` |
| to change a Frame | **E** new version, never edit in place (§5) |

**Default: no model calls.** Structure, order, links, presentation and Frame contracts are decided
deterministically (`validate.py`, `evaluate.py`). Call a model only when the user asks for a review of
meaning (fidelity, evidence sufficiency, coverage, counterarguments, consistency) or the document is a
high-stakes decision and they agree.

## 2. Build and validate (paths A, B)

1. **Survey.** If the project already has an ontology or document system, read it and report conflicts first.
2. **DesignSystem.** `instances/design-system.ttl`: `PlanningSystem`, `MemoSystem` (unchanged since
   v0.2), `DeliberationSystem` (all deliberation semantics). Your own goes in a separate TTL via `--extra`.
3. **Frame (path B).** `instances/frames.ttl`: `ProblemFraming-v1`, `DecisionQuestion-v1`,
   `AlternativeComparison-v1`, `IndependentCritique-v1`, `DeliberationRevision-v1`, `DecisionRecord-v1`.
4. **Write the document with a generated builder** (never hand-edit `generated/`):
   ```python
   # generated/build_deliberation.py (or build_planning.py); see its docstring
   d = Doc("pilot", "Pilot decision", lang="ko", frame="DecisionRecord-v1")
   d.add(d.overview("ov", "…", elaboratedBy=["dec"]),                       # overview first
         d.decision_question("q", "…"),
         d.section("premises", d.heading("ph", "전제"), d.criterion("crit", "…")),  # premises before use
         d.section("details", d.heading("dh", "결정"),
                   d.decision("dec", "…", basedOn=["crit"], supportedBy=["why"]),
                   d.rationale("why", "…")))
   d.write("/abs/path/pilot.ttl")
   ```
   Or copy a skeleton: `templates/default-{planning,memo}.ttl`, `templates/deliberation-0N-*.ttl`
   (`sed 's#new-doc#my-id#g'`, replace every «…»).
5. **Structure rules.** *Depth* = abstraction: a Section's leading content is the overview of its
   sub-Sections; link overview statements down with `elaboratedBy`. *Order* = logical progression:
   a premise (Scope, Criterion, Assumption) comes before what depends on it (`basedOn`). Grounds use
   `supportedBy` (any position). Overview is a position, not a semantic type.
6. **Deliberation rules.** A critique is an opinion, not a veto: keep rejected ones; a `deferred`
   critique needs an UnresolvedIssue with `wasDerivedFrom` it. Change a premise only by adding an
   explicit revision after it (`wasRevisionOf`). Never drop a disagreement to make a document look settled.
7. **Validate:** `python3 scripts/validate.py doc.ttl [--lang ko]` (exit 0 PASS / 1 violations / 2 error).
   Parsing is not validation. On failure fix the cause named by `[ddsh:…Shape]`
   ([references/validation-rules.md](references/validation-rules.md)).
8. **Render:** `python3 scripts/render.py doc.ttl -o doc.md` (keep annotations if it may be parsed back).

## 3. Evaluate (paths B, C, D)

`python3 scripts/evaluate.py doc.ttl [--assessments a.ttl] [--json]` reports every criterion as
Pass / Fail / NeedsReview / NotEvaluated with reasons. No overall score exists; do not invent one.
Semantic items stay NotEvaluated / NeedsReview until a human assessment exists
([references/evaluation.md](references/evaluation.md)).

**Semantic checks by a model** (only when asked, §1). Pick the judge in this order:

1. **Local model (first option).** `python3 scripts/semantic_eval.py --list-models` lists servers that
   answer `/v1/models`. If the user named a model, use it. Otherwise show the list once and let them
   choose; on a shared single-model server prefer the one already loaded (choosing another loads it).
   Spec: `omlx:<model>`, `lmstudio:<model>`, `ollama:<model>`, `vllm:<model>`, `sglang:<model>`
   (append `@http://host:port/v1` or set `DDS_<RUNTIME>_URL` when the port differs; key via
   `DDS_LLM_API_KEY`), or `openai:<base_url>#<model>`.
2. **Light-model subagent (second option)** when nothing answers: `--backend agent:<name>` (§4).
3. Never judge with the session that wrote or revised the document.

Run, keeping state next to the document in `<doc-dir>/.dds/<doc-id>/`:
```bash
python3 scripts/semantic_eval.py /abs/doc.ttl --backend <spec> \
    --cache <state>/cache.ttl --out <state>/assessments.ttl --metrics <state>/runs.jsonl \
    [--prev /abs/previous-version.ttl] [--strong <spec>] [--l2]
python3 scripts/evaluate.py /abs/doc.ttl --assessments <state>/assessments.ttl
```
- With `--prev`, only components affected by the change are re-judged; unchanged results come from
  the cache. Selection follows recorded relations only: say so, and suggest `--l2` (whole-document
  critique) for important versions, after core premise changes, or periodically.
- L2 also runs by itself on: first evaluation, a changed Criterion / Scope / DecisionQuestion,
  ≥ 30 % accumulated change, `--major`, `--high-risk` (flags are the caller's call, never inferred).
- `--strong <spec>` escalates uncertain / low-confidence / high-risk results and acts as the L2 critic.
Details: [references/semantic-evaluation.md](references/semantic-evaluation.md).

## 4. Delegating to a light-model subagent (second option)

1. `semantic_eval.py /abs/doc.ttl --backend agent:haiku --cache … --out … --emit <state>/pending.jsonl`
   → exit 3 means packets are waiting (only cache misses; nothing pending is cached).
2. For each line, start a light subagent (Claude Code: a subagent on the Haiku model; Codex: a
   mini-class subagent) with only this prompt. Several lines may go to one subagent; lines with
   `"level": "L2"` go to a separate, fresh subagent:
   > You are an independent document reviewer. {prefix}
   > Text to judge:
   > {body}
   > Reply with one JSON object that matches this schema and nothing else: {schema}
3. Append one line per packet to `<state>/replies.jsonl`:
   `{"packet_id": "<from the line>", "model": "<model id used>", "output": {<the JSON reply>}}`.
   Unparseable or missing replies: leave them out (they stay pending).
4. Run the same command with `--replies <state>/replies.jsonl` (keep `--emit` to collect anything still
   pending; exit 0 = nothing left), then `evaluate.py`.

## 5. Change a Frame (path E)

Never edit a published Frame. Add `frame:<Name>-v2` with `prov:wasRevisionOf` the old one (see
`examples/frame-evolution/`), keep documents pinned to their version, evaluate before / after with
`evaluate.py --earl`, and compare: `python3 scripts/compare.py before.ttl after.ttl`.

## 6. Report to the user

- What was built or changed, by component id; structural changes separate from content changes.
- Validation result (PASS, or each violation and its fix).
- Evaluation: every criterion with its status; for model checks name the model, and say they are
  opinions (NeedsReview), with calls / tokens from the run metrics.
- What was not checked (e.g. no L2 this run; selection limited to recorded relations).
- Never: an overall score, "fewer issues" or "shorter" as improvement, an AI verdict as fact,
  coverage / MECE claims beyond the stated Scope.

## Agent rules

1. Keep TBox (`ontology/`) and ABox (instances, documents) in separate files.
2. No new top-level classes without user approval (approved: Document, DesignSystem, Component,
   Structure, Semantic, Presentation, PresentationBinding, DocumentFrame, FrameRequirement,
   SemanticBinding). Subclasses of Structure / Semantic / Presentation are fine when the user asks.
3. Keep component ids / IRIs when editing; change content in place, never delete + recreate.
4. Preserve titles, paragraphs, lists, tables, hierarchy and order when converting; the renderer
   never reorganises hierarchy.
5. Container policy: Section → any; List → ListItem; Table → TableRow; TableRow → TableCell; others
   → no children. `Document hasComponent` points to root components only.
6. Validation runs without RDFS/OWL inference on purpose.

## Reference

| Need | Where |
|---|---|
| all commands and flags | `python3 scripts/<name>.py --help` (validate, render, parse, export, evaluate, compare, semantic_eval, bench, gen_builder) |
| classes, relations, namespaces | [references/ontology-design.md](references/ontology-design.md) |
| every SHACL rule and its fix | [references/validation-rules.md](references/validation-rules.md) |
| statuses, criteria, assessment records, Frame evolution | [references/evaluation.md](references/evaluation.md) |
| L0/L1/L2, cache, packets, runtimes, delegation, benchmark | [references/semantic-evaluation.md](references/semantic-evaluation.md) |
| DesignSystems, resolution scheme / Frames / criteria | `instances/design-system.ttl`, `instances/frames.ttl`, `instances/evaluation.ttl` |
| component libraries → builders | `library/*.ttl` → `generated/build_*.py` (`scripts/gen_builder.py LIB -o OUT`) |
| tests | `python3 -m pytest -q tests` |
