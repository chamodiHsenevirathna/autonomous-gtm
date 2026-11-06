from datetime import timedelta
import pytest
from gtm.contracts.errors import RetryableError
from gtm.contracts.sims import FaultSpec
from gtm.data import (enrich_entity, fetch_provider, get_resolved, record_observation, resolve_fields)
from conftest import seed_accounts

pytestmark = pytest.mark.db
ICP = lambda world: [c for c in world.companies if c.icp_fit and c.id != "co_001"][:12]


def acct(conn, clock, world, co_id="co_001", **kw):
    return seed_accounts(conn, clock, world, only={co_id}, **kw)[co_id]


def test_first_party_and_existing_data_first(conn, clock, world, providers):
    a = acct(conn, clock, world)
    r = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["name", "domain"], cost_cap=50)
    assert r.cost == 0 and r.providers_tried == [] and r.status == "complete"
    assert {f: s["status"] for f, s in r.fields.items()} == {"name": "existing", "domain": "existing"}
    # a fresh high-confidence observation also short-circuits the providers
    record_observation(conn, clock, entity_type="account", entity_id=a, field="industry", value="Logistics", source="provider_b", observed_at=clock.now())
    r = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["industry"], cost_cap=50)
    assert r.cost == 0 and r.fields["industry"]["status"] == "existing"
    assert r.providers_tried == []


def test_cost_cap_stops_everything_and_never_fabricates(conn, clock, world, providers):
    a = acct(conn, clock, world)
    # order by cost per correct answer: A (1/0.6) < C (5/0.85) < B. Cap 1 allows only A.
    r = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["employee_count", "tech_stack"], cost_cap=1)
    assert r.providers_tried == ["provider_a"] and r.cost == 1 and r.status == "budget_exhausted"
    assert r.fields["tech_stack"]["status"] == "unknown" and "tech_stack" in r.gaps
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation WHERE field='tech_stack'").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM gtm.resolved_field WHERE field='tech_stack'").fetchone()["n"] == 0
    row = conn.execute("SELECT * FROM gtm.enrichment_request WHERE id=%s", (r.request_id,)).fetchone()
    assert row["status"] == "budget_exhausted" and float(row["cost_total"]) == 1 and float(row["cost_cap"]) == 1


def test_sequential_stops_early_parallel_asks_everyone(conn, clock, world, providers):
    seq_cost = par_cost = 0.0
    for co in ICP(world):
        a = seed_accounts(conn, clock, world, only={co.id})[co.id]
        s = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["industry", "region"], cost_cap=100, mode="sequential")
        b = conn.execute("INSERT INTO gtm.account(name, data_origin, created_at, updated_at) VALUES (%s,'GT',%s,%s) RETURNING id", (co.name, clock.now(), clock.now())).fetchone()["id"]
        p = enrich_entity(conn, clock, providers, entity_type="account", entity_id=b, fields=["industry", "region"], cost_cap=100, mode="parallel")
        assert s.cost <= p.cost
        seq_cost += s.cost
        par_cost += p.cost
    print(f"\n[SIMULATED WORLD] waterfall cost over {len(ICP(world))} accounts: sequential={seq_cost}, parallel={par_cost}")
    assert seq_cost < par_cost


def test_parallel_and_sequential_agree_but_cost_differs(conn, clock, world, providers):
    """Same world, same fields: modes resolve (almost) the same values; parallel buys more calls."""
    sub = {"industry", "region"}
    out = {}
    for mode in ("sequential", "parallel"):
        conn.execute("TRUNCATE gtm.resolved_field, gtm.observation, gtm.enrichment_request CASCADE")
        conn.execute("DELETE FROM gtm.account")
        conn.commit()
        vals, cost = {}, 0.0
        for co in world.companies[:24]:
            a = conn.execute("INSERT INTO gtm.account(name, data_origin, created_at, updated_at) VALUES (%s,'GT',%s,%s) RETURNING id", (co.name, clock.now(), clock.now())).fetchone()["id"]
            r = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=sorted(sub), cost_cap=100, mode=mode)
            cost += r.cost
            vals[co.id] = {f: v["value"] for f, v in r.resolved.items()}
        out[mode] = (vals, cost)
    (sv, sc), (pv, pc) = out["sequential"], out["parallel"]
    both = [(sv[c][f], pv[c][f]) for c in sv for f in sub if f in sv[c] and f in pv[c]]
    agree = sum(a == b for a, b in both) / len(both)
    print(f"\n[SIMULATED WORLD] seq vs par agreement={agree:.2f} over {len(both)} fields; cost seq={sc} par={pc}")
    assert agree >= 0.7 and pc > sc


def test_provider_failure_records_gap_no_fabrication(conn, clock, world, providers, sims):
    a = acct(conn, clock, world)
    sims.control.inject(FaultSpec(sim="provider_b", kind="http_503", params={"retry_after": 9}))
    r = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["legal_name"], cost_cap=50)
    assert r.fields["legal_name"]["status"] == "unknown" and r.gaps == ["legal_name"] and r.status == "partial"
    assert r.failures[0]["provider"] == "provider_b" and r.failures[0]["retry_after"] == 9.0 and "provider_b:failed" in r.providers_tried
    assert r.cost == 0
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation WHERE field='legal_name'").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM gtm.resolved_field WHERE field='legal_name'").fetchone()["n"] == 0
    row = conn.execute("SELECT * FROM gtm.enrichment_request WHERE id=%s", (r.request_id,)).fetchone()
    assert row["status"] == "partial" and "provider_b:failed" in row["providers_tried"]
    # recovery: later run succeeds
    sims.control.clear()
    r2 = enrich_entity(conn, clock, providers, entity_type="account", entity_id=a, fields=["legal_name"], cost_cap=50)
    assert r2.fields["legal_name"]["status"] != "unknown"


def test_fetch_provider_propagates_retryable_and_writes_observations(conn, clock, world, providers, sims):
    a = acct(conn, clock, world)
    sims.control.inject(FaultSpec(sim="provider_a", kind="http_429", params={"retry_after": 3}, count=1))
    with pytest.raises(RetryableError) as ei:
        fetch_provider(conn, clock, providers["provider_a"], "provider_a", "account", a, ["industry"])
    assert ei.value.retry_after == 3.0
    res = fetch_provider(conn, clock, providers["provider_a"], "provider_a", "account", a, ["industry", "employee_count"], run_id=None)
    assert res["found"] and res["cost_units"] == 1 and set(res["observation_ids"]) == {"industry", "employee_count"} and res["partial"] is False
    o = conn.execute("SELECT o.*, s.name AS src FROM gtm.observation o JOIN gtm.data_source s ON s.id=o.data_source_id WHERE o.id=%s", (res["observation_ids"]["industry"],)).fetchone()
    assert o["src"] == "provider_a" and o["data_origin"] == "SIM" and o["fetched_at"] == clock.now() and o["observed_at"] <= clock.now()
    assert abs(float(o["confidence"]) - 0.75) < 1e-9 and o["raw_ref"].startswith("provider_a:company:")
    sims.control.inject(FaultSpec(sim="provider_a", kind="partial_data", count=1))
    assert fetch_provider(conn, clock, providers["provider_a"], "provider_a", "account", a, ["industry", "employee_count"])["partial"] is True


def test_contact_enrichment(conn, clock, world, providers):
    ct = world.contacts[0]
    aid = acct(conn, clock, world)
    cid = conn.execute("INSERT INTO gtm.contact(account_id, full_name, email, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id", (aid, ct.full_name, ct.email, clock.now(), clock.now())).fetchone()["id"]
    r = enrich_entity(conn, clock, providers, entity_type="contact", entity_id=cid, fields=["title", "seniority"], cost_cap=20)
    assert set(r.resolved) == {"title", "seniority"} and "provider_b" in r.providers_tried


def test_parent_domain_mapping(conn, clock, world):
    from gtm.contracts.sims import ProviderField, ProviderResponse

    class Stub:
        def company(self, *, domain=None, name=None, fields):
            return ProviderResponse(provider="provider_b", found=True, cost_units=10,
                                    fields={"parent_id": ProviderField(value="co_003", as_of=clock.now())})
    a = acct(conn, clock, world, "co_001")
    dom = {c.id: c.domain for c in world.companies}
    r = fetch_provider(conn, clock, Stub(), "provider_b", "account", a, ["parent_domain"], parent_resolver=dom.get)
    assert list(r["observation_ids"]) == ["parent_domain"]
    assert conn.execute("SELECT value FROM gtm.observation WHERE id=%s", (r["observation_ids"]["parent_domain"],)).fetchone()["value"] == dom["co_003"]
    r = fetch_provider(conn, clock, Stub(), "provider_b", "account", a, ["parent_domain"])      # no resolver: raw reference kept
    assert list(r["observation_ids"]) == ["parent_ref"]


# ---------------- survivorship ----------------
def mk(conn, clock):
    return conn.execute("INSERT INTO gtm.account(name, data_origin, created_at, updated_at) VALUES ('Acme Example','GT',%s,%s) RETURNING id", (clock.now(), clock.now())).fetchone()["id"]


def obs(conn, clock, a, field, value, source, age_days=1, conf=None):
    return record_observation(conn, clock, entity_type="account", entity_id=a, field=field, value=value, source=source,
                              observed_at=clock.now() - timedelta(days=age_days), confidence=conf)


def test_agreement_combines_independent_sources(conn, clock):
    a = mk(conn, clock)
    obs(conn, clock, a, "employee_count", 500, "provider_a")
    r1 = resolve_fields(conn, clock, "account", a)["employee_count"]
    obs(conn, clock, a, "employee_count", 500, "provider_b")
    r2 = resolve_fields(conn, clock, "account", a)["employee_count"]
    assert r2["confidence"] > r1["confidence"] and abs(r2["confidence"] - (1 - (1 - 0.6) * (1 - 0.95))) < 1e-3 and not r2["conflict_flag"]


def test_higher_reliability_wins_and_conflict_flag_when_close(conn, clock):
    a = mk(conn, clock)
    obs(conn, clock, a, "employee_count", 500, "provider_a")
    obs(conn, clock, a, "employee_count", 900, "provider_b")
    r = resolve_fields(conn, clock, "account", a)["employee_count"]
    assert r["value"] == 900 and not r["conflict_flag"]
    b = mk(conn, clock)
    obs(conn, clock, b, "employee_count", 500, "provider_a", conf=0.8)
    obs(conn, clock, b, "employee_count", 900, "provider_b", conf=0.78)
    r = resolve_fields(conn, clock, "account", b)["employee_count"]
    assert r["conflict_flag"] and r["confidence"] <= 0.5
    row = conn.execute("SELECT conflict_flag FROM gtm.resolved_field WHERE entity_id=%s AND field='employee_count'", (b,)).fetchone()
    assert row["conflict_flag"] is True


def test_expired_excluded_from_scoring(conn, clock):
    a = mk(conn, clock)
    obs(conn, clock, a, "employee_count", 900, "provider_b", age_days=200)      # TTL 120: expired, though most reliable
    obs(conn, clock, a, "employee_count", 500, "provider_a", age_days=5)
    r = resolve_fields(conn, clock, "account", a)["employee_count"]
    assert r["value"] == 500 and r["freshness_state"] == "fresh" and not r["conflict_flag"]
    b = mk(conn, clock)
    obs(conn, clock, b, "hiring_signals", ["Hiring: ML Engineer"], "provider_c", age_days=20)   # TTL 14
    r = resolve_fields(conn, clock, "account", b)["hiring_signals"]
    assert r["freshness_state"] == "expired" and r["confidence"] < 0.3
    c = mk(conn, clock)
    obs(conn, clock, c, "employee_count", 500, "provider_b", age_days=100)
    assert resolve_fields(conn, clock, "account", c)["employee_count"]["freshness_state"] == "stale"


def test_human_value_wins_unless_expired_and_contradicted_by_two(conn, clock):
    a = mk(conn, clock)
    obs(conn, clock, a, "industry", "Logistics", "human", age_days=10)
    obs(conn, clock, a, "industry", "Retail", "provider_b")
    obs(conn, clock, a, "industry", "Retail", "provider_a")
    r = resolve_fields(conn, clock, "account", a)["industry"]
    assert r["value"] == "Logistics" and not r["needs_human_review"]
    b = mk(conn, clock)
    obs(conn, clock, b, "industry", "Logistics", "human", age_days=300)          # expired (TTL 120)
    obs(conn, clock, b, "industry", "Retail", "provider_b")
    assert resolve_fields(conn, clock, "account", b)["industry"]["value"] == "Logistics"   # one source is not enough
    obs(conn, clock, b, "industry", "Retail", "provider_a")
    r = resolve_fields(conn, clock, "account", b)["industry"]
    assert r["value"] == "Retail" and r["needs_human_review"] and r["conflict_flag"]


def test_superseded_retained_and_get_resolved_provenance(conn, clock):
    a = mk(conn, clock)
    first = obs(conn, clock, a, "industry", "Retail", "provider_b")
    second = obs(conn, clock, a, "industry", "Retail Trade", "provider_b")
    assert conn.execute("SELECT superseded_by FROM gtm.observation WHERE id=%s", (first,)).fetchone()["superseded_by"] == second
    assert conn.execute("SELECT count(*) AS n FROM gtm.observation WHERE entity_id=%s", (a,)).fetchone()["n"] == 2
    obs(conn, clock, a, "industry", "Retail Trade", "provider_a")
    resolve_fields(conn, clock, "account", a)
    g = get_resolved(conn, "account", a)["industry"]
    assert g["value"] == "Retail Trade" and {s["source"] for s in g["sources"]} == {"provider_a", "provider_b"} and all(s["agrees"] for s in g["sources"])
    assert set(g) >= {"value", "confidence", "freshness_state", "conflict_flag", "sources"}


def test_provider_b_more_accurate_than_a_on_resolved_fields(conn, clock, world, sims):
    cl = sims.clients().providers
    acc = {}
    for name in ("provider_a", "provider_b"):
        ok = n = 0
        for co in world.companies:
            if co.id == "co_001":
                continue
            a = conn.execute("INSERT INTO gtm.account(name, data_origin, created_at, updated_at) VALUES (%s,'GT',%s,%s) RETURNING id", (co.name, clock.now(), clock.now())).fetchone()["id"]
            r = enrich_entity(conn, clock, {name: cl[name]}, entity_type="account", entity_id=a, fields=["employee_count", "industry", "revenue_band"], cost_cap=100)
            for f, v in r.resolved.items():
                n += 1
                ok += v["value"] == getattr(co, f)
        acc[name] = ok / n
    print(f"\n[SIMULATED WORLD] resolved-field accuracy vs ground truth: provider_a={acc['provider_a']:.2f} provider_b={acc['provider_b']:.2f}")
    assert acc["provider_b"] > acc["provider_a"] + 0.05 and acc["provider_b"] > 0.8 and 0.55 < acc["provider_a"] < 0.95
