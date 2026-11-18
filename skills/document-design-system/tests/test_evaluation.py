"""v0.3.0 evaluation: structural Fail vs NeedsReview vs NotEvaluated, assessments, EARL output."""
import json

from _util import FIXTURES, PROPOSAL, run

from rdflib import Graph

from dds_lib.evaluation import evaluate, from_earl, to_earl
from dds_lib.graph import load_data
from dds_lib.model import documents

DECISION = FIXTURES / "valid" / "decision-record.ttl"
REVIEW = FIXTURES / "assessments" / "decision-record-review.ttl"
BAD_REVIEW = FIXTURES / "assessments" / "invalid-ai-without-model.ttl"
DATE = "2026-11-18T00:00:00Z"


def _eval(path, *assessments):
    g = load_data([path, *assessments])
    doc = documents(Graph().parse(path))[0]
    ev = evaluate(g, doc, date=DATE)
    return {k: i.status for k, i in ev.items.items()}, ev


def test_valid_decision_record():
    st, ev = _eval(DECISION)
    assert st["structure-hierarchy"] == st["structure-depth"] == st["frame-contract"] == "Pass"
    assert st["structure-order"] == "NeedsReview"          # dependent of a revised premise
    assert st["traceability"] == "Pass"                    # links exist (sufficiency not judged)
    assert st["counterargument"] == "NeedsReview"          # overview does not lead to the open issue
    for k in ("fidelity", "perspective-bias", "concept-consistency", "coverage"):
        assert st[k] == "NotEvaluated", k                  # no assessment, no pre-check signal
    assert any("deferred critique" in u for u in ev.unresolved)
    assert any("open issue" in u for u in ev.unresolved)


def test_structural_fail_is_distinct_from_needs_review():
    st, _ = _eval(FIXTURES / "invalid" / "premise-after-dependent.ttl")
    assert st["structure-order"] == "Fail"
    st, _ = _eval(FIXTURES / "invalid" / "traceability-missing.ttl")
    assert st["traceability"] == "Fail"
    st, _ = _eval(FIXTURES / "invalid" / "elaboration-not-deeper.ttl")
    assert st["structure-depth"] == "Fail"
    st, _ = _eval(FIXTURES / "invalid" / "frame-requirement-unmet.ttl")
    assert st["frame-contract"] == "Fail" and st["structure-hierarchy"] == "Pass"
    st, _ = _eval(FIXTURES / "invalid" / "deferred-critique-unlinked.ttl")
    assert st["counterargument"] == "Fail"


def test_document_without_frame():
    st, _ = _eval(PROPOSAL)
    assert st["frame-contract"] == "NotEvaluated"
    assert st["presentation-predictability"] == "NotEvaluated"
    assert st["structure-hierarchy"] == "Pass"


def test_human_closes_ai_does_not():
    st, ev = _eval(DECISION, REVIEW)
    assert st["fidelity"] == "Pass"
    assert st["coverage"] == "NeedsReview"
    reasons = " ".join(ev.items["coverage"].reasons)
    assert "example-model-1" in reasons and "scope:" in reasons and "uncertain:" in reasons


def test_human_cannot_override_structural_fail(tmp_path):
    review = tmp_path / "r.ttl"
    review.write_text(REVIEW.read_text(encoding="utf-8").replace("search-tool-decision", "search-tool-decision"),
                      encoding="utf-8")
    st, ev = _eval(FIXTURES / "invalid" / "traceability-missing.ttl", review)
    assert st["traceability"] == "Fail"
    assert any("failure stands" in r for r in ev.items["traceability"].reasons)


def test_invalid_assessment_is_reported_and_ignored():
    st, ev = _eval(DECISION, BAD_REVIEW)
    assert st["fidelity"] == "NotEvaluated"
    assert ev.assessment_errors and all("AIAssessmentShape" in e for e in ev.assessment_errors)


def test_earl_output_roundtrips():
    _, ev = _eval(DECISION)
    back = from_earl(to_earl(ev))
    assert {k: v["status"] for k, v in back.items()} == {k: i.status for k, i in ev.items.items()}
    assert all(v["frame"].endswith("DecisionRecord-v1") for v in back.values())


def test_cli_exit_codes_and_json(tmp_path):
    r = run("evaluate.py", DECISION, "--json", "--date", DATE, "--earl", tmp_path / "e.ttl")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["items"]["traceability"]["status"] == "Pass"
    assert (tmp_path / "e.ttl").exists()
    r = run("evaluate.py", FIXTURES / "invalid" / "traceability-missing.ttl")
    assert r.returncode == 1
    assert "Traceability: Fail" in r.stdout


def test_component_record_does_not_close_document_item(tmp_path):
    """Two overviews, one human record on one of them: document Fidelity stays open."""
    rec = tmp_path / "r.ttl"
    rec.write_text("""@prefix earl: <http://www.w3.org/ns/earl#> .
@prefix criterion: <https://example.org/data/criterion/> .
[] a earl:Assertion ;
    earl:subject <https://example.org/data/component/search-tool-decision/overview> ;
    earl:test criterion:fidelity ; earl:assertedBy <https://example.org/people/reviewer-a> ; earl:mode earl:manual ;
    earl:result [ a earl:TestResult ; earl:outcome earl:passed ; earl:info "This overview is faithful."@en ] .
""", encoding="utf-8")
    st, ev = _eval(DECISION, rec)
    assert st["fidelity"] == "NotEvaluated"
    assert any("component overview" in r and "does not set" in r for r in ev.items["fidelity"].reasons)
