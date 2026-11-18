#!/usr/bin/env python3
"""semantic_eval — cost-aware semantic evaluation of one document version (L1 selective, L2 conditional).

L0 (SHACL, deterministic checks) stays in validate.py / evaluate.py and never calls a model.
This tool builds minimal evaluation packets for the components affected by a change, reuses cached
results whose key still matches, calls a backend only on misses, and writes the results as AI EARL
assessments for `evaluate.py --assessments`.

Backends (local runtimes speak the OpenAI-compatible API; no extra dependency):
  omlx:<model> | lmstudio:<model> | ollama:<model> | vllm:<model> | sglang:<model>   [@<base_url>]
      default URLs: omlx/lmstudio :1234, ollama :11434, vllm :8000, sglang :30000 (all /v1);
      or env DDS_<RUNTIME>_URL. The model must be listed by /v1/models (checked before the run).
  openai:<base_url>#<model>    any other OpenAI-compatible server
  command:<shell command>      packet JSON on stdin, JSON on stdout
  agent:<model>                second option, no local runtime: --emit pending packets for a light-model
                               subagent (e.g. haiku), then --replies its answers (see references/semantic-evaluation.md)
  scripted                     dry run: no model (cost / call counting only)

  --list-models                show local servers that answer /v1/models and their models, then exit

Usage:
  python3 semantic_eval.py doc.ttl --backend ollama:qwen3:8b \\
      [--prev old.ttl] [--cache cache.ttl] --out assessments.ttl [--metrics runs.jsonl] \\
      [--strong <backend>] [--l2] [--major] [--high-risk] [--combined] [--prices prices.yaml]
  python3 semantic_eval.py doc.ttl --strategy naive --backend ...     # reference strategy, for comparison

Exit: 0 ok, 2 error, 3 packets pending delegation (agent backend). Model verdicts are opinions; evaluate.py shows them as NeedsReview.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import Graph, Literal, URIRef  # noqa: E402
from rdflib.namespace import XSD  # noqa: E402

from dds_lib.graph import DDS, load_data  # noqa: E402
from dds_lib.incremental import components, diff  # noqa: E402
from dds_lib.model import documents  # noqa: E402
from dds_lib.semeval import AgentBackend, L2Policy, backend_from_spec, discover, run, run_naive, write_entries  # noqa: E402


def make_backend(spec: str, check: bool = False, replies=None):
    try:
        return backend_from_spec(spec, check=check, replies=replies)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"error: {e}")


def _doc(path: Path) -> URIRef:
    docs = documents(Graph().parse(str(path)))
    if len(docs) != 1:
        raise SystemExit(f"error: expected one Document in {path}, found {len(docs)}")
    return docs[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, nargs="?")
    ap.add_argument("--backend")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--probe-url", nargs="*", default=[], help="extra base URLs for --list-models")
    ap.add_argument("--emit", type=Path, help="agent backend: write pending packets (JSONL)")
    ap.add_argument("--replies", type=Path, help="agent backend: read subagent replies (JSONL)")
    ap.add_argument("--strong", help="escalation backend (uncertain / low confidence / high risk) and L2 critic")
    ap.add_argument("--strategy", choices=["optimized", "naive"], default="optimized")
    ap.add_argument("--prev", type=Path, help="previous version of the same document (incremental mode)")
    ap.add_argument("--cache", type=Path, help="EARL cache file (read, then updated)")
    ap.add_argument("--out", type=Path, help="assessments for evaluate.py: only results valid for this version")
    ap.add_argument("--metrics", type=Path, help="append one JSON line of run metrics")
    ap.add_argument("--prices", type=Path, help="YAML {model: {input_per_mtok, output_per_mtok}}")
    ap.add_argument("--extra", type=Path, nargs="*", default=[])
    ap.add_argument("--l2", action="store_true", help="force global critique")
    ap.add_argument("--major", action="store_true", help="caller marks a major document version")
    ap.add_argument("--high-risk", action="store_true", help="caller marks a high-risk decision")
    ap.add_argument("--change-ratio", type=float, default=0.3)
    ap.add_argument("--combined", action="store_true", help="one structured call per packet for several criteria")
    ap.add_argument("--escalate-below", type=float, default=0.7)
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    if a.list_models:
        found = discover(a.probe_url)
        print(json.dumps(found, ensure_ascii=False, indent=2) if found else "no OpenAI-compatible local server answered")
        return 0 if found else 1
    if not a.file or not a.backend:
        ap.error("file and --backend are required")
    for out_path in (a.cache, a.out, a.metrics, a.emit):
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
    replies = None
    if a.replies:
        replies = {}
        for line in a.replies.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                replies[d["packet_id"]] = d

    date = a.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = _doc(a.file)
    g = load_data([a.file, *a.extra])
    light = make_backend(a.backend, check=True, replies=replies)
    strong = make_backend(a.strong, check=True, replies=replies) if a.strong else None
    if a.strategy == "naive":
        res = run_naive(g, doc, light, date=date)
    else:
        cache = Graph().parse(str(a.cache)) if a.cache and a.cache.exists() else Graph()
        since = float(cache.value(doc, DDS.changesSinceGlobal) or 0)
        prior_l2 = cache.value(doc, DDS.lastGlobalCritique) is not None
        prev = prev_doc = None
        if a.prev:
            prev, prev_doc = load_data([a.prev, *a.extra]), _doc(a.prev)
            changed = sum(1 for c in diff(prev, prev_doc, g, doc).values() if c.semantic)
            since += changed / max(1, len(components(g, doc)))
        res = run(g, doc, light, strong, prev=prev, prev_doc=prev_doc, cache=cache,
                  policy=L2Policy(a.change_ratio, a.l2, a.major, a.high_risk), since_l2=since,
                  has_prior_l2=prior_l2, combined=a.combined, escalate_below=a.escalate_below, date=date)
        if a.cache:
            new = write_entries([e for e in res.entries if not any(cache.triples((None, DDS.cacheKey, Literal(e.key))))])
            for t in new:
                cache.add(t)
            cache.remove((doc, DDS.changesSinceGlobal, None))
            if res.metrics.by_stage.get("L2"):   # L2 actually answered (not merely pending delegation)
                cache.set((doc, DDS.lastGlobalCritique, Literal(date, datatype=XSD.dateTime)))
                since = 0.0
            cache.add((doc, DDS.changesSinceGlobal, Literal(round(since, 4), datatype=XSD.decimal)))
            cache.serialize(destination=str(a.cache), format="turtle")
    pend = [p for b in (light, strong) if isinstance(b, AgentBackend) for p in b.pending]
    if a.emit:
        a.emit.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pend), encoding="utf-8")
    m = res.metrics
    if a.prices:
        import yaml
        m.price(yaml.safe_load(a.prices.read_text(encoding="utf-8")) or {}, light.model)
    if a.out:
        write_entries(res.entries).serialize(destination=str(a.out), format="turtle")
    summary = m.summary()
    summary["date"] = date
    summary["limitation"] = res.limitation
    if a.metrics:
        with a.metrics.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if m.pending:
        print(f"{m.pending} packet(s) pending delegation" + (f" -> {a.emit}" if a.emit else ""), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
