#!/usr/bin/env python3
"""bench — compare the naive reference strategy with the optimized pipeline on the same scenarios.

For every scenario (one edit of a base document, with labelled injected errors):
  naive      whole document, one call per semantic criterion
  optimized  incremental selection + cache (warmed on the base version) + minimal packets
             (+ L2 only when its triggers fire; --force-l2 to run it every time)

Always measured (model independent): calls, input/output tokens, latency, cache hits,
incremental ratio, SELECTION recall (the error's component was inside a packet that was actually
evaluated for the right criterion). Measured only with a real backend: detection recall, false pass
rate, false alarms on clean scenarios, global-critique detection. A scripted backend reports these
as "not measured" because they would measure the script, not a model.

Usage:
  python3 bench.py tests/fixtures/bench/scenarios.yaml --backend scripted [--json out.json] [--md out.md]
  python3 bench.py tests/fixtures/bench/scenarios.yaml --backend openai:http://127.0.0.1:1234/v1#model
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402
from rdflib import Graph  # noqa: E402

from dds_lib import semeval as S  # noqa: E402
from dds_lib.graph import load_data  # noqa: E402
from dds_lib.model import documents  # noqa: E402
from semantic_eval import make_backend  # noqa: E402

DATE = "2026-11-18T00:00:00Z"


class Recording(S.Backend):
    def __init__(self, inner: S.Backend):
        self.inner, self.model, self.log = inner, inner.model, []

    def call(self, packet):
        rep = self.inner.call(packet)
        self.log.append((packet, rep))
        return rep


def _graph(text: str):
    g = load_data([])
    g.parse(data=text, format="turtle")
    return g, documents(Graph().parse(data=text, format="turtle"))[0]


def _apply(base: str, edits) -> str:
    text = base
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f"error: edit target not unique / missing: {old[:40]!r}")
        text = text.replace(old, new)
    return text


def _covers(packet, err) -> bool:
    locus_in = any(m.endswith("/" + err["locus"]) for m in packet.members)
    return locus_in and err["criterion"] in packet.criteria


def _verdict(rep, packet, criterion) -> str:
    d = S.unwrap(rep.data)
    if packet.combined and isinstance(d.get("items"), dict):
        d = S.unwrap(d["items"].get(criterion) or {})
    return str(d.get("verdict", "uncertain")).lower()


def _score(log, errors, real: bool):
    sel = [any(_covers(p, e) for p, _ in log) for e in errors]
    out = {"selection": sel}
    if real:
        out["detected"] = [any(_covers(p, e) and _verdict(r, p, e["criterion"]) == "inconsistent" for p, r in log)
                           for e in errors]
        out["false_alarms"] = sum(1 for p, r in log for c in p.criteria if _verdict(r, p, c) == "inconsistent")
    return out


def bench(spec_path: Path, backend_spec: str, force_l2: bool = False, combined: bool = False):
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    base_text = (spec_path.parent / spec["base"]).read_text(encoding="utf-8")
    real = backend_spec != "scripted"
    rec = Recording(make_backend(backend_spec))
    base_g, base_doc = _graph(base_text)
    warm = S.run(base_g, base_doc, rec, date=DATE, combined=combined)
    cache = S.write_entries(warm.entries)
    rows = []
    for sc in spec["scenarios"]:
        text = _apply(base_text, sc.get("edits", []))
        g, doc = _graph(text)
        errors = sc.get("errors", [])
        row = {"id": sc["id"], "note": sc.get("note", ""), "errors": len(errors)}
        for strategy in ("naive", "optimized"):
            rec.log = []
            if strategy == "naive":
                res = S.run_naive(g, doc, rec, date=DATE)
            else:
                res = S.run(g, doc, rec, prev=base_g, prev_doc=base_doc, cache=copy.deepcopy(cache),
                            has_prior_l2=True, policy=S.L2Policy(force=force_l2), date=DATE, combined=combined)
            m = res.metrics.summary()
            row[strategy] = {k: m[k] for k in ("calls", "input_tokens", "output_tokens", "cache_hits",
                                               "incremental_ratio", "tokens_estimated", "l2_reasons",
                                               "outside_impact_misses")}
            row[strategy]["latency_ms"] = res.metrics.latencies_ms
            row[strategy].update(_score(rec.log, errors, real))
        rows.append(row)
    return {"backend": backend_spec, "model": rec.model, "real_backend": real, "force_l2": force_l2,
            "combined": combined, "warmup": warm.metrics.summary(), "scenarios": rows,
            "totals": _totals(rows, spec, real)}


def _totals(rows, spec, real):
    errs = {sc["id"]: sc.get("errors", []) for sc in spec["scenarios"]}
    out = {}
    for st in ("naive", "optimized"):
        lat = sorted(x for r in rows for x in r[st]["latency_ms"])
        n_err = sum(len(e) for e in errs.values())
        sel = sum(sum(r[st]["selection"]) for r in rows)
        t = {"calls": sum(r[st]["calls"] for r in rows),
             "input_tokens": sum(r[st]["input_tokens"] for r in rows),
             "output_tokens": sum(r[st]["output_tokens"] for r in rows),
             "tokens_estimated": any(r[st]["tokens_estimated"] for r in rows),
             "selection_recall": round(sel / n_err, 3) if n_err else None,
             "p50_latency_ms": round(statistics.median(lat), 1) if lat else None,
             "p95_latency_ms": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1) if lat else None}
        if real:
            crit = [d for r in rows for d in r[st]["detected"]]
            glob = [d for r in rows for d, e in zip(r[st]["detected"], errs[r["id"]]) if e.get("global")]
            clean = [r for r in rows if not errs[r["id"]]]
            t["critical_error_recall"] = round(sum(crit) / len(crit), 3) if crit else None
            t["false_pass_rate"] = round(1 - sum(crit) / len(crit), 3) if crit else None
            t["global_error_detection"] = round(sum(glob) / len(glob), 3) if glob else None
            t["false_alarms_on_clean"] = sum(r[st]["false_alarms"] for r in clean)
        else:
            t["critical_error_recall"] = t["false_pass_rate"] = "not measured (scripted backend)"
        out[st] = t
    return out


def to_markdown(res) -> str:
    L = [f"# Benchmark — backend `{res['backend']}` (model `{res['model']}`)", "",
         f"force L2: {res['force_l2']} · combined: {res['combined']} · "
         f"tokens: {'estimated' if res['totals']['optimized']['tokens_estimated'] else 'reported by backend'}", "",
         f"Warm-up on the base version (optimized, fills the cache): {res['warmup']['calls']} calls, "
         f"{res['warmup']['input_tokens']} input tokens.", "",
         "| scenario | errors | naive calls | naive in-tok | opt calls | opt in-tok | opt cache hits | L2 | selection naive/opt |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in res["scenarios"]:
        n, o = r["naive"], r["optimized"]
        sel = f"{sum(n['selection'])}/{r['errors']} · {sum(o['selection'])}/{r['errors']}" if r["errors"] else "-"
        L.append(f"| {r['id']} | {r['errors']} | {n['calls']} | {n['input_tokens']} | {o['calls']} | "
                 f"{o['input_tokens']} | {o['cache_hits']} | {'yes' if o['l2_reasons'] else 'no'} | {sel} |")
    L += ["", "| totals | naive | optimized |", "|---|---|---|"]
    for k in res["totals"]["naive"]:
        L.append(f"| {k} | {res['totals']['naive'][k]} | {res['totals']['optimized'][k]} |")
    L += ["", "Selection recall: share of injected errors whose component was inside a packet actually evaluated "
          "for the matching criterion. It bounds detection; it is not detection.",
          "Savings are reported only as measured here, for this data. They are not a property of DDS."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", type=Path)
    ap.add_argument("--backend", default="scripted")
    ap.add_argument("--force-l2", action="store_true")
    ap.add_argument("--combined", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args(argv)
    res = bench(a.scenarios, a.backend, a.force_l2, a.combined)
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(res)
    if a.md:
        a.md.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
