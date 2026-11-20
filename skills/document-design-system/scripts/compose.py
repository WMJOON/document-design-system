#!/usr/bin/env python3
"""compose — YAML document spec -> DDS ABox (Turtle), then SHACL-validate.

Usage:
  python3 compose.py SPEC.yaml -o OUT.ttl [--base IRI] [--lang ko] [--extra DS.ttl ...]
                     [--write-ids] [--no-validate] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402
from rdflib import Graph  # noqa: E402

from dds_lib.compose import ComposeError, compose  # noqa: E402
from dds_lib.graph import format_report, merge, validate_graph  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output Turtle (default: stdout)")
    ap.add_argument("--base", help="ABox base IRI (default: spec 'base' or https://example.org/data/)")
    ap.add_argument("--lang", help="default language tag for content (default: spec 'lang' or ko)")
    ap.add_argument("--extra", type=Path, nargs="*", default=[], help="extra TTL (e.g. custom DesignSystems)")
    ap.add_argument("--write-ids", action="store_true", help="persist generated component ids back into SPEC")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the validation report as JSON")
    a = ap.parse_args(argv)

    spec = yaml.safe_load(a.spec.read_text(encoding="utf-8"))
    extra = Graph()
    for p in a.extra:
        extra.parse(str(p), format="turtle")
    vocab = merge(extra)  # defaults + TBox + extra: table kinds, column labels, row subjects
    try:
        g, doc, generated = compose(spec, base=a.base, lang=a.lang, vocab=vocab)
    except ComposeError as e:
        print(f"compose error: {e}", file=sys.stderr)
        return 2

    ttl = g.serialize(format="turtle")
    if a.output:
        a.output.write_text(ttl, encoding="utf-8")
        print(f"wrote {a.output} ({len(g)} triples, document {doc})", file=sys.stderr)
    else:
        sys.stdout.write(ttl)

    if generated:
        if a.write_ids:
            a.spec.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(f"persisted {len(generated)} generated id(s) into {a.spec}", file=sys.stderr)
        else:
            print(f"warning: generated {len(generated)} component id(s) {generated}; they change on every run. "
                  "Add explicit ids or re-run with --write-ids to keep IRIs stable.", file=sys.stderr)

    if a.no_validate:
        return 0
    report = validate_graph(merge(g, extra))
    if a.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(format_report(report), file=sys.stderr)
    return 0 if report.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
