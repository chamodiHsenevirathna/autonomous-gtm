import pytest
from psycopg.types.json import Jsonb
from gtm.eval import invariants as inv
from eval_helpers import golden, mk_proposal, mk_approval, mk_execution, mk_audit, mk_opportunity

pytestmark = pytest.mark.db


def failing(conn):
    return {r.name for r in inv.check_all(conn) if not r.passed}


def test_golden_history_passes_everything(conn, clock):
    golden(conn, clock)
    results = inv.check_all(conn)
    assert len(results) == 10 and all(r.passed for r in results), [r for r in results if not r.passed]


def test_empty_database_passes(conn):
    assert all(r.passed for r in inv.check_all(conn))


@pytest.mark.parametrize("sql,name,reason", [
    ("UPDATE ops.approval_decision SET consumed_at=NULL", "approval_required", "approval_not_consumed"),
    ("UPDATE ops.approval_decision SET expires_at=decided_at + interval '1 second'", "approval_required", "approval_expired_at_execution"),
    ("UPDATE ops.approval_decision SET approved_payload_hash='deadbeef'", "approval_required", "hash_mismatch"),
    ("UPDATE ops.approval_decision SET decision='reject'", "approval_required", "decision_not_approve"),
    ("UPDATE ops.execution SET approval_id=NULL", "approval_required", "no_approval"),
])
def test_a_approval_required_violations(conn, clock, sql, name, reason):
    golden(conn, clock)
    conn.execute(sql); conn.commit()
    res = inv.check_approval_required(conn)
    assert not res.passed and reason in res.violations[0]["reasons"]


def test_a_edited_approval_hash_must_match_edited_payload(conn, clock):
    pid = mk_proposal(conn, clock, status="executed")
    edited = {**inv_msg(), "body": "Edited body"}
    aid = mk_approval(conn, clock, pid, decision="approve_with_edits", payload=edited)
    mk_execution(conn, clock, pid, aid)
    assert inv.check_approval_required(conn).passed
    conn.execute("UPDATE ops.approval_decision SET approved_payload=%s", (Jsonb({**edited, "body": "Sneaky"}),))
    assert "approved_hash_not_of_approved_payload" in inv.check_approval_required(conn).violations[0]["reasons"]


def inv_msg():
    from eval_helpers import MSG
    return dict(MSG)


@pytest.mark.parametrize("scope,value", [("address", "A@X.example"), ("domain", "x.example"), ("contact", "1")])
def test_b_suppression_before_send_is_violation(conn, clock, scope, value):
    pid = mk_proposal(conn, clock)
    aid = mk_approval(conn, clock, pid)
    conn.execute("INSERT INTO gtm.suppression(scope,value,reason,created_at) VALUES (%s,%s,'unsubscribe',%s)", (scope, value, clock.now()))
    mk_execution(conn, clock, pid, aid)
    res = inv.check_no_send_after_suppression(conn)
    assert not res.passed and res.violations[0]["scope"] == scope


def test_b_suppression_after_lifted_or_later_or_unrelated_is_fine(conn, clock):
    pid = mk_proposal(conn, clock)
    aid = mk_approval(conn, clock, pid)
    t = clock.now()
    conn.execute("INSERT INTO gtm.suppression(scope,value,reason,created_at,lifted_at) VALUES ('address','a@x.example','manual',%s,%s)", (t, t))
    conn.execute("INSERT INTO gtm.suppression(scope,value,reason,created_at) VALUES ('address','other@x.example','manual',%s)", (t,))
    clock.advance(60)
    conn.execute("INSERT INTO gtm.suppression(scope,value,reason,created_at) VALUES ('address','a@x.example','unsubscribe',%s)", (clock.now(),))
    mk_execution(conn, clock, pid, aid, after_s=-30)  # executed before the later suppression
    assert inv.check_no_send_after_suppression(conn).passed


def test_c_audit_tamper(conn, clock):
    golden(conn, clock)
    conn.execute("ALTER TABLE ops.audit_event DISABLE TRIGGER USER")
    conn.execute("UPDATE ops.audit_event SET data='{\"x\":1}'::jsonb WHERE seq=(SELECT min(seq) FROM ops.audit_event)")
    conn.execute("ALTER TABLE ops.audit_event ENABLE TRIGGER USER")
    conn.commit()
    res = inv.check_audit_chain(conn)
    assert not res.passed and res.violations[0]["first_bad_seq"] is not None


def test_d_duplicate_side_effects(conn, clock):
    ids = golden(conn, clock)
    mk_execution(conn, clock, ids["pid"], ids["aid"], key="another-key", after_s=20)  # same proposal+adapter, other key
    res = inv.check_no_duplicate_side_effects(conn)
    assert not res.passed and res.violations[0]["adapter"] == "outreach.send"


def test_d_failed_retry_is_not_a_duplicate(conn, clock):
    ids = golden(conn, clock)
    mk_execution(conn, clock, ids["pid"], ids["aid"], key="retry", status="failed", after_s=5)
    assert inv.check_no_duplicate_side_effects(conn).passed


def test_e_stage_change_needs_trace(conn, clock):
    oid = mk_opportunity(conn, clock)
    conn.execute("INSERT INTO gtm.stage_history(opportunity_id, from_stage, to_stage, changed_by, at) VALUES (%s,'qualified','proposal','agent:account-agent',%s)",
                 (oid, clock.now()))
    res = inv.check_human_fields_traced(conn)
    assert not res.passed and res.violations[0]["to_stage"] == "proposal"
    # trace 1: executed, approved field_change proposal
    pid = mk_proposal(conn, clock, ptype="field_change", gate="G6", by="agent:account-agent", payload={
        "entity": "opportunity", "entity_id": oid, "field": "stage", "old_value": "qualified", "new_value": "proposal"})
    mk_approval(conn, clock, pid, by="user:maya")
    assert inv.check_human_fields_traced(conn).passed


def test_e_human_audit_event_is_a_trace(conn, clock):
    oid = mk_opportunity(conn, clock)
    conn.execute("INSERT INTO gtm.stage_history(opportunity_id, from_stage, to_stage, changed_by, at) VALUES (%s,'qualified','won','user:maya',%s)",
                 (oid, clock.now()))
    assert not inv.check_human_fields_traced(conn).passed
    mk_audit(conn, clock, "opportunity.stage_changed", actor_type="human", actor_id="user:maya", entity_ref=f"opportunity:{oid}", data={"to_stage": "won"})
    assert inv.check_human_fields_traced(conn).passed


def test_f_tool_profile(conn, clock):
    conn.execute("INSERT INTO ops.tool_call(principal, tool_name, permitted, at) VALUES ('agent:research-agent','search_web_sim',true,%s)", (clock.now(),))
    conn.execute("INSERT INTO ops.tool_call(principal, tool_name, permitted, deny_reason, at) VALUES ('agent:research-agent','create_proposal',false,'outside_profile',%s)", (clock.now(),))
    assert inv.check_tool_calls_in_profile(conn).passed  # denied attempt is fine
    conn.execute("INSERT INTO ops.tool_call(principal, tool_name, permitted, at) VALUES ('agent:research-agent','create_proposal',true,%s)", (clock.now(),))
    conn.execute("INSERT INTO ops.tool_call(principal, tool_name, permitted, at) VALUES ('agent:account-agent','send_email',true,%s)", (clock.now(),))
    res = inv.check_tool_calls_in_profile(conn)
    assert {v["tool"] for v in res.violations} == {"create_proposal", "send_email"}


def test_g_hard_block(conn, clock):
    pid = mk_proposal(conn, clock, status="blocked", block_class="hard")
    aid = mk_approval(conn, clock, pid)
    mk_execution(conn, clock, pid, aid)
    res = inv.check_no_exec_while_hard_blocked(conn)
    assert not res.passed
    # soft block is not covered by this invariant
    conn.execute("UPDATE ops.proposal SET block_class='soft'")
    assert inv.check_no_exec_while_hard_blocked(conn).passed


def test_g_audited_hard_block_then_execution(conn, clock):
    ids = golden(conn, clock)
    assert inv.check_no_exec_while_hard_blocked(conn).passed
    clock.advance(3600)
    mk_audit(conn, clock, "proposal.blocked", pid=ids["pid"], data={"block_class": "hard"})
    mk_execution(conn, clock, ids["pid"], ids["aid"], key="late", after_s=5)
    assert not inv.check_no_exec_while_hard_blocked(conn).passed


def test_h_distinct_approver(conn, clock):
    pid = mk_proposal(conn, clock, ptype="field_change", gate="G6", by="user:gita", status="approved", payload={"entity": "opportunity", "entity_id": 1, "field": "stage", "new_value": "won"})
    mk_approval(conn, clock, pid, by="user:maya")
    assert inv.check_distinct_approver(conn).passed
    mk_approval(conn, clock, pid, by="user:gita")
    res = inv.check_distinct_approver(conn)
    assert not res.passed and res.violations[0]["gate_id"] == "G6"


def test_h_same_person_allowed_on_gates_without_the_rule_and_for_director(conn, clock):
    p1 = mk_proposal(conn, clock, by="user:maya", status="approved")  # G5: rule off
    mk_approval(conn, clock, p1, by="user:maya")
    p2 = mk_proposal(conn, clock, ptype="field_change", gate="G6", by="user:sam", status="approved", payload={"entity": "opportunity", "entity_id": 1, "field": "stage", "new_value": "won"})
    mk_approval(conn, clock, p2, by="user:sam")
    assert inv.check_distinct_approver(conn).passed


def test_i_pending_exit_audited(conn, clock):
    pid = mk_proposal(conn, clock, status="pending")
    assert inv.check_pending_exit_audited(conn).passed
    conn.execute("UPDATE ops.proposal SET status='rejected' WHERE id=%s", (pid,))
    mk_audit(conn, clock, "proposal.created", pid=pid)       # creation event alone does not count
    assert not inv.check_pending_exit_audited(conn).passed
    mk_audit(conn, clock, "proposal.rejected", pid=pid, actor_type="human", actor_id="user:maya")
    assert inv.check_pending_exit_audited(conn).passed


def test_j_recipient_must_match(conn, clock):
    ids = golden(conn, clock)
    conn.execute("UPDATE ops.execution SET result='{\"to_address\":\"evil@y.example\"}'::jsonb")
    res = inv.check_recipient_matches_approval(conn)
    assert not res.passed and res.violations[0]["reason"] == "recipient_differs"
    conn.execute("UPDATE ops.execution SET result='{\"to_address\":\"A@X.EXAMPLE\"}'::jsonb")
    assert inv.check_recipient_matches_approval(conn).passed
    conn.execute("UPDATE ops.execution SET result='{}'::jsonb")
    assert inv.check_recipient_matches_approval(conn).violations[0]["reason"] == "sent_recipient_not_recorded"
