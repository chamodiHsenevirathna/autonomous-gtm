"""Recorded-response infrastructure. The replay *client* belongs to the orchestration stream (gtm.llm); this module
records fixtures through any ``LLMClient`` and checks that replay reproduces the mock bit for bit.

Fixture file: ``fixtures/recorded/<task>/<input_hash>.json`` with exactly these keys:
    input_hash, task, prompt_version, input, output, model_id, mode, recorded_with   (+ optional tokens_in, tokens_out)
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from gtm.contracts.llm import LLMClient, LLMRequest

RECORDED_DIR = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "recorded"
RECORD_KEYS = ("input_hash", "task", "prompt_version", "input", "output", "model_id", "mode", "recorded_with")
# Files written by gtm.llm's own recorder lack mode/recorded_with (and add tokens_*); loading tolerates that.
REQUIRED_ON_LOAD = ("input_hash", "task", "prompt_version", "input", "output", "model_id")


def fixture_path(task: str, input_hash: str, root: pathlib.Path | str | None = None) -> pathlib.Path:
    return pathlib.Path(root or RECORDED_DIR) / str(task) / f"{input_hash}.json"


def load_fixture(task: str, input_hash: str, root: pathlib.Path | str | None = None) -> dict:
    doc = json.loads(fixture_path(task, input_hash, root).read_text())
    missing = [k for k in REQUIRED_ON_LOAD if k not in doc]
    if missing:
        raise ValueError(f"recorded fixture {task}/{input_hash} lacks keys {missing}")
    return doc


def record(client: LLMClient, requests: list[LLMRequest], root: pathlib.Path | str | None = None, *,
           recorded_with: str | None = None) -> list[pathlib.Path]:
    """Run each request through ``client`` and store the response. ``input_hash`` comes from the client's own response so
    that replay lookups use the same key the wrapper computes. ``recorded_with`` defaults to the response model_id
    (e.g. 'mock-heuristic-v1'); a recording is never labelled live unless the client really was live."""
    paths = []
    for req in requests:
        resp = client.complete(req)
        doc = {"input_hash": resp.input_hash, "task": str(req.task.value), "prompt_version": req.prompt_version, "input": req.input,
               "output": resp.output, "model_id": resp.model_id, "mode": resp.mode, "recorded_with": recorded_with or resp.model_id,
               "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out}
        p = fixture_path(doc["task"], resp.input_hash, root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        paths.append(p)
    return paths


@dataclass
class ReplayReport:
    ok: bool
    n: int
    mismatches: list[dict] = field(default_factory=list)

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise AssertionError(f"replay differs from mock on {len(self.mismatches)}/{self.n} requests: {self.mismatches[:3]}")


def _bare(model_id: str) -> str:
    return model_id.removeprefix("replay:")


def verify_replay_equals_mock(client_mock: LLMClient, client_replay: LLMClient, requests: list[LLMRequest]) -> ReplayReport:
    """Replay must return the mock's output and input_hash for every request (model ids compare without the 'replay:' prefix).
    A missing fixture counts as a mismatch."""
    bad = []
    for i, req in enumerate(requests):
        m = client_mock.complete(req)
        try:
            r = client_replay.complete(req)
        except Exception as e:
            bad.append({"index": i, "task": str(req.task.value), "error": f"{type(e).__name__}: {e}"})
            continue
        diffs = [k for k, a, b in (("output", m.output, r.output), ("input_hash", m.input_hash, r.input_hash),
                                   ("model_id", _bare(m.model_id), _bare(r.model_id))) if a != b]
        if diffs:
            bad.append({"index": i, "task": str(req.task.value), "differs": diffs})
    return ReplayReport(ok=not bad, n=len(requests), mismatches=bad)
