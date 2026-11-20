"""SHACL-SPARQL constraints run with pyoxigraph (fast path).

pyshacl evaluates sh:sparql constraints through rdflib's SPARQL engine, which is
slow on document-sized graphs. This module splits the shapes graph:

* Core shapes (everything except sh:sparql) -> still validated by pyshacl.
* SPARQL constraints -> executed here with pyoxigraph, then reported in the same
  Violation form.

Semantics kept from SHACL-SPARQL (sh:select):
* targets: sh:targetClass (with rdfs:subClassOf*, no inference), sh:targetNode,
  sh:targetSubjectsOf, sh:targetObjectsOf;
* $this is bound to each focus node by joining the target pattern (a sub-SELECT),
  so blank-node focus nodes and constraints whose $this appears only in FILTER work;
* prefixes come from sh:prefixes -> sh:declare;
* sh:deactivated true is skipped; severity defaults to sh:Violation;
* message templates {?var} / {$var} are filled from the result row.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

SH_NS = "http://www.w3.org/ns/shacl#"


def _sh(local: str) -> URIRef:
    return URIRef(SH_NS + local)


def split_shapes(shapes: Graph) -> Tuple[Graph, List[dict]]:
    """Return (core shapes graph without sh:sparql, list of SPARQL constraints)."""
    core = Graph()
    for p, ns in shapes.namespaces():
        core.bind(p, ns)
    sparql_nodes = set()
    constraints: List[dict] = []
    for shape, _, c in shapes.triples((None, _sh("sparql"), None)):
        sparql_nodes.add(c)
        if (c, _sh("deactivated"), Literal(True)) in shapes or (shape, _sh("deactivated"), Literal(True)) in shapes:
            continue
        prefixes: Dict[str, str] = {}
        for pnode in shapes.objects(c, _sh("prefixes")):
            for decl in shapes.objects(pnode, _sh("declare")):
                pre, ns = shapes.value(decl, _sh("prefix")), shapes.value(decl, _sh("namespace"))
                if pre is not None and ns is not None:
                    prefixes[str(pre)] = str(ns)
        constraints.append({
            "shape": shape,
            "select": str(shapes.value(c, _sh("select"))),
            "prefixes": prefixes,
            "messages": list(shapes.objects(c, _sh("message"))) or list(shapes.objects(shape, _sh("message"))),
            "severity": shapes.value(c, _sh("severity")) or shapes.value(shape, _sh("severity")) or _sh("Violation"),
            "targetClass": list(shapes.objects(shape, _sh("targetClass"))),
            "targetNode": list(shapes.objects(shape, _sh("targetNode"))),
            "targetSubjectsOf": list(shapes.objects(shape, _sh("targetSubjectsOf"))),
            "targetObjectsOf": list(shapes.objects(shape, _sh("targetObjectsOf"))),
        })
    # copy everything except sh:sparql links and the constraint nodes' own triples
    drop_subjects = set()
    stack = list(sparql_nodes)
    while stack:  # constraint node and blank nodes hanging off it
        n = stack.pop()
        if n in drop_subjects:
            continue
        drop_subjects.add(n)
        for o in shapes.objects(n, None):
            if isinstance(o, BNode):
                stack.append(o)
    for s, p, o in shapes:
        if p == _sh("sparql") or s in drop_subjects:
            continue
        core.add((s, p, o))
    return core, constraints


def _term(t) -> str:
    if isinstance(t, URIRef):
        return f"<{t}>"
    raise ValueError(f"unsupported target term: {t!r}")


def _focus_pattern(c: dict) -> str:
    """Graph pattern that binds ?this to every focus node (blank nodes included)."""
    parts = []
    for cls in c["targetClass"]:
        parts.append(f"{{ ?this a/<{RDFS.subClassOf}>* {_term(cls)} }}")
    for n in c["targetNode"]:
        parts.append(f"{{ BIND({_term(n)} AS ?this) }}")
    for p in c["targetSubjectsOf"]:
        parts.append(f"{{ ?this {_term(p)} ?__dds_o }}")
    for p in c["targetObjectsOf"]:
        parts.append(f"{{ ?__dds_s {_term(p)} ?this }}")
    return " UNION ".join(parts)


_VAR = re.compile(r"\{[?$](\w+)\}")


def _bind_this(select: str, focus_pattern: str) -> str:
    """$this -> ?this, and join the focus pattern right after the first WHERE {.
    A pattern (not VALUES) is used so blank-node focus nodes are bound as well."""
    q = re.sub(r"\$(\w+)", r"?\1", select)
    m = re.search(r"\bWHERE\s*\{", q, re.IGNORECASE)
    if not m:
        raise ValueError("sh:select without WHERE {")
    return q[: m.end()] + " { SELECT DISTINCT ?this WHERE { " + focus_pattern + " } } " + q[m.end():]


def run_sparql_constraints(data: Graph, constraints: List[dict]):
    """Yield (shape, focus, message_literals_filled, severity, value) per violation."""
    import pyoxigraph as ox

    store = ox.Store()
    # Blank nodes are skolemized to IRIs so their ids survive the round trip
    # (callers compare focus nodes with the rdflib graph's blank-node ids).
    skolem = Graph()
    for s, p, o in data:
        skolem.add((_sk(s), p, _sk(o)))
    store.load(skolem.serialize(format="nt"), format=ox.RdfFormat.N_TRIPLES)

    def node_text(t):
        if t is None:
            return ""
        if isinstance(t, ox.NamedNode):
            if t.value.startswith(_SKOLEM):
                return BNode(t.value[len(_SKOLEM):])
            return URIRef(t.value)
        if isinstance(t, ox.BlankNode):
            return BNode(t.value)
        return Literal(t.value)

    for c in constraints:
        fp = _focus_pattern(c)
        if not fp:
            continue
        prologue = "".join(f"PREFIX {p}: <{ns}>\n" for p, ns in c["prefixes"].items())
        q = prologue + _bind_this(c["select"], fp)
        sol = store.query(q)
        names = [v.value for v in sol.variables]
        for row in sol:
            vals = {n: row[n] for n in names}
            this = vals.get("this")
            msgs = []
            for m in c["messages"]:
                txt = _VAR.sub(lambda mm: _fmt(vals.get(mm.group(1))), str(m))
                msgs.append(Literal(txt, lang=getattr(m, "language", None)))
            yield c["shape"], node_text(this), msgs, c["severity"], node_text(vals.get("value"))


_SKOLEM = "urn:dds:bnode:"


def _sk(t):
    return URIRef(_SKOLEM + str(t)) if isinstance(t, BNode) else t


def _fmt(t) -> str:
    if t is None:
        return ""
    v = t.value
    return "_:" + v[len(_SKOLEM):] if v.startswith(_SKOLEM) else v
