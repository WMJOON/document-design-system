"""Read-side helpers: document tree traversal, structure kinds, effective presentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .graph import CONFIG_DIR, DDS

# Order matters: most specific first.
KINDS = ["ListItem", "TableRow", "TableCell", "Section", "Heading", "Paragraph", "List", "Table"]
CONTAINER_KINDS = {"Section", "List", "Table", "TableRow"}


def local_name(iri) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


def _superclasses(g: Graph, cls: URIRef) -> set:
    return set(g.transitive_objects(cls, RDFS.subClassOf))


def structure_kind(g: Graph, structure: URIRef) -> Optional[str]:
    """Map a Structure individual to one of KINDS via its rdf:type + rdfs:subClassOf*."""
    for t in g.objects(structure, RDF.type):
        sup = _superclasses(g, t)
        for k in KINDS:
            if DDS[k] in sup:
                return k
    return None


def component_kind(g: Graph, comp: URIRef) -> Optional[str]:
    s = g.value(comp, DDS.hasStructure)
    return structure_kind(g, s) if s is not None else None


def order_of(g: Graph, comp: URIRef) -> int:
    v = g.value(comp, DDS.hasOrder)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 10 ** 9


def sorted_nodes(g: Graph, nodes) -> List[URIRef]:
    return sorted(nodes, key=lambda c: (order_of(g, c), str(c)))


def roots(g: Graph, doc: URIRef) -> List[URIRef]:
    return sorted_nodes(g, g.objects(doc, DDS.hasComponent))


def children(g: Graph, comp: URIRef) -> List[URIRef]:
    return sorted_nodes(g, g.objects(comp, DDS.hasChild))


def documents(g: Graph) -> List[URIRef]:
    return sorted(set(g.subjects(RDF.type, DDS.Document)), key=str)


def content_of(g: Graph, comp: URIRef) -> Optional[Literal]:
    return g.value(comp, DDS.hasContent)


def default_presentation(g: Graph, ds: Optional[URIRef], structure: Optional[URIRef]) -> Optional[URIRef]:
    if ds is None or structure is None:
        return None
    for b in g.objects(ds, DDS.hasDefaultPresentation):
        if g.value(b, DDS.forStructure) == structure:
            return g.value(b, DDS.presentation)
    return None


def effective_presentation(g: Graph, doc: URIRef, comp: URIRef):
    """Return (presentation IRI or None, is_explicit)."""
    explicit = g.value(comp, DDS.hasPresentation)
    if explicit is not None:
        return explicit, True
    ds = g.value(doc, DDS.usesDesignSystem)
    return default_presentation(g, ds, g.value(comp, DDS.hasStructure)), False


def token_of(g: Graph, presentation: Optional[URIRef]) -> Optional[str]:
    if presentation is None:
        return None
    t = g.value(presentation, DDS.token)
    return str(t) if t is not None else local_name(presentation)


def title_of(g: Graph, node: URIRef) -> Optional[Literal]:
    return g.value(node, SKOS.prefLabel)


# --------------------------------------------------------------------------- markdown style map
@dataclass
class TokenStyle:
    prefix: str = ""
    wrap: str = ""

    def apply(self, text: str) -> str:
        if self.wrap:
            text = f"{self.wrap}{text}{self.wrap}"
        if self.prefix:
            text = "\n".join(self.prefix + line for line in text.split("\n"))
        return text

    def strip(self, text: str) -> str:
        if self.prefix:
            text = "\n".join(l[len(self.prefix):] if l.startswith(self.prefix) else l for l in text.split("\n"))
        if self.wrap and text.startswith(self.wrap) and text.endswith(self.wrap) and len(text) >= 2 * len(self.wrap):
            text = text[len(self.wrap):-len(self.wrap)]
        return text


@dataclass
class StyleMap:
    tokens: Dict[str, TokenStyle] = field(default_factory=dict)

    def get(self, token: Optional[str]) -> TokenStyle:
        return self.tokens.get(token or "", TokenStyle())


def load_style_map(path: Optional[Path] = None) -> StyleMap:
    import yaml

    path = path or CONFIG_DIR / "presentation-markdown.yaml"
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    toks = {}
    for k, v in (data.get("tokens") or {}).items():
        v = v or {}
        toks[str(k)] = TokenStyle(prefix=str(v.get("prefix", "")), wrap=str(v.get("wrap", "")))
    return StyleMap(toks)
