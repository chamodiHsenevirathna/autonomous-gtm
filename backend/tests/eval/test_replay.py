import hashlib, json
import pytest
from gtm.contracts.llm import LLMRequest, LLMResponse, Task
from gtm.eval import replay


def ihash(req):
    return hashlib.sha256(json.dumps([req.task.value, req.prompt_version, req.input], sort_keys=True).encode()).hexdigest()


class FakeMock:
    def complete(self, req, *, run_id=None):
        return LLMResponse(output={"label": "genuine", "confidence": 0.9, "reason": req.input["untrusted"][:5]}, model_id="mock-heuristic-v1",
                           mode="mock", input_hash=ihash(req))


class FakeReplay:
    def __init__(self, root, drift=False):
        self.root, self.drift = root, drift

    def complete(self, req, *, run_id=None):
        doc = replay.load_fixture(req.task.value, ihash(req), self.root)
        out = dict(doc["output"], confidence=0.1) if self.drift else doc["output"]
        return LLMResponse(output=out, model_id="replay:" + doc["model_id"], mode="replay", input_hash=doc["input_hash"])


REQS = [LLMRequest(task=Task.TRIAGE, input={"untrusted": f"hello number {i}"}) for i in range(3)]


def test_record_writes_agreed_format(tmp_path):
    paths = replay.record(FakeMock(), REQS, tmp_path)
    assert len(paths) == 3 and paths[0].parent.name == "triage" and paths[0].name == ihash(REQS[0]) + ".json"
    doc = json.loads(paths[0].read_text())
    assert set(replay.RECORD_KEYS) <= set(doc) <= set(replay.RECORD_KEYS) | {"tokens_in", "tokens_out"}
    assert doc["mode"] == "mock" and doc["recorded_with"] == "mock-heuristic-v1" and doc["input"] == REQS[0].input


def test_record_is_idempotent(tmp_path):
    a = replay.record(FakeMock(), REQS, tmp_path)[0].read_text()
    assert replay.record(FakeMock(), REQS, tmp_path)[0].read_text() == a


def test_replay_equals_mock(tmp_path):
    replay.record(FakeMock(), REQS, tmp_path)
    rep = replay.verify_replay_equals_mock(FakeMock(), FakeReplay(tmp_path), REQS)
    assert rep.ok and rep.n == 3
    rep.raise_if_failed()


def test_drift_and_missing_fixture_are_detected(tmp_path):
    replay.record(FakeMock(), REQS[:2], tmp_path)
    rep = replay.verify_replay_equals_mock(FakeMock(), FakeReplay(tmp_path), REQS)
    assert not rep.ok and rep.mismatches[0]["index"] == 2 and "FileNotFoundError" in rep.mismatches[0]["error"]
    rep = replay.verify_replay_equals_mock(FakeMock(), FakeReplay(tmp_path, drift=True), REQS[:2])
    assert not rep.ok and rep.mismatches[0]["differs"] == ["output"]
    with pytest.raises(AssertionError):
        rep.raise_if_failed()


def test_load_fixture_rejects_incomplete_file(tmp_path):
    p = replay.fixture_path("triage", "abc", tmp_path); p.parent.mkdir(parents=True); p.write_text('{"input_hash": "abc"}')
    with pytest.raises(ValueError):
        replay.load_fixture("triage", "abc", tmp_path)
