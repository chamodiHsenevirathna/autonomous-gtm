import pytest
from gtm.approvals import decide
from gtm.config import get_settings
from gtm.contracts.gateway import GatewayStatus
from gtm.data import (MatchConfirmationExecutor, MergeError, MergeExecutor, ensure_account, ensure_contact, get_resolved, propose_match,
                      propose_merge, record_observation, resolve_fields, soft_merge, undo_merge)
from gtm.gateway import Gateway

pytestmark = pytest.mark.db
EMIT = lambda *a, **k: None


def two_accounts(conn, clock):
    w, _ = ensure_account(conn, clock, name="Larkspur Freight", domain="larkspur-freight.example")
    l, d = ensure_account(conn, clock, name="Larkspur Freight", domain="larkspur-ltd.example")
    assert d.band == "possible"
    ct, _ = ensure_contact(conn, clock, email="mo.desai@larkspur-ltd.example", full_name="Mo Desai", account_id=l)
    record_observation(conn, clock, entity_type="account", entity_id=l, field="industry", value="Logistics", source="provider_b", observed_at=clock.now())
    record_observation(conn, clock, entity_type="account", entity_id=w, field="industry", value="Logistics", source="provider_a", observed_at=clock.now())
    conn.execute("INSERT INTO gtm.opportunity(account_id, name, created_at, updated_at) VALUES (%s,'Data platform',%s,%s)", (l, clock.now(), clock.now()))
    conn.commit()
    return w, l, ct


def test_soft_merge_and_undo(conn, clock):
    w, l, ct = two_accounts(conn, clock)
    n_obs = conn.execute("SELECT count(*) AS n FROM gtm.observation").fetchone()["n"]
    log = soft_merge(conn, clock, "account", l, w)
    assert conn.execute("SELECT merged_into_id FROM gtm.account WHERE id=%s", (l,)).fetchone()["merged_into_id"] == w
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation").fetchone()["n"] == n_obs            # nothing deleted
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation WHERE entity_id=%s AND entity_type='account'", (l,)).fetchone()["n"] == 0
    assert conn.execute("SELECT account_id FROM gtm.contact WHERE id=%s", (ct,)).fetchone()["account_id"] == w
    assert conn.execute("SELECT account_id FROM gtm.opportunity").fetchone()["account_id"] == w
    assert "larkspur-ltd.example" in {r["domain"] for r in conn.execute("SELECT domain FROM gtm.account_domain WHERE account_id=%s", (w,))}
    row = conn.execute("SELECT * FROM gtm.merge_log WHERE id=%s", (log,)).fetchone()
    assert row["moved_observation_count"] == 1 and row["undone_at"] is None and (row["loser_id"], row["survivor_id"]) == (l, w)
    assert set(get_resolved(conn, "account", w)["industry"]["sources"][0]) >= {"source", "value"}
    assert len(get_resolved(conn, "account", w)["industry"]["sources"]) == 2                              # evidence combined on the survivor
    with pytest.raises(MergeError):
        soft_merge(conn, clock, "account", l, w)                                                          # already merged
    with pytest.raises(MergeError):
        soft_merge(conn, clock, "account", w, w)
    undo_merge(conn, clock, log)
    assert conn.execute("SELECT merged_into_id FROM gtm.account WHERE id=%s", (l,)).fetchone()["merged_into_id"] is None
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation WHERE entity_id=%s AND entity_type='account'", (l,)).fetchone()["n"] == 1
    assert conn.execute("SELECT account_id FROM gtm.contact WHERE id=%s", (ct,)).fetchone()["account_id"] == l
    assert conn.execute("SELECT account_id FROM gtm.opportunity").fetchone()["account_id"] == l
    assert "larkspur-ltd.example" not in {r["domain"] for r in conn.execute("SELECT domain FROM gtm.account_domain WHERE account_id=%s", (w,))}
    assert conn.execute("SELECT undone_at FROM gtm.merge_log WHERE id=%s", (log,)).fetchone()["undone_at"] is not None
    with pytest.raises(MergeError):
        undo_merge(conn, clock, log)
    assert conn.execute("SELECT count(*) AS n FROM ops.audit_event WHERE event_type IN ('merge.executed','merge.undone')").fetchone()["n"] == 2


@pytest.fixture()
def gw(conn, clock):
    g = Gateway(conn, clock, get_settings(), object(), b"test-secret", emit=EMIT)
    g.register_executor("merge", MergeExecutor())
    g.register_executor("match_confirmation", MatchConfirmationExecutor())
    return g


def test_gateway_executes_merge_only_with_approved_proposal(conn, clock, gw):
    w, l, ct = two_accounts(conn, clock)
    pid = propose_merge(conn, clock, "account", l, w, emit=EMIT)
    conn.commit()
    res = gw.attempt(pid)                                                      # pending: no approval
    assert res.status == GatewayStatus.BLOCKED
    assert conn.execute("SELECT merged_into_id FROM gtm.account WHERE id=%s", (l,)).fetchone()["merged_into_id"] is None
    assert conn.execute("SELECT count(*) AS n FROM gtm.merge_log").fetchone()["n"] == 0
    from gtm.approvals import ApprovalError
    with pytest.raises(ApprovalError):                                         # a BDR cannot approve G2 (revops only)
        decide(conn, clock, proposal_id=pid, decided_by="user:dev", decision="approve", emit=EMIT)
    conn.rollback()
    appr = decide(conn, clock, proposal_id=pid, decided_by="user:priya", decision="approve", emit=EMIT)
    conn.commit()
    res = gw.attempt(pid)
    assert res.status == GatewayStatus.EXECUTED and res.external_ref.startswith("merge_log:")
    assert conn.execute("SELECT merged_into_id FROM gtm.account WHERE id=%s", (l,)).fetchone()["merged_into_id"] == w
    assert conn.execute("SELECT approval_id FROM gtm.merge_log").fetchone()["approval_id"] == appr["id"]
    ex = conn.execute("SELECT adapter, status FROM ops.execution WHERE proposal_id=%s", (pid,)).fetchone()
    assert ex == {"adapter": "db.merge", "status": "succeeded"}
    assert gw.attempt(pid).status == GatewayStatus.EXECUTED                    # replay: no second merge
    assert conn.execute("SELECT count(*) AS n FROM gtm.merge_log").fetchone()["n"] == 1


def test_gateway_rejected_proposal_never_merges(conn, clock, gw):
    w, l, _ = two_accounts(conn, clock)
    pid = propose_merge(conn, clock, "account", l, w, emit=EMIT)
    decide(conn, clock, proposal_id=pid, decided_by="user:priya", decision="reject", emit=EMIT)
    conn.commit()
    assert gw.attempt(pid).status == GatewayStatus.BLOCKED
    assert conn.execute("SELECT count(*) AS n FROM gtm.merge_log").fetchone()["n"] == 0


def test_gateway_invalid_merge_is_hard_blocked(conn, clock, gw):
    w, l, _ = two_accounts(conn, clock)
    soft_merge(conn, clock, "account", l, w)
    pid = propose_merge(conn, clock, "account", l, w, emit=EMIT)
    decide(conn, clock, proposal_id=pid, decided_by="user:priya", decision="approve", emit=EMIT)
    conn.commit()
    res = gw.attempt(pid)
    assert res.status == GatewayStatus.BLOCKED and res.block_class == "hard"


def test_match_confirmation_executor_records_decision(conn, clock, gw):
    w, l, _ = two_accounts(conn, clock)
    row = conn.execute("SELECT * FROM gtm.entity_match WHERE left_id=%s AND right_id=%s", (l, w)).fetchone()
    assert row["decision"] == "pending"
    from gtm.data.entity_resolution import MatchDecision
    pid = propose_match(conn, clock, MatchDecision("account", "possible", w, float(row["score"]), {}, "t"), l, emit=EMIT)
    conn.commit()
    assert gw.attempt(pid).status == GatewayStatus.BLOCKED
    assert conn.execute("SELECT decision FROM gtm.entity_match WHERE id=%s", (row["id"],)).fetchone()["decision"] == "pending"
    decide(conn, clock, proposal_id=pid, decided_by="user:dev", decision="approve", emit=EMIT)
    conn.commit()
    assert gw.attempt(pid).status == GatewayStatus.EXECUTED
    m = conn.execute("SELECT decision, decided_by FROM gtm.entity_match WHERE id=%s", (row["id"],)).fetchone()
    assert m == {"decision": "same", "decided_by": "user:dev"}
    # confirmation alone does not merge
    assert conn.execute("SELECT merged_into_id FROM gtm.account WHERE id=%s", (l,)).fetchone()["merged_into_id"] is None
