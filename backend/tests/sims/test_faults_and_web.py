import pytest
from starlette.testclient import TestClient
from gtm.clock import SimClock
from gtm.contracts.sims import FaultSpec, MOUNT_CONTROL, MOUNT_CRM, MOUNT_OUTREACH, MOUNT_PROVIDER, MOUNT_WEB
from gtm.sims import build_sims
from gtm.world import generate_world

O = MOUNT_OUTREACH
PROV = MOUNT_PROVIDER["provider_a"]
GOLD = {"domain": "brightwater-logistics.example", "fields": ["name", "employee_count", "industry", "region"]}


@pytest.fixture()
def env():
    clock = SimClock()
    b = build_sims(generate_world(), clock)
    return b, TestClient(b.app), clock


ENDPOINTS = {
    "provider_a": lambda c: c.post(PROV + "/company", json=GOLD),
    "crm": lambda c: c.get(MOUNT_CRM + "/crm/v3/objects/contacts/1"),
    "outreach": lambda c: c.get(O + "/events"),
    "web": lambda c: c.get(MOUNT_WEB + "/search", params={"q": "brightwater"}),
}


@pytest.mark.parametrize("sim", list(ENDPOINTS))
@pytest.mark.parametrize("kind,status", [("http_429", 429), ("http_500", 500), ("http_503", 503), ("timeout", 504)])
def test_error_faults_count_limited(env, sim, kind, status):
    b, c, _ = env
    b.control.inject(FaultSpec(sim=sim, kind=kind, params={"retry_after": 3}, count=2))
    first = ENDPOINTS[sim](c)
    assert first.status_code == status
    if kind == "http_429":
        assert first.headers["Retry-After"] == "3"
    assert ENDPOINTS[sim](c).status_code == status
    assert ENDPOINTS[sim](c).status_code in (200, 404)  # recovered after 2 requests
    assert b.control.state()["faults"] == []


def test_fault_until_cleared_and_http_control_plane(env):
    b, c, _ = env
    r = c.post(f"{MOUNT_CONTROL}/faults", json={"sim": "*", "kind": "http_500"})
    assert r.status_code == 200
    for sim in ENDPOINTS:
        assert ENDPOINTS[sim](c).status_code == 500
        assert ENDPOINTS[sim](c).status_code == 500
    st = c.get(f"{MOUNT_CONTROL}/state").json()
    assert st["faults"][0]["remaining"] is None and st["faults_fired"]["http_500"] == 8
    assert c.delete(f"{MOUNT_CONTROL}/faults").status_code == 200
    assert ENDPOINTS["provider_a"](c).status_code == 200


def test_scope_filters_entities(env):
    b, c, _ = env
    b.control.inject(FaultSpec(sim="provider_a", kind="http_503", scope="other-company.example"))
    assert ENDPOINTS["provider_a"](c).status_code == 200
    b.control.clear()
    b.control.inject(FaultSpec(sim="provider_a", kind="http_503", scope="brightwater"))
    assert ENDPOINTS["provider_a"](c).status_code == 503
    b.control.clear()
    b.control.inject(FaultSpec(sim="crm", kind="http_500"))
    assert ENDPOINTS["provider_a"](c).status_code == 200  # other sims unaffected


def test_latency_is_metadata_not_sleep(env):
    b, c, clock = env
    t0 = clock.now()
    base = ENDPOINTS["provider_a"](c).headers["X-Sim-Latency-Ms"]
    b.control.inject(FaultSpec(sim="provider_a", kind="latency", params={"latency_ms": 4000}, count=1))
    r = ENDPOINTS["provider_a"](c)
    assert int(r.headers["X-Sim-Latency-Ms"]) == int(base) + 4000 and r.status_code == 200
    assert ENDPOINTS["provider_a"](c).headers["X-Sim-Latency-Ms"] == base
    assert clock.now() == t0
    assert c.get(f"{MOUNT_CONTROL}/state").json()["simulated_latency_ms"]["provider_a"] == int(base) * 3 + 4000


def test_partial_data(env):
    b, c, _ = env
    full = c.post(PROV + "/company", json=GOLD).json()
    b.control.inject(FaultSpec(sim="provider_a", kind="partial_data", count=1))
    part = c.post(PROV + "/company", json=GOLD).json()
    assert part["partial"] is True and 0 < len(part["fields"]) < len(full["fields"]) and set(part["fields"]) <= set(full["fields"])
    assert c.post(PROV + "/company", json=GOLD).json()["partial"] is False


def test_eventual_consistency_override_and_drop_sync(env):
    b, c, clock = env
    b.control.inject(FaultSpec(sim="outreach", kind="eventual_consistency", params={"delay_s": 600}, count=1))
    c.post(f"{O}/contacts/import", json={"crm_contact_id": "1", "email": "slow@x.example"})
    c.post(f"{O}/contacts/import", json={"crm_contact_id": "2", "email": "fast@x.example"})  # fault consumed: default delay
    clock.advance(300)
    assert not c.get(f"{O}/contacts", params={"external_key": "1"}).json()["contacts"]
    assert c.get(f"{O}/contacts", params={"external_key": "2"}).json()["contacts"]
    clock.advance(301)
    assert c.get(f"{O}/contacts", params={"external_key": "1"}).json()["contacts"]
    b.control.inject(FaultSpec(sim="outreach", kind="drop_sync", count=1))
    r = c.post(f"{O}/contacts/import", json={"crm_contact_id": "3", "email": "lost@x.example"})
    assert r.status_code == 202  # looks fine to the caller
    clock.advance(100000)
    assert not c.get(f"{O}/contacts", params={"external_key": "3"}).json()["contacts"]


def _two_events(b, c, clock):
    c.post(f"{O}/contacts/import", json={"crm_contact_id": "1", "email": "a@x.example"})
    c.post(f"{O}/contacts/import", json={"crm_contact_id": "2", "email": "b@x.example"})
    clock.advance(200)


def test_duplicate_events(env):
    b, c, clock = env
    _two_events(b, c, clock)
    b.control.inject(FaultSpec(sim="outreach", kind="duplicate_events", count=1))
    evs = c.get(f"{O}/events").json()["events"]
    assert len(evs) == 4 and sorted({e["seq"] for e in evs}) == [1, 2]
    assert len(c.get(f"{O}/events").json()["events"]) == 2


def test_out_of_order_events(env):
    b, c, clock = env
    _two_events(b, c, clock)
    b.control.inject(FaultSpec(sim="outreach", kind="out_of_order_events", count=1))
    assert [e["seq"] for e in c.get(f"{O}/events").json()["events"]] == [2, 1]
    assert [e["seq"] for e in c.get(f"{O}/events").json()["events"]] == [1, 2]


def test_event_faults_do_not_consume_on_other_endpoints(env):
    b, c, clock = env
    b.control.inject(FaultSpec(sim="outreach", kind="duplicate_events", count=1))
    c.get(f"{O}/contacts", params={"email": "z@x.example"})
    assert b.control.state()["faults"][0]["remaining"] == 1


def test_web_search_and_page(env):
    b, c, _ = env
    res = c.get(MOUNT_WEB + "/search", params={"q": "Brightwater Logistics hiring"}).json()["results"]
    assert res and all(set(r) == {"url", "title", "snippet"} for r in res)
    assert all("brightwater-logistics.example" in r["url"] for r in res[:3])
    p = c.get(MOUNT_WEB + "/page", params={"url": res[0]["url"]}).json()
    assert set(p) == {"url", "title", "text"} and "Brightwater" in p["title"]
    assert c.get(MOUNT_WEB + "/page", params={"url": "https://nope.example/x"}).status_code == 404


def test_web_injection_pages_served_verbatim_without_flag(env):
    b, c, _ = env
    inj = [p for p in b.world.web_pages if p.contains_injection]
    assert len(inj) >= 2
    for p in inj:
        d = c.get(MOUNT_WEB + "/page", params={"url": p.url}).json()
        assert "ignore all previous instructions" in d["text"] and "contains_injection" not in d
