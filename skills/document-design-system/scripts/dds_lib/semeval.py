"""Cost-aware semantic evaluation: L0 -> selective L1 -> conditional L2, with an EARL-backed cache.

Pipeline (one document version):
  change detection (vs previous version) -> impact analysis -> L1 packets for the affected scope
  -> cache lookup (key = packet content + rule / prompt version + model + scope) -> backend calls
  only on misses -> routing (light model, escalate when uncertain / low confidence / high risk)
  -> conditional L2 global critique -> AI EARL assessments + run metrics.

Results are AI opinions: written as EARL assertions with model id and uncertainty, so evaluate.py
shows them as NeedsReview with their basis and never as verdicts.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD

from . import __version__ as RULE_VERSION
from .evaluation import OUTCOME
from .graph import DDS, EARL, DataNS, bind_prefixes
from .incremental import Change, components, diff, impact, sha
from .packets import PROMPT_VERSION, Packet, build_l1, build_l2, build_naive, estimate_tokens

VERDICT_STATUS = {"consistent": "Pass", "inconsistent": "Fail", "uncertain": "NeedsReview"}


# ============================================================================ backends
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = True
    latency_ms: float = 0.0


@dataclass
class Reply:
    data: dict
    usage: Usage
    model: str
    pending: bool = False   # delegated packet without a reply yet: never cached, never reported


class AgentBackend:
    """Second option when no local runtime is available: delegate packets to a light-model subagent
    (e.g. Claude Haiku in Claude Code, a mini/Luna-class model in Codex) through files.

      phase 1  --backend agent:<model> --emit pending.jsonl   -> cache misses are written, nothing is cached
      phase 2  the calling agent hands each line (prefix + body + schema) to a fresh light subagent and
               writes replies.jsonl: {"packet_id", "output": {verdict...}, "usage"?: {...}, "model"?: "..."}
      phase 3  --backend agent:<model> --replies replies.jsonl -> replies are cached and reported
    <model> names the delegate (it is part of the cache key). Use a different, fresh subagent for L2
    packets (independent critique) and never the session that wrote the document."""

    def __init__(self, model: str, replies: Optional[Dict[str, dict]] = None):
        self.model = "agent:" + model
        self.replies = replies or {}
        self.pending: List[dict] = []

    def call(self, packet: Packet) -> "Reply":
        pid = packet_id(packet)
        rep = self.replies.get(pid)
        if rep is None:
            self.pending.append(dict(packet.to_json(), packet_id=pid))
            return Reply({"verdict": "uncertain", "confidence": 0.0, "rationale": "pending delegation"},
                         Usage(0, 0, 0, True, 0.0), self.model, pending=True)
        u = rep.get("usage") or {}
        usage = Usage(u.get("input_tokens", packet.tokens), u.get("output_tokens", 0), u.get("cached_tokens", 0),
                      estimated="input_tokens" not in u, latency_ms=float(u.get("latency_ms", 0)))
        out = rep.get("output", rep)
        return Reply(out if isinstance(out, dict) else parse_json(str(out)), usage, rep.get("model", self.model))


def packet_id(packet: Packet) -> str:
    return sha(packet.type, ",".join(packet.criteria), packet.subject, packet.content_hash)


class Backend:
    model: str = "unknown"

    def call(self, packet: Packet) -> Reply:  # pragma: no cover - interface
        raise NotImplementedError


class ScriptedBackend(Backend):
    """Deterministic backend for tests and pipeline benchmarks. `rule(packet) -> verdict dict`.
    Its verdicts measure the script, not a model: never report detection quality from it."""

    def __init__(self, rule: Callable[[Packet], dict], model: str = "scripted"):
        self.rule, self.model, self.calls = rule, model, []

    def call(self, packet: Packet) -> Reply:
        self.calls.append(packet)
        data = self.rule(packet)
        out = json.dumps(data)
        return Reply(data, Usage(packet.tokens, estimate_tokens(out), 0, True, 0.0), self.model)


def parse_json(text: str) -> dict:
    """First JSON object in a model reply (models often wrap JSON in prose or code fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))


class CommandBackend(Backend):
    """Runs an external command: packet JSON on stdin, JSON on stdout
    ({"output": {...verdict...}, "usage": {"input_tokens":..,"output_tokens":..}, "model": "..."})."""

    def __init__(self, cmd: List[str], model: str = "command", timeout: int = 300):
        self.cmd, self.model, self.timeout = cmd, model, timeout

    def call(self, packet: Packet) -> Reply:
        t0 = time.perf_counter()
        p = subprocess.run(self.cmd, input=json.dumps(packet.to_json(), ensure_ascii=False), text=True,
                           capture_output=True, timeout=self.timeout, check=True)
        res = json.loads(p.stdout)
        u = res.get("usage") or {}
        usage = Usage(u.get("input_tokens", packet.tokens), u.get("output_tokens", 0), u.get("cached_tokens", 0),
                      estimated="input_tokens" not in u, latency_ms=(time.perf_counter() - t0) * 1000)
        out = res.get("output", res)
        return Reply(out if isinstance(out, dict) else parse_json(str(out)), usage, res.get("model", self.model))


# Local OpenAI-compatible runtimes. Every one serves /v1/chat/completions and /v1/models.
# Base URL: `@url` in the spec > env DDS_<RUNTIME>_URL > this default.
# Defaults follow each project's documentation / examples; servers are often run on other ports,
# so set `@url` or DDS_<RUNTIME>_URL. Two runtimes can share a default port: a URL that answers is
# reported by URL, never assumed to be a particular runtime.
RUNTIMES = {
    "omlx": "http://127.0.0.1:8000/v1",      # oMLX README (brew service default)
    "lmstudio": "http://127.0.0.1:1234/v1",  # LM Studio docs examples
    "ollama": "http://127.0.0.1:11434/v1",   # Ollama OpenAI-compatible endpoint
    "vllm": "http://127.0.0.1:8000/v1",      # vLLM `vllm serve` examples
    "sglang": "http://127.0.0.1:30000/v1",   # SGLang examples
}
THINK = re.compile(r"<think>.*?</think>", re.S)


class OpenAIHTTPBackend(Backend):
    """OpenAI-compatible chat completions over HTTP (stdlib only).

    - prefix -> system message, body -> user message, so servers with prefix caching reuse the shared part
    - structured output: asks for response_format json_schema; if the server rejects it (HTTP 400/404/415/422/
      500 on the first call), falls back to plain JSON instructions for the rest of the run
    - reported token usage is used when present (cached tokens from prompt_tokens_details)
    - reasoning blocks (<think>...</think>) are stripped before parsing
    """

    def __init__(self, base_url: str, model: str, runtime: str = "openai", timeout: int = 600,
                 max_tokens: int = 800, structured: bool = True, api_key: Optional[str] = None):
        self.base = base_url.rstrip("/")
        self.url = self.base + "/chat/completions"
        self.model, self.runtime, self.timeout, self.max_tokens = model, runtime, timeout, max_tokens
        self.structured, self.api_key = structured, api_key

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def models(self) -> List[str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        req = urllib.request.Request(self.base + "/models", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return [m.get("id") for m in json.loads(r.read().decode("utf-8")).get("data", [])]

    def check(self) -> None:
        """Fail early with the available model ids when the model is not served."""
        try:
            ids = self.models()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{self.runtime}: cannot reach {self.base}/models ({e})") from e
        if self.model not in ids and not any(str(i).endswith("/" + self.model) for i in ids):
            raise RuntimeError(f"{self.runtime}: model {self.model!r} not served at {self.base}; available: {ids}")

    def call(self, packet: Packet) -> Reply:
        from .packets import output_schema
        payload = {"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                   "messages": [{"role": "system", "content": packet.prefix},
                                {"role": "user", "content": packet.body}]}
        t0 = time.perf_counter()
        res = None
        if self.structured:
            sp = dict(payload, response_format={"type": "json_schema", "json_schema": {
                "name": "dds_verdict", "schema": output_schema(packet.criteria, packet.combined)}})
            try:
                res = self._post(sp)
            except urllib.error.HTTPError as e:
                if e.code not in (400, 404, 415, 422, 500):
                    raise
                self.structured = False  # server does not accept json_schema: plain JSON from now on
        if res is None:
            res = self._post(payload)
        latency = (time.perf_counter() - t0) * 1000
        msg = res["choices"][0]["message"]
        text = THINK.sub("", msg.get("content") or "")
        u = res.get("usage") or {}
        cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        usage = Usage(u.get("prompt_tokens", packet.tokens), u.get("completion_tokens", estimate_tokens(text)),
                      cached, estimated="prompt_tokens" not in u, latency_ms=latency)
        try:
            data = parse_json(text)
        except (ValueError, json.JSONDecodeError):
            data = {"verdict": "uncertain", "confidence": 0.0, "rationale": "unparseable reply: " + text[:200]}
        return Reply(data, usage, res.get("model", self.model))


def discover(extra_urls: Optional[List[str]] = None, timeout: float = 2.0) -> List[dict]:
    """Probe the default and configured runtime URLs; return the servers that answer /v1/models."""
    import os
    urls: Dict[str, List[str]] = {}
    for rt, url in RUNTIMES.items():
        urls.setdefault(os.environ.get(f"DDS_{rt.upper()}_URL") or url, []).append(rt)
    for u in extra_urls or []:
        urls.setdefault(u.rstrip("/"), [])
    found = []
    for url, rts in urls.items():
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/models", timeout=timeout) as r:
                ids = [m.get("id") for m in json.loads(r.read().decode("utf-8")).get("data", [])]
        except Exception:  # noqa: BLE001 - nothing listening, not OpenAI-compatible, or auth required
            continue
        found.append({"url": url, "default_port_of": rts, "models": ids})
    return found


def backend_from_spec(spec: str, check: bool = False, replies: Optional[Dict[str, dict]] = None) -> Backend:
    """`scripted` | `command:<cmd>` | `openai:<base_url>#<model>` |
    `<runtime>:<model>[@<base_url>]` with runtime in omlx, lmstudio, ollama, vllm, sglang.
    Model ids may contain ':' (Ollama tags). API key, if the server needs one: env DDS_LLM_API_KEY."""
    import os
    import shlex
    if spec == "scripted":
        return ScriptedBackend(lambda p: {"verdict": "consistent", "confidence": 0.9, "rationale": "dry run"},
                               model="scripted-dry-run")
    if spec.startswith("command:"):
        return CommandBackend(shlex.split(spec[len("command:"):]))
    if spec.startswith("agent:"):
        return AgentBackend(spec[len("agent:"):], replies)
    key = os.environ.get("DDS_LLM_API_KEY")
    if spec.startswith("openai:"):
        url, _, model = spec[len("openai:"):].partition("#")
        if not model:
            raise ValueError("openai backend needs <base_url>#<model>")
        b = OpenAIHTTPBackend(url, model, api_key=key)
    else:
        runtime, _, rest = spec.partition(":")
        if runtime not in RUNTIMES or not rest:
            raise ValueError(f"unknown backend {spec!r}; runtimes: {', '.join(RUNTIMES)}")
        model, url = rest, None
        m = re.search(r"@(https?://\S+)$", rest)
        if m:
            model, url = rest[:m.start()], m.group(1)
        url = url or os.environ.get(f"DDS_{runtime.upper()}_URL") or RUNTIMES[runtime]
        b = OpenAIHTTPBackend(url, model, runtime=runtime, api_key=key)
    if check:
        b.check()
    return b


# ============================================================================ cache (EARL)
def cache_key(packet: Packet, model: str, scope: str = "document") -> str:
    """Packet content (target, premises, evidence, details, relation ids, frame, criterion definitions,
    schema) + rule version + prompt version + model + scope. Same text alone never reuses a result."""
    return sha(packet.content_hash, packet.type, ",".join(packet.criteria), RULE_VERSION, PROMPT_VERSION, model, scope)


@dataclass
class CacheEntry:
    key: str
    subject: str
    criterion: str
    status: str
    rationale: str
    confidence: float
    model: str
    packet_type: str
    date: str


def load_cache(g: Optional[Graph]) -> Dict[str, List[CacheEntry]]:
    out: Dict[str, List[CacheEntry]] = {}
    if g is None:
        return out
    from .evaluation import STATUS_OF
    for a in g.subjects(DDS.cacheKey, None):
        r = g.value(a, EARL.result)
        test = str(g.value(a, EARL.test)).rsplit("/", 1)[-1]
        out.setdefault(str(g.value(a, DDS.cacheKey)), []).append(CacheEntry(
            str(g.value(a, DDS.cacheKey)), str(g.value(a, EARL.subject)), test,
            STATUS_OF.get(g.value(r, EARL.outcome), "NeedsReview"), str(g.value(r, EARL.info) or ""),
            float(g.value(a, DDS.confidence) or 0), str(g.value(a, DDS.assessorModel)),
            str(g.value(a, DDS.packetType)), str(g.value(r, DCTERMS.date) or "")))
    return out


def write_entries(entries: List[CacheEntry], ns: Optional[DataNS] = None) -> Graph:
    g = bind_prefixes(Graph(), ns)
    g.bind("earl", EARL)
    g.bind("dcterms", DCTERMS)
    crit = (ns or DataNS()).criterion
    for e in entries:
        a, r = BNode(), BNode()
        g.add((a, RDF.type, EARL.Assertion))
        g.add((a, EARL.subject, URIRef(e.subject)))
        g.add((a, EARL.test, crit[e.criterion]))
        g.add((a, EARL.assertedBy, URIRef("urn:dds:model:" + re.sub(r"[^A-Za-z0-9._-]", "_", e.model))))
        g.add((a, EARL.mode, EARL.automatic))
        g.add((a, DDS.assessorModel, Literal(e.model)))
        g.add((a, DDS.uncertainty, Literal(f"model opinion, confidence {e.confidence:.2f}; not verified", lang="en")))
        g.add((a, DDS.evaluationScope, Literal(f"{e.packet_type} packet (bounded input)", lang="en")))
        g.add((a, DDS.cacheKey, Literal(e.key)))
        g.add((a, DDS.packetType, Literal(e.packet_type)))
        g.add((a, DDS.promptVersion, Literal(PROMPT_VERSION)))
        g.add((a, DDS.ruleVersion, Literal(RULE_VERSION)))
        g.add((a, DDS.confidence, Literal(round(e.confidence, 3), datatype=XSD.decimal)))
        g.add((a, EARL.result, r))
        g.add((r, RDF.type, EARL.TestResult))
        g.add((r, EARL.outcome, OUTCOME[e.status]))
        g.add((r, EARL.info, Literal(e.rationale or "-", lang="en")))
        g.add((r, DCTERMS.date, Literal(e.date, datatype=XSD.dateTime)))
    return g


# ============================================================================ L2 triggers
@dataclass
class L2Policy:
    change_ratio: float = 0.3       # accumulated changed share of components since the last L2
    force: bool = False             # explicit request
    major: bool = False             # caller marks a major document version
    high_risk: bool = False         # caller marks a high-risk decision


def l2_triggers(g: Graph, doc: URIRef, changes: Optional[Dict[str, Change]], since_l2: float,
                has_prior_l2: bool, policy: L2Policy) -> List[str]:
    from .evaluation import _sem_kinds
    why = []
    if policy.force:
        why.append("explicit request")
    if policy.major:
        why.append("major version (caller flag)")
    if policy.high_risk:
        why.append("high-risk decision (caller flag)")
    if not has_prior_l2:
        why.append("no previous global critique")
    if changes:
        core = [i for i, ch in changes.items() if ch.semantic and (URIRef(i), None, None) in g
                and {"Criterion", "Scope", "DecisionQuestion"} & set(_sem_kinds(g, URIRef(i)))]
        if core:
            why.append("core premise changed: " + ", ".join(sorted(i.rsplit('/', 1)[-1] for i in core)))
    if since_l2 >= policy.change_ratio:
        why.append(f"accumulated change {since_l2:.0%} >= {policy.change_ratio:.0%}")
    return why


# ============================================================================ run
@dataclass
class Metrics:
    strategy: str
    document: str
    components: int = 0
    affected: int = 0
    packets: int = 0
    calls: int = 0
    escalations: int = 0
    pending: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    outside_impact_misses: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    shared_prefix_tokens: int = 0
    tokens_estimated: bool = False
    latencies_ms: List[float] = field(default_factory=list)
    l2_reasons: List[str] = field(default_factory=list)
    by_stage: Dict[str, Dict[str, int]] = field(default_factory=dict)
    cost: Optional[float] = None
    cost_note: str = "no price table"

    def record(self, stage: str, p: Packet, rep: Reply):
        self.calls += 1
        u = rep.usage
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cached_tokens += u.cached_tokens
        self.tokens_estimated |= u.estimated
        self.latencies_ms.append(u.latency_ms)
        s = self.by_stage.setdefault(stage, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        s["calls"] += 1
        s["input_tokens"] += u.input_tokens
        s["output_tokens"] += u.output_tokens

    def summary(self) -> dict:
        d = asdict(self)
        lat = sorted(self.latencies_ms)
        d.pop("latencies_ms")
        d["p50_latency_ms"] = round(statistics.median(lat), 1) if lat else None
        d["p95_latency_ms"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1) if lat else None
        d["incremental_ratio"] = round(self.affected / self.components, 3) if self.components else None
        n = self.cache_hits + self.cache_misses
        d["cache_hit_rate"] = round(self.cache_hits / n, 3) if n else None
        d["tokens_per_validated_component"] = (round(self.input_tokens / self.affected, 1)
                                               if self.affected else None)
        return d

    def price(self, table: Dict[str, dict], model: str):
        p = table.get(model)
        if not p:
            self.cost_note = f"no price for {model}"
            return
        self.cost = round(self.input_tokens / 1e6 * p.get("input_per_mtok", 0)
                          + self.output_tokens / 1e6 * p.get("output_per_mtok", 0), 6)
        self.cost_note = "from estimated tokens" if self.tokens_estimated else "from reported tokens"


@dataclass
class RunResult:
    entries: List[CacheEntry]
    metrics: Metrics
    impact_reasons: Dict[str, List[str]]
    limitation: str


def unwrap(d) -> dict:
    """Some models echo the schema shape ({"properties": {...}}); take the inner object."""
    while isinstance(d, dict) and "verdict" not in d and "items" not in d and isinstance(d.get("properties"), dict):
        d = d["properties"]
    return d if isinstance(d, dict) else {}


def _entries(p: Packet, rep: Reply, key: str, date: str) -> List[CacheEntry]:
    data = unwrap(rep.data)
    items = data.get("items") if p.combined and isinstance(data.get("items"), dict) else {p.criteria[0]: data}
    out = []
    for crit in p.criteria:
        v = unwrap(items.get(crit) or {})
        verdict = str(v.get("verdict", "uncertain")).lower()
        try:
            conf = float(v.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        out.append(CacheEntry(key, p.subject, crit, VERDICT_STATUS.get(verdict, "NeedsReview"),
                              str(v.get("rationale", ""))[:500], conf, rep.model, p.type, date))
    return out


def _needs_escalation(entries: List[CacheEntry], threshold: float, high_risk: bool, subject_is_decision: bool):
    if high_risk and subject_is_decision:
        return "high-risk decision"
    for e in entries:
        if e.status == "NeedsReview":
            return "uncertain verdict"
        if e.confidence < threshold:
            return f"low confidence {e.confidence:.2f}"
    return None


def run(g: Graph, doc: URIRef, light: Backend, strong: Optional[Backend] = None, prev: Optional[Graph] = None,
        prev_doc: Optional[URIRef] = None, cache: Optional[Graph] = None, policy: Optional[L2Policy] = None,
        since_l2: float = 0.0, has_prior_l2: bool = False, combined: bool = False,
        escalate_below: float = 0.7, date: Optional[str] = None) -> RunResult:
    """Optimized strategy. `g` must be the merged graph (TBox + defaults + document)."""
    from .evaluation import _sem_kinds
    policy = policy or L2Policy()
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    m = Metrics("optimized", str(doc))
    comps = components(g, doc)
    m.components = len(comps)
    changes = diff(prev, prev_doc or doc, g, doc) if prev is not None else None
    if changes is not None:
        imp = impact(g, doc, changes, prev)
        scope, reasons, limitation = set(imp.affected), imp.reasons, imp.limitation
    else:
        scope = {str(c) for c in comps}
        reasons, limitation = {}, "first evaluation: whole document in scope"
    m.affected = len(scope)
    cached = load_cache(cache)
    out: List[CacheEntry] = []

    escalate = strong is not None and strong.model != light.model
    route = light.model + (f"|{strong.model}" if escalate else "")   # key covers both models
    packets = build_l1(g, doc, combined=combined)
    m.shared_prefix_tokens = sum({p.type: p.prefix_tokens for p in packets}.values())
    for p in packets:
        key = cache_key(p, route)
        hit = cached.get(key)
        in_scope = p.subject in scope or bool(scope & set(p.members))
        if hit:
            m.cache_hits += 1
            out.extend(hit)
            continue
        if not in_scope:
            # key changed although impact analysis did not select it: an unrecorded dependency or a
            # change outside the dependency graph. Re-evaluate and report it.
            m.outside_impact_misses += 1
        m.cache_misses += 1
        m.packets += 1
        rep = light.call(p)
        if rep.pending:
            m.pending += 1
            continue
        m.record("L1-light", p, rep)
        entries = _entries(p, rep, key, date)
        why = None
        if escalate:
            is_decision = "Decision" in _sem_kinds(g, URIRef(p.subject))
            why = _needs_escalation(entries, escalate_below, policy.high_risk, is_decision)
        if why:
            rep2 = strong.call(p)
            if rep2.pending:
                m.pending += 1
                continue
            m.record("L1-strong", p, rep2)
            m.escalations += 1
            entries = _entries(p, rep2, key, date)
        out.extend(entries)

    m.l2_reasons = l2_triggers(g, doc, changes, since_l2, has_prior_l2, policy)
    critic = strong or light
    for p in build_l2(g, doc, combined=combined):
        key = cache_key(p, critic.model, scope="global")
        hit = cached.get(key)
        if hit and not policy.force:
            # still valid for this exact document text: carried over without a call
            m.cache_hits += 1
            out.extend(hit)
            continue
        if m.l2_reasons:
            m.cache_misses += 1
            m.packets += 1
            rep = critic.call(p)
            if rep.pending:
                m.pending += 1
                continue
            m.record("L2", p, rep)
            out.extend(_entries(p, rep, key, date))
    return RunResult(out, m, reasons, limitation)


def run_naive(g: Graph, doc: URIRef, backend: Backend, date: Optional[str] = None) -> RunResult:
    """Reference strategy: whole document, one call per semantic criterion, no cache, every run."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    m = Metrics("naive", str(doc))
    m.components = m.affected = len(components(g, doc))
    out = []
    for p in build_naive(g, doc):
        m.packets += 1
        m.cache_misses += 1
        rep = backend.call(p)
        m.record("naive", p, rep)
        out.extend(_entries(p, rep, sha("naive", p.content_hash, backend.model), date))
    return RunResult(out, m, {}, "naive reference strategy")
