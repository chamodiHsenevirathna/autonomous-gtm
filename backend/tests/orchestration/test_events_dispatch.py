import threading
from datetime import timedelta
import pytest
from gtm import db
from gtm.contracts.events import EventEnvelope
from gtm.orchestration import Dispatcher, Graph, Runner, emit, subscribe
from tests.orchestration.conftest import make_env, run_of


def _g(name="wf", **kw):
    g = Graph(name, **kw)
    g.trigger("t", "lead.received")
    g.code("a", lambda ctx: {"n": len(ctx.events)})
    return g


def test_event_dedupe_and_subscription_filter(conn, clock, env):
    subscribe(conn, "lead.received", "wf-all")
    subscribe(conn, "lead.received", "wf-big", {"payload": {"size": "big"}})
    conn.execute("INSERT INTO ops.subscription(event_type, workflow, enabled) VALUES ('lead.received','wf-off',false)")
    e = env(key="dup", payload={"size": "small"})
    assert emit(conn, clock, e) is not None
    assert emit(conn, clock, e) is None
    assert conn.execute("SELECT count(*) n FROM ops.domain_event").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) n FROM ops.dispatch").fetchone()["n"] == 1      # only wf-all matches
    emit(conn, clock, env(payload={"size": "big"}))
    assert conn.execute("SELECT count(*) n FROM ops.dispatch").fetchone()["n"] == 3


def test_dispatch_skip_locked_two_connections(conn, clock, test_url, runner, env):
    runner.register(_g())
    for _ in range(6):
        emit(conn, clock, env())
    conn.commit()
    other = db.connect(test_url)
    d1, d2 = Dispatcher(conn, clock, runner.graphs), Dispatcher(other, clock, runner.graphs)
    held = d1.claim(3)                               # d1 holds 3 row locks, uncommitted
    assert len(held) == 3
    assert d2.process(100) == 3                      # d2 skips the locked rows instead of blocking
    d1.process(rows=held)
    assert conn.execute("SELECT count(*) n FROM ops.job").fetchone()["n"] == 6
    assert conn.execute("SELECT count(*) n FROM ops.dispatch WHERE status='enqueued'").fetchone()["n"] == 6
    other.close()


def test_dispatch_threads_no_duplicate_jobs(conn, clock, test_url, runner, env):
    runner.register(_g())
    for _ in range(60):
        emit(conn, clock, env())
    conn.commit()
    bar = threading.Barrier(2)
    handled = []

    def work():
        c = db.connect(test_url)
        d = Dispatcher(c, clock, runner.graphs)
        bar.wait()
        n = 0
        while True:
            k = d.process(7)
            if not k:
                break
            n += k
        handled.append(n)
        c.close()
    ts = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(handled) == 60
    assert conn.execute("SELECT count(*) n FROM ops.job").fetchone()["n"] == 60


def test_gap_safe_late_commit_is_not_skipped(conn, clock, test_url, runner, env):
    runner.register(_g())
    slow = db.connect(test_url)
    emit(slow, clock, env(key="early-id-late-commit"))   # lower id, not committed yet
    emit(conn, clock, env(key="later")); conn.commit()
    d = Dispatcher(conn, clock, runner.graphs)
    assert d.process() == 1                              # only the committed one is visible
    slow.commit()                                        # the "gap" fills in
    assert d.process() == 1                              # a cursor over seq would have skipped it
    assert conn.execute("SELECT count(*) n FROM ops.job").fetchone()["n"] == 2
    slow.close()


def test_stale_event_ignored(conn, clock, runner):
    runner.register(_g())
    mk = lambda v, k: EventEnvelope(type="lead.received", entity_ref="opp:1", source_version=v, occurred_at=clock.now(), source="t", dedupe_key=k)
    emit(conn, clock, mk(5, "v5")); conn.commit()
    runner.dispatcher.process()
    emit(conn, clock, mk(3, "v3")); emit(conn, clock, mk(6, "v6")); conn.commit()
    runner.dispatcher.process()
    st = {r["dedupe_key"]: r["status"] for r in conn.execute("SELECT e.dedupe_key, d.status FROM ops.dispatch d JOIN ops.domain_event e ON e.id=d.event_id")}
    assert st == {"v5": "enqueued", "v3": "ignored_stale", "v6": "enqueued"}


def test_stale_by_occurred_at_when_unversioned(conn, clock, runner):
    runner.register(_g())
    mk = lambda at, k: EventEnvelope(type="lead.received", entity_ref="x:1", occurred_at=clock.now() + timedelta(seconds=at), source="t", dedupe_key=k)
    emit(conn, clock, mk(10, "new")); conn.commit(); runner.dispatcher.process()
    emit(conn, clock, mk(1, "old")); conn.commit(); runner.dispatcher.process()
    assert conn.execute("SELECT status FROM ops.dispatch d JOIN ops.domain_event e ON e.id=d.event_id WHERE dedupe_key='old'").fetchone()["status"] == "ignored_stale"


def test_coalescing_by_wake_target(conn, clock, runner, env):
    runner.register(_g(coalesce_seconds=60, coalesce_delay=True, coalesce_key=lambda e: f"account:{e.account_id}"))
    for i in range(3):
        emit(conn, clock, env(account_id=7))
    emit(conn, clock, env(account_id=8)); conn.commit()
    res = runner.run_until_idle()
    jobs = conn.execute("SELECT payload FROM ops.job ORDER BY id").fetchall()
    assert len(jobs) == 2 and len(jobs[0]["payload"]["event_ids"]) == 3
    runs = conn.execute("SELECT account_id, state FROM ops.agent_run ORDER BY account_id").fetchall()
    assert [r["state"]["a"]["n"] for r in runs] == [3, 1]
    assert res["clock_advances"] == 1                      # jumped to the end of the 60s window


def test_lifecycle_filter_hook(conn, clock, services, env):
    r = Runner(conn, clock, services, lifecycle=lambda c, e, wf: e.account_id != 99)
    r.register(_g())
    emit(conn, clock, env(account_id=99)); emit(conn, clock, env(account_id=1)); conn.commit()
    r.run_until_idle()
    assert conn.execute("SELECT count(*) n FROM ops.agent_run").fetchone()["n"] == 1


def test_dispatch_dead_letter_after_n_attempts(conn, clock, services, env):
    def boom(c, e, wf):
        raise RuntimeError("poison")
    r = Runner(conn, clock, services, lifecycle=boom)
    r.register(_g())
    emit(conn, clock, env()); conn.commit()
    r.run_until_idle()
    d = conn.execute("SELECT status, attempts FROM ops.dispatch").fetchone()
    assert (d["status"], d["attempts"]) == ("dead", 3)
    assert conn.execute("SELECT count(*) n FROM ops.domain_event WHERE type='job.dead'").fetchone()["n"] == 1
