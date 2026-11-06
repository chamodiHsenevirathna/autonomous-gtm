from gtm.contracts.world import World
from gtm.world import generate_world, covers


def test_deterministic_byte_identical():
    assert generate_world(42).model_dump_json() == generate_world(42).model_dump_json()
    assert generate_world(42).model_dump_json() != generate_world(7).model_dump_json()


def test_roundtrip_and_sizes():
    w = generate_world()
    assert World.model_validate_json(w.model_dump_json()) == w
    assert len(w.companies) == 40 and 80 <= len(w.contacts) <= 130
    assert len({c.id for c in w.companies}) == 40 and len({c.domain for c in w.companies}) == 40
    assert len({c.email for c in w.contacts}) == len(w.contacts)
    assert all(c.domain.endswith(".example") for c in w.companies)
    assert all(c.email.endswith(".example") for c in w.contacts)
    assert all(2 <= sum(1 for ct in w.contacts if ct.company_id == c.id) <= 3 for c in w.companies if c.id not in {p[1] for p in w.duplicate_company_pairs})


def test_label_sanity():
    w = generate_world()
    ids = {c.id for c in w.companies}
    assert all(c.service_need for c in w.companies if c.icp_fit)
    assert all(c.service_need is None for c in w.companies if not c.icp_fit)
    assert all(c.parent_id in ids for c in w.companies if c.parent_id)
    assert sum(1 for c in w.companies if c.parent_id) >= 3 and any(c.alias_domains for c in w.companies)
    assert 8 <= sum(c.icp_fit for c in w.companies) <= 35
    assert len(w.duplicate_company_pairs) == 2 and all(a in ids and b in ids for a, b in w.duplicate_company_pairs)
    assert len({c.industry for c in w.companies}) >= 6


def test_golden_thread():
    w = generate_world()
    e = next(x for x in w.enquiries if x.id == "enq_001")
    c = next(x for x in w.companies if x.id == "co_001")
    ct = next(x for x in w.contacts if x.id == "ct_001")
    assert (e.kind, e.expected_band, e.truth_company_id, e.truth_contact_id) == ("genuine", "high", "co_001", "ct_001")
    assert c.icp_fit and c.service_need == "data engineering" and 200 <= c.employee_count <= 2000
    assert ct.company_id == "co_001" and ct.seniority in ("vp", "c_level") and e.email == ct.email
    assert e.duplicate_of is None and not e.injection
    assert {r.kind for r in w.replies if r.to_enquiry_id == "enq_001"} == {"interested", "meeting_booked"}


def test_scripted_enquiry_coverage():
    w = generate_world()
    E = {e.id: e for e in w.enquiries}
    kinds = {e.kind for e in w.enquiries}
    assert kinds == {"genuine", "vendor", "recruiter", "spam"}
    assert [e for e in w.enquiries if e.injection] and all(e.expected_band == "none" for e in w.enquiries if e.injection)
    # exact duplicate: same email as its original
    exact = [e for e in w.enquiries if e.duplicate_of and e.email == E[e.duplicate_of].email]
    assert exact
    # fuzzy duplicate: different email/name but the same truth contact
    fuzzy = [e for e in w.enquiries if e.duplicate_of and e.email != E[e.duplicate_of].email]
    assert fuzzy and all(e.full_name != E[e.duplicate_of].full_name and e.truth_contact_id == E[e.duplicate_of].truth_contact_id for e in fuzzy)
    co = {c.id: c for c in w.companies}
    sub = [e for e in w.enquiries if e.truth_company_id and co[e.truth_company_id].parent_id]
    assert sub and all(e.company_name == co[co[e.truth_company_id].parent_id].name for e in sub)
    assert [e for e in w.enquiries if e.email.startswith("info@")]
    assert [e for e in w.enquiries if e.expected_band == "low"]
    assert all(e.duplicate_of in E for e in w.enquiries if e.duplicate_of)


def test_partial_coverage_enquiry_exists():
    w = generate_world()
    pa, pb, pc = w.providers
    found = [e for e in w.enquiries if e.truth_company_id and covers(w.seed, "provider_a", pa.coverage, e.truth_company_id)
             and not covers(w.seed, "provider_b", pb.coverage, e.truth_company_id)]
    assert found


def test_replies_pages_providers():
    w = generate_world()
    assert {r.kind for r in w.replies} == {"interested", "not_now", "not_interested", "ooo", "bounce", "unsubscribe", "referral", "question", "meeting_booked"}
    enq = {e.id for e in w.enquiries}
    assert all(r.to_enquiry_id in enq for r in w.replies) and len({r.id for r in w.replies}) == len(w.replies)
    assert sum(p.contains_injection for p in w.web_pages) >= 2
    assert len({p.url for p in w.web_pages}) == len(w.web_pages)
    assert any(p.company_id == "co_001" for p in w.web_pages)
    pa, pb, pc = w.providers
    assert (pa.coverage, pa.accuracy, pa.cost_per_call) == (0.9, 0.8, 1) and pb.cost_per_call == 10 and pb.coverage < 0.5
    assert pb.accuracy > pc.accuracy > pa.accuracy - 0.01 and pb.latency_ms > pa.latency_ms
    assert "tech_stack" in pc.fields


def test_larger_world_params():
    w = generate_world(1, {"n_companies": 120})
    assert len(w.companies) == 120 and len(w.enquiries) >= 14
