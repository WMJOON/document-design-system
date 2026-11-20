"""Source (authoring) TTL form, v0.4: materialise == compose."""
import pytest
from _util import run

from rdflib import Graph
from rdflib.compare import isomorphic

from dds_lib.compose import compose
from dds_lib.graph import format_report, merge, validate_graph
from dds_lib.markdown import render
from dds_lib.materialize import SourceError, is_source, materialize

DATA = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix k: <https://example.org/kw#> .
@prefix dds: <https://example.org/ontology/dds#> .
@prefix design: <https://example.org/data/design/> .
k:PaymentMethod a skos:Concept ; skos:prefLabel "결제 수단"@ko ; skos:notation "payment_method" .
k:Card a skos:Concept ; skos:prefLabel "카드"@ko ; skos:notation "card" ; skos:definition "카드로 결제합니다."@ko .
k:Deposit a skos:Concept ; skos:prefLabel "예치금"@ko ; skos:notation "deposit" ; skos:definition "예치금으로 결제합니다."@ko .
design:ShortView a dds:TableView ; dds:forTableKind design:ConceptTable ; dds:viewColumns "label code definition" .
"""

SOURCE = """
@prefix dds: <https://example.org/ontology/dds#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix k: <https://example.org/kw#> .
@prefix design: <https://example.org/data/design/> .
@prefix structure: <https://example.org/data/structure/> .
@prefix semantic: <https://example.org/data/semantic/> .
@prefix doc: <https://example.org/data/doc/> .
@prefix c: <https://example.org/data/component/s/> .

doc:s a dds:Document ; skos:prefLabel "원본 문서"@ko ; dds:usesDesignSystem design:PlanningSystem ;
    dds:children ( c:summary c:pm c:intro ) .
c:summary a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasSemantic semantic:Description ;
    dds:hasContent "> 요약입니다."@ko .
c:pm a dds:Component ; dds:hasStructure structure:Section ;
    dds:sectionKind design:ConceptSection ; dds:about k:PaymentMethod ;
    dds:children ( c:pm-table c:pm-notes ) .
c:pm-table a dds:Component ; dds:hasStructure structure:Table ; dds:tableKind design:ConceptTable ;
    dds:tableView design:ShortView ;
    dds:rows ( k:Card [ dds:about k:Deposit ; dds:cells [ design:col-definition "직접 쓴 정의"@ko ] ] ) .
c:pm-notes a dds:Component ; dds:hasStructure structure:List ; dds:items ( "주석 하나"@ko ) .
c:intro a dds:Component ; dds:hasStructure structure:Section ; dds:children ( c:intro-h c:intro-p c:intro-l ) .
c:intro-h a dds:Component ; dds:hasStructure structure:Heading ; dds:hasContent "소개"@ko .
c:intro-p a dds:Component ; dds:hasStructure structure:Paragraph ; dds:hasContent "본문"@ko .
c:intro-l a dds:Component ; dds:hasStructure structure:List ; dds:ordered true ; dds:items ( "첫째"@ko "둘째"@ko ) .
"""

SPEC = {"lang": "ko", "document": {"id": "s", "title": "원본 문서", "design_system": "PlanningSystem", "components": [
    {"id": "summary", "structure": "Paragraph", "semantic": "Description", "content": "> 요약입니다."},
    {"id": "pm", "structure": "Section", "kind": "ConceptSection", "about": "https://example.org/kw#PaymentMethod",
     "table": {"id": "pm-table", "view": "ShortView",
               "rows": ["card", {"about": "deposit", "cells": {"definition": "직접 쓴 정의"}}]},
     "notes": {"id": "pm-notes", "items": ["주석 하나"]}},
    {"id": "intro", "structure": "Section", "children": [
        {"id": "intro-h", "structure": "Heading", "content": "소개"},
        {"id": "intro-p", "structure": "Paragraph", "content": "본문"},
        {"id": "intro-l", "structure": "List", "ordered": True, "items": ["첫째", "둘째"]}]}]}}


def _graphs():
    data = Graph().parse(data=DATA, format="turtle")
    src = Graph().parse(data=SOURCE, format="turtle")
    return data, src, merge(src, data)


def test_materialize_equals_compose():
    data, src, vocab = _graphs()
    assert is_source(src)
    g1, doc = materialize(src, vocab)
    g0, doc0, _ = compose(SPEC, vocab=merge(data))
    assert doc == doc0
    assert isomorphic(g0, g1)
    rep = validate_graph(merge(g1, data))
    assert rep.conforms, format_report(rep)
    md = render(merge(g1, data), doc, annotate=False)
    assert "## 결제 수단\n" in md
    assert "| 카드 | card | 카드로 결제합니다. |" in md
    assert "| 예치금 | deposit | 직접 쓴 정의 |" in md
    assert "- 주석 하나" in md and "1. 첫째" in md


def test_build_validate_render_cli(tmp_path):
    (tmp_path / "data.ttl").write_text(DATA, encoding="utf-8")
    (tmp_path / "doc.ttl").write_text(SOURCE, encoding="utf-8")
    out = tmp_path / "doc.md"
    r = run("build.py", tmp_path / "doc.ttl", "--extra", tmp_path / "data.ttl", "-o", out, "--emit", tmp_path / "full.ttl")
    assert r.returncode == 0, r.stderr
    assert "| 카드 | card |" in out.read_text(encoding="utf-8")
    assert (tmp_path / "full.ttl").exists()
    r = run("validate.py", tmp_path / "doc.ttl", tmp_path / "data.ttl")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("render.py", tmp_path / "doc.ttl", tmp_path / "data.ttl", "--no-annotate")
    assert r.returncode == 0, r.stderr
    assert "## 결제 수단" in r.stdout


def test_source_errors():
    data = Graph().parse(data=DATA, format="turtle")
    bad_row = SOURCE.replace("dds:rows ( k:Card", "dds:rows ( k:Nope")
    src = Graph().parse(data=bad_row, format="turtle")
    with pytest.raises(Exception, match="no IRI/curie/skos:notation match|k:Nope|kw#Nope"):
        materialize(src, merge(src, data))
    mixed = SOURCE + "\nc:intro dds:hasChild c:intro-p .\n"
    src = Graph().parse(data=mixed, format="turtle")
    with pytest.raises(SourceError, match="either dds:children or dds:hasChild"):
        materialize(src, merge(src, data))
    wrong_slot = SOURCE.replace("dds:children ( c:pm-table c:pm-notes )", "dds:children ( c:pm-notes c:pm-table )")
    src = Graph().parse(data=wrong_slot, format="turtle")
    with pytest.raises(SourceError, match="does not fit the slots"):
        materialize(src, merge(src, data))


def test_untyped_table_rows_lists():
    src_ttl = SOURCE.replace("dds:children ( c:intro-h c:intro-p c:intro-l )", "dds:children ( c:intro-h c:intro-p c:intro-l c:intro-t )") + """
c:intro-t a dds:Component ; dds:hasStructure structure:Table ; dds:rows ( ( "항목" "값" ) ( "a" "1" ) ) .
"""
    data = Graph().parse(data=DATA, format="turtle")
    src = Graph().parse(data=src_ttl, format="turtle")
    g, doc = materialize(src, merge(src, data))
    md = render(merge(g, data), doc, annotate=False)
    assert "| 항목 | 값 |" in md and "| a | 1 |" in md
    assert validate_graph(merge(g, data)).conforms
