#!/usr/bin/env python3
"""compare — per-criterion comparison of evaluation results (Frame evolution, regression).

Inputs are EARL files written by `evaluate.py --earl`. With two files: before -> after. With
--history DIR: every *.ttl in DIR in date order, each compared with the previous one.

Usage:
  python3 compare.py before.ttl after.ttl [--json]
  python3 compare.py --history evaluations/search-tool-decision/
Exit: 0 no change, 1 at least one criterion changed, 2 error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import Graph  # noqa: E402

from dds_lib.evaluation import compare, format_comparison, from_earl  # noqa: E402


def _load(p: Path):
    res = from_earl(Graph().parse(str(p)))
    if not res:
        raise SystemExit(f"error: {p} holds no evaluate.py result")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="*")
    ap.add_argument("--history", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.history:
        runs = sorted((_load(p) for p in a.history.glob("*.ttl")),
                      key=lambda r: next(iter(r.values()))["date"])
    elif len(a.files) == 2:
        runs = [_load(p) for p in a.files]
    else:
        ap.error("give two result files or --history DIR")
        return 2
    if len(runs) < 2:
        print("error: need at least two evaluation results", file=sys.stderr)
        return 2
    changed, out = False, []
    for before, after in zip(runs, runs[1:]):
        rows = compare(before, after)
        changed |= any(r["changed"] for r in rows)
        out.append(rows if a.json else format_comparison(rows, before, after))
    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else "\n\n".join(out))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
