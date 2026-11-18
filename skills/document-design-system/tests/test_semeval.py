"""Cost-aware semantic evaluation: incremental selection, cache validity, packets, routing, L2 triggers."""
import json

import pytest
from _util import FIXTURES, run

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import SKOS

from dds_lib import packets as P
from dds_lib import semeval as S
from dds_lib.evaluation import evaluate
from dds_lib.graph import DDS, load_data
from dds_lib.incremental import diff, impact
from dds_lib.model import documents

DECISION = FIXTURES / "valid" / "decision-record.ttl"
C = "https://example.org/data/component/search-tool-decision/"
DATE = "2026-11-18T00:00:00Z"


def ok(packet):
    return {"verdict": "consistent", "confidence": 0.9, "rationale": "ok"}


def _load(text=None):
    if text is None:
        return load_data([DECISION]), documents(Graph().parse(DECISION))[0]
    g = load_data([])
    g.parse(data=text, format="turtle")
    return g, documents(Graph().parse(data=text, format="turtle"))[0]


def _first_run(backend=None):
    g, doc = _load()
    b = backend or S.ScriptedBackend(ok)
    res = S.run(g, doc, b, date=DATE)
    return g, doc, S.write_entries(res.entries), res


def _edit(old, new):
    text = DECISION.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _rerun(text, cache, backend=None, model=None, **kw):
    prev, pdoc = _load()
    g, doc = _load(text)
    b = backend or S.ScriptedBackend(ok, model=model or "scripted")
    return S.run(g, doc, b, prev=prev, prev_doc=pdoc, cache=cache, has_prior_l2=True, date=DATE, **kw), b


def _called(b):
    return {(p.type, p.subject.rsplit("/", 1)[-1]) for p in b.calls}


# ---------------------------------------------------------------- cache
def test_unchanged_rerun_is_all_cache_hits():
    g, doc, cache, first = _first_run()
    res, b = _rerun(DECISION.read_text(encoding="utf-8"), cache)
    assert b.calls == [] and res.metrics.calls == 0
    assert res.metrics.cache_misses == 0 and res.metrics.cache_hits == first.metrics.packets
    assert res.metrics.l2_reasons == []
    assert {e.key for e in res.entries} == {e.key for e in first.entries}   # L2 results carried over


def test_evidence_change_reevaluates_only_its_claims():
    _, _, cache, first = _first_run()
    text = _edit("응답자 다수가 문서 검색에 주당 1시간 이상을", "응답자 소수만 문서 검색에 주당 10분 이상을")
    res, b = _rerun(text, cache)
    assert _called(b) == {("claim-evidence", "claim"), ("claim-evidence", "overview")}
    assert res.metrics.cache_hits > 0 and res.metrics.outside_impact_misses == 0


def test_heading_edit_calls_nothing():
    _, _, cache, _ = _first_run()
    res, b = _rerun(_edit('"결정과 근거"@ko', '"결정 및 근거"@ko'), cache)
    assert b.calls == []


def test_premise_change_invalidates_dependents_and_triggers_l2():
    _, _, cache, _ = _first_run()
    res, b = _rerun(_edit("3개월 안에 되돌릴 수 있어야 한다", "6개월 안에 되돌릴 수 있어야 한다"), cache)
    called = _called(b)
    assert ("premise-consistency", "decision") in called
    assert ("concept-usage", "criterion-rev") in called
    assert any("core premise changed" in r for r in res.metrics.l2_reasons)
    assert ("global-critique", "search-tool-decision") in called


def test_model_change_invalidates_everything():
    _, _, cache, first = _first_run()
    res, b = _rerun(DECISION.read_text(encoding="utf-8"), cache, model="other-model")
    assert res.metrics.cache_hits == 0
    assert len([p for p in b.calls if p.level == "L1"]) == len([p for p in P.build_l1(*_load())])


def test_prompt_version_change_invalidates(monkeypatch):
    _, _, cache, _ = _first_run()
    monkeypatch.setattr(S, "PROMPT_VERSION", "2")
    res, _ = _rerun(DECISION.read_text(encoding="utf-8"), cache)
    assert res.metrics.cache_hits == 0


def test_criterion_definition_change_invalidates_that_criterion_only():
    g0, doc0, cache, _ = _first_run()
    prev, pdoc = _load()
    g, doc = _load()
    crit = URIRef("https://example.org/data/criterion/claim-evidence")
    g.set((crit, SKOS.definition, Literal("Changed definition.", lang="en")))
    b = S.ScriptedBackend(ok)
    S.run(g, doc, b, prev=prev, prev_doc=pdoc, cache=cache, has_prior_l2=True, date=DATE)
    assert {p.type for p in b.calls} == {"claim-evidence"}


def test_frame_change_is_reported_as_outside_impact():
    _, _, cache, _ = _first_run()
    res, b = _rerun(_edit("dds:usesFrame frame:DecisionRecord-v1 ;", "dds:usesFrame frame:DeliberationRevision-v1 ;"),
                    cache)
    assert res.metrics.outside_impact_misses > 0    # packet keys changed outside the component diff


def test_output_holds_only_valid_entries_and_passes_shacl():
    _, _, cache, first = _first_run()
    text = _edit("응답자 다수가", "응답자 소수가")
    res, _ = _rerun(text, cache)
    g, doc = _load(text)
    valid = {S.cache_key(p, "scripted") for p in P.build_l1(g, doc)} | \
            {S.cache_key(p, "scripted", scope="global") for p in P.build_l2(g, doc)}
    assert {e.key for e in res.entries} <= valid
    out = S.write_entries(res.entries)
    gg = load_data([])
    gg.parse(data=text, format="turtle")
    for t in out:
        gg.add((t))
    ev = evaluate(gg, doc, date=DATE)
    assert ev.assessment_errors == []


# ---------------------------------------------------------------- packets and L0
def test_l0_items_produce_no_packets():
    g, doc = _load()
    crits = {c for p in P.build_l1(g, doc) + P.build_l2(g, doc) for c in p.criteria}
    assert "traceability" not in crits                       # link existence is L0 (SHACL)
    assert not {"structure-depth", "structure-order", "presentation-consistency"} & crits


def test_packets_exclude_unrelated_sections():
    g, doc = _load()
    pk = [p for p in P.build_l1(g, doc) if p.type == "claim-evidence" and p.subject.endswith("/claim")][0]
    assert "가상 설문" in pk.body                              # its evidence
    assert "외부 고객 문서는 제외" not in pk.body              # unrelated premise section
    assert "비용 상한의 금액" not in pk.body                    # unrelated open issue
    assert pk.tokens < P.estimate_tokens(P.plain_outline(g, doc)) + pk.prefix_tokens


def test_overview_packet_uses_section_position_and_details():
    g, doc = _load()
    pk = [p for p in P.build_l1(g, doc) if p.type == "overview-fidelity"][0]
    assert pk.subject.endswith("/overview")
    assert "[OVERVIEW]" in pk.body and "[DETAIL] id=decision" in pk.body


def test_shared_prefix_is_identical_within_a_type():
    g, doc = _load()
    by_type = {}
    for p in P.build_l1(g, doc):
        by_type.setdefault(p.type, set()).add(p.prefix)
    assert all(len(v) == 1 for v in by_type.values())


def test_l2_excludes_prior_verdicts():
    g, doc = _load()
    for p in P.build_l2(g, doc):
        assert "verdict" not in p.body and "consistent" not in p.body


# ---------------------------------------------------------------- triggers, routing, combined
def test_cosmetic_edit_triggers_nothing():
    _, _, cache, _ = _first_run()
    text = _edit("한 팀을 대상으로 3개월 시범 도입한다.", "한 팀을 대상으로  3개월 시범 도입한다")
    prev, pdoc = _load()
    g, doc = _load(text)
    ch = diff(prev, pdoc, g, doc)
    assert {k for c in ch.values() for k in c.kinds} == {"cosmetic"}
    assert impact(g, doc, ch, prev).affected == {}
    res, b = _rerun(text, cache)
    assert res.metrics.l2_reasons == []


def test_negation_is_not_cosmetic():
    prev, pdoc = _load()
    g, doc = _load(_edit("되돌릴 수 있어야 한다", "되돌릴 수 없어도 된다"))
    assert "content" in next(iter(diff(prev, pdoc, g, doc).values())).kinds


def test_escalation_on_uncertain_and_not_with_single_model():
    def light_rule(p):
        if p.type == "claim-evidence":
            return {"verdict": "uncertain", "confidence": 0.3, "rationale": "?"}
        return ok(p)
    g, doc = _load()
    light, strong = S.ScriptedBackend(light_rule, "light"), S.ScriptedBackend(ok, "strong")
    res = S.run(g, doc, light, strong, has_prior_l2=True, date=DATE)
    assert res.metrics.escalations == 3 and {p.type for p in strong.calls} == {"claim-evidence"}  # claim, overview, decision
    same = S.ScriptedBackend(light_rule, "light")
    res2 = S.run(g, doc, same, S.ScriptedBackend(ok, "light"), has_prior_l2=True, date=DATE)
    assert res2.metrics.escalations == 0


def test_high_risk_escalates_decisions():
    g, doc = _load()
    light, strong = S.ScriptedBackend(ok, "light"), S.ScriptedBackend(ok, "strong")
    S.run(g, doc, light, strong, policy=S.L2Policy(high_risk=True), date=DATE)
    assert any(p.subject.endswith("/decision") for p in strong.calls)


def test_combined_l2_is_one_call():
    g, doc = _load()
    sep, comb = S.ScriptedBackend(ok), S.ScriptedBackend(
        lambda p: {"items": {c: ok(p) for c in p.criteria}} if p.combined else ok(p))
    S.run(g, doc, sep, date=DATE)
    S.run(g, doc, comb, combined=True, date=DATE)
    assert len([p for p in sep.calls if p.level == "L2"]) == 4
    assert len([p for p in comb.calls if p.level == "L2"]) == 1


def test_naive_reference_is_one_full_document_call_per_semantic_criterion():
    g, doc = _load()
    b = S.ScriptedBackend(ok)
    res = S.run_naive(g, doc, b, date=DATE)
    from dds_lib.evaluation import ORDER, SEMANTIC
    assert res.metrics.calls == len([k for k in ORDER if k in SEMANTIC])
    assert all("비용 상한의 금액" in p.body for p in b.calls)


def test_cli_cache_file_and_metrics(tmp_path):
    cache, out, met = tmp_path / "c.ttl", tmp_path / "a.ttl", tmp_path / "m.jsonl"
    args = [DECISION, "--backend", "scripted", "--cache", cache, "--out", out, "--metrics", met]
    r1 = run("semantic_eval.py", *args, "--date", DATE)
    assert r1.returncode == 0, r1.stderr
    r2 = run("semantic_eval.py", *args, "--prev", DECISION, "--date", "2026-11-19T00:00:00Z")
    lines = [json.loads(x) for x in met.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["calls"] > 0 and lines[1]["calls"] == 0 and lines[1]["cache_hit_rate"] == 1.0
    assert run("evaluate.py", DECISION, "--assessments", out).returncode == 0


def test_cosmetic_edit_keeps_cache_keys():
    _, _, cache, _ = _first_run()
    res, b = _rerun(_edit("한 팀을 대상으로 3개월 시범 도입한다.", "한 팀을 대상으로  3개월 시범 도입한다"), cache)
    assert b.calls == [] and res.metrics.cache_misses == 0


def test_digit_change_is_not_cosmetic_for_keys():
    _, _, cache, _ = _first_run()
    res, b = _rerun(_edit("한 팀을 대상으로 3개월 시범 도입한다.", "한 팀을 대상으로 6개월 시범 도입한다."), cache)
    assert b.calls, "a number change must be re-evaluated"


def test_schema_echo_reply_is_unwrapped():
    g, doc = _load()
    b = S.ScriptedBackend(lambda p: {"properties": {"verdict": "inconsistent", "confidence": 0.8, "rationale": "x"}})
    res = S.run(g, doc, b, has_prior_l2=True, date=DATE)
    assert {e.status for e in res.entries} == {"Fail"}
