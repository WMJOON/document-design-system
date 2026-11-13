#!/usr/bin/env python3
"""parse — Markdown -> DDS ABox (Turtle), then SHACL-validate.

Annotated Markdown (written by render.py) restores component IRIs, hierarchy, order,
Semantic and explicit Presentation. Plain Markdown is parsed structurally
(heading -> Section at depth level-1, paragraphs, lists, tables) with positional ids.

Usage:
  python3 parse.py DOC.md -o OUT.ttl [--doc-id ID] [--design-system PlanningSystem]
                   [--base IRI] [--lang ko] [--extra DS.ttl ...] [--no-validate] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import Graph  # noqa: E402

from dds_lib.graph import format_report, merge, validate_graph  # noqa: E402
from dds_lib.markdown import ParseError, parse  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--doc-id", help="document id for plain Markdown (default: file stem)")
    ap.add_argument("--design-system", default="PlanningSystem")
    ap.add_argument("--base", default="https://example.org/data/")
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--extra", type=Path, nargs="*", default=[])
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    extra = Graph()
    for p in a.extra:
        extra.parse(str(p), format="turtle")
    doc_id = a.doc_id or re.sub(r"[^A-Za-z0-9._-]+", "-", a.markdown.stem).strip("-") or "document"
    try:
        g, doc = parse(a.markdown.read_text(encoding="utf-8"), doc_id=doc_id, design_system=a.design_system,
                       base=a.base, lang=a.lang, extra=extra)
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 2
    ttl = g.serialize(format="turtle")
    if a.output:
        a.output.write_text(ttl, encoding="utf-8")
        print(f"wrote {a.output} ({len(g)} triples, document {doc})", file=sys.stderr)
    else:
        sys.stdout.write(ttl)
    if a.no_validate:
        return 0
    report = validate_graph(merge(g, extra))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if a.json else format_report(report),
          file=sys.stderr)
    return 0 if report.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
