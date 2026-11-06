"""Live client behaviour, checked ONLY against httpx.MockTransport. No real network, no real key is ever read or needed."""
import json, os
import httpx, pytest
from gtm.clock import SimClock
from gtm.config import Settings
from gtm.contracts.errors import PermanentError, PolicyDenied
from gtm.contracts.llm import LLMRequest, Task
from gtm.llm import build_llm
from gtm.llm import client as C
from gtm.llm.prompts import TASKS, task_prompt

TRIAGE = {"label": "genuine", "confidence": 0.9, "reason": "r", "injection_suspected": False}
S = lambda **k: Settings(llm_mode="live", allow_live=True, live_budget_usd=1.0, **k)
REQ = lambda **k: LLMRequest(task=Task.TRIAGE, input={"untrusted": {"message": "hello there, we need data engineering help"}, **k})
ok = lambda inp=TRIAGE, usage=(100, 20), **extra: {"model": "claude-sonnet-5-5", "content": [{"type": "tool_use", "id": "1", "name": "emit_result", "input": inp}], "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}, **extra}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-for-mock-transport-only"); monkeypatch.delenv("GTM_LIVE_MODEL", raising=False); monkeypatch.delenv("GTM_LIVE_EFFORT", raising=False)


def run(handler, settings=None, req=None, model=None, monkeypatch=None):
    return build_llm(settings or S(), SimClock(), transport=httpx.MockTransport(handler)).complete(req or REQ())


def test_request_has_no_forced_tool_choice_and_carries_task_rubric():
    seen = []
    def h(r): seen.append(json.loads(r.content)); return httpx.Response(200, json=ok())
    run(h)
    b = seen[0]
    assert b["tool_choice"] == {"type": "auto"}                              # forced tool choice is rejected by current models (HTTP 400)
    assert "at least 50 employees" in b["system"] and "injection_suspected" in b["system"] and "emit_result" in b["system"]
    assert b["max_tokens"] == 4096 and [t["name"] for t in b["tools"]] == ["emit_result"]


def test_every_task_has_a_v1_prompt():
    for t in Task: assert task_prompt(t.value, "v1")
    with pytest.raises(KeyError): task_prompt("triage", "v9")


def test_optional_effort_is_sent_only_when_configured(monkeypatch):
    seen = []
    def h(r): seen.append(json.loads(r.content)); return httpx.Response(200, json=ok())
    run(h); assert "output_config" not in seen[0]
    monkeypatch.setenv("GTM_LIVE_EFFORT", "low"); run(h); assert seen[1]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("model,inp,out,usd", [("claude-haiku-5-5", 1_000_000, 0, 0.10), ("claude-sonnet-5-5", 1_000_000, 100_000, 3.0), ("claude-opus-5-5", 0, 1_000_000, 20.0)])
def test_cost_uses_the_per_model_price_table(monkeypatch, model, inp, out, usd):
    monkeypatch.setenv("GTM_LIVE_MODEL", model)
    r = run(lambda q: httpx.Response(200, json=ok(usage=(inp, out), model=model)), S().__class__(llm_mode="live", allow_live=True, live_budget_usd=100.0))
    assert abs(r.cost_usd - usd) < 1e-9


def test_unknown_model_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv("GTM_LIVE_MODEL", "some-unpriced-model"); hits = []
    with pytest.raises(PolicyDenied, match="no price"):
        run(lambda q: hits.append(q) or httpx.Response(200, json=ok()))
    assert hits == []


def test_projected_worst_case_cost_blocks_the_call_before_it_is_sent(monkeypatch):
    monkeypatch.setenv("GTM_LIVE_MODEL", "claude-opus-5-5"); hits = []      # worst case = 4096 output tokens at $20/M = $0.08 > $0.05
    with pytest.raises(PolicyDenied, match="projected"):
        run(lambda q: hits.append(q) or httpx.Response(200, json=ok()), Settings(llm_mode="live", allow_live=True, live_budget_usd=0.05))
    assert hits == []


def test_per_request_cap_is_enforced():
    hits = []
    with pytest.raises(PolicyDenied, match="max_cost_usd"):
        run(lambda q: hits.append(q) or httpx.Response(200, json=ok()), req=LLMRequest(task=Task.TRIAGE, input={"untrusted": {"message": "x"}}, max_cost_usd=0.0001))
    assert hits == []


def test_spend_counts_turns_without_a_tool_call_too():
    calls = []
    def h(r):
        calls.append(1)
        return httpx.Response(200, json={"model": "m", "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1000, "output_tokens": 1000}}) if len(calls) == 1 else httpx.Response(200, json=ok())
    c = build_llm(S(), SimClock(), transport=httpx.MockTransport(h)); c.complete(REQ())
    assert c.spent > 0.012                                                 # first (wasted) turn $0.012 + second turn


def test_refusal_and_max_tokens_are_distinct_recorded_failure_classes():
    with pytest.raises(PermanentError) as e:
        run(lambda q: httpx.Response(200, json={"model": "m", "content": [], "stop_reason": "refusal", "stop_details": {"category": "x"}, "usage": {"input_tokens": 5, "output_tokens": 0}}))
    assert e.value.detail["failure_class"] == "refusal"
    with pytest.raises(PermanentError) as e:
        run(lambda q: httpx.Response(200, json={"model": "m", "content": [{"type": "text", "text": "..."}], "stop_reason": "max_tokens", "usage": {"input_tokens": 5, "output_tokens": 4096}}))
    assert e.value.detail["failure_class"] == "max_tokens"
    with pytest.raises(PermanentError) as e:
        run(lambda q: httpx.Response(400, text="no"))
    assert e.value.detail["failure_class"] == "http_4xx"


def test_live_outputs_are_recorded_separately_from_mock_recordings(tmp_path):
    c = build_llm(S(), SimClock(), transport=httpx.MockTransport(lambda q: httpx.Response(200, json=ok())), fixtures_dir=tmp_path, record=True)
    r = c.complete(REQ())
    f = tmp_path / "live" / "triage" / f"{r.input_hash}.json"
    assert f.exists() and json.loads(f.read_text())["model_id"] == "claude-sonnet-5-5"
    assert not (tmp_path / "triage").exists()


# ---- the zero-cost lock
class SpyEnv(dict):
    def __init__(self, base): super().__init__(base); self.reads = []
    def get(self, k, d=None): self.reads.append(k); return super().get(k, d)


def test_lock_blocks_real_network_and_never_reads_the_key(monkeypatch):
    assert C.ZERO_COST_LOCK.exists(), "the zero-cost lock file must be present"
    spy = SpyEnv(os.environ); monkeypatch.setattr(os, "environ", spy)
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network touched")))
    c = build_llm(S(), SimClock())                                          # no MockTransport: this would be the real network
    with pytest.raises(PolicyDenied, match="locked off"):
        c.complete(REQ())
    assert "ANTHROPIC_API_KEY" not in spy.reads and "GTM_LIVE_MODEL" not in spy.reads
