#!/usr/bin/env python3
"""export — serialise DDS graphs to Turtle, JSON-LD, N-Triples or RDF/XML.

Usage:
  python3 export.py DATA.ttl [MORE.ttl ...] -f json-ld [-o OUT] [--with-tbox] [--with-defaults]
                    [--no-validate]
By default only the given ABox files are exported (validated together with TBox + defaults).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dds_lib.graph import format_report, load_data, validate_graph  # noqa: E402

FORMATS = {"turtle": "turtle", "ttl": "turtle", "json-ld": "json-ld", "jsonld": "json-ld",
           "nt": "nt", "ntriples": "nt", "xml": "xml", "rdfxml": "xml"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="+")
    ap.add_argument("-f", "--format", default="turtle", choices=sorted(FORMATS))
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--with-tbox", action="store_true", help="include ontology/*.ttl")
    ap.add_argument("--with-defaults", action="store_true", help="include instances/design-system.ttl")
    ap.add_argument("--no-validate", action="store_true")
    a = ap.parse_args(argv)

    if not a.no_validate:
        report = validate_graph(load_data(a.files))
        if not report.conforms:
            print(format_report(report), file=sys.stderr)
            print("refusing to export a non-conforming graph (use --no-validate)", file=sys.stderr)
            return 1
    g = load_data(a.files, with_defaults=a.with_defaults, with_tbox=a.with_tbox)
    fmt = FORMATS[a.format]
    kw = {"auto_compact": True} if fmt == "json-ld" else {}
    data = g.serialize(format=fmt, **kw)
    if a.output:
        a.output.write_text(data, encoding="utf-8")
        print(f"wrote {a.output} ({len(g)} triples, {fmt})", file=sys.stderr)
    else:
        sys.stdout.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
