"""Change detection and dependency impact analysis between two versions of one document.

Component IRIs are stable across versions, so versions are compared by IRI.
The dependency graph is the existing v0.3.0 relation set (no new model):
  basedOn (premise), supportedBy (grounds), elaboratedBy (overview -> detail), counters, targets,
  prov:wasRevisionOf, prov:wasDerivedFrom, plus the Section hierarchy (hasChild).
Impact = reverse traversal of those edges from the changed components, plus the overview (leading
content) of every ancestor Section. Selection is bounded by RECORDED links: a dependency that is not
written as a relation cannot be found here (that is what global critique, L2, is for).
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from rdflib import Graph, URIRef

from .graph import DDS, PROV
from .model import children, component_kind, roots

DEP_PROPS = [DDS.basedOn, DDS.supportedBy, DDS.elaboratedBy, DDS.counters, DDS.targets,
             PROV.wasRevisionOf, PROV.wasDerivedFrom, PROV.hadPrimarySource]
SEMANTIC_KINDS = {"content", "semantic", "relation", "added", "removed"}


def sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def normalize_text(text: str) -> str:
    """Remove whitespace and punctuation only. Used to call an edit cosmetic; never edit distance,
    because one character can flip meaning (negation, numbers)."""
    return "".join(ch for ch in unicodedata.normalize("NFC", text)
                   if not unicodedata.category(ch).startswith(("Z", "P")) and not ch.isspace())


def components(g: Graph, doc: URIRef) -> List[URIRef]:
    out = []

    def walk(c):
        out.append(c)
        for ch in children(g, c):
            walk(ch)
    for r in roots(g, doc):
        walk(r)
    return out


def parent_of(g: Graph, c) -> Optional[URIRef]:
    return next(iter(g.subjects(DDS.hasChild, c)), None)


@dataclass
class Facets:
    text: str
    lang: str
    semantics: Tuple[str, ...]
    structure: str
    parent: str
    order: str
    presentation: str
    relations: Tuple[Tuple[str, str], ...]
    resolution: str

    @property
    def content_hash(self) -> str:
        return sha(self.text, self.lang, *self.semantics)


def facets(g: Graph, c) -> Facets:
    content = g.value(c, DDS.hasContent)
    rel = tuple(sorted((str(p), str(o)) for p in DEP_PROPS for o in g.objects(c, p)))
    return Facets(text=str(content) if content is not None else "",
                  lang=getattr(content, "language", None) or "",
                  semantics=tuple(sorted(str(s) for s in g.objects(c, DDS.hasSemantic))),
                  structure=str(g.value(c, DDS.hasStructure)), parent=str(parent_of(g, c)),
                  order=str(g.value(c, DDS.hasOrder)), presentation=str(g.value(c, DDS.hasPresentation)),
                  relations=rel, resolution=str(g.value(c, DDS.resolution)))


@dataclass
class Change:
    component: str
    kinds: Set[str]

    @property
    def semantic(self) -> bool:
        return bool(self.kinds & SEMANTIC_KINDS)


def diff(prev: Graph, prev_doc: URIRef, cur: Graph, cur_doc: URIRef) -> Dict[str, Change]:
    """Per-component change kinds: added, removed, content, cosmetic, semantic, relation,
    structure (parent/order/structure type), presentation."""
    a = {str(c): facets(prev, c) for c in components(prev, prev_doc)}
    b = {str(c): facets(cur, c) for c in components(cur, cur_doc)}
    out: Dict[str, Change] = {}
    for iri in sorted(set(a) | set(b)):
        if iri not in a:
            out[iri] = Change(iri, {"added"})
            continue
        if iri not in b:
            out[iri] = Change(iri, {"removed"})
            continue
        x, y, k = a[iri], b[iri], set()
        if x.text != y.text or x.lang != y.lang:
            k.add("cosmetic" if x.lang == y.lang and normalize_text(x.text) == normalize_text(y.text) else "content")
        if x.semantics != y.semantics:
            k.add("semantic")
        if x.relations != y.relations or x.resolution != y.resolution:
            k.add("relation")
        if (x.structure, x.parent, x.order) != (y.structure, y.parent, y.order):
            k.add("structure")
        if x.presentation != y.presentation:
            k.add("presentation")
        if k:
            out[iri] = Change(iri, k)
    return out


def overview_of(g: Graph, doc: URIRef, section: Optional[URIRef]) -> List[URIRef]:
    """Leading content of a Section (or of the document): leaf children before the first sub-Section."""
    kids = roots(g, doc) if section is None else children(g, section)
    if not any(component_kind(g, k) == "Section" for k in kids):
        return []  # no sub-Section to condense: the content is detail, not overview
    out = []
    for k in kids:
        if component_kind(g, k) == "Section":
            break
        if component_kind(g, k) in ("Paragraph", "List", "Table"):
            out.append(k)
    return out


def ancestors(g: Graph, c) -> List[URIRef]:
    out, p = [], parent_of(g, c)
    while p is not None:
        out.append(p)
        p = parent_of(g, p)
    return out


@dataclass
class Impact:
    seeds: Dict[str, int] = field(default_factory=dict)        # changed components (distance 0)
    affected: Dict[str, int] = field(default_factory=dict)     # component -> distance (0 direct change)
    overview_targets: Set[str] = field(default_factory=set)    # overview content to re-check for fidelity
    reasons: Dict[str, List[str]] = field(default_factory=dict)
    limitation: str = ("selection follows recorded relations only; unrecorded dependencies are not found "
                       "(run global critique, L2, to cover them)")

    def add(self, iri: str, dist: int, why: str):
        if iri not in self.affected or dist < self.affected[iri]:
            self.affected[iri] = dist
        self.reasons.setdefault(iri, []).append(why)

    @property
    def direct(self) -> Set[str]:
        return {i for i, d in self.affected.items() if d <= 1}

    @property
    def indirect(self) -> Set[str]:
        return {i for i, d in self.affected.items() if d >= 2}


def impact(cur: Graph, doc: URIRef, changes: Dict[str, Change], prev: Optional[Graph] = None,
           max_depth: Optional[int] = None) -> Impact:
    """Components whose evaluation may change because of `changes`.

    Semantic changes (content, semantic type, relation, added, removed) propagate backwards along the
    dependency edges: premise -> dependents, evidence -> claims, detail -> overviews, target ->
    counterarguments / critiques, original -> revisions. Structure changes only re-check the overviews
    of old and new ancestor Sections. Presentation-only and cosmetic edits select nothing (L0 covers them).
    """
    imp = Impact()
    reverse: Dict[str, List[Tuple[str, str]]] = {}
    for g in [cur] + ([prev] if prev is not None else []):
        for p in DEP_PROPS:
            for s, o in g.subject_objects(p):
                reverse.setdefault(str(o), []).append((str(s), str(p).rsplit("#", 1)[-1].rsplit("/", 1)[-1]))
    present = {str(c) for c in components(cur, doc)}

    queue: List[Tuple[str, int]] = []
    for iri, ch in changes.items():
        if ch.semantic:
            imp.seeds[iri] = 0
            imp.add(iri, 0, "changed: " + ",".join(sorted(ch.kinds)))
            queue.append((iri, 0))
    seen = set()
    while queue:
        iri, d = queue.pop(0)
        if (iri, d) in seen or (max_depth is not None and d >= max_depth):
            continue
        seen.add((iri, d))
        for src, prop in reverse.get(iri, []):
            if src in present and (src not in imp.affected or imp.affected[src] > d + 1):
                imp.add(src, d + 1, f"{prop} -> {iri.rsplit('/', 1)[-1]}")
                queue.append((src, d + 1))
    # overviews of ancestor Sections (and the document) of every semantically affected component
    touched = set(imp.affected) | {i for i, ch in changes.items() if "structure" in ch.kinds}
    for g in [cur] + ([prev] if prev is not None else []):
        for iri in touched:
            node = URIRef(iri)
            if (node, None, None) not in g:
                continue
            for sec in ancestors(g, node) + [None]:
                for ov in overview_of(g, doc, sec):
                    if str(ov) in present and str(ov) != iri:
                        imp.overview_targets.add(str(ov))
    for ov in imp.overview_targets:
        if ov not in imp.affected:
            imp.add(ov, 1, "overview of an affected Section")
    return imp


def removed_in_place(changes: Dict[str, Change]) -> Iterable[str]:
    return [i for i, c in changes.items() if "removed" in c.kinds]
