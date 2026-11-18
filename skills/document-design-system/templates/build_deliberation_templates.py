#!/usr/bin/env python3
"""Write the six deliberation templates (one per standard DocumentFrame, v1).

Generated from generated/build_deliberation.py; do not hand-edit the TTL output, edit this script
and re-run it:  python3 templates/build_deliberation_templates.py

Every template follows the Structure principles:
  - Depth = abstraction: root paragraphs are the document overview; each one links down
    (elaboratedBy) into the Sections that hold the details.
  - Order = logical progression: premises (scope, criteria, assumptions) come first; components
    that depend on them say so with basedOn.
The six documents form one chain: each is prov:wasDerivedFrom the previous step.
Copy one, replace `new-doc` with your id (sed 's#new-doc#my-id#g') and every «...» placeholder.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_deliberation", HERE.parent / "generated" / "build_deliberation.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

DOC = B.BASE + "doc/"
STEPS = ["01-problem-framing", "02-decision-question", "03-alternative-comparison",
         "04-independent-critique", "05-deliberation-revision", "06-decision-record"]


def new(step, title, frame):
    i = STEPS.index(step)
    prev = [DOC + f"new-doc-{STEPS[i - 1]}"] if i else []
    return B.Doc(f"new-doc-{step}", title, lang="ko", frame=frame, derived_from=prev)


def premises(d, *extra):
    return d.section("premises", d.heading("premises-h", "전제"),
                     d.scope("scope", "«범위: 포함하는 것과 제외하는 것»"),
                     d.criterion("criterion", "«판단 기준»"), *extra)


def problem_framing():
    d = new("01-problem-framing", "«문제 정의 제목»", "ProblemFraming-v1")
    d.add(d.overview("overview", "«한 문단 개요: 누구의 어떤 문제를, 어떤 범위에서 다루는가»",
                     elaboratedBy=["problem", "goal"]),
          premises(d, d.assumption("assumption", "«검증 없이 받아들인 가정»")),
          d.section("details", d.heading("details-h", "문제와 목표"),
                    d.problem("problem", "«문제 진술»", basedOn=["scope"]),
                    d.perspective("perspective", "«이해관계자 관점»"),
                    d.goal("goal", "«도달하려는 상태»", basedOn=["criterion"])))
    return d


def decision_question():
    d = new("02-decision-question", "«결정 질문 제목»", "DecisionQuestion-v1")
    d.add(d.overview("overview", "«무엇을 누가 결정해야 하는가»", elaboratedBy=["question"]),
          premises(d, d.assumption("constraint-note", "«결정을 묶는 제약이나 가정»")),
          d.section("details", d.heading("details-h", "결정 질문"),
                    d.decision_question("question", "«결정 질문»", basedOn=["scope", "criterion"]),
                    d.description("required-evidence", "«판단에 필요한 근거»")))
    return d


def alternative_comparison():
    d = new("03-alternative-comparison", "«대안 비교 제목»", "AlternativeComparison-v1")
    d.add(d.overview("overview", "«대안 몇 개를 어떤 기준으로 비교했고, 무엇이 미분류로 남았는가»",
                     elaboratedBy=["alt-a", "alt-b", "unclassified"]),
          premises(d),
          d.section("details", d.heading("details-h", "대안"),
                    d.alternative("alt-a", "«A안»", basedOn=["criterion"], supportedBy=["evidence"]),
                    d.alternative("alt-b", "«B안»", basedOn=["criterion"]),
                    d.evidence("evidence", "«A안을 뒷받침하는 근거»"),
                    d.risk("risk", "«위험»"),
                    d.unresolved_issue("unclassified", "«어느 대안에도 속하지 않는 사례 (완전성은 선언하지 않는다)»")))
    return d


def independent_critique():
    d = new("04-independent-critique", "«독립 비평 제목»", "IndependentCritique-v1")
    d.add(d.overview("overview", "«비평 몇 건, 그중 반영·기각·보류는 각각 몇 건인가»",
                     elaboratedBy=["critique-1", "critique-2"]),
          d.section("details", d.heading("details-h", "비평"),
                    d.claim("claim", "«검토 대상 주장»", supportedBy=["evidence"]),
                    d.evidence("evidence", "«주장의 근거»"),
                    d.critique("critique-1", "«누락된 대안이나 근거 부족 지적»",
                               targets=["claim"], resolution="accepted"),
                    d.counterargument("counter", "«반례»", counters=["claim"]),
                    d.critique("critique-2", "«합의되지 않은 지적»", targets=["claim"], resolution="deferred"),
                    d.unresolved_issue("open", "«보류된 지적의 쟁점»", wasDerivedFrom=["critique-2"])))
    return d


def deliberation_revision():
    d = new("05-deliberation-revision", "«숙의 개정 제목»", "DeliberationRevision-v1")
    d.add(d.overview("overview", "«무엇이 바뀌었고 무엇이 열려 있는가»", elaboratedBy=["revised", "open"]),
          premises(d),
          d.section("details", d.heading("details-h", "개정"),
                    d.critique("critique", "«반영할 지적»", targets=["criterion"], resolution="deferred"),
                    d.criterion("revised", "«전제 변경: 무엇을 왜 바꾸는가. 후행 영향은 재검토한다»",
                                wasRevisionOf=["criterion"]),
                    d.unresolved_issue("open", "«아직 합의되지 않은 사항»", wasDerivedFrom=["critique"])))
    return d


def decision_record():
    d = new("06-decision-record", "«결정 기록 제목»", "DecisionRecord-v1")
    d.add(d.overview("overview", "«무엇을 결정했고, 무엇을 근거로 했으며, 무엇이 남았는가»",
                     elaboratedBy=["decision", "open"]),
          d.decision_question("question", "«결정 질문»"),
          premises(d),
          d.section("details", d.heading("details-h", "결정과 근거"),
                    d.decision("decision", "«결정»", basedOn=["scope", "criterion"], supportedBy=["rationale"]),
                    d.rationale("rationale", "«결정 이유»"),
                    d.claim("claim", "«결정을 지지하는 주장»", supportedBy=["evidence"]),
                    d.evidence("evidence", "«근거»", hadPrimarySource=["https://example.org/sources/replace-me"]),
                    d.counterargument("counter", "«남아 있는 반론»", counters=["claim"])),
          d.section("open-section", d.heading("open-h", "미해결"),
                    d.unresolved_issue("open", "«미해결 사항»")))
    return d


def main():
    for fn, step in zip([problem_framing, decision_question, alternative_comparison,
                         independent_critique, deliberation_revision, decision_record], STEPS):
        out = HERE / f"deliberation-{step}.ttl"
        fn().write(out)
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
