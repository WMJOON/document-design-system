#!/usr/bin/env python3
"""validate — OWL/SHACL validation of DDS ABox files.

Merges ontology/*.ttl (TBox) + instances/design-system.ttl (default DesignSystems)
+ the given files, then runs SHACL Core + SHACL-SPARQL with inference disabled.

Usage:
  python3 validate.py DATA.ttl [MORE.ttl ...] [--no-defaults] [--json] [--lang en|ko]
Exit code: 0 conforms, 1 violations, 2 parse/engine error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dds_lib.graph import format_report, load_data, validate_graph  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="+")
    ap.add_argument("--no-defaults", action="store_true", help="do not merge instances/design-system.ttl")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lang", default="en", help="message language (en|ko)")
    a = ap.parse_args(argv)
    try:
        g = load_data(a.files, with_defaults=not a.no_defaults)
        report = validate_graph(g, lang=a.lang)
    except Exception as e:  # parse errors, broken shapes
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0 if report.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
