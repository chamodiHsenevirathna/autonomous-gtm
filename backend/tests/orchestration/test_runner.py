from datetime import timedelta
import pytest
from gtm import audit, db
from gtm.contracts.errors import NotReady, PermanentError, PolicyDenied, RetryableError
from gtm.contracts.events import EventEnvelope
from gtm.orchestration import Graph, Retry, Runner, Services, add_schedule, emit, leases
from tests.orchestration.conftest import make_env, run_of, steps


class Crash(BaseException):
    """Simulated process death (not caught by the runner)."""


def go(conn, clock, runner, g, env, adv=True, **kw):
    runner.register(g)
    emit(conn, clock, env(**kw)); conn.commit()
    return runner.run_until_idle(advance_clock=adv)


def base(name="wf", **kw):
    g = Graph(name, **kw)
    g.trigger("t", "lead.received")
    return g


def test_fanout_fanin_failing_item_partial(conn, clock, runner, env):
    g = base()
    g.code("src", lambda ctx: {"urls": ["a", "b", "c", "d"]})

    def look(ctx, u):
        if u == "c":
            raise PermanentError("404")
        return {"t": u.upper()}
    g.map("look", lambda ctx: ctx.state["src"]["urls"], look, after="src", concurrency=2)
    g.reduce("merge", "look", lambda ctx, res: {"ok": [v["output"]["t"] for v in res.values() if v["ok"]], "gaps": [k for k, v in res.items() if not v["ok"]]})
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "completed"
    assert r["state"]["merge"] == {"ok": ["A", "B", "D"], "gaps": ["2"]}
    assert r["state"]["look"]["failed"] == 1
    items = [(s["item_key"], s["status"]) for s in steps(conn, r["id"]) if s["node_id"] == "look" and s["item_key"] != "__items__"]
    assert items == [("0", "succeeded"), ("1", "succeeded"), ("2", "failed"), ("3", "succeeded")]


def test_map_item_retry_does_not_repeat_finished_items(conn, clock, runner, env):
    calls = []
    g = base()

    def look(ctx, i):
        calls.append(i)
        if i == 1 and calls.count(1) < 3:
            raise RetryableError("503")
        return {"i": i}
    g.map("m", lambda ctx: [0, 1, 2], look)
    go(conn, clock, runner, g, env)
    assert run_of(conn)["status"] == "completed"
    assert calls.count(0) == 1 and calls.count(2) == 1 and calls.count(1) == 3


def test_retry_then_success_with_backoff(conn, clock, runner, env):
    times = []

    def flaky(ctx):
        times.append(clock.now())
        if len(times) < 3:
            raise RetryableError("503")
        return {"ok": True}
    g = base().tool("t1", flaky)
    t0 = clock.now()
    go(conn, clock, runner, g, env)
    assert run_of(conn)["status"] == "completed"
    assert [s["status"] for s in steps(conn) if s["node_id"] == "t1"] == ["retrying", "retrying", "succeeded"]
    d1, d2 = (times[1] - times[0]).total_seconds(), (times[2] - times[1]).total_seconds()
    assert 1 <= d1 <= 2 and 2 <= d2 <= 4                       # base 2s, 2**n growth, jitter in [0.5, 1]


def test_backoff_is_deterministic(conn, clock, test_url, env, services):
    def once(c):
        cl = type(clock)()
        ts = []

        def f(ctx):
            ts.append(cl.now())
            if len(ts) < 3:
                raise RetryableError("x")
            return {}
        r = Runner(c, cl, Services(settings=services.settings, clock=cl))
        g = base("det").tool("t1", f); r.register(g)
        emit(c, cl, make_env(cl, key="same")); c.commit(); r.run_until_idle()
        return [x.isoformat() for x in ts]
    a = once(conn)
    db.truncate_all(conn); conn.commit()
    from gtm import seed; seed.seed_reference(conn)
    assert once(conn) == a


def test_retry_exhausted_needs_attention_and_resume(conn, clock, runner, env):
    state = {"fail": True}

    def f(ctx):
        if state["fail"]:
            raise RetryableError("down")
        return {"ok": 1}
    g = base().tool("t1", f, retry=Retry(3, 1, 4)).code("after", lambda ctx: {"x": 1}, after="t1")
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "needs_attention" and "t1" in r["error"]
    assert len([s for s in steps(conn) if s["node_id"] == "t1"]) == 3
    state["fail"] = False
    runner.resume(r["id"]); runner.run_until_idle()
    assert run_of(conn)["status"] == "completed"


@pytest.mark.parametrize("exc", [PermanentError("bad"), PolicyDenied("no"), ValueError("bug")])
def test_permanent_policy_and_bug_fail_without_retry(conn, clock, runner, env, exc):
    n = []

    def f(ctx):
        n.append(1)
        raise exc
    g = base().tool("t1", f).code("never", lambda ctx: {}, after="t1")
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "needs_attention" and len(n) == 1
    assert "never" not in r["state"]
    assert [s["status"] for s in steps(conn) if s["node_id"] == "t1"] == ["failed"]


def test_on_error_continue(conn, clock, runner, env):
    g = base().tool("t1", lambda ctx: (_ for _ in ()).throw(PermanentError("x")), on_error="continue")
    g.code("c", lambda ctx: {"saw": ctx.state["t1"]["error"]}, after="t1")
    go(conn, clock, runner, g, env)
    assert run_of(conn)["status"] == "completed"


def test_timeout_is_retryable_on_sim_clock(conn, clock, runner, env):
    calls = []

    def slow(ctx):
        calls.append(1)
        clock.advance(seconds=100 if len(calls) == 1 else 1)
        return {}
    g = base().tool("t1", slow, timeout=30)
    go(conn, clock, runner, g, env)
    assert len(calls) == 2 and run_of(conn)["status"] == "completed"
    assert "timeout" in conn.execute("SELECT error FROM ops.run_step WHERE status='retrying'").fetchone()["error"]


def test_notready_parks_then_resumes_by_polling(conn, clock, runner, env):
    ready_at = clock.now() + timedelta(seconds=90)

    def f(ctx):
        if clock.now() < ready_at:
            raise NotReady("not synced yet")
        return {"visible": True}
    g = base().tool("sync", f).code("send", lambda ctx: {"sent": True}, after="sync")
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "completed"
    st = [s["status"] for s in steps(conn) if s["node_id"] == "sync"]
    assert st[-1] == "succeeded" and set(st[:-1]) == {"parked"}
    assert st.count("parked") >= 2


def test_notready_deadline_parks_run_not_fail(conn, clock, runner, env):
    g = base(park_deadline=120).tool("sync", lambda ctx: (_ for _ in ()).throw(NotReady("never")))
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "needs_attention" and "not ready" in r["error"]


def test_wait_resumes_on_event(conn, clock, runner, env):
    g = base().wait("sync", event="sync.contact_visible", poll=None, deadline=1800,
                    match=lambda ctx, e: e.payload.get("contact") == 5)
    g.code("go", lambda ctx: {"via": ctx.state["sync"]["via"]}, after="sync")
    go(conn, clock, runner, g, env, adv=False)
    assert run_of(conn)["status"] == "waiting"
    emit(conn, clock, env(type="sync.contact_visible", payload={"contact": 9})); conn.commit()
    runner.run_until_idle(advance_clock=False)
    assert run_of(conn)["status"] == "waiting"                    # non-matching event: still waiting
    emit(conn, clock, env(type="sync.contact_visible", payload={"contact": 5})); conn.commit()
    runner.run_until_idle(advance_clock=False)
    r = run_of(conn)
    assert r["status"] == "completed" and r["state"]["go"] == {"via": "event"}
    assert r["state"]["_event_waits"] == []


def test_wait_resumes_by_polling_with_backoff(conn, clock, runner, env):
    polls = []
    ready = clock.now() + timedelta(seconds=100)

    def until(ctx):
        polls.append(clock.now())
        return {"seen": True} if clock.now() >= ready else None
    g = base().wait("w", until, poll=(5, 2, 40), deadline=1800)
    go(conn, clock, runner, g, env)
    assert run_of(conn)["status"] == "completed"
    gaps = [round((b - a).total_seconds()) for a, b in zip(polls, polls[1:])]
    assert gaps[:4] == [5, 10, 20, 40] and max(gaps) <= 40


def test_wait_deadline_parks_with_needs_attention(conn, clock, runner, env):
    g = base().wait("w", lambda ctx: None, poll=(10, 2, 60), deadline=300)
    g.code("after", lambda ctx: {}, after="w")
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "needs_attention" and "wait_deadline" in r["error"]
    assert conn.execute("SELECT count(*) n FROM ops.audit_event WHERE event_type='run.parked'").fetchone()["n"] == 1
    assert conn.execute("SELECT status FROM ops.run_step WHERE node_id='w' ORDER BY id DESC LIMIT 1").fetchone()["status"] == "parked"


def _proposal(conn, clock):
    return conn.execute("INSERT INTO ops.proposal(type, gate_id, payload, payload_hash, proposed_by, created_at) "
                        "VALUES ('task','G7','{}','h','agent:account-agent',%s) RETURNING id", (clock.now(),)).fetchone()["id"]


def test_approval_node_by_event_and_by_status(conn, clock, runner, env):
    pid = _proposal(conn, clock)
    g = base().approval("gate", lambda ctx: pid).code("exec", lambda ctx: {"d": ctx.state["gate"]["decision"]}, after="gate")
    go(conn, clock, runner, g, env, adv=False)
    assert run_of(conn)["status"] == "waiting"
    emit(conn, clock, env(type="proposal.rejected", payload={"proposal_id": pid + 100})); conn.commit()
    runner.run_until_idle(advance_clock=False)
    assert run_of(conn)["status"] == "waiting"
    emit(conn, clock, env(type="proposal.approved", payload={"proposal_id": pid})); conn.commit()
    runner.run_until_idle(advance_clock=False)
    r = run_of(conn)
    assert r["status"] == "completed" and r["state"]["exec"] == {"d": "approved"}
    # status-poll path: decision already recorded before the wait starts
    pid2 = _proposal(conn, clock)
    conn.execute("UPDATE ops.proposal SET status='rejected' WHERE id=%s", (pid2,))
    g2 = base("wf2").approval("gate", lambda ctx: pid2)
    go(conn, clock, runner, g2, env)
    assert run_of(conn, "wf2")["state"]["gate"]["decision"] == "rejected"


def test_approval_expiry_parks(conn, clock, runner, env):
    pid = _proposal(conn, clock)
    go(conn, clock, runner, base().approval("gate", lambda ctx: pid), env)
    r = run_of(conn)
    assert r["status"] == "needs_attention" and "wait_deadline" in r["error"]
    assert (clock.now() - r["started_at"]).total_seconds() >= runner.services.settings.approval_ttl_hours * 3600


def test_conditional_branch_and_join(conn, clock, runner, env):
    g = base().conditional("c", lambda ctx: "yes")
    g.code("y", lambda ctx: {"v": "y"}, after="c", when=("c", "yes"))
    g.code("n", lambda ctx: {"v": "n"}, after="c", when=("c", "no"))
    g.code("end", lambda ctx: {"got": ctx.state.get("y", {}).get("v")}, after=["y", "n"], join=True)
    g.code("strict", lambda ctx: {}, after=["y", "n"])
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "completed" and r["state"]["end"] == {"got": "y"}
    assert set(r["state"]["_skipped"]) == {"n", "strict"}


def test_side_effecting_adapter_lint():
    with pytest.raises(ValueError):
        base().tool("send", lambda ctx: {}, adapter="outreach.send")


def test_crash_restart_resumes_without_duplicate_side_effects(conn, clock, test_url, services, env):
    effects, crash = [], {"on": True}
    g = lambda: _crash_graph(effects, crash)
    r1 = Runner(conn, clock, services, worker_id="w1")
    r1.register(g())
    emit(conn, clock, env()); conn.commit()
    with pytest.raises(Crash):
        r1.run_until_idle()
    assert effects == ["send"] and conn.execute("SELECT status FROM ops.job").fetchone()["status"] == "leased"
    crash["on"] = False
    c2 = db.connect(test_url)                                    # a brand-new process/connection
    r2 = Runner(c2, clock, services, worker_id="w2")
    r2.register(g())
    r2.run_until_idle()                                          # jumps to lease expiry, resumes at 'finish'
    row = c2.execute("SELECT * FROM ops.agent_run").fetchone()
    assert row["status"] == "completed" and effects == ["send"]  # effect NOT repeated
    sts = [(s["node_id"], s["status"]) for s in steps(c2)]
    assert ("t", "succeeded") in sts and sts.count(("send", "succeeded")) == 1
    assert ("finish", "failed") in sts and ("finish", "succeeded") in sts      # orphan 'running' attempt marked failed(crash)
    c2.close()


def _crash_graph(effects, crash):
    def send(ctx):
        ctx.once("email", lambda: effects.append("send") or {"sent": 1})
        return {"done": True}

    def finish(ctx):
        if crash["on"]:
            raise Crash()
        return {"fin": True}
    return base().tool("send", send).code("finish", finish, after="send")


def test_crash_inside_node_after_effect_is_not_repeated(conn, clock, test_url, services, env):
    effects, crash = [], {"on": True}

    def send(ctx):
        ctx.once("email", lambda: effects.append("send") or {"sent": 1})
        if crash["on"]:
            raise Crash()                                        # dies after the effect, before the step commits
        return {"done": True}
    mk = lambda: base().tool("send", send)
    r1 = Runner(conn, clock, services); r1.register(mk())
    emit(conn, clock, env()); conn.commit()
    with pytest.raises(Crash):
        r1.run_until_idle()
    crash["on"] = False
    c2 = db.connect(test_url)
    r2 = Runner(c2, clock, services); r2.register(mk()); r2.run_until_idle()
    assert effects == ["send"] and c2.execute("SELECT status FROM ops.agent_run").fetchone()["status"] == "completed"
    c2.close()


def test_idempotent_step_replay_returns_stored_result(conn, clock, runner, env):
    calls = []
    g = base().tool("t1", lambda ctx: calls.append(1) or {"v": len(calls)})
    go(conn, clock, runner, g, env)
    run = run_of(conn)
    key = conn.execute("SELECT key FROM ops.idempotency_record WHERE key LIKE %s", (f"wf@1:{run['id']}:t1:%",)).fetchone()["key"]
    assert key == f"wf@1:{run['id']}:t1:"
    # simulate lost progress for the node (state and step rows gone), then resume
    st = run["state"]; st.pop("t1")
    from psycopg.types.json import Jsonb
    conn.execute("UPDATE ops.agent_run SET state=%s, status='needs_attention' WHERE id=%s", (Jsonb(st), run["id"])); conn.commit()
    runner.resume(run["id"]); runner.run_until_idle()
    r = run_of(conn)
    assert calls == [1] and r["state"]["t1"] == {"v": 1} and r["status"] == "completed"


def test_duplicate_trigger_does_not_start_second_run(conn, clock, runner, env):
    g = base().code("a", lambda ctx: {})
    runner.register(g)
    e = env(key="same-lead")
    emit(conn, clock, e); emit(conn, clock, e); runner.start("wf", e); runner.start("wf", e); conn.commit()
    runner.run_until_idle()
    assert conn.execute("SELECT count(*) n FROM ops.agent_run").fetchone()["n"] == 1


def test_lease_fencing_rejects_stale_writer(conn, clock, test_url, services, env):
    thief = db.connect(test_url)
    wrote = []

    def slow_writer(ctx):
        clock.advance(seconds=1000)                              # this run stalls past its lease ...
        assert leases.acquire(thief, clock, 7, 9999, 300) == ctx.fencing_token + 1   # ... another run takes over
        thief.commit()
        wrote.append("zombie")
        return {"x": 1}
    g = base(lease=True).code("w", slow_writer).code("after", lambda ctx: {}, after="w")
    r = Runner(conn, clock, services, lease_seconds=300)
    r.register(g)
    emit(conn, clock, env(account_id=7)); conn.commit()
    r.run_until_idle(max_steps=1)
    run = run_of(conn)
    assert wrote == ["zombie"] and "w" not in run["state"]       # its output was discarded
    assert run["status"] == "waiting"                            # LeaseLost -> NOT_READY -> parked, will re-acquire
    assert conn.execute("SELECT status FROM ops.run_step WHERE node_id='w' ORDER BY id DESC LIMIT 1").fetchone()["status"] == "parked"
    thief.close()


def test_lease_basics(conn, clock):
    t1 = leases.acquire(conn, clock, 1, 10, 60)
    assert leases.acquire(conn, clock, 1, 11, 60) is None        # live holder
    assert leases.acquire(conn, clock, 1, 10, 60) == t1          # re-entrant
    clock.advance(seconds=61)
    t2 = leases.acquire(conn, clock, 1, 11, 60)
    assert t2 == t1 + 1
    with pytest.raises(leases.LeaseLost):
        leases.check(conn, clock, 1, 10, t1, 60)
    leases.check(conn, clock, 1, 11, t2, 60)


def test_lease_serialises_runs_for_same_account(conn, clock, runner, env):
    order = []
    g = base(lease=True).code("w", lambda ctx: order.append(ctx.run_id) or {})
    runner.register(g)
    emit(conn, clock, env(account_id=3)); emit(conn, clock, env(account_id=3)); conn.commit()
    runner.run_until_idle()
    assert len(order) == 2 and conn.execute("SELECT count(*) n FROM ops.agent_run WHERE status='completed'").fetchone()["n"] == 2
    assert conn.execute("SELECT holder_run_id FROM ops.account_lease").fetchone()["holder_run_id"] is None


def test_schedule_fires_heartbeat_events(conn, clock, runner):
    g = Graph("wake"); g.trigger("t", "heartbeat.due"); g.code("a", lambda ctx: {"acct": ctx.account_id})
    runner.register(g)
    add_schedule(conn, clock, "heartbeat", "account:5", 3600); conn.commit()
    res = runner.run_until_idle(horizon=clock.now() + timedelta(hours=3, minutes=1))
    evs = conn.execute("SELECT type, account_id, entity_ref FROM ops.domain_event ORDER BY id").fetchall()
    assert len(evs) == 4 and all(e["type"] == "heartbeat.due" and e["account_id"] == 5 for e in evs)
    assert conn.execute("SELECT count(*) n FROM ops.agent_run WHERE status='completed'").fetchone()["n"] == 4
    assert res["scheduled"] == 4
    nxt = conn.execute("SELECT next_run_at FROM ops.schedule").fetchone()["next_run_at"]
    assert nxt > clock.now()


def test_schedule_skips_missed_beats(conn, clock, runner):
    add_schedule(conn, clock, "heartbeat", "account:5", 60); conn.commit()
    clock.advance(seconds=1000)
    runner.run_until_idle(advance_clock=False)
    assert conn.execute("SELECT count(*) n FROM ops.domain_event").fetchone()["n"] == 1


def test_cost_cap_budget_exceeded(conn, clock, runner, env):
    ran = []
    g = base(cost_cap=0.05).code("spend", lambda ctx: ctx.charge(0.10, 100, 50, "m1") or {})
    g.code("next", lambda ctx: ran.append(1) or {}, after="spend")
    go(conn, clock, runner, g, env)
    r = run_of(conn)
    assert r["status"] == "budget_exceeded" and not ran
    assert float(r["cost"]) == pytest.approx(0.10) and r["tokens_in"] == 100 and r["model_ids"] == ["m1"]


def test_job_dead_letter_after_repeated_crash(conn, clock, services, env):
    r = Runner(conn, clock, services, max_job_attempts=2)
    r.register(base().code("a", lambda ctx: (_ for _ in ()).throw(Crash())))
    emit(conn, clock, env()); conn.commit()
    for _ in range(5):
        try:
            r.run_until_idle()
        except Crash:
            conn.rollback()
    assert conn.execute("SELECT status FROM ops.job").fetchone()["status"] == "dead"
    assert run_of(conn)["status"] == "needs_attention"
    assert conn.execute("SELECT count(*) n FROM ops.domain_event WHERE type='job.dead'").fetchone()["n"] == 1


def test_trace_rows_complete_and_audit_chain(conn, clock, runner, env):
    g = base().tool("t1", lambda ctx: {"r": ctx.call("crm.read", lambda x: x * 2, 21)})
    g.code("c", lambda ctx: ctx.audit("thing.done", {"v": 1}, entity_ref="lead:1") and {}, after="t1")

    def denied(ctx):
        ctx.call("crm.write", lambda: (_ for _ in ()).throw(PolicyDenied("no token")))
    g.tool("d", denied, after="c", on_error="continue")
    go(conn, clock, runner, g, env)
    run = run_of(conn)
    assert run["status"] == "completed" and run["ended_at"] is not None and run["workflow_version"] == "1"
    assert [s["node_id"] for s in steps(conn)] == ["t", "t1", "c", "d"]
    tc = conn.execute("SELECT tool_name, permitted, step_id FROM ops.tool_call ORDER BY id").fetchall()
    assert [(t["tool_name"], t["permitted"]) for t in tc] == [("crm.read", True), ("crm.write", False)]
    assert all(t["step_id"] for t in tc)
    kinds = [a["event_type"] for a in conn.execute("SELECT event_type FROM ops.audit_event ORDER BY seq")]
    assert kinds == ["run.started", "thing.done", "run.finished"]
    assert audit.verify_chain(conn)[0]


def test_ctx_emit_is_deduplicated_across_retries(conn, clock, runner, env):
    n = []

    def f(ctx):
        ctx.emit("lead.qualified", {"a": 1})
        n.append(1)
        if len(n) == 1:
            raise RetryableError("x")
        return {}
    go(conn, clock, runner, base().tool("t1", f), env)
    assert conn.execute("SELECT count(*) n FROM ops.domain_event WHERE type='lead.qualified'").fetchone()["n"] == 1


def test_llm_node_uses_mock_and_charges(conn, clock, services, env):
    from gtm.llm import build_llm, register_mock
    register_mock("triage", lambda i: {"label": "genuine", "confidence": 0.9, "reason": "ok"})
    services.llm = build_llm(services.settings, clock, conn=conn)
    r = Runner(conn, clock, services)
    g = base().llm("tri", "triage", lambda ctx: {"untrusted": {"text": "hi"}})
    go(conn, clock, r, g, env)
    run = run_of(conn)
    assert run["state"]["tri"]["label"] == "genuine" and run["state"]["tri"]["_llm"]["model_id"] == "mock-heuristic-v1"
    assert run["model_ids"] == ["mock-heuristic-v1"] and run["tokens_in"] > 0
