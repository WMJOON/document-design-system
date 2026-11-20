"""Namespaces, graph loading/merging and SHACL validation."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, List, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

SKILL_ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_DIR = SKILL_ROOT / "ontology"
SHAPES_DIR = SKILL_ROOT / "shapes"
INSTANCES_DIR = SKILL_ROOT / "instances"
CONFIG_DIR = SKILL_ROOT / "config"

DDS = Namespace("https://example.org/ontology/dds#")
DDSH = Namespace("https://example.org/ontology/dds/shapes#")
SH = Namespace("http://www.w3.org/ns/shacl#")
PROV = Namespace("http://www.w3.org/ns/prov#")
EARL = Namespace("http://www.w3.org/ns/earl#")

DEFAULT_BASE = "https://example.org/data/"
DEFAULT_DESIGN_SYSTEMS = INSTANCES_DIR / "design-system.ttl"
DEFAULT_FRAMES = INSTANCES_DIR / "frames.ttl"
DEFAULT_CRITERIA = INSTANCES_DIR / "evaluation.ttl"
DEFAULT_INSTANCES = [DEFAULT_DESIGN_SYSTEMS, DEFAULT_FRAMES, DEFAULT_CRITERIA]


class DataNS:
    """ABox namespaces derived from one base IRI (``--base``)."""

    def __init__(self, base: str = DEFAULT_BASE):
        if not base.endswith(("/", "#")):
            base += "/"
        self.base = base
        self.structure = Namespace(base + "structure/")
        self.semantic = Namespace(base + "semantic/")
        self.presentation = Namespace(base + "presentation/")
        self.design = Namespace(base + "design/")
        self.frame = Namespace(base + "frame/")
        self.resolution = Namespace(base + "resolution/")
        self.criterion = Namespace(base + "criterion/")
        self.doc = Namespace(base + "doc/")
        self.component = Namespace(base + "component/")

    def doc_iri(self, doc_id: str) -> URIRef:
        return self.doc[doc_id]

    def component_iri(self, doc_id: str, comp_id: str) -> URIRef:
        return self.component[f"{doc_id}/{comp_id}"]


def bind_prefixes(g: Graph, ns: Optional[DataNS] = None) -> Graph:
    ns = ns or DataNS()
    g.bind("dds", DDS)
    g.bind("skos", SKOS)
    g.bind("xsd", XSD)
    g.bind("structure", ns.structure)
    g.bind("semantic", ns.semantic)
    g.bind("presentation", ns.presentation)
    g.bind("design", ns.design)
    g.bind("frame", ns.frame)
    g.bind("resolution", ns.resolution)
    g.bind("prov", PROV)
    g.bind("criterion", ns.criterion)
    g.bind("doc", ns.doc)
    g.bind("component", ns.component)
    return g


def _parse_all(paths: Iterable[Path], g: Optional[Graph] = None) -> Graph:
    g = g if g is not None else Graph()
    for p in paths:
        g.parse(str(p), format="turtle")
    return g


def load_tbox() -> Graph:
    return _parse_all(sorted(ONTOLOGY_DIR.glob("*.ttl")))


def load_shapes() -> Graph:
    return _parse_all(sorted(SHAPES_DIR.glob("*.ttl")))


def load_data(paths: Iterable[Path], with_defaults: bool = True, with_tbox: bool = True,
              ns: Optional[DataNS] = None) -> Graph:
    """Merge TBox + default DesignSystems and Frames + given ABox files into one graph."""
    g = bind_prefixes(Graph(bind_namespaces="core"), ns)
    if with_tbox:
        _parse_all(sorted(ONTOLOGY_DIR.glob("*.ttl")), g)
    if with_defaults:
        _parse_all(DEFAULT_INSTANCES, g)
    _parse_all([Path(p) for p in paths], g)
    return g


def merge(*graphs: Graph, with_defaults: bool = True, with_tbox: bool = True,
          ns: Optional[DataNS] = None) -> Graph:
    """Merge in-memory graphs with TBox + default DesignSystems."""
    g = load_data([], with_defaults=with_defaults, with_tbox=with_tbox, ns=ns)
    for x in graphs:
        for t in x:
            g.add(t)
    return g


def resolve(name: str, default_ns: Namespace, ns: DataNS) -> URIRef:
    """Resolve 'Requirement', 'semantic:Requirement' or a full IRI."""
    name = str(name).strip()
    if name.startswith(("http://", "https://", "urn:")):
        return URIRef(name)
    if ":" in name:
        prefix, local = name.split(":", 1)
        table = {"structure": ns.structure, "semantic": ns.semantic, "presentation": ns.presentation,
                 "design": ns.design, "frame": ns.frame, "resolution": ns.resolution,
                 "dds": DDS, "prov": PROV}
        if prefix in table:
            return table[prefix][local]
    return default_ns[name]


# --------------------------------------------------------------------------- validation
@dataclass
class Violation:
    focus: str
    shape: str
    message: str
    path: Optional[str] = None
    value: Optional[str] = None
    severity: str = "Violation"


@dataclass
class Report:
    conforms: bool
    violations: List[Violation] = field(default_factory=list)

    def shapes(self) -> set:
        return {v.shape for v in self.violations}

    def to_dict(self) -> dict:
        return {"conforms": self.conforms, "violations": [asdict(v) for v in self.violations]}


def _short(g: Graph, term) -> Optional[str]:
    if term is None:
        return None
    if isinstance(term, URIRef):
        try:
            return g.namespace_manager.normalizeUri(term)
        except Exception:  # pragma: no cover - defensive
            return str(term)
    return str(term)


def _msg_lang(m: Literal) -> str:
    """Language of a result message. pyshacl drops language tags after {?var}
    substitution (SPARQL constraints), so fall back to script detection."""
    lang = getattr(m, "language", None)
    if lang:
        return lang
    return "ko" if any("\uac00" <= ch <= "\ud7a3" for ch in str(m)) else "en"


def _pick_message(msgs: List[Literal], lang: str) -> str:
    if not msgs:
        return ""
    for want in (lang, "en"):
        for m in sorted(msgs, key=str):
            if _msg_lang(m) == want:
                return str(m)
    return str(sorted(msgs, key=str)[0])


def validate_graph(data: Graph, shapes: Optional[Graph] = None, lang: str = "en") -> Report:
    """Run SHACL (Core + SPARQL) with inference DISABLED.

    rdfs:domain/range would otherwise *infer* missing types (e.g. a dangling
    usesDesignSystem target would become a DesignSystem). The TBox is merged into
    the data graph instead, so sh:class follows rdfs:subClassOf natively.
    """
    import os
    from pyshacl import validate

    shapes = shapes if shapes is not None else load_shapes()
    # Fast path (default): Core shapes with pyshacl, sh:sparql constraints with pyoxigraph.
    # DDS_SHACL_ENGINE=pyshacl runs everything through pyshacl as before.
    fast = os.environ.get("DDS_SHACL_ENGINE", "oxigraph") != "pyshacl"
    if fast:
        try:
            import pyoxigraph  # noqa: F401
        except ImportError:
            fast = False
    extra: List[Violation] = []
    if fast:
        from .oxshacl import run_sparql_constraints, split_shapes
        core, constraints = split_shapes(shapes)
        aux = Graph()
        aux.namespace_manager = data.namespace_manager
        bind_prefixes(aux)
        aux.bind("ddsh", DDSH)
        for shape, focus, msgs, sev, value in run_sparql_constraints(data, constraints):
            extra.append(Violation(
                focus=_short(aux, focus or None),
                shape=_short(aux, shape),
                message=_pick_message(msgs, lang),
                path=None,
                value=_short(aux, value or None),
                severity=str(sev).split("#")[-1],
            ))
        shapes = core
    conforms, results, _text = validate(
        data_graph=data, shacl_graph=shapes, inference="none",
        abort_on_first=False, allow_warnings=False, meta_shacl=False, advanced=True,
    )
    if not isinstance(results, Graph):  # pyshacl ValidationFailure (broken shapes)
        raise RuntimeError(f"SHACL engine failure: {_text}")
    nm = data.namespace_manager
    results.namespace_manager = nm
    bind_prefixes(results)
    results.bind("ddsh", DDSH)
    out: List[Violation] = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        msgs = list(results.objects(r, SH.resultMessage))
        out.append(Violation(
            focus=_short(results, results.value(r, SH.focusNode)),
            shape=_short(results, results.value(r, SH.sourceShape)),
            message=_pick_message(msgs, lang),
            path=_short(results, results.value(r, SH.resultPath)),
            value=_short(results, results.value(r, SH.value)),
            severity=_short(results, results.value(r, SH.resultSeverity)).split(":")[-1].split("#")[-1],
        ))
    out.extend(extra)
    out.sort(key=lambda v: (v.shape or "", v.focus or "", v.value or ""))
    conforms = bool(conforms) and not any(v.severity == "Violation" for v in extra)
    return Report(conforms=conforms, violations=out)


def format_report(report: Report) -> str:
    if report.conforms:
        return "PASS  SHACL conforms (0 violations)"
    lines = [f"FAIL  {len(report.violations)} SHACL violation(s)"]
    for v in report.violations:
        where = v.focus + (f" · {v.path}" if v.path else "")
        val = f" = {v.value}" if v.value else ""
        lines.append(f"  - [{v.shape}] {where}{val}\n      {v.message}")
    return "\n".join(lines)
