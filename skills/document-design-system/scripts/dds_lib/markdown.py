"""RDF <-> Markdown.

render(): reads the ontology structure (order, Section nesting, List/Table children) and
writes Markdown. It never invents hierarchy: heading level = Section depth.
With ``annotate=True`` each component is preceded by an HTML comment
``<!-- dds {...} -->`` holding its id, structure, explicit semantics/presentation, so that
parse() can restore IRIs, hierarchy, order and semantics (round trip). Default
(DesignSystem-bound) presentations are *not* written, so they stay implicit after parsing.

parse(): Markdown -> ABox. Annotated Markdown restores the original graph (with orders
normalised to 1..n). Plain Markdown is parsed structurally: every heading opens a Section
at depth = level - 1; ids are positional (s1, s1-h, p3, ...).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS, XSD

from .graph import DDS, DataNS, bind_prefixes, load_data, resolve
from .model import (children, component_kind, content_of, effective_presentation, load_style_map,
                    local_name, roots, structure_kind, title_of, token_of)

ANN = re.compile(r"^<!--\s*dds\s+(\{.*\})\s*-->\s*$")
END = re.compile(r"^<!--\s*/dds\s+(\{.*\})\s*-->\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
DEFAULT_ITEM_STRUCT = {"items": "ListItem", "rows": "TableRow", "cells": "TableCell"}


def _dump(d: Dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def _inline_encode(text: str) -> str:
    return text.replace("\n", "<br>")


def _inline_decode(text: str) -> str:
    return text.replace("<br>", "\n")


def _cell_encode(text: str) -> str:
    return _inline_encode(text).replace("|", "\\|")


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if line[i] == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += line[i]
        i += 1
    cells.append(cur.strip())
    return cells


# ============================================================================ render
class _Ctx:
    def __init__(self, g: Graph, doc: URIRef, annotate: bool, style_path: Optional[Path]):
        self.g, self.doc, self.annotate = g, doc, annotate
        self.styles = load_style_map(style_path)
        s = str(doc)
        if "/doc/" not in s:
            raise ValueError(f"document IRI {doc} does not follow <base>doc/<id>")
        self.base = s[: s.rfind("/doc/") + 1]
        self.doc_id = s[s.rfind("/doc/") + 5:]
        self.ns = DataNS(self.base)
        title = title_of(g, doc)
        self.lang = title.language if isinstance(title, Literal) and title.language else None
        if self.lang is None:
            for c in g.objects(None, DDS.hasContent):
                if getattr(c, "language", None):
                    self.lang = c.language
                    break

    def compact(self, iri, ns) -> str:
        s = str(iri)
        return s[len(str(ns)):] if s.startswith(str(ns)) and "/" not in s[len(str(ns)):] else s

    def ident(self, comp: URIRef) -> Dict[str, str]:
        prefix = f"{self.ns.component}{self.doc_id}/"
        s = str(comp)
        return {"id": s[len(prefix):]} if s.startswith(prefix) else {"iri": s}

    def meta(self, comp: URIRef, default_struct: Optional[str] = None) -> Dict[str, Any]:
        g = self.g
        m: Dict[str, Any] = self.ident(comp)
        st = g.value(comp, DDS.hasStructure)
        st_c = self.compact(st, self.ns.structure)
        if default_struct is None or st_c != default_struct:
            m["s"] = st_c
        sems = sorted(self.compact(x, self.ns.semantic) for x in g.objects(comp, DDS.hasSemantic))
        if sems:
            m["sem"] = sems
        p = g.value(comp, DDS.hasPresentation)
        if p is not None:
            m["p"] = self.compact(p, self.ns.presentation)
        o = g.value(comp, DDS.ordered)
        if o is not None:
            m["ordered"] = bool(o.toPython())
        c = content_of(g, comp)
        if c is not None and getattr(c, "language", None) != self.lang:
            m["lang"] = c.language
        # typed tables (v0.2): keep kind / row subject / cell column / header overrides for round trip
        tk = g.value(comp, DDS.tableKind)
        if tk is not None:
            m["kind"] = self.compact(tk, self.ns.design)
            tv = g.value(comp, DDS.tableView)
            if tv is not None:
                m["view"] = self.compact(tv, self.ns.design)
        sk = g.value(comp, DDS.sectionKind)
        if sk is not None:
            m["skind"] = self.compact(sk, self.ns.design)
        if g.value(comp, DDS.fillsSlot) is not None:
            m["slot"] = str(g.value(comp, DDS.fillsSlot))
        if g.value(comp, DDS.about) is not None:
            m["about"] = str(g.value(comp, DDS.about))
        if g.value(comp, DDS.headerRow) is not None:
            m["hdr"] = bool(g.value(comp, DDS.headerRow).toPython())
        if g.value(comp, DDS.column) is not None:
            m["col"] = str(g.value(comp, DDS.column))
        return m

    def text(self, comp: URIRef) -> str:
        c = content_of(self.g, comp)
        raw = str(c) if c is not None else ""
        pres, _explicit = effective_presentation(self.g, self.doc, comp)
        return self.styles.get(token_of(self.g, pres)).apply(raw) if raw else raw


def render(g: Graph, doc: URIRef, annotate: bool = True, style_path: Optional[Path] = None) -> str:
    ctx = _Ctx(g, doc, annotate, style_path)
    out: List[str] = []

    def block(lines: List[str]):
        out.extend(lines)
        out.append("")

    def ann(m: Dict[str, Any]) -> List[str]:
        return [f"<!-- dds {_dump(m)} -->"] if annotate else []

    if annotate:
        head = {"document": ctx.doc_id, "design_system": ctx.compact(g.value(doc, DDS.usesDesignSystem), ctx.ns.design),
                "base": ctx.base}
        if ctx.lang:
            head["lang"] = ctx.lang
        out.append(f"<!-- dds {_dump(head)} -->")
    title = title_of(g, doc)
    block([f"# {title}" if title is not None else f"# {ctx.doc_id}"])

    def walk(comp: URIRef, depth: int):
        kind = component_kind(g, comp)
        m = ctx.meta(comp)
        if kind == "Section":
            if annotate:
                out.append(f"<!-- dds {_dump(m)} -->")
            for ch in children(g, comp):
                walk(ch, depth + 1)
            if annotate:
                block([f"<!-- /dds {_dump(ctx.ident(comp))} -->"])
            return
        if kind == "Heading":
            level = min(6, 1 + max(1, depth))
            block(ann(m) + [f"{'#' * level} {_inline_encode(ctx.text(comp))}"])
        elif kind == "Paragraph":
            block(ann(m) + [ctx.text(comp)])
        elif kind == "List":
            items = children(g, comp)
            m["items"] = [ctx.meta(i, DEFAULT_ITEM_STRUCT["items"]) for i in items]
            ordered = bool(g.value(comp, DDS.ordered).toPython()) if g.value(comp, DDS.ordered) is not None else False
            lines = [f"{(str(n) + '.') if ordered else '-'} {_inline_encode(ctx.text(i))}" for n, i in enumerate(items, 1)]
            block(ann(m) + lines)
        elif kind == "Table":
            rows = children(g, comp)
            m["rows"] = []
            grid: List[List[str]] = []
            for r in rows:
                cells = children(g, r)
                rm = ctx.meta(r, DEFAULT_ITEM_STRUCT["rows"])
                rm["cells"] = [ctx.meta(c, DEFAULT_ITEM_STRUCT["cells"]) for c in cells]
                m["rows"].append(rm)
                grid.append([_cell_encode(ctx.text(c)) for c in cells])
            width = max((len(r) for r in grid), default=0)
            lines = []
            for n, r in enumerate(grid):
                r = r + [""] * (width - len(r))
                lines.append("| " + " | ".join(r) + " |")
                if n == 0:
                    lines.append("|" + "|".join(["---"] * width) + "|")
            block(ann(m) + lines)
        else:  # unknown / stray kinds: render content as a paragraph, never silently drop
            block(ann(m) + [ctx.text(comp)])

    for r in roots(g, doc):
        walk(r, 0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


# ============================================================================ parse
class ParseError(ValueError):
    pass


class _Builder:
    def __init__(self, doc_id: str, design_system: str, base: str, lang: str):
        self.ns = DataNS(base)
        self.doc_id, self.lang = doc_id, lang
        self.g = bind_prefixes(Graph(bind_namespaces="core"), self.ns)
        self.doc = self.ns.doc_iri(doc_id)
        self.g.add((self.doc, RDF.type, DDS.Document))
        self.g.add((self.doc, DDS.usesDesignSystem, resolve(design_system, self.ns.design, self.ns)))
        self.order: Dict[URIRef, int] = {}
        self.vocab = load_data([], with_defaults=True)  # to map structure individuals -> kinds
        self.seq = 0
        self.used: set = set()

    def title(self, text: str):
        self.g.add((self.doc, SKOS.prefLabel, Literal(text, lang=self.lang)))

    def node(self, m: Dict[str, Any], parent: Optional[URIRef], default_struct: str) -> URIRef:
        g, ns = self.g, self.ns
        iri = URIRef(m["iri"]) if "iri" in m else ns.component_iri(self.doc_id, m["id"])
        g.add((iri, RDF.type, DDS.Component))
        g.add((iri, DDS.hasStructure, resolve(m.get("s", default_struct), ns.structure, ns)))
        for s in m.get("sem", []):
            g.add((iri, DDS.hasSemantic, resolve(s, ns.semantic, ns)))
        if m.get("p"):
            g.add((iri, DDS.hasPresentation, resolve(m["p"], ns.presentation, ns)))
        if "ordered" in m:
            g.add((iri, DDS.ordered, Literal(bool(m["ordered"]))))
        if m.get("kind"):
            g.add((iri, DDS.tableKind, resolve(m["kind"], ns.design, ns)))
            if m.get("view"):
                g.add((iri, DDS.tableView, resolve(m["view"], ns.design, ns)))
        if m.get("skind"):
            g.add((iri, DDS.sectionKind, resolve(m["skind"], ns.design, ns)))
        if m.get("slot"):
            g.add((iri, DDS.fillsSlot, Literal(m["slot"])))
        if m.get("about"):
            g.add((iri, DDS.about, URIRef(m["about"])))
        if "hdr" in m:
            g.add((iri, DDS.headerRow, Literal(bool(m["hdr"]))))
        if m.get("col"):
            g.add((iri, DDS.column, URIRef(m["col"])))
        owner = parent if parent is not None else self.doc
        n = self.order.get(owner, 0) + 1
        self.order[owner] = n
        g.add((iri, DDS.hasOrder, Literal(n, datatype=XSD.integer)))
        g.add((owner, DDS.hasComponent if parent is None else DDS.hasChild, iri))
        return iri

    def kind(self, m: Dict[str, Any], default_struct: str) -> Optional[str]:
        st = resolve(m.get("s", default_struct), self.ns.structure, self.ns)
        merged = self.vocab
        return structure_kind(merged, st) or structure_kind(self.g, st)

    def content(self, iri: URIRef, text: str, m: Dict[str, Any]):
        self.g.add((iri, DDS.hasContent, Literal(text, lang=m.get("lang", self.lang))))

    def gen(self, prefix: str) -> str:
        while True:
            self.seq += 1
            cand = f"{prefix}{self.seq}"
            if cand not in self.used:
                self.used.add(cand)
                return cand

    def fresh(self, cand: str) -> str:
        """Positional id for content added by hand; never reuse an existing id."""
        base, n = cand, 1
        while cand in self.used:
            n += 1
            cand = f"{base}-{n}"
        self.used.add(cand)
        return cand


def _read_block(lines: List[str], i: int, split_headings: bool = True) -> Tuple[List[str], int]:
    """Read lines up to a blank line / annotation. A heading line is always its own block
    (when split_headings), so "## Title\nText" yields two blocks."""
    if split_headings and i < len(lines) and HEADING.match(lines[i]):
        return [lines[i]], i + 1
    blk = []
    while i < len(lines) and lines[i].strip() != "" and not ANN.match(lines[i]) and not END.match(lines[i]):
        if split_headings and blk and HEADING.match(lines[i]):
            break
        blk.append(lines[i])
        i += 1
    return blk, i


def parse(md: str, doc_id: Optional[str] = None, design_system: str = "PlanningSystem",
          base: str = "https://example.org/data/", lang: str = "ko", extra: Optional[Graph] = None,
          style_path: Optional[Path] = None) -> Tuple[Graph, URIRef]:
    lines = md.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    head = ANN.match(lines[i]) if i < len(lines) else None
    meta = json.loads(head.group(1)) if head else {}
    if head and "document" in meta:
        i += 1
        b = _Builder(meta["document"], meta.get("design_system", design_system), meta.get("base", base),
                     meta.get("lang", lang))
        annotated = True
    else:
        b = _Builder(doc_id or "document", design_system, base, lang)
        annotated = False
    if extra is not None:
        for t in extra:
            b.vocab.add(t)
    for line in lines:
        mm = ANN.match(line)
        if mm:
            for found in re.findall(r'"id":"((?:[^"\\]|\\.)*)"', mm.group(1)):
                b.used.add(found)
    styles = load_style_map(style_path)
    for t in b.g:  # make the document's DS visible to presentation lookups
        b.vocab.add(t)

    def strip_style(iri: URIRef, text: str) -> str:
        vg = b.vocab
        for t in b.g.triples((iri, None, None)):
            vg.add(t)
        pres, _ = effective_presentation(vg, b.doc, iri)
        return styles.get(token_of(vg, pres)).strip(text)

    # title
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        b.title(HEADING.match(lines[i]).group(2))
        i += 1

    stack: List[Tuple[URIRef, int]] = []  # (section iri, depth)
    pending: Optional[Dict[str, Any]] = None

    def parent() -> Optional[URIRef]:
        return stack[-1][0] if stack else None

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        a, e = ANN.match(line), END.match(line)
        if e:
            if stack:
                stack.pop()
            i += 1
            continue
        if a:
            pending = json.loads(a.group(1))
            i += 1
            if b.kind(pending, "Paragraph") == "Section":
                sec = b.node(pending, parent(), "Section")
                stack.append((sec, len(stack) + 1))
                pending = None
            continue
        m = pending
        pending = None
        kind = b.kind(m, "Paragraph") if m is not None else None
        blk, i = _read_block(lines, i, split_headings=kind in (None, "Heading", "List", "Table"))
        lineno = i - len(blk) + 1
        if m is not None:
            if kind == "Heading":
                hm = HEADING.match(blk[0])
                if not hm:
                    raise ParseError(f"line {lineno}: annotation says Heading ({m.get('id')}) but line is not a heading: {blk[0]!r}")
                node = b.node(m, parent(), "Heading")
                b.content(node, strip_style(node, _inline_decode(hm.group(2))), m)
                if len(blk) > 1:  # defensive: text glued under the heading becomes a new paragraph
                    pn = b.node({"id": b.gen("p")}, parent(), "Paragraph")
                    b.content(pn, "\n".join(blk[1:]), {})
            elif kind == "List":
                node = b.node(m, parent(), "List")
                metas = list(m.get("items", []))
                lid = m.get("id") or b.gen("l")
                for k, ln in enumerate(blk):
                    lm = LIST_ITEM.match(ln)
                    if not lm:
                        raise ParseError(f"line {lineno + k}: expected a list item in list {lid!r}: {ln!r}")
                    im = metas[k] if k < len(metas) else {"id": b.fresh(f"{lid}-i{k + 1}")}
                    it = b.node(im, node, "ListItem")
                    b.content(it, strip_style(it, _inline_decode(lm.group(3))), im)
            elif kind == "Table":
                node = b.node(m, parent(), "Table")
                tid = m.get("id") or b.gen("t")
                rows_meta = list(m.get("rows", []))
                body = [ln for ln in blk if not re.match(r"^\s*\|?\s*:?-{3,}", ln)]
                for r, ln in enumerate(body):
                    if not ln.lstrip().startswith("|"):
                        raise ParseError(f"line {lineno + r}: expected a table row in table {tid!r}: {ln!r}")
                    rm = rows_meta[r] if r < len(rows_meta) else {"id": b.fresh(f"{tid}-r{r + 1}"), "cells": []}
                    row = b.node({k: v for k, v in rm.items() if k != "cells"}, node, "TableRow")
                    rid = rm.get("id") or str(row).rsplit("/", 1)[-1]
                    cmetas = list(rm.get("cells", []))
                    for c, cell in enumerate(_split_row(ln)):
                        cm = cmetas[c] if c < len(cmetas) else {"id": b.fresh(f"{rid}-c{c + 1}")}
                        cn = b.node(cm, row, "TableCell")
                        b.content(cn, strip_style(cn, _inline_decode(cell)), cm)
            else:  # Paragraph and other leaf kinds
                node = b.node(m, parent(), "Paragraph")
                b.content(node, strip_style(node, "\n".join(blk)), m)
            continue
        # ---------------- plain (unannotated) block
        h = HEADING.match(blk[0])
        if h and len(blk) == 1:
            level = len(h.group(1))
            depth = max(1, level - 1)
            if not annotated:
                while stack and stack[-1][1] >= depth:
                    stack.pop()
                sid = b.gen("s")
                sec = b.node({"id": sid}, parent(), "Section")
                stack.append((sec, depth))
                hd = b.node({"id": f"{sid}-h"}, sec, "Heading")
            else:
                hd = b.node({"id": b.gen("h")}, parent(), "Heading")
            b.content(hd, h.group(2), {})
        elif all(LIST_ITEM.match(l) for l in blk):
            ordered = bool(re.match(r"\d", LIST_ITEM.match(blk[0]).group(2)))
            lid = b.gen("l")
            node = b.node({"id": lid, "ordered": ordered}, parent(), "List")
            for k, l in enumerate(blk, 1):
                it = b.node({"id": f"{lid}-i{k}"}, node, "ListItem")
                b.content(it, _inline_decode(LIST_ITEM.match(l).group(3)), {})
        elif all(l.lstrip().startswith("|") for l in blk):
            tid = b.gen("t")
            node = b.node({"id": tid}, parent(), "Table")
            body = [l for l in blk if not re.match(r"^\s*\|?\s*:?-{3,}", l)]
            for r, l in enumerate(body, 1):
                row = b.node({"id": f"{tid}-r{r}"}, node, "TableRow")
                for c, cell in enumerate(_split_row(l), 1):
                    cn = b.node({"id": f"{tid}-r{r}-c{c}"}, row, "TableCell")
                    b.content(cn, _inline_decode(cell), {})
        else:
            node = b.node({"id": b.gen("p")}, parent(), "Paragraph")
            b.content(node, "\n".join(blk), {})
    return b.g, b.doc
