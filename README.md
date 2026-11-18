# Document Design System (DDS)

**Documents that people decide with — built from typed components, validated like code, and
evaluated honestly.**

DDS is an Agent Skill (for Claude Code, Codex and similar agents) that models documents — plans,
policies, specs, decision records — as an RDF/OWL graph instead of free text. *Structure* organises
information by level of abstraction and logical order, *semantics* record what each part means for the
judgment and how meanings depend on each other, and *presentation* shows each kind of meaning the same
way every time. That lets an agent check a document the way a compiler checks code: is every decision backed by a rationale, is
every premise stated before it is used, did a critique quietly disappear, does the summary lead to its
evidence?

Turtle (TTL) is the source of truth. Markdown is a rendering that converts back without loss.

## What you get

- **Composable documents**: reusable component libraries turned into small Python builders, plus templates.
- **Structural validation**: SHACL rules with a precise cause for every violation (hierarchy, order,
  required meanings, links, styles).
- **Decision support**: versioned *DocumentFrames* for problem framing, decision questions, option
  comparison, independent critique, revision and decision records.
- **Traceable meaning**: claims link to evidence, decisions to rationale, dependents to their premises,
  critiques to what they review — with PROV-O provenance.
- **Honest evaluation**: each criterion is reported as Pass / Fail / NeedsReview / NotEvaluated, with
  reasons. There is no overall score, and a model's opinion is never presented as a verdict.
- **Cheap semantic checks**: when a model is needed, DDS sends it only the changed parts, caches
  results, and runs on any local runtime (oMLX, LM Studio, Ollama, vLLM, SGLang) or a light subagent.

## Install

```bash
git clone https://github.com/WMJOON/document-design-system.git
pip install -r document-design-system/requirements.txt        # rdflib, pyshacl, PyYAML (Python ≥ 3.9)
# use it as an agent skill: copy or symlink the skill folder into your agent's skills directory
ln -s "$PWD/document-design-system/skills/document-design-system" ~/.claude/skills/document-design-system
```

Your agent reads [`SKILL.md`](skills/document-design-system/SKILL.md), which tells it which path to take
for a request. Everything below also works by hand from `skills/document-design-system/`.

## How a document is modelled

Three independent axes, each with one design principle:

| Axis | Principle | What it decides | Expressed by | Checked by |
|---|---|---|---|---|
| **Structure** | Hierarchy & progressive disclosure | **Depth** = level of abstraction: a Section's leading content is the overview of its sub-Sections, and deeper means more detail. **Order** = logical progression: a premise comes before whatever depends on it. | Section nesting and sibling order over blocks: Section, Heading, Paragraph, List / ListItem, Table / TableRow / TableCell | SHACL: hierarchy and container rules, overview links point down, premises come first |
| **Semantic** | Meaning & fidelity | What each part does for the judgment, and which parts rest on, support, contradict or review others | Roles (Problem, Goal, Scope, Criterion, Alternative, Claim, Evidence, Counterargument, Decision, Rationale, Critique, UnresolvedIssue, Requirement, Policy, …) and relations (`basedOn`, `supportedBy`, `elaboratedBy`, `counters`, `targets`) with PROV-O provenance | SHACL for required roles and links; fidelity, coverage, counterarguments, perspective bias and evidence sufficiency by review (a person, or a model as a second opinion) |
| **Presentation** | Consistency & predictability | How each kind of meaning is shown, the same way every time, so readers know where to look — it follows meaning and never defines it | Typography / Layout / Style tokens → Markdown rules; defaults per structure (DesignSystem) and per meaning (DocumentFrame) | Consistency, distinguishability and predictability checks |

Two contracts bind the axes together:

- A **DesignSystem** says what a document *may* use: which structures, roles and styles
  (`PlanningSystem`, `MemoSystem`, `DeliberationSystem`, or your own).
- A **DocumentFrame** says what a document *must* contain and how each meaning is presented — e.g.
  `DecisionRecord-v1` needs a decision question, a decision and a rationale. Frames are versioned by
  IRI, so revising a Frame never changes documents written against the old version.

## Three ways to use it

### 1. Write a document and validate it

```bash
cd skills/document-design-system
sed 's#new-doc#my-id#g' templates/default-planning.ttl > /tmp/doc.ttl     # or build it in Python (below)
python3 scripts/validate.py /tmp/doc.ttl                                  # PASS, or each violation and its cause
python3 scripts/render.py /tmp/doc.ttl -o /tmp/doc.md                     # TTL -> Markdown
python3 scripts/parse.py /tmp/doc.md -o /tmp/back.ttl                     # Markdown -> TTL (round trip)
python3 scripts/export.py /tmp/doc.ttl -f json-ld                         # turtle, json-ld, nt, xml
```

A violation names the rule, the component and the cause:

```text
$ python3 scripts/validate.py tests/fixtures/invalid/premise-after-dependent.ttl
FAIL  1 SHACL violation(s)
  - [ddsh:PremiseOrderShape] c:decision = c:criterion-rev
      Premise https://example.org/data/component/search-tool-decision/criterion-rev (dds:basedOn) must come before the component that depends on it.
```

### 2. Write a decision document

Pick a Frame and build the document from the generated builder. Links are keyword arguments; the
builder fills ids, hierarchy and order.

```python
import sys; sys.path.insert(0, "generated")
from build_deliberation import Doc

d = Doc("pilot", "Pilot decision", lang="en", frame="DecisionRecord-v1")
d.add(d.overview("ov", "We run a three-month pilot with one team.", elaboratedBy=["dec"]),
      d.decision_question("q", "Do we adopt the search tool this quarter?"),
      d.section("premises", d.heading("ph", "Premises"),
                d.criterion("crit", "Any change must be reversible within three months.")),
      d.section("details", d.heading("dh", "Decision"),
                d.decision("dec", "Pilot with one team.", basedOn=["crit"], supportedBy=["why"]),
                d.rationale("why", "Cheap to undo, and it measures real use.")))
d.write("/tmp/pilot.ttl")
```

Six standard Frames ship with templates you can copy (`templates/deliberation-0N-*.ttl`):
ProblemFraming → DecisionQuestion → AlternativeComparison → IndependentCritique →
DeliberationRevision → DecisionRecord. Critiques are opinions, not vetoes: a rejected critique stays in
the document, and a deferred one must be carried by an UnresolvedIssue.

### 3. Evaluate it — with or without a model

```bash
python3 scripts/evaluate.py /tmp/pilot.ttl          # deterministic: no model is called
```

```text
Structure
  Hierarchy: Pass
  Depth: Pass
  Order: Pass
  Frame contract: Pass

Semantic
  Fidelity: NotEvaluated
  Coverage: NeedsReview
      - no Scope component: coverage / MECE cannot be judged without a stated scope
  Counterargument: NotEvaluated
  …
  Traceability: Pass
      - every Claim / Decision links to grounds; whether they suffice is not judged
  …
```

Semantic items (fidelity, evidence sufficiency, coverage, counterarguments, perspective bias,
consistency) need judgment. Add a model only when you want that review:

```bash
python3 scripts/semantic_eval.py --list-models                    # local servers and their models
python3 scripts/semantic_eval.py /tmp/pilot.ttl --backend ollama:qwen3:8b \
    --cache /tmp/.dds/cache.ttl --out /tmp/.dds/assessments.ttl
python3 scripts/evaluate.py /tmp/pilot.ttl --assessments /tmp/.dds/assessments.ttl
```

Model results are shown with the model name and its confidence, as **NeedsReview**. Only a recorded
human assessment closes a semantic item.

## Semantic checks that cost less

| Layer | Checks | Model calls |
|---|---|---|
| L0 | structure, depth, order, styles, required meanings, links, provenance | never (SHACL + Python) |
| L1 | one component at a time: overview vs details, claim vs evidence, use of premises | only for components affected by a change and missing from the cache |
| L2 | independent whole-document critique: coverage, counterarguments, perspectives, unlinked contradictions | only on triggers: first run, a changed criterion or scope, accumulated change, `--l2`, `--major`, `--high-risk` |

- **Incremental**: with `--prev old.ttl`, only components reached from the change through the recorded
  relations are re-judged. Dependencies that were never recorded are not found — that is what L2 is for.
- **Cache**: results are stored as W3C EARL records keyed by the exact packet content, premises,
  evidence, criterion definitions, rule / prompt version and model. Change any of them and the result
  is recomputed; a whitespace-only edit is not.
- **Small inputs**: each packet holds the target, its premises and its evidence, not the whole document.
- **Judges**: any OpenAI-compatible runtime — `omlx:`, `lmstudio:`, `ollama:`, `vllm:`, `sglang:`
  `<model>` (add `@http://host:port/v1` for a non-default port), or `openai:<url>#<model>`. Without a
  local runtime, the agent can delegate packets to a light-model subagent
  (`--backend agent:haiku --emit … / --replies …`). `--strong <spec>` escalates uncertain results.
- **Measure, don't assume**: `scripts/bench.py` compares the optimized pipeline with a naive
  "whole document, one call per criterion" strategy on labelled scenarios — calls, tokens, latency,
  and whether each injected error was even looked at. Savings depend on your documents and models;
  DDS does not promise a number.

Details: [`references/semantic-evaluation.md`](skills/document-design-system/references/semantic-evaluation.md).

## What is validated

- Documents, components and DesignSystems: one DesignSystem per document, one structure per
  component, supported types and styles only, language-tagged content.
- Hierarchy: no cycles, one parent, no orphans, unique sibling order, container rules
  (Section → any; List → ListItem; Table → TableRow; TableRow → TableCell).
- Frames: required meanings and counts, compatible DesignSystem, presentation mappings.
- Meaning links: targets inside the same document; overviews point down (depth); premises come first
  and revisions after them (order); counterarguments and critiques say what they address; deferred
  critiques stay visible; traceability where the Frame requires it.
- Assessment records: subject, criterion, outcome, basis; model id and uncertainty for AI opinions.

SHACL Core + SHACL-SPARQL (pyshacl), run **without inference** so missing data cannot be inferred away.
Every rule has a test fixture that breaks exactly that rule. See
[`references/validation-rules.md`](skills/document-design-system/references/validation-rules.md).

## What DDS does not claim

Complete meaning preservation, discovery of every alternative, absolute MECE, real stakeholder
agreement, or objective AI judgment. Coverage is judged only within a stated Scope; what cannot be
checked stays NeedsReview or NotEvaluated. See
[`references/evaluation.md`](skills/document-design-system/references/evaluation.md).

## Repository layout

```
skills/document-design-system/
├── SKILL.md       agent playbook: which path, which commands, what to report
├── ontology/      classes and properties (TBox)
├── shapes/        SHACL rules
├── instances/     DesignSystems, standard Frames, evaluation criteria
├── library/       component prototypes  ──gen_builder.py──▶  generated/build_*.py
├── templates/     blank skeletons and six deliberation templates
├── examples/      Frame evolution (v1 → v2)
├── config/        presentation token → Markdown rules
├── scripts/       validate · render · parse · export · evaluate · compare · semantic_eval · bench
├── references/    design notes, rules, evaluation, semantic checks
└── tests/         pytest (run: python3 -m pytest -q tests)
```

## Versions

- **v0.3.0** — DocumentFrames, deliberation semantics and relations, provenance, depth / order rules,
  per-criterion evaluation, Frame evolution, cost-aware semantic checks on local runtimes.
- **v0.2.0** — component libraries and generated builders; TTL as the only authoring format.
- **v0.1.0** — three-axis ontology, SHACL validation, Markdown round trip.

## Namespaces

The vocabulary uses the placeholder `https://example.org/ontology/dds#`; instance data defaults to
`https://example.org/data/` (`--base`). Replace them with namespaces you control before publishing your
own vocabulary.

## 한국어 요약

DDS는 사람이 판단에 쓰는 문서(기획안, 정책서, 명세서, 결정 기록)를 자유 텍스트가 아닌 RDF/OWL 그래프로 다루는 에이전트 스킬입니다. 세 축이 각자 하나의 원칙을 맡습니다.

| 축 | 원칙 | 정하는 것 |
|---|---|---|
| 구조 | 계층과 점진 공개 | 깊이 = 추상화 수준(상위 Section의 앞부분이 하위의 개요), 순서 = 논리 전개(전제가 먼저) |
| 의미 | 의미 보존과 충실성 | 각 부분이 판단에서 하는 역할, 그리고 전제·근거·반박·비평으로 이어진 의존 관계 |
| 표현 | 일관성과 예측 가능성 | 같은 의미는 늘 같은 모양으로 보이게 한다. 표현은 의미를 따를 뿐 의미를 정하지 않는다 |

DesignSystem은 문서가 쓸 수 있는 것을, DocumentFrame은 문서가 반드시 담아야 할 것을 정합니다. 그래서 코드를 컴파일러가 검사하듯 문서를 검사할 수 있습니다. 결정에 근거가 있는지, 전제가 쓰이기 전에 먼저 나오는지, 비평이 슬그머니 사라지지 않았는지, 요약이 근거로 이어지는지를 봅니다. TTL이 정본이고 Markdown은 손실 없이 되돌릴 수 있는 렌더링입니다.

- **세 가지 사용 흐름**: 문서 작성·검증·렌더링, DocumentFrame(문제 정의 → 결정 질문 → 대안 비교 → 독립 비평 → 숙의 개정 → 결정 기록)으로 결정 문서 작성, 항목별 평가.
- **평가**: 항목마다 Pass / Fail / NeedsReview / NotEvaluated와 근거를 보고하며 합계 점수는 없습니다. 모델 의견은 판정이 아니라 검토 필요로 표시하고, 의미 항목은 사람의 평가 기록으로만 닫힙니다.
- **비용을 줄인 의미 검사**: 모델이 필요하지 않은 검사는 SHACL·Python으로 끝내고, 변경 영향 범위만 최소 입력으로 다시 판정하며, 결과를 캐시합니다. 판정 모델은 OpenAI 호환 로컬 런타임(oMLX, LM Studio, Ollama, vLLM, SGLang)을 쓰고, 없으면 경량 서브에이전트에 위임합니다. 절감 효과는 `bench.py`로 직접 측정하며 미리 약속하지 않습니다.
- 에이전트는 `SKILL.md`를 읽고 요청에 맞는 경로를 고릅니다.

## License

MIT
