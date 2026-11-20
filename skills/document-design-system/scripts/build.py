#!/usr/bin/env python3
"""build — source TTL -> materialise -> SHACL -> Markdown, in one process.

Usage:
  python3 build.py DOC.ttl [--extra DATA.ttl ...] [-o OUT.md] [--emit FULL.ttl]
                   [--annotate] [--lang ko] [--json] [--force]

DOC.ttl is the authoring form (dds:children / dds:rows / dds:items) or the expanded form.
--extra: glossary data, table/section kinds, views, custom DesignSystems.
Exit codes: 0 ok, 1 SHACL violations, 2 source/compose error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import Graph  # noqa: E402

from dds_lib.compose import ComposeError  # noqa: E402
from dds_lib.graph import format_report, merge, validate_graph  # noqa: E402
from dds_lib.markdown import render  # noqa: E402
from dds_lib.materialize import is_source, materialize  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path)
    ap.add_argument("--extra", type=Path, nargs="*", default=[])
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--emit", type=Path, help="also write the materialised (expanded) Turtle")
    ap.add_argument("--annotate", action="store_true", help="keep <!-- dds --> round-trip comments")
    ap.add_argument("--lang", default="ko", help="validation message language")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="render even if SHACL fails")
    a = ap.parse_args(argv)

    extra = Graph()
    for p in a.extra:
        extra.parse(str(p), format="turtle")
    src = Graph().parse(str(a.doc), format="turtle")
    vocab = merge(src, extra)
    try:
        if is_source(src):
            full, doc = materialize(src, vocab)
        else:
            from dds_lib.model import documents
            full, doc = src, documents(src)[0]
    except ComposeError as e:
        print(f"build error: {e}", file=sys.stderr)
        return 2
    if a.emit:
        a.emit.write_text(full.serialize(format="turtle"), encoding="utf-8")
    report = validate_graph(merge(full, extra), lang=a.lang)
    if a.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(format_report(report), file=sys.stderr)
    if not report.conforms and not a.force:
        return 1
    md = render(merge(full, extra), doc, annotate=a.annotate)
    if a.output:
        a.output.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 0 if report.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
