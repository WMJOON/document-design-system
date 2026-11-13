"""YAML document spec -> DDS ABox graph (stable IRIs, normalised order)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS, XSD

from .graph import DDS, DataNS, bind_prefixes, resolve


class ComposeError(ValueError):
    pass


def _as_list(v) -> List[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class Composer:
    def __init__(self, ns: DataNS, lang: str, doc_id: str):
        self.ns, self.lang, self.doc_id = ns, lang, doc_id
        self.g = bind_prefixes(Graph(bind_namespaces="core"), ns)
        self.seen: Dict[str, str] = {}
        self.generated: List[str] = []

    # -- helpers ---------------------------------------------------------
    def _iri(self, comp_id: str, where: str) -> URIRef:
        if not isinstance(comp_id, str) or not comp_id or any(c in comp_id for c in ' <>"{}|\\^`#?'):
            raise ComposeError(f"invalid component id {comp_id!r} at {where}")
        if comp_id in self.seen:
            raise ComposeError(f"duplicate component id {comp_id!r} at {where} (first used at {self.seen[comp_id]})")
        self.seen[comp_id] = where
        return self.ns.component_iri(self.doc_id, comp_id)

    def _text(self, v) -> Literal:
        if isinstance(v, dict):  # {text: ..., lang: ...}
            return Literal(str(v["text"]), lang=v.get("lang", self.lang))
        return Literal(str(v), lang=self.lang)

    def _common(self, node: URIRef, spec: Dict[str, Any], order: int):
        g = self.g
        g.add((node, RDF.type, DDS.Component))
        g.add((node, DDS.hasOrder, Literal(order, datatype=XSD.integer)))
        for s in _as_list(spec.get("semantic")):
            g.add((node, DDS.hasSemantic, resolve(s, self.ns.semantic, self.ns)))
        if spec.get("presentation"):
            g.add((node, DDS.hasPresentation, resolve(spec["presentation"], self.ns.presentation, self.ns)))
        if "content" in spec and spec["content"] is not None:
            g.add((node, DDS.hasContent, self._text(spec["content"])))

    def _leaf(self, parent: URIRef, spec, comp_id: str, structure: str, order: int, where: str):
        if not isinstance(spec, dict):
            spec = {"content": spec}
        node = self._iri(spec.get("id") or comp_id, where)
        self.g.add((parent, DDS.hasChild, node))
        self.g.add((node, DDS.hasStructure, self.ns.structure[structure]))
        self._common(node, spec, order)
        return node

    # -- main ------------------------------------------------------------
    def component(self, spec: Dict[str, Any], order: int, where: str) -> URIRef:
        if not isinstance(spec, dict):
            raise ComposeError(f"component at {where} must be a mapping")
        if "structure" not in spec:
            raise ComposeError(f"component at {where} has no 'structure'")
        if not spec.get("id"):
            spec["id"] = f"c-{uuid.uuid4().hex[:8]}"
            self.generated.append(spec["id"])
        cid = spec["id"]
        node = self._iri(cid, where)
        g = self.g
        g.add((node, DDS.hasStructure, resolve(spec["structure"], self.ns.structure, self.ns)))
        self._common(node, spec, order)
        if "ordered" in spec:
            g.add((node, DDS.ordered, Literal(bool(spec["ordered"]))))

        n = 0
        for i, item in enumerate(_as_list(spec.get("items")), 1):  # List shorthand
            n += 1
            self._leaf(node, item, f"{cid}-i{i}", "ListItem", n, f"{where}.items[{i}]")
        for r, row in enumerate(_as_list(spec.get("rows")), 1):  # Table shorthand
            n += 1
            cells = row.get("cells", []) if isinstance(row, dict) else row
            rid = (row.get("id") if isinstance(row, dict) else None) or f"{cid}-r{r}"
            rnode = self._iri(rid, f"{where}.rows[{r}]")
            g.add((node, DDS.hasChild, rnode))
            g.add((rnode, DDS.hasStructure, self.ns.structure.TableRow))
            self._common(rnode, row if isinstance(row, dict) else {}, n)
            for c, cell in enumerate(_as_list(cells), 1):
                self._leaf(rnode, cell, f"{rid}-c{c}", "TableCell", c, f"{where}.rows[{r}].cells[{c}]")
        for i, child in enumerate(_as_list(spec.get("children")), 1):
            n += 1
            cnode = self.component(child, n, f"{where}.children[{i}]")
            g.add((node, DDS.hasChild, cnode))
        return node


def compose(spec: Dict[str, Any], base: Optional[str] = None, lang: Optional[str] = None
            ) -> Tuple[Graph, URIRef, List[str]]:
    """Return (graph, document IRI, list of generated component ids).

    The ``spec`` dict is mutated in place with generated ids, so the caller can
    persist them (``--write-ids``) and keep IRIs stable across re-composition.
    """
    if "document" not in spec:
        raise ComposeError("top-level 'document' key is required")
    d = spec["document"]
    ns = DataNS(base or spec.get("base") or "https://example.org/data/")
    lang = lang or spec.get("lang") or "ko"
    doc_id = d.get("id")
    if not doc_id:
        raise ComposeError("document.id is required (it anchors every component IRI)")
    c = Composer(ns, lang, doc_id)
    doc = ns.doc_iri(doc_id)
    g = c.g
    g.add((doc, RDF.type, DDS.Document))
    if d.get("title"):
        g.add((doc, SKOS.prefLabel, c._text(d["title"])))
    if not d.get("design_system"):
        raise ComposeError("document.design_system is required")
    g.add((doc, DDS.usesDesignSystem, resolve(d["design_system"], ns.design, ns)))
    for i, comp in enumerate(_as_list(d.get("components")), 1):
        g.add((doc, DDS.hasComponent, c.component(comp, i, f"components[{i}]")))
    return g, doc, c.generated
