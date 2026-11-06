from datetime import timedelta
import pytest
from starlette.testclient import TestClient
from gtm.clock import SimClock
from gtm.contracts.sims import MOUNT_CONTROL, MOUNT_OUTREACH
from gtm.sims import build_sims
from gtm.world import generate_world

O = MOUNT_OUTREACH
SEND = {"contact_id": "oc_1", "from_address": "sales@corvane.example", "to_address": "a@x.example", "subject": "Hi", "body": "Hello"}


@pytest.fixture()
def env():
    clock = SimClock()
    b = build_sims(generate_world(), clock)
    return b, TestClient(b.app), clock


def imp(c, key="1", email="a@x.example"):
    return c.post(f"{O}/contacts/import", json={"crm_contact_id": key, "email": email, "full_name": "A X"}, headers={"Idempotency-Key": "imp" + key})


def test_eventual_consistency_default_delay(env):
    b, c, clock = env
    r = imp(c)
    assert r.status_code == 202 and set(r.json()) == {"import_id", "visible_at"}
    delay = b.outreach_state.delay_for("a@x.example")
    assert 5 <= delay <= 120
    assert c.get(f"{O}/contacts", params={"external_key": "1"}).json() == {"contacts": []}
    clock.advance(delay - 1)
    assert c.get(f"{O}/contacts", params={"email": "a@x.example"}).json()["contacts"] == []
    clock.advance(1)
    hit = c.get(f"{O}/contacts", params={"external_key": "1"}).json()["contacts"]
    assert len(hit) == 1 and hit[0]["email"] == "a@x.example" and hit[0]["external_key"] == "1"
    assert c.get(f"{O}/contacts", params={"email": "A@x.example"}).json()["contacts"][0]["id"] == hit[0]["id"]


def test_delay_deterministic_per_contact():
    w = generate_world()
    d1 = build_sims(w, SimClock()).outreach_state.delay_for("q@x.example")
    d2 = build_sims(w, SimClock()).outreach_state.delay_for("q@x.example")
    assert d1 == d2
    assert len({build_sims(w, SimClock()).outreach_state.delay_for(f"u{i}@x.example") for i in range(30)}) > 5


def test_send_422_before_visible_then_ok_and_idempotent(env):
    _, c, clock = env
    imp(c)
    h = {"Idempotency-Key": "m1"}
    assert c.post(f"{O}/messages", json=SEND, headers=h).status_code == 422
    clock.advance(121)
    r1 = c.post(f"{O}/messages", json=SEND, headers=h)
    r2 = c.post(f"{O}/messages", json=SEND, headers=h)
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json() == r2.json() and r1.json()["status"] == "sent"
    r3 = c.post(f"{O}/messages", json=SEND, headers={"Idempotency-Key": "m2"})
    assert r3.json()["message_id"] != r1.json()["message_id"]


def test_send_requires_key_and_known_contact(env):
    _, c, clock = env
    assert c.post(f"{O}/messages", json=SEND).status_code == 400
    assert c.post(f"{O}/messages", json=SEND, headers={"Idempotency-Key": "z"}).status_code == 404


def test_events_pull_and_cursor(env):
    _, c, clock = env
    imp(c)
    assert c.get(f"{O}/events").json() == {"events": []}
    clock.advance(200)
    evs = c.get(f"{O}/events").json()["events"]
    assert [e["type"] for e in evs] == ["contact_visible"] and evs[0]["seq"] == 1
    assert c.get(f"{O}/events", params={"since": 1}).json()["events"] == []


def test_scripted_reply_arrives_after_clock_passes(env):
    b, c, clock = env
    enq = next(e for e in b.world.enquiries if e.id == "enq_001")
    imp(c, "7", enq.email)
    clock.advance(130)
    c.post(f"{O}/messages", json={**SEND, "contact_id": "oc_7", "to_address": enq.email}, headers={"Idempotency-Key": "g"})
    at = clock.now() + timedelta(seconds=5400)
    b.script_reply("rpl_001", enq.email, at)
    clock.advance(5399)
    assert [e["type"] for e in c.get(f"{O}/events").json()["events"]] == ["contact_visible"]
    clock.advance(1)
    evs = c.get(f"{O}/events", params={"since": 1}).json()["events"]
    assert [e["type"] for e in evs] == ["reply"]
    assert evs[0]["payload"]["reply_id"] == "rpl_001" and evs[0]["payload"]["email"] == enq.email and evs[0]["payload"]["message_id"] == "msg_00001"
    assert evs[0]["ts"].startswith(at.isoformat()[:19])


def test_every_reply_kind_maps_to_event_type(env):
    b, c, clock = env
    for r in b.world.replies:
        enq = next(e for e in b.world.enquiries if e.id == r.to_enquiry_id)
        b.script_reply(r.id, enq.email, clock.now() + timedelta(seconds=r.at_offset_s))
    clock.advance(200000)
    evs = c.get(f"{O}/events").json()["events"]
    kinds = {r.id: r.kind for r in b.world.replies}
    assert len(evs) == len(b.world.replies)
    for e in evs:
        k = kinds[e["payload"]["reply_id"]]
        assert e["type"] == (k if k in ("bounce", "unsubscribe", "meeting_booked") else "reply")
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1)) and [e["ts"] for e in evs] == sorted(e["ts"] for e in evs)


def test_unsubscribe_suppresses_in_sim_403(env):
    b, c, clock = env
    enq = next(e for e in b.world.enquiries if e.id == "enq_014")  # has an unsubscribe reply
    imp(c, "9", enq.email)
    clock.advance(130)
    ok = c.post(f"{O}/messages", json={**SEND, "contact_id": "oc_9", "to_address": enq.email}, headers={"Idempotency-Key": "a"})
    assert ok.status_code == 201
    rep = next(r for r in b.world.replies if r.to_enquiry_id == enq.id and r.kind == "unsubscribe")
    b.script_reply(rep.id, enq.email, clock.now() + timedelta(seconds=10))
    clock.advance(10)
    r = c.post(f"{O}/messages", json={**SEND, "contact_id": "oc_9", "to_address": enq.email}, headers={"Idempotency-Key": "b"})
    assert r.status_code == 403 and r.json()["message"] == "suppressed"


def test_auto_replies_flag():
    w = generate_world()
    clock = SimClock()
    b = build_sims(w, clock, auto_replies=True)
    c = TestClient(b.app)
    enq = next(e for e in w.enquiries if e.id == "enq_002")
    imp(c, "3", enq.email)
    clock.advance(130)
    c.post(f"{O}/messages", json={**SEND, "contact_id": "oc_3", "to_address": enq.email}, headers={"Idempotency-Key": "a"})
    clock.advance(7200)
    assert [e["type"] for e in c.get(f"{O}/events", params={"since": 1}).json()["events"]] == ["reply"]


def test_control_script_endpoint_and_state(env):
    b, c, clock = env
    r = c.post(f"{MOUNT_CONTROL}/script", json={"reply_id": "rpl_003", "to_email": "x@y.example", "at": (clock.now() + timedelta(seconds=30)).isoformat()})
    assert r.status_code == 200
    assert c.post(f"{MOUNT_CONTROL}/script", json={"reply_id": "nope", "to_email": "x@y.example", "at": clock.now().isoformat()}).status_code == 404
    assert c.get(f"{MOUNT_CONTROL}/state").json()["outreach"]["scheduled_pending"] == 1
    clock.advance(31)
    assert c.get(f"{MOUNT_CONTROL}/state").json()["outreach"]["events"] == 1
