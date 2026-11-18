"""Local runtime integration (OpenAI-compatible HTTP) and light-subagent delegation, without real servers."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from _util import FIXTURES, run

from rdflib import Graph

from dds_lib import semeval as S
from dds_lib.graph import load_data
from dds_lib.model import documents

DECISION = FIXTURES / "valid" / "decision-record.ttl"


class Fake(BaseHTTPRequestHandler):
    reject_schema = False
    think = False
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "org/tiny-model"}, {"id": "other"}]})
        self._send(404, {})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append(req)
        if "response_format" in req and Fake.reject_schema:
            return self._send(400, {"error": "response_format not supported"})
        text = json.dumps({"verdict": "inconsistent", "confidence": 0.8, "rationale": "r"})
        if Fake.think:
            text = "<think>{maybe} hmm</think>" + text
        self._send(200, {"model": req["model"], "choices": [{"message": {"content": text}}],
                         "usage": {"prompt_tokens": 111, "completion_tokens": 22,
                                   "prompt_tokens_details": {"cached_tokens": 50}}})


@pytest.fixture()
def server():
    Fake.reject_schema, Fake.think, Fake.seen = False, False, []
    httpd = HTTPServer(("127.0.0.1", 0), Fake)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


def _doc():
    return load_data([DECISION]), documents(Graph().parse(DECISION))[0]


@pytest.mark.parametrize("runtime", sorted(S.RUNTIMES))
def test_runtime_spec_parses_with_url_override(runtime, server):
    b = S.backend_from_spec(f"{runtime}:tiny-model@{server}", check=True)   # suffix match on org/tiny-model
    assert b.runtime == runtime and b.base == server and b.model == "tiny-model"


def test_ollama_style_model_tag_and_env_url(monkeypatch, server):
    monkeypatch.setenv("DDS_OLLAMA_URL", server)
    b = S.backend_from_spec("ollama:qwen3:8b")
    assert b.model == "qwen3:8b" and b.base == server


def test_unknown_model_fails_early_with_available_ids(server):
    with pytest.raises(RuntimeError, match="available"):
        S.backend_from_spec(f"vllm:missing@{server}", check=True)


def test_structured_output_then_fallback(server):
    g, doc = _doc()
    b = S.backend_from_spec(f"sglang:tiny-model@{server}")
    res = S.run(g, doc, b, has_prior_l2=True, date="2026-11-18T00:00:00Z")
    assert "response_format" in Fake.seen[0]
    assert res.metrics.input_tokens == 111 * res.metrics.calls and res.metrics.cached_tokens > 0
    assert not res.metrics.tokens_estimated
    Fake.seen, Fake.reject_schema = [], True
    b2 = S.backend_from_spec(f"lmstudio:tiny-model@{server}")
    res2 = S.run(g, doc, b2, has_prior_l2=True, date="2026-11-18T00:00:00Z")
    assert b2.structured is False and res2.metrics.calls > 0
    assert {e.status for e in res2.entries} == {"Fail"}


def test_reasoning_block_is_stripped(server):
    Fake.think = True
    g, doc = _doc()
    res = S.run(g, doc, S.backend_from_spec(f"omlx:tiny-model@{server}"), has_prior_l2=True, date="2026-11-18T00:00:00Z")
    assert {e.status for e in res.entries} == {"Fail"}


def test_discover_reports_by_url(server):
    found = S.discover([server])
    assert any(f["url"] == server and "org/tiny-model" in f["models"] for f in found)


# ---------------------------------------------------------------- second option: light subagent
def test_agent_delegation_emit_then_ingest(tmp_path):
    cache, out, pend, rep = tmp_path / "c.ttl", tmp_path / "a.ttl", tmp_path / "p.jsonl", tmp_path / "r.jsonl"
    r = run("semantic_eval.py", DECISION, "--backend", "agent:haiku", "--cache", cache, "--out", out, "--emit", pend)
    assert r.returncode == 3, r.stderr
    lines = [json.loads(x) for x in pend.read_text(encoding="utf-8").splitlines()]
    assert lines and all({"packet_id", "prefix", "body", "schema"} <= set(x) for x in lines)
    assert "pending" not in cache.read_text(encoding="utf-8")      # nothing pending was cached
    rep.write_text("".join(json.dumps({"packet_id": x["packet_id"], "model": "claude-haiku",
                                       "output": {"verdict": "consistent", "confidence": 0.9, "rationale": "ok"}})
                           + "\n" for x in lines), encoding="utf-8")
    r = run("semantic_eval.py", DECISION, "--backend", "agent:haiku", "--cache", cache, "--out", out, "--replies", rep)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["calls"] == len(lines)
    r = run("semantic_eval.py", DECISION, "--backend", "agent:haiku", "--cache", cache, "--out", out,
            "--prev", DECISION, "--emit", pend)
    assert r.returncode == 0 and json.loads(r.stdout)["calls"] == 0   # served from cache, nothing to delegate
    assert run("evaluate.py", DECISION, "--assessments", out).returncode == 0
