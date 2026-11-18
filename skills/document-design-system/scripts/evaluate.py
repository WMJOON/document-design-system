#!/usr/bin/env python3
"""evaluate — per-criterion document evaluation (Structure / Semantic / Presentation).

Runs SHACL plus deterministic pre-checks, then folds in recorded assessments (EARL, see
references/evaluation.md). Every criterion gets Pass / Fail / NeedsReview / NotEvaluated with its
reasons; there is no overall score. Semantic items close only on a HUMAN assessment.

Usage:
  python3 evaluate.py doc.ttl [--assessments review.ttl ...] [--json] [--earl result.ttl]
                      [--date 2026-11-18T00:00:00Z] [--lang ko] [--extra more.ttl]
Exit: 0 no Fail, 1 at least one Fail, 2 error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dds_lib.evaluation import evaluate, format_text, to_earl  # noqa: E402
from dds_lib.graph import load_data  # noqa: E402
from dds_lib.model import documents  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--assessments", type=Path, nargs="*", default=[], help="EARL assessment records")
    ap.add_argument("--extra", type=Path, nargs="*", default=[], help="additional ABox (DesignSystems, Frames)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--earl", type=Path, help="also write the result as EARL Turtle (evaluation history)")
    ap.add_argument("--date", help="evaluation timestamp (default: now, UTC)")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args(argv)
    try:
        g = load_data([a.file, *a.extra, *a.assessments])
        docs = [d for d in documents(g) if (d, None, None) in load_data([a.file], with_defaults=False, with_tbox=False)]
        if len(docs) != 1:
            print(f"error: expected one Document in {a.file}, found {len(docs)}", file=sys.stderr)
            return 2
        ev = evaluate(g, docs[0], date=a.date, lang=a.lang)
    except Exception as e:  # pragma: no cover - CLI guard
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(ev.to_dict(), ensure_ascii=False, indent=2) if a.json else format_text(ev))
    if a.earl:
        to_earl(ev).serialize(destination=str(a.earl), format="turtle")
        print(f"wrote {a.earl}", file=sys.stderr)
    return 1 if any(i.status == "Fail" for i in ev.items.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
