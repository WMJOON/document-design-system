# Document Design System (DDS)

An Agent Skill that models documents — plans, policies, requirement specs, technical specs, decision
records — as an **RDF/OWL ontology**, validates them with **SHACL**, renders them to **Markdown**, and
(since v0.3.0) supports **deliberation**: reusable DocumentFrames, argument and premise relations,
provenance, and a per-criterion evaluation that separates what SHACL can decide from what needs review.

A document is the combination of three independent dimensions:

| Dimension | Answers | Examples |
|---|---|---|
| **Structure** | What kind of block is it? | Section, Heading, Paragraph, List/ListItem, Table/TableRow/TableCell |
| **Semantic** | What role does the content play? | Requirement, Policy, Constraint, Decision, Evidence, Assumption, Description; v0.3.0: Problem, Goal, Scope, DecisionQuestion, Criterion, Alternative, Claim, Counterargument, Perspective, Risk, Rationale, Critique, UnresolvedIssue |
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

## Deliberation documents (v0.3.0)

A document is an interface for judgment, not a goal in itself. v0.3.0 adds:

- **Structure has two properties.** *Depth* is the level of abstraction: a Section's leading content
  is the overview of its sub-Sections (overview is a position, not a semantic type). *Order* is the
  logical progression: a premise comes before what depends on it.
- **DocumentFrame** — a versioned contract (`frame:DecisionRecord-v1`) saying which semantics a
  document needs (`FrameRequirement`, with a minimum count) and how each meaning is presented
  (`SemanticBinding`). Six standard Frames: ProblemFraming, DecisionQuestion, AlternativeComparison,
  IndependentCritique, DeliberationRevision, DecisionRecord. A document pins one version with
  `dds:usesFrame`; a revision is a new IRI (`-v2`, `prov:wasRevisionOf`), so old documents keep their meaning.
- **Relations between components**: `elaboratedBy` (overview → deeper detail), `supportedBy` (grounds),
  `basedOn` (premise, must come earlier), `counters`, `targets` + `resolution` (accepted / rejected /
  deferred; a deferred critique must be carried by an UnresolvedIssue). Provenance reuses PROV-O
  (`wasDerivedFrom`, `wasRevisionOf`, `hadPrimarySource`).
- **`design:DeliberationSystem`** supports the new semantics; Planning / Memo systems are unchanged.
- **Evaluation** — `evaluate.py` reports each criterion (Structure, Semantic, Presentation) as
  Pass / Fail / NeedsReview / NotEvaluated, with reasons and no overall score. Semantic items
  (fidelity, coverage, counterargument, perspective bias, concept consistency) close only on a recorded
  human assessment (W3C EARL); AI assessments must carry a model id and uncertainty and are shown
  as NeedsReview. `compare.py` compares results per criterion across Frame versions.

```bash
python3 scripts/gen_builder.py library/deliberation-components.ttl -o generated/build_deliberation.py
python3 scripts/validate.py templates/deliberation-06-decision-record.ttl
python3 scripts/evaluate.py tests/fixtures/valid/decision-record.ttl \
        --assessments tests/fixtures/assessments/decision-record-review.ttl --earl /tmp/eval.ttl
python3 scripts/compare.py before.ttl after.ttl          # or --history DIR
```

```python
from build_deliberation import Doc       # generated/
d = Doc("pilot", "Pilot decision", lang="en", frame="DecisionRecord-v1")
d.add(d.overview("ov", "We run a three-month pilot.", elaboratedBy=["dec"]),
      d.decision_question("q", "Do we adopt the tool this quarter?"),
      d.section("premises", d.heading("ph", "Premises"), d.criterion("crit", "Must be reversible.")),
      d.section("details", d.heading("dh", "Decision"),
                d.decision("dec", "Pilot with one team.", basedOn=["crit"], supportedBy=["why"]),
                d.rationale("why", "Cheap to undo; measures real use.")))
d.write("pilot.ttl")
```

- **Cost-aware semantic evaluation** — `semantic_eval.py` re-judges only components affected by a
  change (reverse traversal of the relations above), reuses cached results (EARL, keyed by packet
  content, premises, evidence, criterion definitions, rule / prompt version and model), sends minimal
  packets, escalates uncertain results to a stronger model, and runs a whole-document critique (L2)
  only on deterministic triggers. `bench.py` compares it with a naive reference strategy on the same
  scenarios. The judge is a local model on any OpenAI-compatible runtime (oMLX, LM Studio, Ollama,
  vLLM, SGLang: `--backend ollama:qwen3:8b`, `--list-models` to see what is available) or, as a second
  option, a light-model subagent the calling agent delegates to (`--backend agent:haiku --emit` /
  `--replies`). See [`references/semantic-evaluation.md`](skills/document-design-system/references/semantic-evaluation.md).

What DDS does **not** claim: complete meaning preservation, discovery of every alternative, absolute
MECE, real stakeholder agreement, or objective AI evaluation. Coverage is judged only within a stated
Scope; unverifiable items stay NeedsReview / NotEvaluated. See
[`references/evaluation.md`](skills/document-design-system/references/evaluation.md).

## What is validated

- Document → exactly one existing DesignSystem, at least one root Component
- Component → exactly one Structure, 0..n Semantics, 0..1 Presentation, a positive `hasOrder`,
  language-tagged content where required
- Hierarchy → no cycles, single parent, no orphans, unique sibling order, container policy
  (Section → any; List → ListItem; Table → TableRow; TableRow → TableCell)
- DesignSystem support → every Structure / Semantic / Presentation used, including default bindings,
  is supported by the document's DesignSystem
- v0.3.0 → Frame contract (required semantics and counts, DesignSystem compatibility, mappings),
  relation targets in the same document, overview links point down (depth), premises precede their
  dependents and revisions follow their premise (order), counterargument / critique completeness,
  traceability when the Frame requires it, assessment record completeness

The rules use SHACL Core plus SHACL-SPARQL (pyshacl) and run **without inference**, so `rdfs:domain` and
`rdfs:range` cannot hide missing data. See
[`references/validation-rules.md`](skills/document-design-system/references/validation-rules.md).

## Layout

```
skills/document-design-system/
├── SKILL.md            # agent instructions
├── ontology/           # TBox (core, structure, semantic, presentation, relations)
├── shapes/             # SHACL shapes
├── instances/          # default DesignSystems, standard Frames, evaluation criteria, example (ABox)
├── library/            # component prototypes (planning, deliberation; source of the builders)
├── generated/          # generated document builder (do not hand-edit)
├── config/             # Presentation token -> Markdown mapping
├── scripts/            # gen_builder / validate / render / parse / export / evaluate / compare / semantic_eval / bench (+ dds_lib)
├── templates/          # blank TTL skeletons (default-*.ttl) + six deliberation templates
├── examples/           # frame-evolution: DecisionRecord v2 and its revision proposal
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

v0.3.0은 판단을 돕는 숙의 문서를 지원합니다. Structure는 깊이(추상화 수준: 상위 Section의 선행 내용이 하위의 개요)와 순서(논리 전개: 전제가 먼저)로 정보를 조직합니다. 재사용 계약인 DocumentFrame(버전별 IRI) 6종, 컴포넌트 간 관계(개요→상세, 근거, 전제, 반박, 비평과 처리 결과), PROV-O 출처를 추가했습니다. `evaluate.py`는 항목마다 Pass / Fail / NeedsReview / NotEvaluated를 근거와 함께 보고하고 합계 점수는 내지 않습니다. 의미 품질 항목은 사람의 평가 기록(EARL)으로만 닫히고, AI 평가는 모델 식별자·불확실성과 함께 검토 필요로 표시합니다. `compare.py`는 Frame 버전 전후 결과를 항목별로 비교합니다. `semantic_eval.py`는 변경 영향 범위만 모델로 재평가하고(관계 역방향 탐색), 결과를 EARL 기록으로 캐시하며, 최소 입력 패킷과 조건부 전역 비평(L2)으로 호출 수와 토큰을 줄입니다. 절감 효과는 `bench.py`로 같은 데이터에서 측정해 품질 지표와 함께 보고합니다. 판정 모델은 OpenAI 호환 로컬 런타임(oMLX, LM Studio, Ollama, vLLM, SGLang)의 모델을 1차로 고르고(`--list-models`), 로컬 런타임이 없으면 경량 모델 서브에이전트(Haiku 등)에 패킷을 위임합니다(`--emit` → `--replies`).

## License

MIT
