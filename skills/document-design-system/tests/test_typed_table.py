"""Typed tables (v0.2): TableKind / Column / ColumnLabel."""
import pytest
from _util import run

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import SKOS

from dds_lib.compose import ComposeError, compose
from dds_lib.graph import DDS, format_report, merge, validate_graph
from dds_lib.markdown import parse, render

DATA = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix k: <https://example.org/kw#> .
@prefix dds: <https://example.org/ontology/dds#> .
@prefix design: <https://example.org/data/design/> .
k:Card a skos:Concept ; skos:prefLabel "카드"@ko ; skos:notation "card" ;
    skos:definition "카드로 결제합니다."@ko ; skos:example "삼성카드"@ko .
k:Deposit a skos:Concept ; skos:prefLabel "예치금"@ko ; skos:notation "deposit" ;
    skos:definition "예치금으로 결제합니다."@ko .
design:PlanningSystem dds:hasColumnLabel [ a dds:ColumnLabel ; dds:forColumn design:col-label ; skos:prefLabel "이름"@ko ] .
design:InputView a dds:TableView ; dds:forTableKind design:ConceptTable ; dds:viewColumns "label definition example" .
design:BadView a dds:TableView ; dds:forTableKind design:ConceptTable ; dds:viewColumns "definition label" .
"""


def _vocab():
    return merge(Graph().parse(data=DATA, format="turtle"))


def _spec(**table):
    t = {"id": "t", "structure": "Table", "kind": "ConceptTable", "rows": ["card", "k:Deposit"]}
    t.update(table)
    return {"lang": "ko", "document": {"id": "d", "title": "T", "design_system": "PlanningSystem",
                                       "components": [t]}}


def _cells(g, row_id):
    row = URIRef(f"https://example.org/data/component/d/{row_id}")
    cells = sorted(g.objects(row, DDS.hasChild), key=lambda c: int(g.value(c, DDS.hasOrder)))
    return [str(g.value(c, DDS.hasContent) or "") for c in cells]


def test_typed_table_fills_cells_and_validates():
    v = _vocab()
    g, doc, _ = compose(_spec(), vocab=v)
    assert _cells(g, "t-r0") == ["이름", "코드", "정의", "설명", "예시", "근거"]  # DesignSystem label overrides "개념"
    assert _cells(g, "t-r1") == ["카드", "card", "카드로 결제합니다.", "", "삼성카드", ""]
    assert _cells(g, "t-r2")[:2] == ["예치금", "deposit"]
    rep = validate_graph(merge(g, Graph().parse(data=DATA, format="turtle")))
    assert rep.conforms, format_report(rep)


def test_unknown_subject_and_kind_errors():
    v = _vocab()
    with pytest.raises(ComposeError, match="no IRI/curie/skos:notation match"):
        compose(_spec(rows=["nope"]), vocab=v)
    with pytest.raises(ComposeError, match="unknown or has no columns"):
        compose(_spec(kind="NoSuchKind"), vocab=v)
    with pytest.raises(ComposeError, match="not allowed on a component"):
        compose(_spec(headers={"label": "x"}), vocab=v)
    with pytest.raises(ComposeError, match="not allowed on a component"):
        compose(_spec(columns=["label"]), vocab=v)


def test_shacl_rejects_wrong_cell_count():
    v = _vocab()
    g, doc, _ = compose(_spec(), vocab=v)
    row = URIRef("https://example.org/data/component/d/t-r1")
    last = max(g.objects(row, DDS.hasChild), key=lambda c: int(g.value(c, DDS.hasOrder)))
    g.remove((row, DDS.hasChild, last))
    g.remove((last, None, None))
    rep = validate_graph(merge(g, Graph().parse(data=DATA, format="turtle")))
    assert not rep.conforms
    assert "TypedTableCellCountShape" in format_report(rep)


def test_cli_compose_with_extra(tmp_path):
    import yaml
    d = tmp_path / "data.ttl"
    d.write_text(DATA, encoding="utf-8")
    s = tmp_path / "s.yaml"
    s.write_text(yaml.safe_dump(_spec(), allow_unicode=True), encoding="utf-8")
    out = tmp_path / "o.ttl"
    r = run("compose.py", s, "-o", out, "--extra", d)
    assert r.returncode == 0, r.stderr
    r = run("render.py", out, d, "--no-annotate")
    assert r.returncode == 0, r.stderr
    assert "| 카드 | card |" in r.stdout


def test_row_class_and_required_typed_tables():
    data = DATA + """
k:NotConcept a k:Other ; skos:notation "nc" ; skos:prefLabel "x"@ko .
design:StrictSystem a dds:DesignSystem ; dds:requiresTypedTables true ;
    dds:supportsStructure <https://example.org/data/structure/Section> , <https://example.org/data/structure/Table> ,
        <https://example.org/data/structure/TableRow> , <https://example.org/data/structure/TableCell> .
"""
    extra = Graph().parse(data=data, format="turtle")
    v = merge(extra)
    g, doc, _ = compose(_spec(rows=["nc"]), vocab=v)
    rep = validate_graph(merge(g, extra))
    assert "TypedTableRowClassShape" in format_report(rep)
    spec = {"lang": "ko", "document": {"id": "d2", "title": "T", "design_system": "StrictSystem",
            "components": [{"id": "free", "structure": "Table", "rows": [["a", "b"], ["1", "2"]]}]}}
    g2, _, _ = compose(spec, vocab=v)
    rep2 = validate_graph(merge(g2, extra))
    assert "RequireTypedTablesShape" in format_report(rep2)


# ---------------------------------------------------------------- kinded sections (v0.3)
DATA_SEC = DATA + """
@prefix dcterms: <http://purl.org/dc/terms/> .
k:PaymentMethod a skos:Concept ; skos:prefLabel "결제 수단"@ko ; skos:notation "payment_method" ;
    dcterms:description "고객이 돈을 낸 수단입니다."@ko .
"""


def _sec_spec(**sec):
    s = {"id": "pm", "structure": "Section", "kind": "ConceptSection", "about": "payment_method",
         "table": {"rows": ["card", "deposit"], "view": "InputView"},
         "notes": ["값 이름은 notation을 씁니다."]}
    s.update(sec)
    return {"lang": "ko", "document": {"id": "d", "title": "T", "design_system": "PlanningSystem", "components": [s]}}


def test_concept_section_composition():
    extra = Graph().parse(data=DATA_SEC, format="turtle")
    v = merge(extra)
    g, doc, _ = compose(_sec_spec(), vocab=v)
    md = render(merge(g), doc, annotate=False)
    assert "## 결제 수단\n" in md
    assert "고객이 돈을 낸 수단입니다." not in md      # description only when given
    assert "| 이름 | 정의 | 예시 |" in md          # InputView + 디자인 시스템 머리 문구("이름")
    assert "- 값 이름은 notation을 씁니다." in md
    rep = validate_graph(merge(g, extra))
    assert rep.conforms, format_report(rep)
    g1, _ = parse(render(merge(g), doc))
    assert isomorphic(g, g1)


def test_concept_section_errors_and_shapes():
    extra = Graph().parse(data=DATA_SEC, format="turtle")
    v = merge(extra)
    with pytest.raises(ComposeError, match="unknown key"):
        compose(_sec_spec(children=[]), vocab=v)
    with pytest.raises(ComposeError, match="required slot 'table'"):
        compose(_sec_spec(table=None), vocab=v)
    g, doc, _ = compose(_sec_spec(), vocab=v)
    # swap order of table and notes -> order violation
    t = URIRef("https://example.org/data/component/d/pm-table")
    nl = URIRef("https://example.org/data/component/d/pm-notes")
    ot, on = g.value(t, DDS.hasOrder), g.value(nl, DDS.hasOrder)
    g.set((t, DDS.hasOrder, on))
    g.set((nl, DDS.hasOrder, ot))
    assert "SectionSlotOrderShape" in format_report(validate_graph(merge(g, extra)))


def test_explicit_cells():
    v = _vocab()
    g, doc, _ = compose(_spec(rows=[{"about": "card", "cells": {"example": "현대카드"}},
                                    {"about": "deposit", "cells": {"definition": "-"}}]), vocab=v)
    assert _cells(g, "t-r1")[4] == "현대카드"
    assert _cells(g, "t-r2")[:3] == ["예치금", "deposit", "-"]


def test_named_view_selects_columns_in_kind_order():
    v = _vocab()
    g, doc, _ = compose(_spec(view="InputView"), vocab=v)
    assert _cells(g, "t-r0") == ["이름", "정의", "예시"]
    assert _cells(g, "t-r1") == ["카드", "카드로 결제합니다.", "삼성카드"]
    assert validate_graph(merge(g, Graph().parse(data=DATA, format="turtle"))).conforms
    g1, _ = parse(render(merge(g), doc))
    assert isomorphic(g, g1)
    with pytest.raises(ComposeError, match="must follow the kind's order"):
        compose(_spec(view="BadView"), vocab=v)
    with pytest.raises(ComposeError, match="not defined for table kind"):
        compose(_spec(view="NoView"), vocab=v)


def test_design_system_default_view():
    extra = Graph().parse(data=DATA + """
design:PlanningSystem dds:hasDefaultView design:InputView .
""", format="turtle")
    g, doc, _ = compose(_spec(), vocab=merge(extra))
    assert _cells(g, "t-r0") == ["이름", "정의", "예시"]
