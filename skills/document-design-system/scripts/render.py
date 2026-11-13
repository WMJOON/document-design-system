#!/usr/bin/env python3
"""render — DDS ABox -> Markdown.

Validates first (SHACL); refuses to render a non-conforming graph unless --force.

Usage:
  python3 render.py DATA.ttl [-o OUT.md] [--doc IRI] [--no-annotate] [--extra DS.ttl ...]
                    [--style config/presentation-markdown.yaml] [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import URIRef  # noqa: E402

from dds_lib.graph import format_report, load_data, validate_graph  # noqa: E402
from dds_lib.markdown import render  # noqa: E402
from dds_lib.model import documents  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="+")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--doc", help="Document IRI (required if the graph holds several)")
    ap.add_argument("--no-annotate", action="store_true", help="omit <!-- dds --> round-trip comments")
    ap.add_argument("--style", type=Path, help="Presentation->Markdown mapping YAML")
    ap.add_argument("--force", action="store_true", help="render even if SHACL validation fails")
    a = ap.parse_args(argv)

    g = load_data(a.files)
    report = validate_graph(g)
    if not report.conforms:
        print(format_report(report), file=sys.stderr)
        if not a.force:
            print("refusing to render a non-conforming document (use --force)", file=sys.stderr)
            return 1
    docs = [URIRef(a.doc)] if a.doc else documents(g)
    if len(docs) != 1:
        print(f"error: {len(docs)} documents found; pass --doc IRI. Candidates: {[str(d) for d in docs]}", file=sys.stderr)
        return 2
    md = render(g, docs[0], annotate=not a.no_annotate, style_path=a.style)
    if a.output:
        a.output.write_text(md, encoding="utf-8")
        print(f"wrote {a.output}", file=sys.stderr)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
