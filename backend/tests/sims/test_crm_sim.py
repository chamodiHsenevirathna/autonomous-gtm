import pytest
from starlette.testclient import TestClient
from gtm.clock import SimClock
from gtm.contracts.sims import MOUNT_CRM
from gtm.sims import build_sims
from gtm.world import generate_world

BASE = MOUNT_CRM + "/crm/v3/objects"


@pytest.fixture()
def env():
    clock = SimClock()
    b = build_sims(generate_world(), clock)
    return b, TestClient(b.app), clock


def test_create_get_patch_search(env):
    b, c, clock = env
    r = c.post(f"{BASE}/contacts", json={"properties": {"email": "a@x.example", "firstname": "A"}}, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 201
    obj = r.json()
    assert isinstance(obj["id"], str) and obj["properties"]["email"] == "a@x.example"
    assert c.get(f"{BASE}/contacts/{obj['id']}").json()["id"] == obj["id"]
    clock.advance(60)
    p = c.patch(f"{BASE}/contacts/{obj['id']}", json={"properties": {"firstname": "B"}}).json()
    assert p["properties"]["firstname"] == "B" and p["properties"]["email"] == "a@x.example" and p["updatedAt"] > p["createdAt"]
    s = c.post(f"{BASE}/contacts/search", json={"filters": [{"propertyName": "email", "operator": "EQ", "value": "A@X.example"}]}).json()
    assert s["total"] == 1 and s["results"][0]["id"] == obj["id"]
    assert c.post(f"{BASE}/contacts/search", json={"filters": [{"propertyName": "email", "value": "none@x.example"}]}).json()["total"] == 0


def test_idempotency_key_returns_same_object(env):
    _, c, _ = env
    h = {"Idempotency-Key": "same"}
    r1 = c.post(f"{BASE}/companies", json={"properties": {"name": "Acme Example"}}, headers=h)
    r2 = c.post(f"{BASE}/companies", json={"properties": {"name": "Acme Example"}}, headers=h)
    assert (r1.status_code, r2.status_code) == (201, 200) and r1.json()["id"] == r2.json()["id"]
    assert c.post(f"{BASE}/companies", json={"properties": {"name": "Acme Example"}}, headers={"Idempotency-Key": "other"}).json()["id"] != r1.json()["id"]
    # replay of a contact create is 200, not 409
    k = {"Idempotency-Key": "ck"}
    a = c.post(f"{BASE}/contacts", json={"properties": {"email": "z@x.example"}}, headers=k)
    assert c.post(f"{BASE}/contacts", json={"properties": {"email": "z@x.example"}}, headers=k).status_code == 200 and a.status_code == 201


def test_duplicate_contact_email_409_with_existing_id(env):
    _, c, _ = env
    first = c.post(f"{BASE}/contacts", json={"properties": {"email": "dup@x.example"}}, headers={"Idempotency-Key": "1"}).json()
    r = c.post(f"{BASE}/contacts", json={"properties": {"email": "DUP@x.example"}}, headers={"Idempotency-Key": "2"})
    assert r.status_code == 409 and r.json()["existingId"] == first["id"] and "message" in r.json()
    # deals are not email-unique
    assert c.post(f"{BASE}/deals", json={"properties": {"email": "dup@x.example"}}).status_code == 201


def test_404s(env):
    _, c, _ = env
    assert c.get(f"{BASE}/contacts/9").status_code == 404
    assert c.patch(f"{BASE}/contacts/9", json={"properties": {}}).status_code == 404
    assert c.get(f"{BASE}/widgets/1").status_code == 404
