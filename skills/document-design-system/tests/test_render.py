from _util import EXAMPLE, FIXTURES, run

from rdflib import URIRef

from dds_lib.graph import load_data
from dds_lib.markdown import render
from dds_lib.model import effective_presentation

DOC = URIRef("https://example.org/data/doc/proposal")


def _md(annotate=False, style=None):
    return render(load_data([EXAMPLE]), DOC, annotate=annotate, style_path=style)


def test_order_and_heading_levels():
    md = _md()
    lines = [l for l in md.splitlines() if l.strip()]
    assert lines[0] == "# AI 상담 시스템 기획안"
    assert lines.index("## 프로젝트 개요") < lines.index("환불 가능 여부를 판단해야 한다.") < lines.index("## 범위")


def test_heading_level_comes_from_section_depth(tmp_path):
    out = tmp_path / "doc.ttl"
    assert run("compose.py", FIXTURES.parent.parent / "templates" / "planning-document.yaml", "-o", out).returncode == 0
    md = render(load_data([out]), URIRef("https://example.org/data/doc/ai-support-proposal"), annotate=False)
    assert "## 범위와 제약" in md and "### 가정과 근거" in md  # nested Section -> H3
    assert "1. 개인정보는 마스킹된 상태로만 처리한다." in md
    assert "| 항목 | 결정 | 근거 |\n|---|---|---|\n| 모델 호스팅 |" in md
    assert "> 환불 가능 여부를 판단해야 한다." in md  # explicit Callout presentation
    assert "**상담 이력 데이터는 6개월치가 확보되어 있다.**" in md


def test_default_presentation_from_design_system(tmp_path):
    g = load_data([EXAMPLE])
    c = URIRef("https://example.org/data/component/proposal/scope-title")  # Heading, no explicit presentation
    pres, explicit = effective_presentation(g, DOC, c)
    assert str(pres).endswith("/presentation/Heading1") and not explicit

    style = tmp_path / "style.yaml"
    style.write_text("tokens:\n  heading-1:\n    wrap: '~'\n")
    md = _md(style=style)
    assert "## ~범위~" in md


def test_default_presentation_not_written_to_annotation():
    md = _md(annotate=True)
    line = next(l for l in md.splitlines() if '"id":"scope-title"' in l)
    assert '"p"' not in line
    explicit = next(l for l in md.splitlines() if '"id":"REQ001"' in l)
    assert '"p":"Body"' in explicit


def test_render_refuses_invalid_document():
    r = run("render.py", FIXTURES / "invalid" / "cyclic-child.ttl")
    assert r.returncode == 1 and "NoCycleShape" in r.stderr
