import itertools
import pytest
from gtm import config
from gtm.contracts.events import EventEnvelope
from gtm.orchestration import Runner, Services

_n = itertools.count(1)


def make_env(clock, type="lead.received", account_id=None, key=None, **kw) -> EventEnvelope:
    return EventEnvelope(type=type, account_id=account_id, occurred_at=clock.now(), source="test",
                         dedupe_key=key or f"k{next(_n)}", **kw)


@pytest.fixture()
def services(clock):
    return Services(settings=config.get_settings(), clock=clock)


@pytest.fixture()
def runner(conn, clock, services):
    return Runner(conn, clock, services)


@pytest.fixture()
def env(clock):
    return lambda *a, **k: make_env(clock, *a, **k)


def steps(conn, run_id=None):
    q = "SELECT node_id, item_key, attempt, status FROM ops.run_step" + (" WHERE run_id=%s" if run_id else "") + " ORDER BY id"
    return conn.execute(q, (run_id,) if run_id else ()).fetchall()


def run_of(conn, wf=None):
    return conn.execute("SELECT * FROM ops.agent_run" + (" WHERE workflow=%s" if wf else "") + " ORDER BY id DESC LIMIT 1", (wf,) if wf else ()).fetchone()
