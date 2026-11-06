from datetime import timedelta
import pytest
from gtm import config
from gtm.contracts.errors import PolicyDenied
from gtm.contracts.events import EventEnvelope
from gtm.orchestration import Runner, Services, emit
from gtm.pipeline import ScanParams, MONITOR_PRINCIPAL, build_graphs, check_narrative, scan_pipeline, set_opportunity_system_fields, weekly_digest


def mk_opp(conn, clock, *, name="Deal", stage="proposal", acct=None, contacts=2, close_days=60, amount=1000, next_step="call", service_line=None):
    if acct is None:
        acct = conn.execute("INSERT INTO gtm.account(name, owner_principal, created_at, updated_at) VALUES (%s,'user:maya',%s,%s) RETURNING id",
                            (f"A{clock.now().timestamp()}{name}", clock.now(), clock.now())).fetchone()["id"]
    o = conn.execute("INSERT INTO gtm.opportunity(account_id, name, stage, amount, close_date, next_step, owner_principal, service_line, last_activity_at, created_at, updated_at) "
                     "VALUES (%s,%s,%s,%s,%s,%s,'user:maya',%s,%s,%s,%s) RETURNING id",
                     (acct, name, stage, amount, (clock.now() + timedelta(days=close_days)).date(), next_step, service_line, clock.now(), clock.now(), clock.now())).fetchone()["id"]
    for i in range(contacts):
        c = conn.execute("INSERT INTO gtm.contact(account_id, full_name, created_at, updated_at) VALUES (%s,%s,%s,%s) RETURNING id", (acct, f"P{o}{i}", clock.now(), clock.now())).fetchone()["id"]
        conn.execute("INSERT INTO gtm.opportunity_contact(opportunity_id, contact_id) VALUES (%s,%s)", (o, c))
    return o


def opp(conn, o):
    return conn.execute("SELECT * FROM gtm.opportunity WHERE id=%s", (o,)).fetchone()


P = ScanParams(stage_dwell_days={'default': 90})


def test_s22_stall_flag_clear_and_human_fields(conn, clock):
    o = mk_opp(conn, clock, contacts=1)
    before = opp(conn, o)
    clock.advance(days=45)
    r = scan_pipeline(conn, clock, params=P)
    row = opp(conn, o)
    assert row["is_stalled"] and "no_activity:45d" in row["stall_reason"] and "single_threaded" in row["stall_reason"] and row["days_in_stage"] == 45
    assert r["flagged"] == 1
    assert conn.execute("SELECT count(*) AS n FROM ops.domain_event WHERE type='deal.flagged'").fetchone()["n"] == 1
    for f in ("stage", "amount", "close_date", "next_step", "owner_principal", "forecast_category"):
        assert row[f] == before[f]
    assert conn.execute("SELECT count(*) AS n FROM gtm.stage_history").fetchone()["n"] == 0
    props = conn.execute("SELECT type, proposed_by, status FROM ops.proposal").fetchall()
    assert props and all(p["type"] == "task" and p["proposed_by"] == MONITOR_PRINCIPAL and p["status"] == "pending" for p in props)
    # idempotent
    r2 = scan_pipeline(conn, clock, params=P)
    assert r2["flagged"] == 0 and conn.execute("SELECT count(*) AS n FROM ops.domain_event WHERE type='deal.flagged'").fetchone()["n"] == 1
    n_props = conn.execute("SELECT count(*) AS n FROM ops.proposal").fetchone()["n"]
    scan_pipeline(conn, clock, params=P)
    assert conn.execute("SELECT count(*) AS n FROM ops.proposal").fetchone()["n"] == n_props
    # activity clears
    conn.execute("INSERT INTO gtm.activity(opportunity_id, account_id, type, actor, created_at) VALUES (%s,%s,'call','user:maya',%s)", (o, row["account_id"], clock.now()))
    r3 = scan_pipeline(conn, clock, params=P)
    assert r3["cleared"] == 1 and not opp(conn, o)["is_stalled"] and opp(conn, o)["stall_reason"] is None
    assert conn.execute("SELECT count(*) AS n FROM ops.audit_event WHERE event_type='deal.stall_cleared'").fetchone()["n"] == 1


def test_rules(conn, clock):
    dwell = mk_opp(conn, clock, name="dwell")
    late = mk_opp(conn, clock, name="late", close_days=-1)
    ok = mk_opp(conn, clock, name="ok")
    conn.execute("INSERT INTO gtm.stage_history(opportunity_id, to_stage, at) VALUES (%s,'proposal',%s)", (dwell, clock.now() - timedelta(days=40)))
    clock.advance(days=3)
    conn.execute("UPDATE gtm.opportunity SET last_activity_at=%s", (clock.now(),))
    scan_pipeline(conn, clock)
    assert "stage_dwell:43d" in opp(conn, dwell)["stall_reason"]
    assert "close_date_passed" in opp(conn, late)["stall_reason"]
    assert not opp(conn, ok)["is_stalled"]


def test_closed_ignored(conn, clock):
    o = mk_opp(conn, clock, stage="closed_lost")
    clock.advance(days=90)
    assert scan_pipeline(conn, clock)["scanned"] == 0 and not opp(conn, o)["is_stalled"]


def test_policy_blocks_human_fields(conn, clock):
    o = mk_opp(conn, clock)
    for f in ("stage", "amount", "close_date", "next_step"):
        with pytest.raises(PolicyDenied):
            set_opportunity_system_fields(conn, clock, principal=MONITOR_PRINCIPAL, opportunity_id=o, fields={f: "x"})
    with pytest.raises(PolicyDenied):
        set_opportunity_system_fields(conn, clock, principal="agent:account-agent", opportunity_id=o, fields={"is_stalled": True})
    assert set_opportunity_system_fields(conn, clock, principal="system:rules", opportunity_id=o, fields={"is_stalled": True})


def test_hygiene_proposals_only(conn, clock):
    acct = conn.execute("INSERT INTO gtm.account(name, created_at, updated_at) VALUES ('Dup',%s,%s) RETURNING id", (clock.now(), clock.now())).fetchone()["id"]
    o = mk_opp(conn, clock, acct=acct, name="Hole", amount=None, next_step=None, service_line="x")
    conn.execute("UPDATE gtm.opportunity SET close_date=NULL WHERE id=%s", (o,))
    mk_opp(conn, clock, acct=acct, name="Hole2", service_line="x")
    snap = opp(conn, o)
    r = scan_pipeline(conn, clock)
    titles = [p["payload"]["title"] for p in conn.execute("SELECT payload FROM ops.proposal").fetchall()]
    assert any("close date" in t for t in titles) and any("amount" in t for t in titles) and any("next step" in t for t in titles) and any("duplicate" in t.lower() for t in titles)
    assert r["duplicates"] == 1
    row = opp(conn, o)
    assert (row["amount"], row["close_date"], row["next_step"]) == (snap["amount"], snap["close_date"], snap["next_step"])
    n = conn.execute("SELECT count(*) AS n FROM ops.proposal").fetchone()["n"]
    scan_pipeline(conn, clock)
    assert conn.execute("SELECT count(*) AS n FROM ops.proposal").fetchone()["n"] == n


def test_digest_numbers_from_sql(conn, clock):
    mk_opp(conn, clock, amount=100, contacts=1)
    mk_opp(conn, clock, amount=300, name="b")
    clock.advance(days=20)
    scan_pipeline(conn, clock)
    d = weekly_digest(conn, clock, narrative_fn=lambda n: f"There are {n['open_opportunities']} open deals and {n['stalled']} stalled.")
    n = d["numbers"]
    assert n["open_opportunities"] == 2 and n["open_amount"] == 400 and n["stalled"] == 2 and n["single_threaded"] == 1 and n["by_stage"] == {"proposal": 2}
    assert d["narrative"] and d["narrative_check"]["ok"]
    bad = weekly_digest(conn, clock, narrative_fn=lambda n: "There are 7 open deals.")
    assert bad["narrative"] is None and bad["narrative_check"]["unsupported"] == ["7"]
    assert check_narrative("400 total", n)["ok"]


def test_scan_graph_via_runner(conn, clock):
    o = mk_opp(conn, clock)
    clock.advance(days=45)
    r = Runner(conn, clock, Services(config.get_settings(), clock))
    for g in build_graphs():
        r.register(g)
    emit(conn, clock, EventEnvelope(type="pipeline.scan", occurred_at=clock.now(), source="test", dedupe_key="scan1"))
    conn.commit()
    r.run_until_idle()
    assert opp(conn, o)["is_stalled"]
    run = conn.execute("SELECT status FROM ops.agent_run WHERE workflow='pipeline_scan'").fetchone()
    assert run["status"] == "completed"
