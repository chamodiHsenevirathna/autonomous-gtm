import pytest
from gtm.approvals import decide
from gtm.data import (attach_parent, attach_parent_from_resolved, ensure_account, ensure_contact, propose_match, record_observation,
                      resolve_account, resolve_contact, resolve_fields, scan_duplicates)
from gtm.data.entity_resolution import (account_domain_key, is_role_mailbox, normalize_company_name, normalize_domain, normalize_email)
from gtm.data.merge import record_match_rejection
from conftest import seed_accounts

pytestmark = pytest.mark.db
EMIT = lambda *a, **k: None


def test_normalisation():
    assert normalize_email(" Ana.Reyes+promo@Example.COM ") == "ana.reyes@example.com"
    assert normalize_domain("https://www.Acme-Example.com/about") == "acme-example.com"
    assert account_domain_key("gmail.com") is None and account_domain_key("WWW.corvane.example") == "corvane.example"
    assert normalize_company_name("Wexcombe Farms, Ltd.") == normalize_company_name("WEXCOMBE FARMS LTD") == "wexcombe farms"
    assert normalize_company_name("Ltd") == "ltd" and normalize_company_name("Smith & Sons Inc") == "smith and sons"
    assert is_role_mailbox("Info@acme.example") and is_role_mailbox("sales+x@acme.example") and not is_role_mailbox("ana@acme.example")


def test_account_bands(conn, clock):
    a, d = ensure_account(conn, clock, name="Kestrel Systems", domain="kestrel-systems.example")
    assert d.band == "distinct"
    # same: exact domain + name similarity >= 0.9 (suffix and www normalised)
    b, d = ensure_account(conn, clock, name="KESTREL SYSTEMS LTD", domain="www.kestrel-systems.example")
    assert b == a and d.band == "same" and d.match_id
    assert conn.execute("SELECT count(*) AS n FROM gtm.account").fetchone()["n"] == 1
    # alias domain learned from a link
    c, d = ensure_account(conn, clock, name="Kestrel Systems", domain="kestrel-group.example")
    assert d.band == "possible" and c != a and d.candidate_id == a                      # name equal, different domain: ask a human
    assert conn.execute("SELECT decision, band FROM gtm.entity_match WHERE left_id=%s AND right_id=%s", (c, a)).fetchone() == {"decision": "pending", "band": "possible"}
    # distinct
    e, d = ensure_account(conn, clock, name="Redwater Networks", domain="redwater-networks.example")
    assert d.band == "distinct" and e not in (a, c)
    # same domain, quite different name: conflicting strong keys => possible, not same
    d = resolve_account(conn, clock, name="Totally Different Holdings", domain="kestrel-systems.example")
    assert d.band == "possible" and d.reason == "domain_exact_name_differs"


def test_free_mail_never_an_account_key(conn, clock):
    a, _ = ensure_account(conn, clock, name="Pemberton Consulting", domain="gmail.com")
    assert conn.execute("SELECT primary_domain FROM gtm.account WHERE id=%s", (a,)).fetchone()["primary_domain"] is None
    b, d = ensure_account(conn, clock, name="Marsh Advisory", domain="gmail.com")
    assert b != a and d.band == "distinct"
    assert conn.execute("SELECT count(*) AS n FROM gtm.account_domain WHERE domain='gmail.com'").fetchone()["n"] == 0


def test_contact_exact_plus_address_and_fuzzy(conn, clock):
    acc, _ = ensure_account(conn, clock, name="Harrowgate Manufacturing", domain="harrowgate-manufacturing.example")
    c1, d = ensure_contact(conn, clock, email="hannah.vasquez@harrowgate-manufacturing.example", full_name="Hannah Vasquez", account_id=acc)
    assert d.band == "distinct"
    c2, d = ensure_contact(conn, clock, email="Hannah.Vasquez+inbound@Harrowgate-Manufacturing.example", full_name="H. Vasquez")
    assert c2 == c1 and d.band == "same" and d.reason == "email_exact"
    # fuzzy: typo in the name and an alias domain => possible, new row, pending match, no merge
    acc2, _ = ensure_account(conn, clock, name="Harrowgate Manufacturing", domain="harrowgate-group.example")
    c3, d = ensure_contact(conn, clock, email="hannah.vasquez@harrowgate-group.example", full_name="Hannahh Vasquez",
                           company_name="Harrowgate Manufacturing", account_id=acc2)
    assert d.band == "possible" and d.candidate_id == c1 and c3 != c1 and d.needs_proposal
    assert conn.execute("SELECT merged_into_id FROM gtm.contact WHERE id=%s", (c3,)).fetchone()["merged_into_id"] is None
    # different person, same company: distinct
    _, d = ensure_contact(conn, clock, email="oskar.novak@harrowgate-manufacturing.example", full_name="Oskar Novak", account_id=acc)
    assert d.band == "distinct"


def test_shared_mailbox_never_matches_people(conn, clock):
    acc, _ = ensure_account(conn, clock, name="Redwater Networks", domain="redwater-networks.example")
    p, _ = ensure_contact(conn, clock, email="info.desk@redwater-networks.example", full_name="Info Desk", account_id=acc)
    m, d = ensure_contact(conn, clock, email="info@redwater-networks.example", full_name="Info Desk", account_id=acc)
    assert m != p and d.band == "distinct" and d.reason == "role_mailbox"
    m2, d2 = ensure_contact(conn, clock, email="info+form@redwater-networks.example", full_name="Operations Team", account_id=acc)
    assert m2 == m and d2.reason == "same_role_mailbox"          # the same shared mailbox, still never a person
    s, d3 = ensure_contact(conn, clock, email="sales@redwater-networks.example", full_name="Info Desk")
    assert d3.band == "distinct" and s not in (p, m)
    # a person lookalike never links to a role mailbox
    _, d4 = ensure_contact(conn, clock, email="x.person@redwater-networks.example", full_name="Info Desk", account_id=acc)
    assert d4.candidate_id != m


def test_negative_match_memory(conn, clock):
    a, _ = ensure_account(conn, clock, name="Kestrel Systems", domain="kestrel-systems.example")
    b, d = ensure_account(conn, clock, name="Kestrel Systems", domain="kestrel-uk.example")
    assert d.band == "possible"
    pid = propose_match(conn, clock, d, b, emit=EMIT)
    assert pid and propose_match(conn, clock, d, b, emit=EMIT) == pid                    # idempotent while pending
    assert (conn.execute("SELECT type, gate_id, payload FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["gate_id"]) == "G1"
    assert scan_duplicates(conn, clock, "account")                                       # still a pending candidate
    decide(conn, clock, proposal_id=pid, decided_by="user:dev", decision="reject", reason_code="different_company", emit=EMIT)
    record_match_rejection(conn, clock, pid)
    row = conn.execute("SELECT * FROM gtm.entity_match WHERE entity_type='account' AND left_id=%s AND right_id=%s", (b, a)).fetchone()
    assert row["is_negative"] and row["decision"] == "distinct"
    assert scan_duplicates(conn, clock, "account") == []                                 # not re-asked
    assert propose_match(conn, clock, d, b, emit=EMIT) is None


def test_hierarchy_parent_attached_from_parent_domain_observation(conn, clock):
    p, _ = ensure_account(conn, clock, name="Meridian Industries", domain="meridian-industries.example")
    s, d = ensure_account(conn, clock, name="Meridian Digital", domain="meridian-digital.example")
    assert d.band == "distinct" and s != p                                               # a subsidiary is NOT a duplicate of its parent
    record_observation(conn, clock, entity_type="account", entity_id=s, field="parent_domain", value="meridian-industries.example", source="provider_b", observed_at=clock.now())
    resolve_fields(conn, clock, "account", s)
    assert attach_parent_from_resolved(conn, clock, s) == p
    assert attach_parent_from_resolved(conn, clock, s) == p                              # idempotent
    row = conn.execute("SELECT parent_account_id, hierarchy_role FROM gtm.account WHERE id=%s", (s,)).fetchone()
    assert row == {"parent_account_id": p, "hierarchy_role": "subsidiary"}
    assert conn.execute("SELECT hierarchy_role FROM gtm.account WHERE id=%s", (p,)).fetchone()["hierarchy_role"] == "ultimate_parent"
    rel = conn.execute("SELECT * FROM gtm.account_relationship").fetchall()
    assert len(rel) == 1 and (rel[0]["from_account_id"], rel[0]["to_account_id"], rel[0]["type"]) == (p, s, "parent_of")
    assert attach_parent(conn, clock, p, "meridian-digital.example") is None             # no cycles
    assert attach_parent(conn, clock, s, "unknown.example") is None and attach_parent(conn, clock, s, "meridian-digital.example") is None


# ------------- ER over the world's ground truth (SIMULATED WORLD numbers) -------------
def test_account_er_on_world_duplicate_pairs(conn, clock, world):
    truth = {frozenset(p) for p in world.duplicate_company_pairs}
    internal: dict[int, str] = {}
    flagged = set()
    for co in world.companies:
        aid, d = ensure_account(conn, clock, name=co.name, domain=co.domain)
        internal[aid] = co.id
        if d.band in ("possible", "same") and d.candidate_id:
            flagged.add(frozenset((co.id, internal.get(d.candidate_id, "?"))))
    # accounts that were auto-linked ("same") collapse into an existing row: count rows
    rows = conn.execute("SELECT count(*) AS n FROM gtm.account").fetchone()["n"]
    tp = len(flagged & truth)
    precision = tp / len(flagged) if flagged else 1.0
    recall = tp / len(truth)
    print(f"\n[SIMULATED WORLD] account ER: flagged={len(flagged)} true duplicate pairs={len(truth)} precision={precision:.2f} recall={recall:.2f}; rows={rows}/{len(world.companies)}")
    assert rows == len(world.companies)          # no wrong auto-link collapsed two distinct companies
    assert recall == 1.0 and precision >= 0.5


def test_account_er_alias_domain_links_automatically(conn, clock, world):
    ids = seed_accounts(conn, clock, world)
    co = next(c for c in world.companies if c.alias_domains)
    aid, d = ensure_account(conn, clock, name=co.name, domain=co.alias_domains[0])
    assert d.band == "same" and aid == ids[co.id]


def test_enquiry_er_on_world(conn, clock, world):
    """Process the scripted enquiries in order as the intake pipeline would; score duplicate detection against `duplicate_of`."""
    first_seen: dict[str, int] = {}
    results = {}
    for e in world.enquiries:
        dom = e.email.split("@")[1]
        acc, _ = ensure_account(conn, clock, name=e.company_name, domain=dom)
        cid, d = ensure_contact(conn, clock, email=e.email, full_name=e.full_name, company_name=e.company_name, account_id=acc)
        first_seen[e.id] = cid
        results[e.id] = (cid, d)
    dups = [e for e in world.enquiries if e.duplicate_of]
    exact = [e for e in dups if e.email == next(x for x in world.enquiries if x.id == e.duplicate_of).email]
    fuzzy = [e for e in dups if e not in exact]
    exact_recall = sum(results[e.id][1].band == "same" and results[e.id][0] == first_seen[e.duplicate_of] for e in exact) / len(exact)
    fuzzy_flagged = [results[e.id][1].band == "possible" and results[e.id][1].candidate_id == first_seen[e.duplicate_of] for e in fuzzy]
    wrong_auto = [e.id for e in world.enquiries if results[e.id][1].band == "same" and not e.duplicate_of]
    false_possible = [e.id for e in world.enquiries if results[e.id][1].band == "possible" and not e.duplicate_of]
    print(f"\n[SIMULATED WORLD] enquiry ER: exact-duplicate recall={exact_recall:.2f} ({len(exact)}), fuzzy flagged={sum(fuzzy_flagged)}/{len(fuzzy)}, "
          f"wrong auto-links={wrong_auto}, false 'possible' on non-duplicates={false_possible}")
    assert exact_recall == 1.0 and all(fuzzy_flagged) and wrong_auto == []
    assert false_possible == []
    shared = next(e for e in world.enquiries if e.email.startswith("info@"))
    assert results[shared.id][1].reason == "role_mailbox"
    assert conn.execute("SELECT count(*) AS n FROM gtm.entity_match WHERE entity_type='contact' AND band='possible'").fetchone()["n"] == len(fuzzy)


def test_subsidiary_enquiry_attached_to_parent(conn, clock, world):
    co = {c.id: c for c in world.companies}
    seed_accounts(conn, clock, world)
    sub = next(c for c in world.companies if c.parent_id and c.icp_fit)
    sid = conn.execute("SELECT id FROM gtm.account WHERE primary_domain=%s", (sub.domain,)).fetchone()["id"]
    record_observation(conn, clock, entity_type="account", entity_id=sid, field="parent_domain", value=co[sub.parent_id].domain, source="provider_b", observed_at=clock.now())
    resolve_fields(conn, clock, "account", sid)
    pid = attach_parent_from_resolved(conn, clock, sid)
    assert conn.execute("SELECT primary_domain FROM gtm.account WHERE id=%s", (pid,)).fetchone()["primary_domain"] == co[sub.parent_id].domain
    # all world subsidiaries attach the same way
    n = 0
    for c in world.companies:
        if c.parent_id:
            a = conn.execute("SELECT id FROM gtm.account WHERE primary_domain=%s", (c.domain,)).fetchone()["id"]
            n += attach_parent(conn, clock, a, co[c.parent_id].domain) is not None
    assert n == sum(1 for c in world.companies if c.parent_id)
