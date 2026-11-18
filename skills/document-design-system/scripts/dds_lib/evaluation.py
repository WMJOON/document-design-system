"""Document evaluation: deterministic checks + recorded assessments -> per-criterion status.

Status vocabulary (EARL outcome):
  Pass          earl:passed     a stated, checkable condition holds
  Fail          earl:failed     a checkable condition is violated (SHACL, or a human assessment)
  NeedsReview   earl:cantTell   a deterministic pre-check flagged something it cannot decide,
                                or only an AI opinion exists (shown with its basis, never as a verdict)
  NotEvaluated  earl:untested   nothing checked it

Rules:
  - SHACL decides only Structure items, the Frame contract and link EXISTENCE (traceability,
    counterargument targets). It never decides whether evidence is sufficient or a summary faithful.
  - A semantic item becomes Pass/Fail only through a HUMAN assessment (earl:mode earl:manual) about
    the DOCUMENT; records about a single component are listed but never close the document item.
    Exceptions are link-existence checks (traceability Pass = links exist; SHACL-backed Fail).
    A human cannot turn a SHACL Fail into Pass; the conflict is reported.
  - No overall score. Each item keeps its own status and reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

from .graph import DDS, EARL, PROV, DataNS, bind_prefixes, validate_graph
from .model import children, content_of, effective_presentation, local_name, roots

STATUSES = ("Pass", "Fail", "NeedsReview", "NotEvaluated")
OUTCOME = {"Pass": EARL.passed, "Fail": EARL.failed, "NeedsReview": EARL.cantTell, "NotEvaluated": EARL.untested}
STATUS_OF = {v: k for k, v in OUTCOME.items()}
TOOL = URIRef("https://example.org/ontology/dds#evaluate")

ORDER = ["structure-hierarchy", "structure-depth", "structure-order", "frame-contract",
         "fidelity", "coverage", "counterargument", "perspective-bias", "traceability", "claim-evidence",
         "concept-consistency", "presentation-consistency", "presentation-distinguishability", "presentation-predictability"]
SEMANTIC = {"fidelity", "coverage", "counterargument", "perspective-bias", "traceability", "claim-evidence",
            "concept-consistency"}

SHAPE_ITEM = {
    "ddsh:ElaborationDepthShape": "structure-depth",
    "ddsh:PremiseOrderShape": "structure-order",
    "ddsh:RevisionOrderShape": "structure-order",
    "ddsh:TraceabilityShape": "traceability",
    "ddsh:CounterTargetShape": "counterargument",
    "ddsh:DeferredCritiqueShape": "counterargument",
    "ddsh:FrameContractShape": "frame-contract",
    "ddsh:FrameDesignSystemShape": "frame-contract",
    "ddsh:MappingSupportedShape": "frame-contract",
    "ddsh:UniqueMappingShape": "frame-contract",
    "ddsh:Document-frame": "frame-contract",
}
FRAME_SHAPE_PREFIXES = ("ddsh:Frame-", "ddsh:Requirement-", "ddsh:SemanticBinding-")
ASSESSMENT_SHAPES = ("ddsh:Assessment-", "ddsh:AIAssessmentShape", "ddsh:CoverageScopeShape")
# meanings that must stay visually distinct (premises share one "premise" pattern on purpose)
KEY_SEMANTICS = ("Decision", "Evidence", "Counterargument", "Critique", "UnresolvedIssue")


@dataclass
class Item:
    key: str
    dimension: str
    label: str
    status: str = "NotEvaluated"
    reasons: List[str] = field(default_factory=list)

    def set(self, status: str, reason: Optional[str] = None):
        self.status = status
        if reason:
            self.reasons.append(reason)


@dataclass
class Evaluation:
    document: str
    frame: Optional[str]
    date: str
    items: Dict[str, Item]
    unresolved: List[str] = field(default_factory=list)
    assessment_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"document": self.document, "frame": self.frame, "date": self.date,
                "items": {k: {"dimension": i.dimension, "label": i.label, "status": i.status, "reasons": i.reasons}
                          for k, i in self.items.items()},
                "unresolved": self.unresolved, "assessment_errors": self.assessment_errors}


# ---------------------------------------------------------------------------- helpers
def _sem_kinds(g: Graph, comp) -> List[str]:
    out = []
    for s in g.objects(comp, DDS.hasSemantic):
        for t in g.objects(s, RDF.type):
            out.extend(local_name(c) for c in g.transitive_objects(t, RDFS.subClassOf)
                       if str(c).startswith(str(DDS)) and local_name(c) != "Semantic")
    return sorted(set(out))


def _components(g: Graph, doc) -> List[URIRef]:
    out = []

    def walk(c):
        out.append(c)
        for ch in children(g, c):
            walk(ch)
    for r in roots(g, doc):
        walk(r)
    return out


def _label(g: Graph, comp) -> str:
    c = content_of(g, comp)
    name = str(comp).rsplit("/", 1)[-1]
    if c is None:
        return name
    t = str(c).replace("\n", " ")
    return f"{name} ({t[:40]}{'…' if len(t) > 40 else ''})"


def _criteria(g: Graph) -> Dict[str, tuple]:
    out = {}
    for c in g.subjects(RDF.type, SKOS.Concept):
        n, d = g.value(c, SKOS.notation), g.value(c, DDS.dimension)
        if n is not None and d is not None:
            out[str(n)] = (c, str(d), str(g.value(c, SKOS.prefLabel) or n))
    return out


# ---------------------------------------------------------------------------- evaluate
def evaluate(g: Graph, doc: URIRef, date: Optional[str] = None, lang: str = "en") -> Evaluation:
    """g: merged graph (TBox + defaults + document + optional assessment records)."""
    crit = _criteria(g)
    items = {k: Item(k, crit[k][1], crit[k][2]) for k in ORDER}
    frame = g.value(doc, DDS.usesFrame)
    comps = _components(g, doc)
    compset = set(comps)
    ev = Evaluation(str(doc), str(frame) if frame is not None else None,
                    date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), items)

    # 1. SHACL ------------------------------------------------------------------
    report = validate_graph(g, lang=lang)
    bad_assessments = set()
    for k in ("structure-hierarchy", "structure-depth", "structure-order"):
        items[k].set("Pass")
    if frame is not None:
        items["frame-contract"].set("Pass")
    else:
        items["frame-contract"].reasons.append("document uses no DocumentFrame")
    for v in report.violations:
        if v.shape and v.shape.startswith(ASSESSMENT_SHAPES):
            ev.assessment_errors.append(f"[{v.shape}] {v.focus}: {v.message}")
            bad_assessments.add(v.focus)
            continue
        key = SHAPE_ITEM.get(v.shape) or ("frame-contract" if v.shape and v.shape.startswith(FRAME_SHAPE_PREFIXES)
                                          else "structure-hierarchy")
        items[key].set("Fail", f"[{v.shape}] {v.focus}: {v.message}")

    # 2. deterministic pre-checks ---------------------------------------------------
    kinds = {c: _sem_kinds(g, c) for c in comps}
    # Order: dependents of a revised premise must be re-reviewed (meaning may have shifted)
    for rev in comps:
        for old in g.objects(rev, PROV.wasRevisionOf):
            for dep in g.subjects(DDS.basedOn, old):
                if dep in compset and items["structure-order"].status != "Fail":
                    items["structure-order"].set(
                        "NeedsReview", f"{_label(g, dep)} depends on premise {_label(g, old)}, "
                                       f"which {_label(g, rev)} revises: re-review the dependent")
    # Traceability: link existence only
    tr = items["traceability"]
    if tr.status != "Fail":
        traced = [c for c in comps if {"Claim", "Decision"} & set(kinds[c])]
        missing = [c for c in traced if g.value(c, DDS.supportedBy) is None]
        if missing:
            tr.set("NeedsReview", "no grounds linked (dds:supportedBy): " + ", ".join(_label(g, c) for c in missing))
        elif traced:
            tr.set("Pass", "every Claim / Decision links to grounds; whether they suffice is not judged")
    # Counterargument preservation: overview must lead to counterarguments and open issues
    overviews = [c for c in comps if g.value(c, DDS.elaboratedBy) is not None]
    reached = set()
    for o in overviews:
        for t in g.objects(o, DDS.elaboratedBy):
            reached.add(t)
            reached.update(_components_under(g, t))
    sensitive = [c for c in comps if {"Counterargument", "UnresolvedIssue"} & set(kinds[c])]
    ca = items["counterargument"]
    if ca.status != "Fail":
        hidden = [c for c in sensitive if c not in reached and not _sibling_in_reached(g, c, reached)]
        if overviews and hidden:
            ca.set("NeedsReview", "overview does not lead to: " + ", ".join(_label(g, c) for c in hidden))
    # Coverage needs a stated scope
    if not any("Scope" in kinds[c] for c in comps):
        items["coverage"].set("NeedsReview", "no Scope component: coverage / MECE cannot be judged without a stated scope")
    persp = [c for c in comps if "Perspective" in kinds[c]]
    if len(persp) == 1:
        items["perspective-bias"].set("NeedsReview", "only one stakeholder perspective is recorded")

    # 3. presentation ---------------------------------------------------------------
    _presentation(g, doc, comps, kinds, frame, items)

    # 4. recorded assessments --------------------------------------------------------
    _apply_assessments(g, doc, compset, crit, items, bad_assessments)

    # 5. unresolved list ---------------------------------------------------------------
    for c in comps:
        if "UnresolvedIssue" in kinds[c]:
            ev.unresolved.append(f"open issue: {_label(g, c)}")
        r = g.value(c, DDS.resolution)
        if r is not None and str(g.value(r, SKOS.notation)) == "deferred":
            ev.unresolved.append(f"deferred critique: {_label(g, c)}")
    for k in ORDER:
        if items[k].status == "NeedsReview":
            ev.unresolved.append(f"{items[k].dimension} / {items[k].label} requires review")
    return ev


def _components_under(g: Graph, c) -> List[URIRef]:
    out = []
    for ch in children(g, c):
        out.append(ch)
        out.extend(_components_under(g, ch))
    return out


def _sibling_in_reached(g: Graph, c, reached) -> bool:
    """A counterargument sitting in the same Section as an elaborated detail counts as reachable."""
    parent = next(iter(g.subjects(DDS.hasChild, c)), None)
    return parent is not None and any(s in reached for s in g.objects(parent, DDS.hasChild))


def _presentation(g, doc, comps, kinds, frame, items):
    by_sem: Dict[tuple, set] = {}
    by_pres: Dict[str, set] = {}
    ambiguous = []
    for c in comps:
        ks = tuple(kinds[c])
        if not ks:
            continue
        pres, _ = effective_presentation(g, doc, c)
        by_sem.setdefault(ks, set()).add(str(pres) if pres else None)
        for k in ks:
            if k in KEY_SEMANTICS and pres is not None:
                by_pres.setdefault(local_name(pres), set()).add(k)
        if frame is not None:
            mapped = {frame_presentation_for(g, frame, s) for s in g.objects(c, DDS.hasSemantic)} - {None}
            if len(mapped) > 1:
                ambiguous.append(c)
    con, dis, pre = (items["presentation-consistency"], items["presentation-distinguishability"],
                     items["presentation-predictability"])
    if by_sem:
        mixed = {ks: ps for ks, ps in by_sem.items() if len(ps) > 1}
        if mixed:
            for ks, ps in sorted(mixed.items()):
                con.set("NeedsReview", f"{'+'.join(ks)} is shown in {len(ps)} ways: "
                                       + ", ".join(sorted(local_name(p) if p else "plain" for p in ps)))
        else:
            con.set("Pass")
        clash = {p: ks for p, ks in by_pres.items() if len(ks) > 1}
        for p, ks in sorted(clash.items()):
            dis.set("NeedsReview", f"{', '.join(sorted(ks))} share presentation {p}")
        for c in ambiguous:
            dis.set("NeedsReview", f"{_label(g, c)} has several semantics with different mapped presentations")
        if not clash and not ambiguous:
            dis.set("Pass")
    if frame is None:
        pre.reasons.append("no DocumentFrame: no semantic presentation mapping to follow")
    else:
        present = {k for ks in kinds.values() for k in ks if k in KEY_SEMANTICS}
        mapped = {local_name(t) for b in g.objects(frame, DDS.definesPresentationMapping)
                  for s in g.objects(b, DDS.forSemantic) for t in g.objects(s, RDF.type)}
        unmapped = sorted(present - mapped)
        if unmapped:
            pre.set("NeedsReview", "Frame has no presentation mapping for: " + ", ".join(unmapped))
        else:
            pre.set("Pass")


def frame_presentation_for(g, frame, sem):
    for b in g.objects(frame, DDS.definesPresentationMapping):
        if g.value(b, DDS.forSemantic) == sem:
            return g.value(b, DDS.mappedPresentation)
    return None


def _apply_assessments(g, doc, compset, crit, items, bad=frozenset()):
    by_key: Dict[str, list] = {}
    for a in g.subjects(RDF.type, EARL.Assertion):
        names = {str(a)}
        if isinstance(a, URIRef):
            names.add(g.namespace_manager.normalizeUri(a))
        if names & set(bad):
            continue  # invalid record (reported in assessment_errors), never applied
        subj = g.value(a, EARL.subject)
        if subj != doc and subj not in compset:
            continue
        if g.value(a, EARL.assertedBy) == TOOL:
            continue  # our own previous output, not an assessment
        test = g.value(a, EARL.test)
        key = str(g.value(test, SKOS.notation)) if test is not None else None
        res = g.value(a, EARL.result)
        out = STATUS_OF.get(g.value(res, EARL.outcome)) if res is not None else None
        if key not in items or out is None:
            continue
        manual = (a, EARL.mode, EARL.manual) in g
        who = g.value(a, DDS.assessorModel) or g.value(a, EARL.assertedBy)
        info = "; ".join(str(i) for i in g.objects(res, EARL.info))
        scope = g.value(a, DDS.evaluationScope)
        unc = g.value(a, DDS.uncertainty)
        note = (f"{'human' if manual else 'AI'} ({local_name(who) if isinstance(who, URIRef) else who}) "
                f"says {out}: {info}" + (f" [scope: {scope}]" if scope else "") + (f" [uncertain: {unc}]" if unc else ""))
        if subj != doc:
            # A record about one component (e.g. one Section overview) never closes the document item:
            # other overviews may be unreviewed. It is listed per component.
            items[key].reasons.append(f"component {str(subj).rsplit('/', 1)[-1]}: {note} (does not set the document status)")
            continue
        by_key.setdefault(key, []).append((manual, out, note))
    for key, recs in by_key.items():
        it = items[key]
        human = {o for m, o, _ in recs if m}
        for _, _, note in recs:
            it.reasons.append(note)
        if it.status == "Fail" and key not in SEMANTIC:
            continue  # deterministic failure stands
        if it.status == "Fail" and human and human != {"Fail"}:
            it.reasons.append("human assessment conflicts with a structural failure; the failure stands")
            continue
        if len(human) > 1:
            it.set("NeedsReview", "human assessments disagree")
        elif human:
            it.status = human.pop()
        elif it.status in ("NotEvaluated", "Pass"):
            it.set("NeedsReview", "only AI opinion recorded; a human assessment closes this item")


# ---------------------------------------------------------------------------- output
def format_text(ev: Evaluation) -> str:
    lines = ["Document Evaluation", f"  document: {ev.document}", f"  frame:    {ev.frame or '-'}", f"  date:     {ev.date}"]
    for dim in ("Structure", "Semantic", "Presentation"):
        lines.append("")
        lines.append(dim)
        for k in ORDER:
            it = ev.items[k]
            if it.dimension != dim:
                continue
            lines.append(f"  {it.label}: {it.status}")
            for r in it.reasons:
                lines.append(f"      - {r}")
    if ev.assessment_errors:
        lines += ["", "Invalid assessment records (ignored)"] + [f"  - {e}" for e in ev.assessment_errors]
    lines += ["", "Unresolved Issues"] + ([f"  - {u}" for u in ev.unresolved] or ["  (none)"])
    lines += ["", "Statuses are per item; there is no overall score. Semantic Pass/Fail comes from a human record,",
              "except link-existence checks: Traceability Pass means links exist (not that they suffice), and a",
              "SHACL-backed Fail (traceability, counterargument links) is deterministic."]
    return "\n".join(lines)


def to_earl(ev: Evaluation, ns: Optional[DataNS] = None) -> Graph:
    """Evaluation result as EARL assertions (one per criterion), for history and comparison."""
    g = bind_prefixes(Graph(), ns)
    g.bind("earl", EARL)
    g.bind("dcterms", DCTERMS)
    crit_ns = (ns or DataNS()).criterion
    doc = URIRef(ev.document)
    for k in ORDER:
        it = ev.items[k]
        a, r = BNode(), BNode()
        g.add((a, RDF.type, EARL.Assertion))
        g.add((a, EARL.subject, doc))
        g.add((a, EARL.test, crit_ns[k]))
        g.add((a, EARL.assertedBy, TOOL))
        g.add((a, EARL.mode, EARL.automatic))
        if ev.frame:
            g.add((a, DDS.frameVersion, URIRef(ev.frame)))
        g.add((a, EARL.result, r))
        g.add((r, RDF.type, EARL.TestResult))
        g.add((r, EARL.outcome, OUTCOME[it.status]))
        g.add((r, DCTERMS.date, Literal(ev.date, datatype=XSD.dateTime)))
        for reason in it.reasons:
            g.add((r, EARL.info, Literal(reason)))
    return g


def from_earl(g: Graph) -> Dict[str, dict]:
    """Read an evaluation result written by to_earl -> {criterion: {status, frame, date, reasons}}."""
    out = {}
    for a in g.subjects(EARL.assertedBy, TOOL):
        r = g.value(a, EARL.result)
        key = str(g.value(a, EARL.test)).rsplit("/", 1)[-1]
        out[key] = {"status": STATUS_OF.get(g.value(r, EARL.outcome), "NotEvaluated"),
                    "frame": str(g.value(a, DDS.frameVersion) or ""),
                    "document": str(g.value(a, EARL.subject)),
                    "date": str(g.value(r, DCTERMS.date) or ""),
                    "reasons": sorted(str(i) for i in g.objects(r, EARL.info))}
    return out


# ---------------------------------------------------------------------------- comparison (Frame evolution)
def compare(before: Dict[str, dict], after: Dict[str, dict]) -> List[dict]:
    """Per-criterion comparison of two evaluation results (from_earl). No totals, no 'better' verdict:
    a status change is reported as a change, with the reasons on both sides."""
    rows = []
    for k in ORDER:
        b, a = before.get(k, {}), after.get(k, {})
        rows.append({"criterion": k, "before": b.get("status", "NotEvaluated"), "after": a.get("status", "NotEvaluated"),
                     "changed": b.get("status") != a.get("status"),
                     "reasons_before": b.get("reasons", []), "reasons_after": a.get("reasons", [])})
    return rows


def format_comparison(rows: List[dict], before: Dict[str, dict], after: Dict[str, dict]) -> str:
    def head(r):
        v = next(iter(r.values()), {})
        return f"{v.get('document', '?')} | frame {v.get('frame') or '-'} | {v.get('date', '?')}"
    lines = ["Evaluation comparison", f"  before: {head(before)}", f"  after:  {head(after)}", ""]
    w = max(len(r["criterion"]) for r in rows)
    for r in rows:
        mark = "CHANGED" if r["changed"] else ""
        lines.append(f"  {r['criterion']:<{w}}  {r['before']:<12} -> {r['after']:<12} {mark}")
        if r["changed"]:
            for x in r["reasons_after"]:
                lines.append(f"      after: {x}")
    n = sum(r["changed"] for r in rows)
    lines += ["", f"{n} criterion(s) changed. Changes are reported per item; fewer issues, higher agreement or a",
              "shorter document are not treated as quality improvement by themselves."]
    return "\n".join(lines)
