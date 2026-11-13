import yaml
from _util import EXAMPLE, FIXTURES, TEMPLATE, run

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import XSD

from dds_lib.compose import compose
from dds_lib.graph import DDS, load_data, merge, validate_graph
from dds_lib.markdown import parse, render
from dds_lib.model import component_kind, documents


def _spec():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def test_ttl_markdown_ttl_is_isomorphic():
    g0, doc, _ = compose(_spec())
    md = render(merge(g0), doc)
    g1, doc1 = parse(md)
    assert doc1 == doc
    assert isomorphic(g0, g1)
    assert validate_graph(merge(g1)).conforms


def test_roundtrip_preserves_language_and_ordered():
    g0, doc, _ = compose(_spec())
    g1, _ = parse(render(merge(g0), doc))
    langs = {o.language for o in g1.objects(None, DDS.hasContent)}
    assert langs == {"ko"}
    assert Literal(True) in set(g1.objects(None, DDS.ordered))


def test_roundtrip_normalises_order_gaps():
    g = Graph().parse(EXAMPLE)
    a = URIRef("https://example.org/data/component/proposal/overview")
    b = URIRef("https://example.org/data/component/proposal/scope")
    g.set((a, DDS.hasOrder, Literal(10, datatype=XSD.integer)))
    g.set((b, DDS.hasOrder, Literal(30, datatype=XSD.integer)))
    doc = documents(g)[0]
    g1, _ = parse(render(merge(g), doc))
    assert int(g1.value(a, DDS.hasOrder)) == 1 and int(g1.value(b, DDS.hasOrder)) == 2


def test_example_document_roundtrip():
    g0 = Graph().parse(EXAMPLE)
    doc = documents(g0)[0]
    g1, _ = parse(render(merge(g0), doc))
    assert isomorphic(g0, g1)


def test_plain_markdown_parses_structurally(tmp_path):
    md = "# 메모\n\n## 결론\n\n착수한다.\n\n1. 예산\n2. 인력\n\n### 근거\n\n| 지표 | 값 |\n|---|---|\n| 문의량 | 1\\|2 |\n"
    g, doc = parse(md, doc_id="memo")
    full = merge(g)
    assert validate_graph(full).conforms
    kinds = sorted(component_kind(full, c) for c in g.subjects(DDS.hasStructure, None))
    assert kinds.count("Section") == 2 and kinds.count("TableCell") == 4 and "List" in kinds
    assert Literal("1|2", lang="ko") in set(g.objects(None, DDS.hasContent))
    # nested: '### 근거' section is a child of '## 결론' section
    s1 = URIRef("https://example.org/data/component/memo/s1")
    assert any(component_kind(full, c) == "Section" for c in g.objects(s1, DDS.hasChild))


def test_compose_iris_stable_across_runs_and_content_edits():
    g1, _, _ = compose(_spec())
    spec = _spec()
    spec["document"]["components"][0]["children"][2]["content"] = "환불 가능 여부와 금액을 판단해야 한다."
    g2, _, _ = compose(spec)
    comps = lambda g: set(g.subjects(DDS.hasStructure, None))  # noqa: E731
    assert comps(g1) == comps(g2)
    req = URIRef("https://example.org/data/component/ai-support-proposal/REQ001")
    assert "금액" in str(g2.value(req, DDS.hasContent))


def test_write_ids_persists_generated_ids(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text(
        "document:\n  id: d\n  title: T\n  design_system: PlanningSystem\n  components:\n"
        "    - structure: Paragraph\n      content: hello\n", encoding="utf-8")
    out1, out2 = tmp_path / "a.ttl", tmp_path / "b.ttl"
    r = run("compose.py", spec, "-o", out1)
    assert r.returncode == 0 and "warning: generated" in r.stderr
    assert "c-" not in spec.read_text()  # default: user file untouched
    assert run("compose.py", spec, "-o", out1, "--write-ids").returncode == 0
    assert "id: c-" in spec.read_text()
    assert run("compose.py", spec, "-o", out2).returncode == 0
    s = lambda p: set(Graph().parse(p).subjects(DDS.hasStructure, None))  # noqa: E731
    assert s(out1) == s(out2)


def test_cli_pipeline(tmp_path):
    ttl, md, back, js = (tmp_path / n for n in ("d.ttl", "d.md", "back.ttl", "d.jsonld"))
    assert run("compose.py", TEMPLATE, "-o", ttl).returncode == 0
    assert run("render.py", ttl, "-o", md).returncode == 0
    assert run("parse.py", md, "-o", back).returncode == 0
    assert isomorphic(Graph().parse(ttl), Graph().parse(back))
    assert run("export.py", ttl, "-f", "json-ld", "-o", js).returncode == 0
    assert len(Graph().parse(js, format="json-ld")) == len(Graph().parse(ttl))


def test_compose_rejects_duplicate_ids(tmp_path):
    spec = tmp_path / "dup.yaml"
    spec.write_text(
        "document:\n  id: d\n  design_system: PlanningSystem\n  components:\n"
        "    - {id: x, structure: Paragraph, content: a}\n    - {id: x, structure: Paragraph, content: b}\n")
    r = run("compose.py", spec)
    assert r.returncode == 2 and "duplicate component id" in r.stderr


def _rendered_template():
    g0, doc, _ = compose(_spec())
    return g0, render(merge(g0), doc)


def test_hand_edited_markdown_keeps_new_content_and_old_iris():
    g0, md = _rendered_template()
    md = md.replace("2. 1차 범위는 환불 문의로 한정한다.",
                    "2. 1차 범위는 환불 문의로 한정한다.\n3. 손으로 추가한 항목")
    md = md.replace("| 모델 호스팅 | 사내 호스팅 | 데이터 반출 금지 정책 |",
                    "| 모델 호스팅 | 사내 호스팅 | 데이터 반출 금지 정책 |\n| 추가 행 | 보류 | 검토 중 |")
    md = md.replace("## 범위와 제약", "## 범위와 제약 (수정)")
    g1, _ = parse(md)
    contents = {str(o) for o in g1.objects(None, DDS.hasContent)}
    assert {"손으로 추가한 항목", "추가 행", "보류", "검토 중", "범위와 제약 (수정)"} <= contents
    old = set(g0.subjects(DDS.hasStructure, None))
    new = set(g1.subjects(DDS.hasStructure, None))
    assert old <= new and len(new - old) == 1 + 1 + 3  # 1 item, 1 row + 3 cells
    title = URIRef("https://example.org/data/component/ai-support-proposal/scope-title")
    assert str(g1.value(title, DDS.hasContent)) == "범위와 제약 (수정)"
    assert validate_graph(merge(g1)).conforms


def test_annotation_mismatch_is_an_error_not_a_crash(tmp_path):
    from dds_lib.markdown import ParseError
    import pytest

    _, md = _rendered_template()
    broken = md.replace("## 프로젝트 개요", "프로젝트 개요 (heading marker removed)")
    with pytest.raises(ParseError):
        parse(broken)
    f = tmp_path / "broken.md"
    f.write_text(broken, encoding="utf-8")
    r = run("parse.py", f)
    assert r.returncode == 2 and "parse error" in r.stderr


def test_plain_heading_glued_to_paragraph():
    g, _ = parse("# 메모\n## 결론\n다음 분기에 착수한다.\n### 근거\n문의량 증가\n", doc_id="glued")
    full = merge(g)
    assert validate_graph(full).conforms
    contents = {str(o) for o in g.objects(None, DDS.hasContent)}
    assert {"결론", "다음 분기에 착수한다.", "근거", "문의량 증가"} <= contents
    assert sum(1 for c in g.subjects(DDS.hasStructure, None) if component_kind(full, c) == "Section") == 2
