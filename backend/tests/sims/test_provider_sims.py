import pytest
from starlette.testclient import TestClient
from gtm.clock import SimClock
from gtm.contracts.sims import MOUNT_PROVIDER
from gtm.sims import build_sims
from gtm.world import generate_world, covers


@pytest.fixture(scope="module")
def world():
    return generate_world(42)


@pytest.fixture()
def bundle(world):
    return build_sims(world, SimClock())


def call(b, name, path, body):
    return TestClient(b.app).post(MOUNT_PROVIDER[name] + path, json=body)


def test_company_contract_and_cost(bundle, world):
    r = call(bundle, "provider_a", "/company", {"domain": "brightwater-logistics.example", "fields": ["name", "employee_count", "tech_stack"]})
    d = r.json()
    assert r.status_code == 200 and d["found"] and d["provider"] == "provider_a" and d["cost_units"] == 1
    assert set(d["fields"]) == {"name", "employee_count"}  # tech_stack is provider_c's field
    assert call(bundle, "provider_b", "/company", {"domain": "brightwater-logistics.example", "fields": ["name"]}).json()["cost_units"] == 10
    assert call(bundle, "provider_c", "/company", {"name": "Brightwater Logistics", "fields": ["tech_stack", "hiring_signals"]}).json()["found"]


def test_unknown_and_alias(bundle):
    d = call(bundle, "provider_a", "/company", {"domain": "nobody.example", "fields": ["name"]}).json()
    assert d["found"] is False and d["cost_units"] == 1 and d["fields"] == {}
    d = call(bundle, "provider_b", "/company", {"domain": "brightwater-group.example", "fields": ["employee_count"]}).json()
    assert d["found"]


def test_deterministic_and_as_of_not_in_future(world):
    b1, b2 = build_sims(world, SimClock()), build_sims(world, SimClock())
    body = {"domain": "brightwater-logistics.example", "fields": ["name", "employee_count", "industry", "region"]}
    assert call(b1, "provider_a", "/company", body).json() == call(b2, "provider_a", "/company", body).json()
    clock = SimClock()
    d = call(build_sims(world, clock), "provider_b", "/company", {**body, "fields": ["employee_count"]}).json()
    from datetime import datetime
    as_of = datetime.fromisoformat(d["fields"]["employee_count"]["as_of"])
    assert 0 <= (clock.now() - as_of).days <= 90


def test_person(bundle, world):
    ct = next(c for c in world.contacts if c.id == "ct_001")
    d = call(bundle, "provider_b", "/person", {"email": ct.email, "fields": ["title", "seniority", "full_name", "bogus"]}).json()
    assert d["found"] and set(d["fields"]) == {"title", "seniority", "full_name"}
    assert call(bundle, "provider_c", "/person", {"email": ct.email, "fields": ["title"]}).json()["fields"] == {}
    assert not call(bundle, "provider_a", "/person", {"email": "ghost@nowhere.example", "fields": ["title"]}).json()["found"]


def test_partial_coverage_company(bundle, world):
    e = next(e for e in world.enquiries if e.truth_company_id and e.expected_band == "medium" and e.id == "enq_014")
    c = next(c for c in world.companies if c.id == e.truth_company_id)
    a = call(bundle, "provider_a", "/company", {"domain": c.domain, "fields": ["name"]}).json()
    b = call(bundle, "provider_b", "/company", {"domain": c.domain, "fields": ["name"]}).json()
    assert a["found"] and not b["found"]


def test_golden_company_known_to_all(bundle):
    for n in MOUNT_PROVIDER:
        assert call(bundle, n, "/company", {"domain": "brightwater-logistics.example", "fields": ["name"]}).json()["found"]


def _measure(big, name, fields):
    b = build_sims(big, SimClock())
    params = next(p for p in big.providers if p.name == name)
    tc = TestClient(b.app)
    seen = ok = known = 0
    for c in big.companies:
        if c.id == "co_001":
            continue
        seen += 1
        d = tc.post(MOUNT_PROVIDER[name] + "/company", json={"domain": c.domain, "fields": fields}).json()
        if not d["found"]:
            continue
        known += 1
        for f in fields:
            ok += d["fields"][f]["value"] == getattr(c, f)
    return known / seen, ok / (known * len(fields)), params


@pytest.mark.parametrize("name,fields", [("provider_a", ["name", "employee_count", "industry"]),
                                         ("provider_b", ["employee_count", "industry", "revenue_band"]),
                                         ("provider_c", ["tech_stack", "hiring_signals"])])
def test_statistical_accuracy_and_coverage(name, fields):
    big = generate_world(5, {"n_companies": 400})
    cov, acc, p = _measure(big, name, fields)
    assert abs(cov - p.coverage) < 0.08, (name, cov)
    assert abs(acc - p.accuracy) < 0.07, (name, acc)
