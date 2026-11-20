"""Source TTL (authoring form, v0.4) -> full DDS graph.

The source form keeps only what a person decides: structure, order, the resources a section or
table row is about, and hand-written text. Everything derivable (hasOrder, header rows, cells
filled from the glossary, kinded-section headings) is built here, in memory.

Source vocabulary (ontology/source.ttl)
- dds:children ( c1 c2 ... )   order of children on a Document, Section or List (rdf:List)
- dds:items ( "a"@ko "b"@ko )   List items as literals
- dds:rows ( kw:A [ dds:about kw:B ; dds:cells [ design:col-definition "..."@ko ] ] )   typed table
- dds:rows ( ( "h1" "h2" ) ( "a" "b" ) )   untyped table (first row = header)
- the expanded form (dds:hasChild + dds:hasOrder) is still accepted for any node

Implementation: the source graph is read into the same spec structure compose() uses, so there is
ONE code path that builds components (dds_lib.compose.Composer).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, SKOS

from .compose import ComposeError, compose
from .graph import DDS

SOURCE_PREDICATES = (DDS.children, DDS.rows, DDS.items)


class SourceError(ComposeError):
    pass


def is_source(g: Graph) -> bool:
    """True if the graph uses the authoring form somewhere."""
    return any((None, p, None) in g for p in SOURCE_PREDICATES)


def _list(g: Graph, head, where: str) -> List[Any]:
    try:
        return list(Collection(g, head))
    except Exception as e:  # broken rdf:List
        raise SourceError(f"{where}: broken rdf:List ({e})") from e


def _local(iri, ns_prefix: str) -> str:
    s = str(iri)
    return s[len(ns_prefix):] if s.startswith(ns_prefix) else s


def _text(lit) -> str:
    # Content is re-tagged with the document language by compose (one language per document).
    return str(lit)


class _Reader:
    def __init__(self, g: Graph, vocab: Graph, doc: URIRef):
        self.g, self.vocab, self.doc = g, vocab, doc
        s = str(doc)
        if "/doc/" not in s:
            raise SourceError(f"document IRI {doc} does not follow <base>doc/<id>")
        self.base = s[: s.rfind("/doc/") + 1]
        self.doc_id = s[s.rfind("/doc/") + 5:]
        self.comp_prefix = f"{self.base}component/{self.doc_id}/"

    def cid(self, node) -> str:
        if not isinstance(node, URIRef) or not str(node).startswith(self.comp_prefix):
            raise SourceError(f"component {node} must be an IRI under {self.comp_prefix}")
        return str(node)[len(self.comp_prefix):]

    def children(self, node) -> List[URIRef]:
        g = self.g
        head = g.value(node, DDS.children)
        hc = list(g.objects(node, DDS.hasChild)) + list(g.objects(node, DDS.hasComponent))
        if head is not None and hc:
            raise SourceError(f"{node}: use either dds:children or dds:hasChild/hasComponent, not both")
        if head is not None:
            return _list(g, head, f"{node} dds:children")
        return sorted(hc, key=lambda c: int(g.value(c, DDS.hasOrder) or 0))

    def column_key(self, col) -> str:
        k = self.vocab.value(col, DDS.columnKey)
        if k is None:
            raise SourceError(f"cell column {col} is not a dds:Column with a columnKey (load it with --extra)")
        return str(k)

    def rows(self, node) -> List[Any]:
        g = self.g
        out = []
        for item in _list(g, g.value(node, DDS.rows), f"{node} dds:rows"):
            if isinstance(item, URIRef):
                out.append({"about": str(item)})
            elif isinstance(item, BNode):
                r: Dict[str, Any] = {}
                about = g.value(item, DDS.about)
                if about is not None:
                    r["about"] = str(about)
                cells = g.value(item, DDS.cells)
                if cells is not None:
                    r["cells"] = {self.column_key(p): _text(o) for p, o in g.predicate_objects(cells)
                                  if p != RDF.type}
                out.append(r)
            else:
                raise SourceError(f"{node} dds:rows: item {item!r} must be an IRI or a [ dds:about … ] node")
        return out

    def expanded_table_rows(self, node) -> List[Any]:
        rows = []
        for r in self.children(node):
            cells = [_text(self.g.value(c, DDS.hasContent) or Literal("")) for c in self.children(r)]
            rows.append({"id": self.cid(r), "cells": cells})
        return rows

    def component(self, node) -> Dict[str, Any]:
        g = self.g
        st = g.value(node, DDS.hasStructure)
        if st is None:
            raise SourceError(f"component {node} has no dds:hasStructure")
        spec: Dict[str, Any] = {"id": self.cid(node), "structure": str(st)}
        kind_local = str(st).rsplit("/", 1)[-1]
        sems = [str(s) for s in g.objects(node, DDS.hasSemantic)]
        if sems:
            spec["semantic"] = sems
        p = g.value(node, DDS.hasPresentation)
        if p is not None:
            spec["presentation"] = str(p)
        c = g.value(node, DDS.hasContent)
        if c is not None:
            spec["content"] = _text(c)
        o = g.value(node, DDS.ordered)
        if o is not None:
            spec["ordered"] = bool(o.toPython())
        sk = g.value(node, DDS.sectionKind)
        tk = g.value(node, DDS.tableKind)
        if g.value(node, DDS.about) is not None and (sk is not None):
            spec["about"] = str(g.value(node, DDS.about))
        if sk is not None:
            spec["kind"] = str(sk)
            self.fill_slots(node, sk, spec)
            return spec
        if tk is not None:
            spec["kind"] = str(tk)
            v = g.value(node, DDS.tableView)
            if v is not None:
                spec["view"] = str(v)
            if g.value(node, DDS.rows) is None:
                raise SourceError(f"typed table {node} needs dds:rows ( … ) in the source form")
            spec["rows"] = self.rows(node)
            return spec
        if kind_local == "List" and g.value(node, DDS.items) is not None:
            spec["items"] = [_text(x) for x in _list(g, g.value(node, DDS.items), f"{node} dds:items")]
            return spec
        if kind_local == "Table":
            if g.value(node, DDS.rows) is not None:  # untyped table: dds:rows ( ( "a" "b" ) ( "1" "2" ) )
                rows = []
                for item in _list(g, g.value(node, DDS.rows), f"{node} dds:rows"):
                    if g.value(item, RDF.first) is None and item != RDF.nil:
                        raise SourceError(f"untyped table {node}: each row must be a list of literals")
                    rows.append([_text(x) for x in _list(g, item, f"{node} row")])
                spec["rows"] = rows
            else:
                spec["rows"] = self.expanded_table_rows(node)
            return spec
        if kind_local == "List":
            spec["items"] = [dict(self.component(i), structure="ListItem") for i in self.children(node)]
            for it in spec["items"]:
                it.pop("structure", None)
            return spec
        kids = self.children(node)
        if kids:
            spec["children"] = [self.component(k) for k in kids]
        return spec

    def fill_slots(self, node, sk, spec):
        """Assign a kinded section's source children to slots by structure, in slot order."""
        v = self.vocab
        slots = sorted(v.objects(sk, DDS.hasSlot), key=lambda s: int(v.value(s, DDS.slotOrder) or 0))
        if not slots:
            raise SourceError(f"section kind {sk} unknown or has no slots (load it with --extra)")
        kids = list(self.children(node))
        i = 0
        for s in slots:
            key = str(v.value(s, DDS.slotKey))
            want = v.value(s, DDS.slotStructure)
            multiple = bool(v.value(s, DDS.slotMultiple) is not None and v.value(s, DDS.slotMultiple).toPython())
            if str(want).endswith("/Heading"):
                if i < len(kids) and self.g.value(kids[i], DDS.hasStructure) == want:  # explicit title
                    spec["title"] = _text(self.g.value(kids[i], DDS.hasContent))
                    i += 1
                continue
            got = []
            while i < len(kids) and self.g.value(kids[i], DDS.hasStructure) == want:
                comp = self.component(kids[i])
                comp.pop("structure", None)
                got.append(comp)
                i += 1
                if not multiple:
                    break
            if got:
                spec[key] = got if multiple else got[0]
        if i != len(kids):
            raise SourceError(f"section {node}: child {kids[i]} does not fit the slots of {sk} "
                              "(wrong structure or order)")


def materialize(source: Graph, vocab: Optional[Graph] = None) -> Tuple[Graph, URIRef]:
    """Return (full DDS graph for the one Document in `source`, document IRI)."""
    vocab = vocab if vocab is not None else source
    docs = list(source.subjects(RDF.type, DDS.Document))
    if len(docs) != 1:
        raise SourceError(f"source must contain exactly one dds:Document, found {len(docs)}")
    doc = docs[0]
    r = _Reader(source, vocab, doc)
    title = source.value(doc, SKOS.prefLabel)
    ds = source.value(doc, DDS.usesDesignSystem)
    if ds is None:
        raise SourceError(f"{doc}: dds:usesDesignSystem is required")
    lang = title.language if isinstance(title, Literal) and title.language else "ko"
    spec = {"lang": lang, "document": {
        "id": r.doc_id, "title": str(title) if title is not None else r.doc_id, "design_system": str(ds),
        "components": [r.component(c) for c in r.children(doc)]}}
    g, d, _ = compose(spec, base=r.base, lang=lang, vocab=vocab)
    return g, d


def expand_in_place(g: Graph) -> Graph:
    """If `g` (data + vocab, as loaded by validate/render) holds a source-form document,
    add its materialised triples to `g`. Returns g."""
    if is_source(g):
        full, _ = materialize(g, g)
        for p in SOURCE_PREDICATES:  # authoring-only lists are replaced by the expanded form
            g.remove((None, p, None))
        for t in full:
            g.add(t)
    return g
