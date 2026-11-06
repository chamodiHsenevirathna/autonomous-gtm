import pytest
from psycopg import errors
from gtm import audit
from gtm.contracts.proposals import payload_hash, MessagePayload
from gtm.contracts.gateway import mint_token, verify_token
from gtm.clock import SimClock
from datetime import timedelta

pytestmark = pytest.mark.db


def test_migrations_and_seed(conn):
    n = conn.execute("SELECT count(*) AS n FROM ops.gate_catalog").fetchone()["n"]
    assert n >= 9
    assert conn.execute("SELECT count(*) AS n FROM gtm.data_source").fetchone()["n"] == 5


def test_audit_chain_verifies_and_is_append_only(conn, clock):
    for i in range(5):
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="test.event", data={"i": i})
        clock.advance(60)
    conn.commit()
    ok, n, bad = audit.verify_chain(conn)
    assert ok and n == 5 and bad is None
    with pytest.raises(errors.RaiseException):
        conn.execute("UPDATE ops.audit_event SET event_type='x' WHERE seq=1")
    conn.rollback()
    with pytest.raises(errors.RaiseException):
        conn.execute("DELETE FROM ops.audit_event")
    conn.rollback()


def test_audit_tamper_detected(conn, clock):
    for i in range(3):
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="e", data={"i": i})
    conn.commit()
    # bypass the trigger as a superuser-style tamper to prove verification catches it
    conn.execute("ALTER TABLE ops.audit_event DISABLE TRIGGER USER")
    conn.execute("UPDATE ops.audit_event SET data='{\"i\": 99}'::jsonb WHERE seq=(SELECT min(seq) FROM ops.audit_event)")
    conn.execute("ALTER TABLE ops.audit_event ENABLE TRIGGER USER")
    conn.commit()
    ok, _, bad = audit.verify_chain(conn)
    assert not ok and bad is not None


def test_payload_hash_changes_with_recipient():
    p = MessagePayload(contact_id=1, resolved_recipient="a@x.example", sender_identity="maya@corvane.example", subject="s", body="b").model_dump()
    h1 = payload_hash(7, "message", p)
    p2 = dict(p, resolved_recipient="b@x.example")
    assert h1 != payload_hash(7, "message", p2)
    assert h1 == payload_hash(7, "message", dict(p))
    assert h1 != payload_hash(8, "message", p)


def test_execution_token_rules():
    clock = SimClock(); secret = b"k"
    tok = mint_token(secret, proposal_id=1, payload_hash="h", adapter="outreach.send", expires_at=clock.now() + timedelta(minutes=15))
    assert verify_token(secret, tok, adapter="outreach.send", now=clock.now(), payload_hash="h")
    assert not verify_token(secret, None, adapter="outreach.send", now=clock.now())
    assert not verify_token(secret, tok, adapter="crm.write", now=clock.now())
    assert not verify_token(secret, tok, adapter="outreach.send", now=clock.now(), payload_hash="other")
    assert not verify_token(b"wrong", tok, adapter="outreach.send", now=clock.now())
    assert not verify_token(secret, tok, adapter="outreach.send", now=clock.now() + timedelta(minutes=16))
