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
