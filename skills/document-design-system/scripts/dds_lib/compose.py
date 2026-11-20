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
    def __init__(self, ns: DataNS, lang: str, doc_id: str, vocab: Optional[Graph] = None):
        self.ns, self.lang, self.doc_id = ns, lang, doc_id
        self.g = bind_prefixes(Graph(bind_namespaces="core"), ns)
        self.seen: Dict[str, str] = {}
        self.generated: List[str] = []
        self.vocab = vocab if vocab is not None else Graph()
        self.design_system: Optional[URIRef] = None
        self._notation_index: Optional[Dict[str, List[URIRef]]] = None

    # -- typed tables ------------------------------------------------------
    def _pick_literal(self, values) -> Optional[str]:
        lits = [v for v in values if isinstance(v, Literal)]
        for want in (self.lang, None):
            for v in lits:
                if (v.language or None) == want:
                    return str(v)
        return str(lits[0]) if lits else None

    def _subject(self, ref, where: str) -> URIRef:
        ref = str(ref)
        if "://" in ref:
            if (URIRef(ref), None, None) not in self.vocab:
                raise ComposeError(f"row subject {ref!r} at {where}: no IRI/curie/skos:notation match in --extra data")
            return URIRef(ref)
        if ":" in ref:
            pfx, local = ref.split(":", 1)
            for p, ns_iri in self.vocab.namespaces():
                if p == pfx:
                    cand = URIRef(str(ns_iri) + local)
                    if (cand, None, None) in self.vocab:
                        return cand
        if self._notation_index is None:
            idx: Dict[str, List[URIRef]] = {}
            for s, o in self.vocab.subject_objects(SKOS.notation):
                idx.setdefault(str(o), []).append(s)
            self._notation_index = idx
        hits = sorted(set(self._notation_index.get(ref, [])))
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ComposeError(f"row subject {ref!r} at {where}: no IRI/curie/skos:notation match in --extra data")
        raise ComposeError(f"row subject {ref!r} at {where}: ambiguous notation {[str(h) for h in hits]}; use a curie or IRI")

    def _columns(self, kind: URIRef, where: str) -> List[URIRef]:
        uses = list(self.vocab.objects(kind, DDS.hasColumnUse))
        if not uses:
            raise ComposeError(f"table kind {kind} at {where} is unknown or has no columns (load it with --extra)")
        uses.sort(key=lambda u: int(self.vocab.value(u, DDS.columnOrder) or 0))
        return [self.vocab.value(u, DDS.column) for u in uses]

    def _view(self, kind: URIRef, name, where: str) -> Optional[URIRef]:
        """Named view from the spec, else the DesignSystem's default view for this kind, else None (all columns)."""
        v = self.vocab
        if name:
            view = resolve(name, self.ns.design, self.ns)
            if v.value(view, DDS.forTableKind) != kind:
                raise ComposeError(f"view {view} at {where}: unknown or not defined for table kind {kind}")
            return view
        if self.design_system is not None:
            for dv in v.objects(self.design_system, DDS.hasDefaultView):
                if v.value(dv, DDS.forTableKind) == kind:
                    return dv
        return None

    def _header_text(self, col: URIRef, overrides: Dict[str, str]) -> str:
        key = str(self.vocab.value(col, DDS.columnKey) or "")
        if key in overrides:
            return str(overrides[key])
        if self.design_system is not None:
            for lab in self.vocab.objects(self.design_system, DDS.hasColumnLabel):
                if self.vocab.value(lab, DDS.forColumn) == col:
                    t = self._pick_literal(self.vocab.objects(lab, SKOS.prefLabel))
                    if t:
                        return t
        return self._pick_literal(self.vocab.objects(col, SKOS.prefLabel)) or key

    def _cell_value(self, subj: URIRef, col: URIRef) -> str:
        kind = str(self.vocab.value(col, DDS.valueKind) or "text")
        for prop in self.vocab.objects(col, DDS.valueProperty):
            vals = list(self.vocab.objects(subj, prop))
            if not vals:
                continue
            out = []
            for v in vals:
                if isinstance(v, URIRef):
                    p = SKOS.notation if kind == "notation" else SKOS.prefLabel
                    out.append(self._pick_literal(self.vocab.objects(v, p)) or str(v).rsplit("/", 1)[-1].rsplit("#", 1)[-1])
                else:
                    out.append(v)
            if all(isinstance(v, Literal) for v in out):
                return self._pick_literal(out) or ""
            return ", ".join(str(v) for v in out)
        return ""

    def typed_table(self, node: URIRef, spec: Dict[str, Any], cid: str, where: str) -> int:
        g = self.g
        kind = resolve(spec["kind"], self.ns.design, self.ns)
        g.add((node, DDS.tableKind, kind))
        cols = self._columns(kind, where)
        keys = [str(self.vocab.value(c, DDS.columnKey) or "") for c in cols]
        if spec.get("columns") or spec.get("headers"):
            raise ComposeError(f"table at {where}: 'columns'/'headers' are not allowed on a component; "
                               "define a dds:TableView (column choice and order) and select it with 'view'")
        view = self._view(kind, spec.get("view"), where)
        if view is not None:
            g.add((node, DDS.tableView, view))
            pick = str(self.vocab.value(view, DDS.viewColumns) or "").split()
            unknown = [k for k in pick if k not in keys]
            if unknown or not pick:
                raise ComposeError(f"view {view} at {where}: columns {unknown or pick} not in table kind ({keys})")
            pos = [keys.index(k) for k in pick]
            if pos != sorted(pos) or len(set(pos)) != len(pos):
                raise ComposeError(f"view {view} at {where}: columns {pick} must follow the kind's order {keys}")
            cols = [cols[i] for i in pos]
            keys = pick
        overrides: Dict[str, str] = {}
        n = 1
        hnode = self._iri(f"{cid}-r0", f"{where}.header")
        g.add((node, DDS.hasChild, hnode))
        g.add((hnode, DDS.hasStructure, self.ns.structure.TableRow))
        g.add((hnode, DDS.headerRow, Literal(True)))
        self._common(hnode, {}, n)
        for c, col in enumerate(cols, 1):
            cell = self._leaf(hnode, {"content": self._header_text(col, overrides)}, f"{cid}-r0-c{c}", "TableCell", c,
                              f"{where}.header[{c}]")
            g.add((cell, DDS.column, col))
        for r, row in enumerate(_as_list(spec.get("rows")), 1):
            n += 1
            rd = row if isinstance(row, dict) else {"about": row}
            given = rd.get("cells") or {}
            bad = [k for k in given if k not in keys]
            if bad:
                raise ComposeError(f"rows[{r}].cells at {where}: unknown column key(s) {bad} (kind has {keys})")
            subj = self._subject(rd["about"], f"{where}.rows[{r}]") if rd.get("about") is not None else None
            if subj is None and len(given) < len(keys):
                raise ComposeError(f"rows[{r}] at {where}: needs 'about' or a value for every column")
            rid = rd.get("id") or f"{cid}-r{r}"
            rnode = self._iri(rid, f"{where}.rows[{r}]")
            g.add((node, DDS.hasChild, rnode))
            g.add((rnode, DDS.hasStructure, self.ns.structure.TableRow))
            if subj is not None:
                g.add((rnode, DDS.about, subj))
            self._common(rnode, {k: v for k, v in rd.items() if k in ("semantic", "presentation")}, n)
            for c, (col, key) in enumerate(zip(cols, keys), 1):
                val = given[key] if key in given else self._cell_value(subj, col)
                cell = self._leaf(rnode, {"content": val} if not isinstance(val, dict) else val,
                                  f"{rid}-c{c}", "TableCell", c, f"{where}.rows[{r}].cells[{c}]")
                g.add((cell, DDS.column, col))
        return n

    # -- kinded sections (v0.3) ----------------------------------------------
    def _is_section(self, structure) -> bool:
        return resolve(structure, self.ns.structure, self.ns) == self.ns.structure.Section

    def kinded_section(self, node: URIRef, spec: Dict[str, Any], cid: str, where: str):
        g, v = self.g, self.vocab
        kind = resolve(spec["kind"], self.ns.design, self.ns)
        slots = list(v.objects(kind, DDS.hasSlot))
        if not slots:
            raise ComposeError(f"section kind {kind} at {where} is unknown or has no slots (load it with --extra)")
        slots.sort(key=lambda s: int(v.value(s, DDS.slotOrder) or 0))
        g.add((node, DDS.sectionKind, kind))
        if spec.get("about") is None:
            raise ComposeError(f"kinded section at {where} needs 'about' (the resource it is about)")
        subj = self._subject(spec["about"], where)
        g.add((node, DDS.about, subj))
        label = self._pick_literal(v.objects(subj, SKOS.prefLabel)) or str(spec["about"])
        allowed = {str(v.value(s, DDS.slotKey)) for s in slots} | {"id", "structure", "kind", "about", "title",
                                                                   "semantic", "presentation"}
        extra = [k for k in spec if k not in allowed]
        if extra:
            raise ComposeError(f"kinded section at {where}: unknown key(s) {extra}; slots are "
                               f"{[str(v.value(s, DDS.slotKey)) for s in slots]}")
        n = 0
        for s in slots:
            key = str(v.value(s, DDS.slotKey))
            st = v.value(s, DDS.slotStructure)
            st_local = str(st).rsplit("/", 1)[-1]
            required = bool(v.value(s, DDS.slotRequired) is not None and v.value(s, DDS.slotRequired).toPython())
            multiple = bool(v.value(s, DDS.slotMultiple) is not None and v.value(s, DDS.slotMultiple).toPython())
            given = spec.get(key)
            if st_local == "Heading":
                pat = self._pick_literal(v.objects(kind, DDS.headingPattern)) or "{label}"
                given = spec.get("title") or pat.replace("{label}", label)
            elif st_local == "Paragraph" and given is None:
                for prop in v.objects(s, DDS.fillProperty):
                    given = self._pick_literal(v.objects(subj, prop))
                    if given:
                        break
            if given in (None, "", []):
                if required:
                    raise ComposeError(f"kinded section at {where}: required slot '{key}' is empty")
                continue
            for i, part in enumerate(_as_list(given) if multiple else [given], 1):
                n += 1
                child_id = f"{cid}-{key}" if not multiple else f"{cid}-{key}{i}"
                if isinstance(part, dict) and st_local != "Table":  # full component (e.g. from source TTL)
                    child = dict(part, id=part.get("id", child_id), structure=st_local)
                elif st_local in ("Heading", "Paragraph"):
                    child = {"id": child_id, "structure": st_local, "content": part}
                    if st_local == "Paragraph" and key == "description":
                        child["semantic"] = "Description"
                elif st_local == "List":
                    child = {"id": child_id, "structure": "List", "items": part}
                elif st_local == "Table":
                    child = dict(part, id=part.get("id", child_id), structure="Table")
                    tk = v.value(s, DDS.slotTableKind)
                    if tk is not None:
                        child.setdefault("kind", str(tk))
                else:
                    child = dict(part, id=part.get("id", child_id), structure=st_local)
                cnode = self.component(child, n, f"{where}.{key}")
                g.add((node, DDS.hasChild, cnode))
                g.add((cnode, DDS.fillsSlot, Literal(key)))

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

        if spec.get("kind") and self._is_section(spec["structure"]):  # kinded section (v0.3)
            self.kinded_section(node, spec, cid, where)
            return node
        n = 0
        for i, item in enumerate(_as_list(spec.get("items")), 1):  # List shorthand
            n += 1
            self._leaf(node, item, f"{cid}-i{i}", "ListItem", n, f"{where}.items[{i}]")
        if spec.get("kind"):  # typed table: header + rows filled from --extra data
            n = self.typed_table(node, spec, cid, where)
        for r, row in enumerate([] if spec.get("kind") else _as_list(spec.get("rows")), 1):  # Table shorthand
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


def compose(spec: Dict[str, Any], base: Optional[str] = None, lang: Optional[str] = None,
            vocab: Optional[Graph] = None) -> Tuple[Graph, URIRef, List[str]]:
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
    c = Composer(ns, lang, doc_id, vocab)
    doc = ns.doc_iri(doc_id)
    g = c.g
    g.add((doc, RDF.type, DDS.Document))
    if d.get("title"):
        g.add((doc, SKOS.prefLabel, c._text(d["title"])))
    if not d.get("design_system"):
        raise ComposeError("document.design_system is required")
    c.design_system = resolve(d["design_system"], ns.design, ns)
    g.add((doc, DDS.usesDesignSystem, c.design_system))
    for i, comp in enumerate(_as_list(d.get("components")), 1):
        g.add((doc, DDS.hasComponent, c.component(comp, i, f"components[{i}]")))
    return g, doc, c.generated
