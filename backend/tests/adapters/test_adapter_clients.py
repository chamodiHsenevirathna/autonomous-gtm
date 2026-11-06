from datetime import timedelta
import httpx
import pytest
from gtm.adapters import ConflictError, CrmClient, OutreachClient, ProviderClient, WebClient
from gtm.clock import SimClock
from gtm.contracts.errors import NotReady, PermanentError, PolicyDenied, RetryableError
from gtm.contracts.gateway import ExecutionToken, TokenVerifier, mint_token
from gtm.contracts.sims import FaultSpec
from gtm.sims import build_sims
from gtm.world import generate_world

SECRET = b"unit-test-secret"


class Recorder:
    """httpx transport that counts requests and answers with a canned response."""
    def __init__(self, status=200, body=None, headers=None):
        self.calls, self.status, self.body, self.headers = [], status, body if body is not None else {}, headers or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, json=self.body, headers=self.headers)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), base_url="http://x")


@pytest.fixture()
def clock():
    return SimClock()


@pytest.fixture()
def verifier(clock):
    return TokenVerifier(SECRET, clock)


def tok(clock, adapter, secret=SECRET, ttl=3600, h="abc"):
    return mint_token(secret, proposal_id=1, payload_hash=h, adapter=adapter, expires_at=clock.now() + timedelta(seconds=ttl))


def writes(rec, verifier):
    crm, out = CrmClient(rec.client(), verifier), OutreachClient(rec.client(), verifier)
    return {
        "crm.write": lambda t: crm.create("contacts", {"email": "a@x.example"}, token=t, idempotency_key="k"),
        "crm.write/update": lambda t: crm.update("contacts", "1", {"a": 1}, token=t, idempotency_key="k"),
        "outreach.import": lambda t: out.import_contact("1", "a@x.example", token=t, idempotency_key="k"),
        "outreach.send": lambda t: out.send("oc_1", "s@c.example", "a@x.example", "s", "b", token=t, idempotency_key="k"),
    }


@pytest.mark.parametrize("name", ["crm.write", "crm.write/update", "outreach.import", "outreach.send"])
def test_bad_tokens_never_reach_http(clock, verifier, name):
    rec = Recorder()
    adapter = name.split("/")[0]
    call = writes(rec, verifier)[name]
    good = tok(clock, adapter)
    bad = {
        "none": None,
        "forged": ExecutionToken(**{**good.model_dump(), "signature": "0" * 64}),
        "wrong_secret": tok(clock, adapter, secret=b"other"),
        "expired": tok(clock, adapter, ttl=-1),
        "wrong_adapter": tok(clock, "outreach.send" if adapter != "outreach.send" else "crm.write"),
        "tampered_expiry": ExecutionToken(**{**good.model_dump(), "expires_at": good.expires_at + timedelta(days=9)}),
    }
    for label, t in bad.items():
        with pytest.raises(PolicyDenied):
            call(t)
        assert rec.calls == [], label


def test_payload_hash_binding(clock, verifier):
    rec = Recorder(body={"id": "1", "properties": {}, "createdAt": clock.now().isoformat(), "updatedAt": clock.now().isoformat()})
    crm = CrmClient(rec.client(), verifier)
    t = tok(clock, "crm.write", h="approved")
    with pytest.raises(PolicyDenied):
        crm.create("contacts", {}, token=t, idempotency_key="k", payload_hash="different")
    assert rec.calls == []
    crm.create("contacts", {}, token=t, idempotency_key="k", payload_hash="approved")
    assert len(rec.calls) == 1 and rec.calls[0].headers["Idempotency-Key"] == "k"


def test_missing_idempotency_key_is_rejected_before_http(clock, verifier):
    rec = Recorder()
    with pytest.raises(PermanentError):
        CrmClient(rec.client(), verifier).create("contacts", {}, token=tok(clock, "crm.write"), idempotency_key="")
    assert rec.calls == []


@pytest.mark.parametrize("status,exc", [(429, RetryableError), (500, RetryableError), (503, RetryableError), (504, RetryableError),
                                        (408, RetryableError), (400, PermanentError), (404, PermanentError), (403, PermanentError)])
def test_status_mapping_and_retry_after(status, exc):
    rec = Recorder(status, {"message": "x"}, {"Retry-After": "7"} if status == 429 else {})
    with pytest.raises(exc) as ei:
        ProviderClient("provider_a", rec.client()).company(domain="x.example", fields=["name"])
    assert type(ei.value) is exc and len(rec.calls) == 1  # no retries inside adapters
    assert ei.value.retry_after == (7.0 if status == 429 else None)
    assert ei.value.detail["status"] == status


def test_transport_error_is_retryable():
    def boom(request):
        raise httpx.ConnectError("down")
    c = httpx.Client(transport=httpx.MockTransport(boom), base_url="http://x")
    with pytest.raises(RetryableError):
        WebClient(c).search("x")


def test_conflict_carries_existing_id(clock, verifier):
    rec = Recorder(409, {"message": "exists", "existingId": "1234"})
    with pytest.raises(ConflictError) as ei:
        CrmClient(rec.client(), verifier).create("contacts", {"email": "a@x.example"}, token=tok(clock, "crm.write"), idempotency_key="k")
    assert ei.value.existing_id == "1234" and isinstance(ei.value, PermanentError)


def test_send_422_maps_to_not_ready(clock, verifier):
    rec = Recorder(422, {"message": "contact not yet visible"})
    with pytest.raises(NotReady) as ei:
        OutreachClient(rec.client(), verifier).send("oc_1", "a@c.example", "b@x.example", "s", "b", token=tok(clock, "outreach.send"), idempotency_key="k")
    assert ei.value.retry_after


# ---- end to end through the simulators ----
@pytest.fixture()
def sims():
    clock = SimClock()
    b = build_sims(generate_world(), clock)
    return b, b.clients(token_secret=SECRET), clock


def test_full_flow_through_sims(sims):
    b, a, clock = sims
    r = a.providers["provider_b"].company(domain="brightwater-logistics.example", fields=["employee_count", "revenue_band"])
    assert r.found and r.cost_units == 10 and set(r.fields) == {"employee_count", "revenue_band"}
    assert a.providers["provider_a"].person(email="marta.lindqvist@brightwater-logistics.example", fields=["title"]).found
    c = a.crm.create("contacts", {"email": "m@brightwater-logistics.example"}, token=tok(clock, "crm.write"), idempotency_key="c1")
    again = a.crm.create("contacts", {"email": "m@brightwater-logistics.example"}, token=tok(clock, "crm.write"), idempotency_key="c1")
    assert again.id == c.id
    with pytest.raises(ConflictError) as ei:
        a.crm.create("contacts", {"email": "m@brightwater-logistics.example"}, token=tok(clock, "crm.write"), idempotency_key="c2")
    assert ei.value.existing_id == c.id
    assert a.crm.update("contacts", c.id, {"jobtitle": "VP"}, token=tok(clock, "crm.write"), idempotency_key="u1").properties["jobtitle"] == "VP"
    assert a.crm.get("contacts", c.id).id == c.id and [x.id for x in a.crm.search("contacts", {"email": "m@brightwater-logistics.example"})] == [c.id]
    a.outreach.import_contact(c.id, "m@brightwater-logistics.example", token=tok(clock, "outreach.import"), idempotency_key="i1")
    assert a.outreach.lookup(external_key=c.id) is None
    with pytest.raises(NotReady):
        a.outreach.send(f"oc_{c.id}", "s@corvane.example", "m@brightwater-logistics.example", "Hi", "Body", token=tok(clock, "outreach.send"), idempotency_key="s1")
    clock.advance(121)
    hit = a.outreach.lookup(external_key=c.id)
    assert hit and hit["id"] == f"oc_{c.id}"
    s1 = a.outreach.send(hit["id"], "s@corvane.example", "m@brightwater-logistics.example", "Hi", "Body", token=tok(clock, "outreach.send"), idempotency_key="s1")
    s2 = a.outreach.send(hit["id"], "s@corvane.example", "m@brightwater-logistics.example", "Hi", "Body", token=tok(clock, "outreach.send"), idempotency_key="s1")
    assert s1 == s2
    assert [e.type for e in a.outreach.events()] == ["contact_visible"]
    assert a.web.search("brightwater careers") and a.web.page(a.web.search("brightwater careers")[0]["url"])["text"]


def test_sim_faults_map_to_adapter_errors(sims):
    b, a, clock = sims
    b.control.inject(FaultSpec(sim="provider_a", kind="http_429", params={"retry_after": 4}, count=1))
    with pytest.raises(RetryableError) as ei:
        a.providers["provider_a"].company(domain="brightwater-logistics.example", fields=["name"])
    assert ei.value.retry_after == 4.0
    assert a.providers["provider_a"].company(domain="brightwater-logistics.example", fields=["name"]).found
    b.control.inject(FaultSpec(sim="crm", kind="timeout", count=1))
    with pytest.raises(RetryableError):
        a.crm.get("contacts", "1")
    with pytest.raises(PermanentError):
        a.crm.get("contacts", "999")
