# Cost-aware semantic evaluation (L0 / L1 / L2)

Goal: the same evaluation quality at a lower model cost. Models take part only in judgments that
cannot be made deterministically. Savings are measured per dataset (`scripts/bench.py`); none is
promised in advance.

## Layers

| Layer | What | Tool | Model calls |
|---|---|---|---|
| L0 | hierarchy, depth, order, presentation, semantic types, required relations, relation targets, provenance, link existence (traceability) | `validate.py`, `evaluate.py` (SHACL + Python) | never |
| L1 | local meaning for one component: overview fidelity, claim–evidence, premise consistency, concept usage after a premise revision | `semantic_eval.py` | only for affected components whose cache key changed |
| L2 | independent whole-document critique: coverage, counterargument, perspective bias, long-tail, consistency across unlinked parts | `semantic_eval.py` | only when a trigger fires |

## Incremental pipeline

1. **Change detection** (`dds_lib/incremental.py`): previous and current versions are compared by
   component IRI (IRIs are stable). Kinds: added, removed, content, cosmetic, semantic, relation,
   structure, presentation. *Cosmetic* = equal after removing whitespace and punctuation. Edit
   distance is never used to skip a check (one character can flip meaning: negation, numbers).
2. **Impact analysis**: semantic changes propagate backwards along the recorded relations
   (`basedOn`, `supportedBy`, `elaboratedBy`, `counters`, `targets`, `wasRevisionOf`,
   `wasDerivedFrom`), plus the overview (leading content) of every ancestor Section. Structure changes
   only re-check overviews; presentation and cosmetic changes select nothing.
   **Limitation**: only recorded relations are followed. An unrecorded dependency is not found; that is
   what L2 is for. Every run reports this.
3. **Packets** (`dds_lib/packets.py`): stable prefix (instructions, criterion definitions, output
   schema) + variable body (target, premises, grounds, details). No whole document, no unrelated
   Section, except L2. Overview fidelity uses the Section's leading content and the details it leads
   to (no Summary type). L2 bodies exclude prior verdicts (independent reviewer).
4. **Cache** (EARL, `dds_lib/semeval.py`): key = hash of prefix + normalized body (target text,
   premise closure, grounds, details, relation ids, frame, criterion definitions, schema) + rule
   version + prompt version + model route (light|strong) + scope. A change in any premise, evidence,
   criterion definition, model or prompt version changes the key. Cached results are AI EARL
   assessments (`dds:cacheKey`, `dds:packetType`, `dds:promptVersion`, `dds:ruleVersion`,
   `dds:confidence`, model id, uncertainty), so they validate against the assessment shapes.
   `--out` holds only results valid for the current version: stale entries cannot reach
   `evaluate.py`. Packets whose key changed although impact analysis did not select them are counted
   as `outside_impact_misses` (a signal of dependencies outside the graph, e.g. a Frame change).
5. **Routing**: light backend first; escalate to `--strong` on `uncertain`, confidence below
   `--escalate-below` (0.7), or a Decision under `--high-risk`. With one model, no escalation.
6. **L2 triggers** (deterministic): `--l2`, `--major`, `--high-risk` (caller flags, never inferred),
   no previous global critique, a changed Criterion / Scope / DecisionQuestion, or accumulated changes
   since the last L2 ≥ `--change-ratio` (0.3; state kept in the cache file). Cosmetic edits never
   trigger L2. Still-valid L2 results are carried over without a call.
7. **Combined mode** (`--combined`): one structured call for several criteria of one packet (L2).
   Off by default until a real-model comparison shows no detection loss.

## Choosing the judge (who answers the packets)

**First option: a local model on an OpenAI-compatible runtime.** No extra dependency (stdlib HTTP).

| Runtime | Spec | Default base URL (docs / examples) |
|---|---|---|
| oMLX | `omlx:<model>` | `http://127.0.0.1:8000/v1` |
| LM Studio | `lmstudio:<model>` | `http://127.0.0.1:1234/v1` |
| Ollama | `ollama:<model>` (tags such as `qwen3:8b` are fine) | `http://127.0.0.1:11434/v1` |
| vLLM | `vllm:<model>` | `http://127.0.0.1:8000/v1` |
| SGLang | `sglang:<model>` | `http://127.0.0.1:30000/v1` |
| any other | `openai:<base_url>#<model>` | — |

- Override the URL with `<runtime>:<model>@http://host:port/v1` or env `DDS_<RUNTIME>_URL`;
  a key, if the server needs one, via `DDS_LLM_API_KEY`.
- `semantic_eval.py --list-models [--probe-url URL ...]` lists the servers that answer `/v1/models`
  and their models. It reports servers **by URL**: two runtimes share port 8000 by default, so a reply
  does not tell which runtime it is. Offer the listed models to the user as choices.
- The model is checked against `/v1/models` before the run (an id ending in `/<model>` also counts).
  *Listed is not loaded*: on single-model servers, choosing a model that is not resident loads it and
  may unload another one. Prefer the resident model when the server is shared.
- Structured output: `response_format: json_schema` first; if the server rejects it, plain JSON
  instructions for the rest of the run. `<think>` blocks are stripped; replies that echo the schema
  (`{"properties": {...}}`) are unwrapped; unparseable replies become `uncertain`.
- `--strong <spec>` adds an escalation model (uncertain / low confidence / `--high-risk` decisions) and
  the L2 critic. With one model there is no escalation.

**Second option: delegate to a light-model subagent** when no local runtime is available
(`agent:<name>`, e.g. `agent:haiku`; the name is part of the cache key).

1. `semantic_eval.py doc.ttl --backend agent:haiku --cache c.ttl --emit pending.jsonl` writes only the
   cache misses (one JSON per line: `packet_id`, `type`, `criteria`, `prefix`, `body`, `schema`) and
   exits with code 3. Nothing pending is cached.
2. The calling agent gives each line to a light subagent (Claude Code: a subagent on the Haiku model;
   Codex: a mini-class subagent). Send `prefix` + `body` only, ask for JSON matching `schema`, and batch
   several packets per subagent if useful. Use a **fresh** subagent for L2 (`level: L2`) packets, and
   never the session that wrote or revised the document.
3. Write `replies.jsonl` (`{"packet_id", "output": {...}, "model": "<model id>", "usage"?: {...}}`) and
   run again with `--replies replies.jsonl`. Results are cached; the next run delegates only new misses.

`command:<cmd>` (packet JSON on stdin, JSON on stdout) and `scripted` (dry run, no model) remain for
custom judges and cost counting.

## Metrics

Per run (`--metrics` JSONL): components, affected, incremental ratio, packets, calls, escalations,
cache hits / misses / hit rate, input / output / cached tokens (backend-reported, else marked
`tokens_estimated`), tokens per validated component, shared prefix tokens (prompt-caching proxy),
P50 / P95 latency, L2 reasons, cost (only with `--prices`, labelled when based on estimates).

## Benchmark

`scripts/bench.py SCENARIOS --backend …` compares the **naive reference strategy** (whole document,
one call per semantic criterion, every run; defined for comparison, not a former DDS behaviour) with
the optimized pipeline on the same edits. Selection recall (was the error's component inside a packet
evaluated for that criterion) is model independent. Detection recall, false pass rate, false alarms
and global-error detection are measured only with a real backend.

## Not claimed

Completeness of selective evaluation; accuracy of any model; a fixed saving; lossless combined
evaluation. Model verdicts remain opinions (NeedsReview in `evaluate.py`).
