import json

import pytest
from _util import FIXTURES, run

from dds_lib.graph import load_data, validate_graph

# fixture -> (required shapes, additionally tolerated shapes)
EXPECT = {
    "missing-structure": ({"ddsh:Component-structure"}, set()),
    "unsupported-structure": ({"ddsh:SupportedStructureShape"}, set()),
    "unsupported-semantic": ({"ddsh:SupportedSemanticShape"}, set()),
    "unsupported-presentation": ({"ddsh:SupportedPresentationShape"}, set()),
    "duplicate-order": ({"ddsh:UniqueSiblingOrderShape"}, set()),
    "invalid-order": ({"ddsh:Component-order"}, set()),
    # a reachable cycle always gives its entry node a second parent
    "cyclic-child": ({"ddsh:NoCycleShape"}, {"ddsh:SingleParentShape"}),
    "missing-design-system": ({"ddsh:Document-designSystem"}, set()),
    "orphan-component": ({"ddsh:ReachableShape"}, set()),
    "two-parents": ({"ddsh:SingleParentShape"}, set()),
    "non-container-child": ({"ddsh:ContainerPolicyShape"}, set()),
    "content-on-container": ({"ddsh:ContentForbiddenShape"}, set()),
    "missing-content": ({"ddsh:ContentRequiredShape"}, set()),
    "plain-string-content": ({"ddsh:Component-content"}, set()),
    "list-item-outside-list": ({"ddsh:ItemParentShape"}, set()),
    "ordered-on-paragraph": ({"ddsh:OrderedOnlyOnListShape"}, set()),
    "untyped-component": ({"ddsh:ComponentShape"}, {"ddsh:Component-child"}),
    "binding-unsupported": ({"ddsh:BindingSupportedShape"}, set()),
    # v0.3.0 frame contract, relations, deliberation structure
    "frame-requirement-unmet": ({"ddsh:FrameContractShape"}, set()),
    "frame-design-system-incompatible": ({"ddsh:FrameDesignSystemShape"}, set()),
    "mapping-unsupported": ({"ddsh:MappingSupportedShape"}, set()),
    "duplicate-mapping": ({"ddsh:UniqueMappingShape"}, set()),
    "requirement-without-semantic": ({"ddsh:Requirement-semantic"}, set()),
    "multiple-frames": ({"ddsh:Document-frame"}, set()),
    "relation-cross-document": ({"ddsh:RelationTargetShape"}, set()),
    # a non-component target is also outside the document
    "relation-untyped-target": ({"ddsh:Component-relation"}, {"ddsh:RelationTargetShape"}),
    # Structure: depth = abstraction, order = logical progression
    "elaboration-not-deeper": ({"ddsh:ElaborationDepthShape"}, set()),
    "premise-after-dependent": ({"ddsh:PremiseOrderShape"}, set()),
    "revision-before-original": ({"ddsh:RevisionOrderShape"}, set()),
    "counter-without-target": ({"ddsh:CounterTargetShape"}, set()),
    "critique-without-resolution": ({"ddsh:CritiqueShape"}, set()),
    "deferred-critique-unlinked": ({"ddsh:DeferredCritiqueShape"}, set()),
    "traceability-missing": ({"ddsh:TraceabilityShape"}, set()),
    "invalid-resolution": ({"ddsh:Component-resolution"}, set()),
    "provenance-literal": ({"ddsh:Component-provenance"}, set()),
    # v0.3.0 Frame / binding / provenance property shapes and assessment records
    "document-provenance-literal": ({"ddsh:Document-provenance"}, set()),
    "frame-without-requirement": ({"ddsh:Frame-requirement"}, set()),
    "frame-mapping-untyped": ({"ddsh:Frame-mapping"}, set()),
    "frame-design-system-untyped": ({"ddsh:Frame-designSystem"}, set()),
    "frame-traceability-not-boolean": ({"ddsh:Frame-traceability"}, set()),
    "frame-question-without-language": ({"ddsh:Frame-question"}, set()),
    "frame-revision-not-a-frame": ({"ddsh:Frame-revision"}, set()),
    "requirement-min-zero": ({"ddsh:Requirement-min"}, set()),
    "binding-without-semantic": ({"ddsh:SemanticBinding-semantic"}, set()),
    "binding-without-presentation": ({"ddsh:SemanticBinding-presentation"}, set()),
    "assessment-without-subject": ({"ddsh:Assessment-subject"}, set()),
    "assessment-unknown-test": ({"ddsh:Assessment-test"}, set()),
    "assessment-without-assessor": ({"ddsh:Assessment-assertedBy"}, set()),
    "assessment-bad-outcome": ({"ddsh:Assessment-outcome"}, set()),
    "assessment-without-basis": ({"ddsh:Assessment-info"}, set()),
    "ai-assessment-without-model": ({"ddsh:AIAssessmentShape"}, set()),
    "coverage-without-scope": ({"ddsh:CoverageScopeShape"}, set()),
    "critique-without-target": ({"ddsh:CritiqueShape"}, set()),
}


def test_every_invalid_fixture_has_an_expectation():
    names = {p.stem for p in (FIXTURES / "invalid").glob("*.ttl")}
    assert names == set(EXPECT)


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_invalid_fixture_fails_on_intended_shape(name):
    required, tolerated = EXPECT[name]
    r = validate_graph(load_data([FIXTURES / "invalid" / f"{name}.ttl"]))
    assert not r.conforms
    got = r.shapes()
    assert required <= got, f"missing {required - got}; got {got}"
    assert got <= required | tolerated, f"unexpected {got - required - tolerated}"
    assert all(v.message for v in r.violations), "every violation needs a cause message"


@pytest.mark.parametrize("path", sorted((FIXTURES / "valid").glob("*.ttl")), ids=lambda p: p.stem)
def test_valid_fixtures_conform(path):
    r = validate_graph(load_data([path]))
    assert r.conforms, r.violations


def test_multiple_semantics_allowed():
    from rdflib.namespace import Namespace
    from dds_lib.graph import DDS

    g = load_data([FIXTURES / "valid" / "multi-semantic.ttl"])
    c = Namespace("https://example.org/data/component/t/")
    assert len(set(g.objects(c.p, DDS.hasSemantic))) == 3


def test_cli_exit_codes_and_json():
    ok = run("validate.py", FIXTURES / "valid" / "minimal.ttl")
    assert ok.returncode == 0 and "PASS" in ok.stdout
    bad = run("validate.py", FIXTURES / "invalid" / "duplicate-order.ttl", "--json", "--lang", "ko")
    assert bad.returncode == 1
    data = json.loads(bad.stdout)
    assert data["conforms"] is False
    assert {v["shape"] for v in data["violations"]} == {"ddsh:UniqueSiblingOrderShape"}
    assert "중복" in data["violations"][0]["message"]


def test_cli_parse_error_exit_2(tmp_path):
    broken = tmp_path / "broken.ttl"
    broken.write_text("this is not turtle")
    assert run("validate.py", broken).returncode == 2


def test_no_inference_dangling_design_system():
    """rdfs:range must not 'invent' a DesignSystem: validation runs without inference."""
    r = validate_graph(load_data([FIXTURES / "invalid" / "missing-design-system.ttl"]))
    assert any(v.value and "DoesNotExist" in v.value for v in r.violations)


@pytest.mark.parametrize("lang,hangul", [("en", False), ("ko", True)])
def test_message_language_is_deterministic(lang, hangul):
    """pyshacl drops language tags on substituted SPARQL messages; selection must still follow --lang."""
    for _ in range(3):
        r = validate_graph(load_data([FIXTURES / "invalid" / "duplicate-order.ttl"]), lang=lang)
        for v in r.violations:
            assert any("가" <= ch <= "힣" for ch in v.message) is hangul


def test_frame_min_occurs_counts_components(tmp_path):
    """AlternativeComparison-v1 needs 2 Alternatives: 1 fails, 2 pass."""
    head = """@prefix dds: <https://example.org/ontology/dds#> .
@prefix structure: <https://example.org/data/structure/> .
@prefix semantic: <https://example.org/data/semantic/> .
@prefix design: <https://example.org/data/design/> .
@prefix frame: <https://example.org/data/frame/> .
@prefix doc: <https://example.org/data/doc/> .
@prefix c: <https://example.org/data/component/cmp/> .
doc:cmp a dds:Document ; dds:usesDesignSystem design:DeliberationSystem ;
    dds:usesFrame frame:AlternativeComparison-v1 ; dds:hasComponent c:crit , c:ev , c:a1 {more} .
c:crit a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasOrder 1 ;
    dds:hasSemantic semantic:Criterion ; dds:hasContent "비용"@ko .
c:ev a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasOrder 2 ;
    dds:hasSemantic semantic:Evidence ; dds:hasContent "견적"@ko .
c:a1 a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasOrder 3 ;
    dds:hasSemantic semantic:Alternative ; dds:hasContent "A안"@ko .
"""
    one = tmp_path / "one.ttl"
    one.write_text(head.replace("{more}", ""), encoding="utf-8")
    r = validate_graph(load_data([one]))
    assert r.shapes() == {"ddsh:FrameContractShape"}
    assert "2" in r.violations[0].message and "1" in r.violations[0].message
    two = tmp_path / "two.ttl"
    two.write_text(head.replace("{more}", ", c:a2") + """c:a2 a dds:Component ; dds:hasStructure structure:Paragraph ;
    dds:hasOrder 4 ; dds:hasSemantic semantic:Alternative ; dds:hasContent "B안"@ko .
""", encoding="utf-8")
    assert validate_graph(load_data([two])).conforms


def test_documents_without_frame_ignore_frame_rules():
    """A v0.2.0 document (no usesFrame) is not affected by frame / traceability rules."""
    from _util import PROPOSAL
    r = validate_graph(load_data([PROPOSAL]))
    assert r.conforms, r.violations


def test_premise_order_within_one_section(tmp_path):
    """basedOn a later sibling fails; an earlier sibling or an ancestor premise passes."""
    head = """@prefix dds: <https://example.org/ontology/dds#> .
@prefix structure: <https://example.org/data/structure/> .
@prefix semantic: <https://example.org/data/semantic/> .
@prefix design: <https://example.org/data/design/> .
@prefix doc: <https://example.org/data/doc/> .
@prefix c: <https://example.org/data/component/ord/> .
doc:ord a dds:Document ; dds:usesDesignSystem design:DeliberationSystem ; dds:hasComponent c:s .
c:s a dds:Component ; dds:hasStructure structure:Section ; dds:hasOrder 1 ; dds:hasChild c:h , c:a , c:b .
c:h a dds:Component ; dds:hasStructure structure:Heading ; dds:hasOrder 1 ; dds:hasContent "s"@ko .
c:a a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasOrder 2 ;
    dds:hasSemantic semantic:Assumption ; dds:hasContent "a"@ko .
c:b a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasOrder 3 ;
    dds:hasSemantic semantic:Decision ; dds:hasContent "b"@ko .
"""
    cases = {"c:b dds:basedOn c:a .": True, "c:a dds:basedOn c:b .": False, "c:b dds:basedOn c:s .": True}
    for i, (extra, ok) in enumerate(cases.items()):
        f = tmp_path / f"o{i}.ttl"
        f.write_text(head + extra + "\n", encoding="utf-8")
        r = validate_graph(load_data([f]))
        assert r.conforms is ok, (extra, r.violations)
        if not ok:
            assert r.shapes() == {"ddsh:PremiseOrderShape"}


def test_every_v03_shape_has_an_invalid_fixture():
    """AGENTS.md: each shape added in v0.3.0 is triggered by at least one single-violation fixture."""
    from rdflib import Graph
    from rdflib.namespace import RDF
    from dds_lib.graph import DDSH, SH, SHAPES_DIR
    g = Graph()
    for f in ("frame.shacl.ttl", "deliberation.shacl.ttl", "evaluation.shacl.ttl"):
        g.parse(SHAPES_DIR / f)
    # shapes that raise violations themselves: property shapes (sh:path) and SPARQL constraints;
    # NodeShapes that only group sh:property are excluded
    shapes = set(g.subjects(SH.path, None)) | set(g.subjects(SH.sparql, None))
    names = {"ddsh:" + str(s)[len(str(DDSH)):] for s in shapes if str(s).startswith(str(DDSH))}
    covered = set().union(*(req for req, _ in EXPECT.values()))
    assert names - covered == set()
