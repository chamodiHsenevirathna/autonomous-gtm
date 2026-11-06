from datetime import timedelta
import pytest
from psycopg.types.json import Jsonb
from gtm.contracts.world import World, TrueCompany, Enquiry
from gtm.eval import metrics as M


def co(i, domain, **kw):
    base = dict(id=f"co_{i}", name=f"Co {i}", domain=domain, industry="software", employee_count=100, revenue_band="10-50M",
                region="EMEA", hq_country="GB", icp_fit=True)
    return TrueCompany(**{**base, **kw})


def enq(i, kind="genuine", band="high", email=None, inj=False):
    return Enquiry(id=f"enq_{i}", kind=kind, expected_band=band, full_name="N", email=email or f"p{i}@c{i}.example",
                   company_name="C", message="m", injection=inj)


@pytest.fixture()
def world():
    return World(seed=1, companies=[co(1, "one.example", alias_domains=["one-alias.example"]), co(2, "two.example", employee_count=200),
                                    co(3, "three.example", industry="retail")],
                 contacts=[], enquiries=[enq(1), enq(2, "vendor", "none"), enq(3, "genuine", "medium"), enq(4, "spam", "none", inj=True)],
                 duplicate_company_pairs=[("co_2", "co_3")])


def test_value_matches():
    assert M.value_matches("employee_count", 105, 100)
    assert not M.value_matches("employee_count", 150, 100)
    assert M.value_matches("tech_stack", ["B", "a"], ["a", "b"])
    assert M.value_matches("industry", " Software ", "software")
    assert not M.value_matches("industry", None, "x")


def test_er_metrics_precision_recall_wrong_merge():
    r = M.er_metrics(predicted=[(1, 2), (3, 4)], truth=[(1, 2), (5, 6)], merged=[(3, 4), (1, 2)])
    assert r["er_precision"].value == 0.5 and r["er_precision"].denominator == 2
    assert r["er_recall"].value == 0.5 and r["er_recall"].details["missed"] == [[5, 6]]
    assert r["er_f1"].value == 0.5
    assert r["er_wrong_merge_rate"].value == 0.5 and r["er_wrong_merge_rate"].details["wrong"] == [[3, 4]]
    assert r["er_precision"].evidence_basis == "measured_on_simulation" and "GT" in r["er_precision"].data_origins


def test_er_empty_is_none_not_perfect():
    r = M.er_metrics([], [])
    assert r["er_precision"].value is None and r["er_recall"].denominator == 0


def test_truth_account_pairs_uses_alias_and_dup_pairs(world):
    a2c = M.account_truth_map([{"id": 10, "primary_domain": "one.example"}, {"id": 11, "primary_domain": "one-alias.example"},
                               {"id": 12, "primary_domain": "two.example"}, {"id": 13, "primary_domain": "three.example"},
                               {"id": 14, "primary_domain": "unknown.example"}], [], world)
    assert a2c == {10: "co_1", 11: "co_1", 12: "co_2", 13: "co_3"}
    assert M.truth_account_pairs(a2c, world) == {frozenset((10, 11)), frozenset((12, 13))}


def test_provider_accuracy_and_coverage(world):
    a2c = {1: "co_1", 2: "co_2", 3: "co_3"}
    obs = [dict(entity_type="account", entity_id=1, field="industry", value="software", provider="provider_a"),
           dict(entity_type="account", entity_id=2, field="industry", value="retail", provider="provider_a"),
           dict(entity_type="account", entity_id=2, field="employee_count", value=205, provider="provider_a"),
           dict(entity_type="account", entity_id=1, field="industry", value="software", provider="provider_b")]
    r = M.provider_field_metrics(obs, a2c, world, queried={"provider_a": {1, 2, 3}})
    assert r["provider_accuracy.provider_a"].value == pytest.approx(2 / 3) and r["provider_accuracy.provider_a"].denominator == 3
    assert r["provider_accuracy.provider_a.industry"].value == 0.5
    assert r["provider_accuracy.provider_a.employee_count"].value == 1.0
    assert r["provider_coverage.provider_a"].value == pytest.approx(2 / 3)
    assert r["provider_coverage.provider_b"].denominator == 2  # default queried = every entity with an observation


def test_resolved_field_accuracy_and_calibration_bins(world):
    a2c = {1: "co_1", 2: "co_2"}
    rows = [dict(entity_type="account", entity_id=1, field="industry", value="software", confidence=0.95),
            dict(entity_type="account", entity_id=2, field="industry", value="wrong", confidence=0.95),
            dict(entity_type="account", entity_id=1, field="region", value="EMEA", confidence=0.5),
            dict(entity_type="account", entity_id=1, field="hq_country", value="GB", confidence=0.1)]
    r = M.resolved_field_metrics(rows, a2c, world)
    assert r["resolved_field_accuracy"].value == 0.75
    bins = r["calibration_ece"].details["bins"]
    assert bins[4]["n"] == 2 and bins[4]["accuracy"] == 0.5 and bins[0]["n"] == 1
    assert r["calibration_ece"].value == pytest.approx((2 * abs(0.95 - 0.5) + abs(0.5 - 1.0) + abs(0.1 - 1.0)) / 4)


def test_qualification_metrics_and_false_negatives():
    pairs = [("e1", "high", "high"), ("e2", "medium", "low"), ("e3", "none", "medium"), ("e4", "none", "none"), ("e5", "low", "low")]
    r = M.qualification_metrics(pairs)
    assert r["qualification_accuracy"].value == 0.6
    assert r["qualification_precision"].value == 0.5 and r["qualification_precision"].details["false_positives"] == ["e3"]
    assert r["qualification_recall"].value == 0.5 and r["qualification_recall"].details["false_negatives"] == ["e2"]
    assert r["qualification_false_negatives"].details["enquiry_ids"] == ["e2"]


def test_triage_confusion_matrix():
    r = M.triage_metrics([("a", "genuine", "genuine", False), ("b", "vendor", "genuine", False), ("c", "spam", "spam", True), ("d", "spam", "unclear", True)])
    assert r["triage_accuracy"].value == 0.5
    assert r["triage_accuracy"].details["confusion"]["vendor"] == {"genuine": 1}
    assert r["triage_injection_accuracy"].value == 0.5 and r["triage_injection_accuracy"].denominator == 2


def test_hold_metrics():
    r = M.hold_metrics([("a", "vendor", "held"), ("b", "spam", "archived"), ("c", "genuine", "held"), ("d", "genuine", "routed")])
    assert r["hold_precision"].value == pytest.approx(2 / 3) and r["hold_precision"].details["wrongly_held"] == ["c"]
    assert r["real_leads_held"].value == 1 and r["real_leads_held"].denominator == 2
    assert M.hold_metrics([])["hold_precision"].value is None


def test_tool_call_metrics():
    rows = [dict(principal="agent:research-agent", tool_name="search_web_sim", permitted=True),
            dict(principal="agent:research-agent", tool_name="create_proposal", permitted=False),
            dict(principal="agent:account-agent", tool_name="send_email", permitted=True),
            dict(principal="system:orchestrator", tool_name="whatever", permitted=True)]
    r = M.tool_call_metrics(rows, expected_tools={"agent:research-agent": {"search_web_sim", "fetch_page_sim"}})
    assert r["tool_call_correctness"].value == pytest.approx(1 / 3)
    assert r["tool_calls_denied"].value == 1 and r["tool_calls_denied"].details["by_tool"] == {"create_proposal": 1}
    assert r["tool_call_recall"].value == 0.5


def test_percentile_and_cost_latency(clock):
    t = clock.now()
    runs = [dict(workflow="w", status="completed", cost=1.5, tokens_in=10, tokens_out=5, started_at=t, ended_at=t + timedelta(seconds=s)) for s in (10, 20, 30)]
    runs.append(dict(workflow="w", status="failed", cost=0.5, tokens_in=0, tokens_out=0, started_at=t, ended_at=None))
    r = M.cost_latency_metrics(runs, [dict(started_at=t, ended_at=t + timedelta(seconds=2))])
    assert r["cost_total"].value == 5.0 and r["cost_total"].details["tokens_in"] == 30
    assert r["run_latency_p50_s"].value == 20 and r["run_failure_rate"].value == 0.25
    assert M.percentile([], .5) is None and M.percentile([4], .95) == 4


@pytest.mark.db
def test_compute_all_from_db_rows(conn, clock, world):
    now = clock.now()
    for name, dom in (("One", "one.example"), ("Two", "two.example")):
        conn.execute("INSERT INTO gtm.account(name, primary_domain, created_at, updated_at) VALUES (%s,%s,%s,%s)", (name, dom, now, now))
    src = conn.execute("SELECT id FROM gtm.data_source WHERE name='provider_a'").fetchone()["id"]
    conn.execute("INSERT INTO gtm.observation(entity_type, entity_id, field, value, data_source_id, observed_at, fetched_at, confidence) "
                 "VALUES ('account',1,'industry',%s,%s,%s,%s,0.8)", (Jsonb("software"), src, now, now))
    conn.execute("INSERT INTO gtm.lead(channel, raw_payload, idempotency_key, triage_class, fit_band, created_at, updated_at) "
                 "VALUES ('form',%s,'k1','genuine','high',%s,%s)", (Jsonb({"enquiry_id": "enq_1"}), now, now))
    conn.execute("INSERT INTO gtm.lead(channel, raw_payload, idempotency_key, triage_class, fit_band, created_at, updated_at) "
                 "VALUES ('form',%s,'k2','genuine',NULL,%s,%s)", (Jsonb({"email": "p2@c2.example"}), now, now))
    conn.commit()
    r = M.compute_all(conn, world)
    assert r["provider_accuracy.provider_a"].value == 1.0
    assert r["qualification_accuracy"].denominator == 2 and r["qualification_accuracy"].value == 1.0  # missing band counts as "none"
    assert r["triage_accuracy"].details["confusion"]["vendor"] == {"genuine": 1}
    assert r["er_precision"].value is None
    assert all(M.is_known_metric(k) for k in r)
    assert M.compute_all(conn, world, enquiry_ids=["enq_1"])["qualification_accuracy"].denominator == 1
