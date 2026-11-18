"""Evaluation packets: the minimal LLM input for one semantic check.

A packet = stable PREFIX (instructions, criterion definitions, output schema; identical across
packets of the same type, so a backend can cache it) + variable BODY (target, premises, evidence,
details). Packets never carry the whole document, except the L2 global critique, which needs it.

L1 types (local, one target):
  overview-fidelity     Section leading content vs the details it leads to (elaboratedBy + sub-Sections)
  claim-evidence        Claim / Decision / Alternative vs its supportedBy grounds
  premise-consistency   component vs the transitive basedOn premises it depends on
  concept-usage         explicit premise revision (wasRevisionOf) vs original and dependents
L2 type:
  global-critique       whole document outline: coverage, counterargument, perspective bias, long-tail
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rdflib import Graph, URIRef
from rdflib.namespace import SKOS

from .graph import DDS, PROV
from .incremental import components, normalize_text, overview_of, parent_of, sha
from .model import children, component_kind, local_name, title_of

PROMPT_VERSION = "1"

# packet type -> (level, EARL criterion keys it answers)
TYPES = {
    "overview-fidelity": ("L1", ["fidelity"]),
    "claim-evidence": ("L1", ["claim-evidence"]),
    "premise-consistency": ("L1", ["concept-consistency"]),
    "concept-usage": ("L1", ["concept-consistency"]),
    "global-critique": ("L2", ["coverage", "counterargument", "perspective-bias", "concept-consistency"]),
}

INSTRUCTIONS = {
    "overview-fidelity": "Check whether the OVERVIEW faithfully condenses the DETAILS: no claim the details do not "
                         "support, no reversal, no dropped counterargument, exception or uncertainty that matters "
                         "for the judgment.",
    "claim-evidence": "Check whether the GROUNDS actually support the TARGET claim or decision. Judge sufficiency, "
                      "not whether a link exists.",
    "premise-consistency": "Check whether the TARGET uses its PREMISES with the same meaning as they define, without "
                           "silently changing or reinterpreting them.",
    "concept-usage": "A premise was explicitly REVISED. Check whether the DEPENDENTS still fit the revised premise "
                     "or need to change.",
    "global-critique": "Act as an independent reviewer of the whole DOCUMENT. Judge only the listed criteria. Do not "
                       "assume the document is complete; name missing alternatives, hidden counterarguments, "
                       "unrepresented perspectives, unclassified cases, and statements that contradict premises "
                       "even where no explicit link connects them.",
}

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "confidence", "rationale"],
    "properties": {
        "verdict": {"enum": ["consistent", "inconsistent", "uncertain"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
}


def output_schema(criteria: List[str], combined: bool) -> dict:
    if not combined or len(criteria) == 1:
        return VERDICT_SCHEMA
    return {"type": "object", "required": ["items"],
            "properties": {"items": {"type": "object", "required": criteria,
                                     "properties": {c: VERDICT_SCHEMA for c in criteria}}}}


def estimate_tokens(text: str) -> int:
    """Rough, dependency-free estimate (ASCII ~4 chars/token, other scripts ~1.5 chars/token).
    Reported as `estimated`; never used for cost unless the caller accepts estimates."""
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_n / 4 + (len(text) - ascii_n) / 1.5) + 1


@dataclass
class Packet:
    type: str
    level: str
    criteria: List[str]          # EARL criterion keys answered by this packet
    subject: str                 # IRI the result is about (component for L1, document for L2)
    prefix: str
    body: str
    members: List[str] = field(default_factory=list)   # component IRIs whose content is in the body
    combined: bool = False

    @property
    def content_hash(self) -> str:
        """Hash for cache keys: prefix + body with whitespace / punctuation normalized, so a cosmetic
        edit keeps the key while any letter or digit change (negation, numbers) changes it.
        The model always receives the original text."""
        return sha(self.prefix, normalize_text(self.body))

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.prefix) + estimate_tokens(self.body)

    @property
    def prefix_tokens(self) -> int:
        return estimate_tokens(self.prefix)

    def to_json(self) -> dict:
        return {"type": self.type, "level": self.level, "criteria": self.criteria, "subject": self.subject,
                "prompt_version": PROMPT_VERSION, "prefix": self.prefix, "body": self.body,
                "schema": output_schema(self.criteria, self.combined)}


def _criterion_text(g: Graph, key: str) -> str:
    for c in g.subjects(SKOS.notation, None):
        if str(g.value(c, SKOS.notation)) == key and g.value(c, SKOS.definition) is not None:
            return f"- {key}: {g.value(c, SKOS.definition)}"
    return f"- {key}"


def prefix_for(g: Graph, ptype: str, criteria: List[str], combined: bool) -> str:
    return "\n".join([
        f"DDS evaluation, prompt version {PROMPT_VERSION}. Type: {ptype}.",
        INSTRUCTIONS[ptype],
        "Criteria:", *(_criterion_text(g, k) for k in criteria),
        "Answer with JSON only, matching this schema:",
        json.dumps(output_schema(criteria, combined), sort_keys=True),
        "Use 'uncertain' when the given text is not enough to decide.",
    ])


def _line(g: Graph, c, role: str) -> str:
    sems = ",".join(sorted(local_name(s) for s in g.objects(c, DDS.hasSemantic)))
    text = g.value(c, DDS.hasContent)
    return f"[{role}] id={str(c).rsplit('/', 1)[-1]} semantic={sems or '-'}\n{text if text is not None else ''}"


def _subtree_text(g: Graph, c) -> List:
    out = [c] if g.value(c, DDS.hasContent) is not None else []
    for ch in children(g, c):
        out.extend(_subtree_text(g, ch))
    return out


def _premise_closure(g: Graph, c) -> List:
    seen, todo = [], list(g.objects(c, DDS.basedOn))
    while todo:
        p = todo.pop(0)
        if p not in seen:
            seen.append(p)
            todo.extend(g.objects(p, DDS.basedOn))
    return seen


def _kinds(g: Graph, c) -> set:
    from .evaluation import _sem_kinds
    return set(_sem_kinds(g, c))


def build_l1(g: Graph, doc: URIRef, only: Optional[set] = None, combined: bool = False) -> List[Packet]:
    """All L1 packets of the document (or only those whose subject is in `only`)."""
    frame = g.value(doc, DDS.usesFrame)
    head = f"frame={local_name(frame) if frame is not None else '-'}"
    out: List[Packet] = []

    def make(ptype, subject, parts):
        level, crit = TYPES[ptype]
        if only is not None and str(subject) not in only:
            return
        body = "\n\n".join([head] + [_line(g, c, role) for role, c in parts])
        out.append(Packet(ptype, level, crit, str(subject), prefix_for(g, ptype, crit, combined), body,
                          members=sorted({str(c) for _, c in parts}), combined=combined))

    comps = components(g, doc)
    sections = [None] + [c for c in comps if component_kind(g, c) == "Section"]
    for sec in sections:
        for ov in overview_of(g, doc, sec):
            targets = list(g.objects(ov, DDS.elaboratedBy))
            if not targets:
                continue
            details = []
            for t in sorted(targets, key=str):
                for d in _subtree_text(g, t):
                    if d not in details and d != ov:
                        details.append(d)
            make("overview-fidelity", ov, [("OVERVIEW", ov)] + [("DETAIL", d) for d in details])
    for c in comps:
        kinds = _kinds(g, c)
        grounds = sorted(g.objects(c, DDS.supportedBy), key=str)
        if grounds and kinds & {"Claim", "Decision", "Alternative"}:
            make("claim-evidence", c, [("TARGET", c)] + [("GROUND", e) for e in grounds])
        prem = _premise_closure(g, c)
        if prem:
            make("premise-consistency", c, [("TARGET", c)] + [("PREMISE", p) for p in prem])
        for orig in g.objects(c, PROV.wasRevisionOf):
            if (orig, DDS.hasStructure, None) not in g:
                continue
            deps = sorted(g.subjects(DDS.basedOn, orig), key=str)
            if deps:
                make("concept-usage", c, [("ORIGINAL", orig), ("REVISED", c)] + [("DEPENDENT", d) for d in deps])
    return out


def plain_outline(g: Graph, doc: URIRef) -> str:
    """Whole document as a compact outline (structure + semantics + text), no annotations, no prior verdicts."""
    lines = [f"# {title_of(g, doc) or local_name(doc)}"]

    def walk(c, depth):
        kind = component_kind(g, c)
        if kind == "Section":
            for ch in children(g, c):
                walk(ch, depth + 1)
            return
        text = g.value(c, DDS.hasContent)
        sems = ",".join(sorted(local_name(s) for s in g.objects(c, DDS.hasSemantic)))
        if kind == "Heading":
            lines.append("#" * min(6, depth + 1) + f" {text}")
        elif text is not None:
            lines.append(f"{'  ' * max(0, depth - 1)}- ({sems or kind}) {text}")
        for ch in children(g, c):
            walk(ch, depth + 1)
    for r in components(g, doc):
        if parent_of(g, r) is None:
            walk(r, 1)
    return "\n".join(lines)


def build_l2(g: Graph, doc: URIRef, combined: bool = False) -> List[Packet]:
    """Global independent critique. Excludes prior AI verdicts (independence). One packet per
    criterion unless combined."""
    level, crit = TYPES["global-critique"]
    body = plain_outline(g, doc)
    members = [str(c) for c in components(g, doc)]
    groups = [crit] if combined else [[k] for k in crit]
    return [Packet("global-critique", level, ks, str(doc), prefix_for(g, "global-critique", ks, combined), body,
                   members=members, combined=combined) for ks in groups]


def build_naive(g: Graph, doc: URIRef) -> List[Packet]:
    """Reference strategy for comparison only: whole document, one call per semantic criterion."""
    from .evaluation import ORDER, SEMANTIC
    body = plain_outline(g, doc)
    members = [str(c) for c in components(g, doc)]
    out = []
    for k in [k for k in ORDER if k in SEMANTIC]:
        out.append(Packet("naive", "naive", [k], str(doc),
                          "\n".join([f"DDS naive evaluation, prompt version {PROMPT_VERSION}.",
                                     "Judge the whole DOCUMENT on this criterion.", _criterion_text(g, k),
                                     "Answer with JSON only, matching this schema:",
                                     json.dumps(VERDICT_SCHEMA, sort_keys=True)]),
                          body, members=members))
    return out
