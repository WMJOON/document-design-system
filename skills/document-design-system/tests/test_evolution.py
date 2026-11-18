"""v0.3.0 Frame evolution: versioned Frames, pinned documents, per-criterion comparison."""
from _util import FIXTURES, SKILL, run

from rdflib import Graph, URIRef
from rdflib.namespace import OWL

from dds_lib.evaluation import compare, evaluate, from_earl, to_earl
from dds_lib.graph import DDS, PROV, load_data, validate_graph
from dds_lib.model import documents

EVO = SKILL / "examples" / "frame-evolution"
V2 = EVO / "decision-record-v2.ttl"
DECISION = FIXTURES / "valid" / "decision-record.ttl"
FRAME = "https://example.org/data/frame/"


def _statuses(path, *extra, date="2026-11-18T00:00:00Z"):
    g = load_data([path, *extra])
    ev = evaluate(g, documents(Graph().parse(path))[0], date=date)
    return ev


def test_v2_is_a_new_version_of_v1():
    g = load_data([V2])
    v1, v2 = URIRef(FRAME + "DecisionRecord-v1"), URIRef(FRAME + "DecisionRecord-v2")
    assert (v2, PROV.wasRevisionOf, v1) in g
    assert str(g.value(v1, OWL.versionInfo)) == "1" and str(g.value(v2, OWL.versionInfo)) == "2"
    assert validate_graph(g).conforms


def test_revision_proposal_is_a_valid_deliberation_document():
    r = run("validate.py", EVO / "revision-proposal.ttl")
    assert r.returncode == 0, r.stdout


def test_loading_v2_does_not_change_v1_documents():
    a = _statuses(DECISION)
    b = _statuses(DECISION, V2)
    assert {k: i.status for k, i in a.items.items()} == {k: i.status for k, i in b.items.items()}
    rows = compare(from_earl(to_earl(a)), from_earl(to_earl(b)))
    assert not any(r["changed"] for r in rows)


def test_repinning_to_v2_is_compared_per_criterion(tmp_path):
    """A document without Scope passes v1 and fails v2's contract: the change is reported, not hidden."""
    text = DECISION.read_text(encoding="utf-8").replace("dds:hasSemantic semantic:Scope ;", "dds:hasSemantic semantic:Description ;")
    v1doc = tmp_path / "v1.ttl"
    v1doc.write_text(text, encoding="utf-8")
    v2doc = tmp_path / "v2.ttl"
    v2doc.write_text(text.replace("frame:DecisionRecord-v1 ;", "frame:DecisionRecord-v2 ;"), encoding="utf-8")
    before = _statuses(v1doc)
    after = _statuses(v2doc, V2, date="2026-11-19T00:00:00Z")
    assert before.items["frame-contract"].status == "Pass"
    assert after.items["frame-contract"].status == "Fail"
    e1, e2 = tmp_path / "e1.ttl", tmp_path / "e2.ttl"
    to_earl(before).serialize(destination=str(e1), format="turtle")
    to_earl(after).serialize(destination=str(e2), format="turtle")
    r = run("compare.py", e1, e2)
    assert r.returncode == 1
    assert "frame-contract" in r.stdout and "CHANGED" in r.stdout
    hist = tmp_path / "hist"
    hist.mkdir()
    e1.rename(hist / "a.ttl")
    e2.rename(hist / "b.ttl")
    r = run("compare.py", "--history", hist)
    assert r.returncode == 1 and "DecisionRecord-v2" in r.stdout
