import json
import pytest
import yaml
from gtm.contracts.scenario import Scenario
from gtm.eval import runner as R
from eval_helpers import small_world, golden
from fake_harness import FakeHarness

pytestmark = pytest.mark.db


def sc(sid="T01", script=(), expectations=(), **kw):
    base = dict(id=sid, title="t " + sid, pass_criterion="c", truth_source="ts", evidence_basis="machinery_check", data_origins=["SCR"],
                script=list(script), expectations=list(expectations))
    return Scenario.model_validate({**base, **kw})


@pytest.fixture()
def h(conn):
    return FakeHarness(conn)


GOLDEN_SCRIPT = [{"kind": "enquiry", "ref": "enq_001"}, {"kind": "human_decision", "ref": "first_pending", "params": {"decision": "approve", "by": "user:maya"}}]
GOLDEN_EXPECT = [
    {"kind": "invariant", "name": "all"},
    {"kind": "state", "name": "one send", "spec": {"sql": "SELECT count(*) FROM ops.execution WHERE status='succeeded'", "eq": 1}},
    {"kind": "state", "name": "lead proposed", "spec": {"sql": "SELECT status FROM gtm.lead WHERE id=%(lead_id)s", "eq": "proposed"}},
    {"kind": "state", "name": "ctx path", "spec": {"ctx": "last_decision.status", "eq": "approved"}},
    {"kind": "state", "name": "snapshot", "spec": {"snapshot": "sent", "eq": 1}},
    {"kind": "metric", "name": "qualification_accuracy", "spec": {"eq": 1.0}},
    {"kind": "event", "name": "lead event", "spec": {"type": "lead.received", "payload": {"enquiry_id": "enq_001"}, "eq": 1}},
    {"kind": "audit", "name": "executed", "spec": {"event_type": "proposal.executed", "proposal": "type:message", "eq": 1}},
    {"kind": "audit", "name": "chain", "spec": {"verify_chain": True}},
]


def test_golden_scenario_passes_end_to_end(h):
    r = R.run_scenario(h, sc(script=GOLDEN_SCRIPT, expectations=GOLDEN_EXPECT))
    assert r.passed, r.failures
    assert len(r.expectations) == len(GOLDEN_EXPECT) and r.metrics["qualification_accuracy"]["value"] == 1.0
    assert r.evidence_basis == "machinery_check" and r.data_origins == ["SCR"] and h.resets == 1


def test_failing_expectation_is_reported(h):
    r = R.run_scenario(h, sc(script=GOLDEN_SCRIPT, expectations=[
        {"kind": "state", "name": "wrong", "spec": {"sql": "SELECT count(*) FROM ops.execution", "eq": 5}}]))
    assert not r.passed and r.failures[0]["name"] == "wrong" and "actual=1" in r.failures[0]["detail"]


def test_wrong_band_fails_metric(conn):
    r = R.run_scenario(FakeHarness(conn, wrong_band=True), sc(script=[{"kind": "enquiry", "ref": "enq_001"}], expectations=[
        {"kind": "metric", "name": "qualification_recall", "spec": {"min": 0.9}}]))
    assert not r.passed and "qualification_recall" in r.failures[0]["name"]


def test_metric_without_data_is_not_a_pass(h):
    r = R.run_scenario(h, sc(expectations=[{"kind": "metric", "name": "er_precision", "spec": {"min": 0.0}}]))
    assert not r.passed and "not measurable" in r.failures[0]["detail"]
    r2 = R.run_scenario(h, sc(expectations=[{"kind": "metric", "name": "er_precision", "spec": {"allow_none": True}}]))
    assert r2.passed


def test_implicit_invariants_catch_a_send_without_approval(conn):
    harness = FakeHarness(conn, send_without_approval=True)
    r = R.run_scenario(harness, sc(script=[{"kind": "enquiry", "ref": "enq_001"}, {"kind": "gateway_attempt", "ref": "type:message"}]))
    assert not r.passed
    assert any(f["kind"] == "implicit_invariant" and f["name"] == "approval_required" for f in r.failures)


def test_red_team_bypass_is_denied_and_no_effect(h):
    r = R.run_scenario(h, sc(script=[{"kind": "enquiry", "ref": "enq_001"},
                                     {"kind": "gateway_attempt", "ref": "first_pending", "params": {"bypass": "forged_token"}}],
                             expectations=[{"kind": "state", "name": "denied", "spec": {"ctx": "last_gateway.status", "in": ["BLOCKED", "DENIED"]}},
                                           {"kind": "no_effect", "name": "nothing sent", "spec": {"adapter": "outreach.send", "snapshot_key": "sent"}}]))
    assert r.passed, r.failures


def test_unsubscribe_blocks_send_hard(h):
    script = [{"kind": "enquiry", "ref": "enq_001"}, {"kind": "reply", "params": {"select": "reply:unsubscribe@enq_001"}},
              {"kind": "human_decision", "ref": "type:message", "params": {"decision": "approve"}}]
    r = R.run_scenario(h, sc(script=script, expectations=[
        {"kind": "no_effect", "name": "no send", "spec": {"adapter": "outreach.send"}},
        {"kind": "invariant", "name": "no_send_after_suppression"}]))
    assert r.passed, r.failures


def test_edit_then_approve_sends_edited_payload_only(h):
    script = [{"kind": "enquiry", "ref": "enq_001"},
              {"kind": "human_decision", "ref": "first_pending", "params": {"edit": {"body": "Edited by human"}}}]
    r = R.run_scenario(h, sc(script=script, expectations=[
        {"kind": "state", "name": "edited hash used", "spec": {"sql": "SELECT approved_payload->>'body' FROM ops.approval_decision LIMIT 1", "eq": "Edited by human"}},
        {"kind": "state", "name": "decision", "spec": {"sql": "SELECT decision FROM ops.approval_decision LIMIT 1", "eq": "approve_with_edits"}}]))
    assert r.passed, r.failures


def test_expected_violation_and_tamper(h):
    script = [{"kind": "enquiry", "ref": "enq_001"}, {"kind": "tamper", "params": {"what": "audit_row"}}]
    r = R.run_scenario(h, sc(script=script, expectations=[{"kind": "invariant", "name": "audit_chain", "spec": {"expect": "violated"}},
                                                          {"kind": "audit", "name": "chain broken", "spec": {"verify_chain": False}}]))
    assert r.passed, r.failures
    # without declaring it, the tamper fails the scenario through the implicit invariant
    r2 = R.run_scenario(h, sc(script=script))
    assert not r2.passed and r2.failures[0]["name"] == "audit_chain"


def test_denied_decision_with_expect_denied(h):
    script = [{"kind": "enquiry", "ref": "enq_001"}, {"kind": "human_decision", "ref": "first_pending", "params": {"by": "agent:account-agent", "expect_denied": True}}]
    assert R.run_scenario(h, sc(script=script, expectations=[{"kind": "state", "name": "d", "spec": {"ctx": "last_decision.denied", "eq": True}}])).passed
    script[1]["params"].pop("expect_denied")
    r = R.run_scenario(h, sc(script=script))
    assert not r.passed and r.failures[0]["kind"] == "error"


def test_offsets_advance_the_clock_in_order(h):
    t0 = h.clock.now()
    script = [{"kind": "enquiry", "ref": "enq_003", "at_offset_s": 120}, {"kind": "enquiry", "ref": "enq_001", "at_offset_s": 30}]
    r = R.run_scenario(h, sc(script=script))
    assert r.passed and (h.clock.now() - t0).total_seconds() == 120
    assert h.conn.execute("SELECT idempotency_key FROM gtm.lead ORDER BY id").fetchall()[0]["idempotency_key"] == "enq:enq_001"


def test_symbolic_selectors_and_errors(h):
    w = small_world()
    assert R.resolve_selector(w, "exact_duplicate_of_enq_001") == "enq_002"
    assert R.resolve_selector(w, "vendor_pitch") == "enq_003"
    assert R.resolve_selector(w, "shared_mailbox") == "enq_004" and R.resolve_selector(w, "injection_in_enquiry") == "enq_004"
    assert R.resolve_selector(w, "reply:unsubscribe") == "rep_001" and R.resolve_selector(w, "enq_001") == "enq_001"
    with pytest.raises(R.ScenarioError):
        R.resolve_selector(w, "fuzzy_duplicate_of_enq_001")  # world does not provide one
    r = R.run_scenario(h, sc(script=[{"kind": "enquiry", "params": {"select": "recruiter"}}]))
    assert not r.passed and "recruiter" in r.failures[0]["detail"]


def test_resolve_proposal(conn, clock):
    from eval_helpers import mk_proposal
    a = mk_proposal(conn, clock, status="pending"); b = mk_proposal(conn, clock, status="executed"); c = mk_proposal(conn, clock, status="pending", gate="G4", ptype="crm_write", payload={"operations": []})
    assert R.resolve_proposal(conn, "first_pending") == a and R.resolve_proposal(conn, "last_pending") == c
    assert R.resolve_proposal(conn, "type:message,status:pending|executed,nth:1") == b
    assert R.resolve_proposal(conn, "gate:G4") == c and R.resolve_proposal(conn, str(b)) == b and R.resolve_proposal(conn, "last") == c
    with pytest.raises(R.ScenarioError):
        R.resolve_proposal(conn, "status:blocked")


def test_judge_and_dig():
    assert R.judge(3, {"gte": 1, "lt": 5})[0] and not R.judge(3, {"gte": 4})[0]
    assert R.judge(None, {"is_null": True})[0] and R.judge(0.51, {"approx": 0.5, "tol": 0.02})[0] and not R.judge(None, {"gte": 1})[0]
    assert R.judge("a", {"in": ["a", "b"]})[0] and R.judge(2, {})[0] is True  # default gte 1
    assert R.dig({"a": [{"b": 7}]}, "a.0.b") == 7 and R.dig({"a": 1}, "a.b.c") is None


# ---------------------------------------------------------------- baselines, reports, persistence, CLI
def test_baseline_regression_detection(h):
    ok = R.run_scenario(h, sc("T01", GOLDEN_SCRIPT, GOLDEN_EXPECT))
    bad = R.run_scenario(h, sc("T02", [{"kind": "enquiry", "ref": "enq_001"}], [{"kind": "state", "name": "x", "spec": {"snapshot": "sent", "eq": 9}}]))
    base = {"tolerance": 0.02, "scenarios": {"T01": {"passed": True, "metrics": {"qualification_accuracy": 1.0}},
                                              "T02": {"passed": False}}}
    cmp = R.compare_to_baseline([ok, bad], base)
    assert cmp["regressions"] == [] and cmp["known_failures"] == ["T02"] and cmp["new_failures"] == []
    ok.metrics["qualification_accuracy"]["value"] = 0.5   # worse than baseline
    ok.passed = False
    cmp = R.compare_to_baseline([ok, bad], base)
    assert {g["kind"] for g in cmp["regressions"]} == {"status", "metric"} and cmp["new_failures"] == ["T01"]
    # lower-is-better metrics regress upwards
    ok.metrics["cost_total"] = {"value": 3.0, "denominator": 1}
    cost_base = {"scenarios": {"T01": {"passed": True, "metrics": {"cost_total": 0.0}}}}
    assert any(g.get("metric") == "cost_total" for g in R.compare_to_baseline([ok], cost_base)["regressions"])


def test_run_suite_persists_and_renders(h):
    scs = [sc("T01", GOLDEN_SCRIPT, GOLDEN_EXPECT), sc("T02", [{"kind": "enquiry", "ref": "enq_001"}],
                                                        [{"kind": "state", "name": "boom", "spec": {"snapshot": "sent", "eq": 9}}], evidence_basis="measured_on_simulation", data_origins=["GT", "MOD"])]
    results, report = R.run_suite(h, scs)
    assert [r.passed for r in results] == [True, False] and report["summary"]["failed"] == 1
    rows = h.conn.execute("SELECT scenario_id, passed, evidence_basis, data_origins FROM ops.eval_result ORDER BY scenario_id").fetchall()
    assert [(r["scenario_id"], r["passed"]) for r in rows] == [("T01", True), ("T02", False)]
    assert rows[1]["evidence_basis"] == "measured_on_simulation" and rows[1]["data_origins"] == ["GT", "MOD"]
    assert h.conn.execute("SELECT count(*) AS n FROM ops.eval_run").fetchone()["n"] == 1
    md = R.render_markdown(report)
    assert "No real-world conversion" in md and "T02" in md and "boom" in md
    json.dumps(report, default=str)


def test_cli(test_url, tmp_path, monkeypatch):
    sdir = tmp_path / "scn"; sdir.mkdir()
    good = sc("T01", GOLDEN_SCRIPT, GOLDEN_EXPECT).model_dump(mode="json")
    (sdir / "T01.yaml").write_text(yaml.safe_dump(good))
    args = ["--scenarios-dir", str(sdir), "--baseline-dir", str(tmp_path / "nob"), "--out-dir", str(tmp_path / "out"),
            "--harness", "fake_harness:make", "--database-url", test_url]
    assert R.main(args) == 0
    assert (tmp_path / "out" / "report.json").exists() and "PASS" in (tmp_path / "out" / "report.md").read_text()
    # update baseline, then break the scenario -> regression -> non-zero exit
    assert R.main(args + ["--update-baseline"]) == 0
    assert json.loads((tmp_path / "nob" / "baseline.json").read_text())["scenarios"]["T01"]["passed"] is True
    bad = dict(good, expectations=good["expectations"] + [{"kind": "state", "name": "x", "spec": {"snapshot": "sent", "eq": 9}}])
    (sdir / "T01.yaml").write_text(yaml.safe_dump(bad))
    assert R.main(args) == 1
    assert R.main(args + ["--scenarios", "S99"]) == 2
    assert R.main(args[:-2] + ["--database-url", "postgresql://u:p@127.0.0.1:5433/gtm"]) == 2
    assert R.main(args + ["--list"]) == 0


def test_enquiry_all_drain_all_and_mid_script_check(h):
    script = [{"kind": "enquiry", "params": {"select": "all", "kinds": ["genuine"]}},
              {"kind": "custom", "params": {"name": "check", "kind": "state", "check_name": "three proposals pending (mid-script)",
                                            "spec": {"sql": "SELECT count(*) FROM ops.proposal WHERE status='pending'", "eq": 3}}},
              {"kind": "human_decision", "ref": "type:message", "params": {"drain": True}}]
    r = R.run_scenario(h, sc(script=script, expectations=[
        {"kind": "state", "name": "all sent", "spec": {"sql": "SELECT count(*) FROM ops.execution WHERE status='succeeded'", "eq": 3}},
        {"kind": "state", "name": "now param", "spec": {"sql": "SELECT count(*) FROM ops.proposal WHERE status='pending' AND expires_at < %(now)s", "eq": 0}}]))
    assert r.passed, r.failures
    assert r.expectations[0].name.startswith("three proposals")  # mid-script checks are reported first


def test_mid_script_check_failure_is_reported(h):
    script = [{"kind": "enquiry", "ref": "enq_001"},
              {"kind": "custom", "params": {"name": "check", "kind": "state", "check_name": "early", "spec": {"snapshot": "sent", "eq": 1}}}]
    r = R.run_scenario(h, sc(script=script))
    assert not r.passed and r.failures[0]["name"] == "early"
