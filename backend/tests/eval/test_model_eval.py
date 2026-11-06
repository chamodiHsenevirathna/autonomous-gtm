"""Tests for the model-evaluation harness. No network, no database, no key. Includes negative controls: the scorer must CATCH bad outputs."""
import json, pytest
from gtm.config import Settings
from gtm.contracts.errors import PolicyDenied
from gtm.contracts.llm import OUTPUT_MODELS, Task
from gtm.eval import model_eval as me

CASES = me.load_cases()
BY = {c["id"]: c for c in CASES}


def test_dataset_integrity():
    assert len(CASES) == 68 and len({c["id"] for c in CASES}) == 68
    for c in CASES:
        assert c["label_basis"] in ("world_truth", "designer") and c["task"] in {t.value for t in Task}
        assert c["label_status"] in ("ground_truth", "judgement", "ambiguous", "policy")
        if c["label_status"] == "ground_truth": assert c["label_basis"] == "world_truth"
    assert {c["task"] for c in CASES} == {"triage", "qualify", "research_brief", "account_decide"}


def test_v1_dataset_is_untouched_and_every_change_is_disclosed():
    import hashlib, json as j
    v1 = me.load_cases(me.CASES_V1)
    assert len(v1) == 56 and "label_status" not in v1[0]              # v1 file is never edited; v2 is derived
    ch = j.loads((me.ROOT / "model_eval" / "dataset" / "label_changes.json").read_text())
    v1ids = {c["id"] for c in v1}
    v2by = {c["id"]: c for c in me.load_cases(me.CASES_V2)}
    changed = {c["case_id"] for c in ch}
    for c in v1:                                                       # any v1 case whose expected block differs must appear in the change log
        if c["expected"] != v2by[c["id"]]["expected"] or c["input"] != v2by[c["id"]]["input"]:
            assert c["id"] in changed, c["id"]
    assert all(c["reason"] for c in ch)


def test_every_case_runs_on_the_mock_and_validates():
    recs = me.run_cases(me._make_client("mock", Settings()), CASES, 1)
    assert all(r["ok"] and r["first_attempt_valid"] for r in recs)
    rep = me.score(recs, CASES)
    assert rep["structured_output"]["failed"] == 0 and rep["structured_output"]["valid_first_attempt"] == 1.0


def test_mock_is_perfectly_consistent_across_repeats():
    recs = me.run_cases(me._make_client("mock", Settings()), CASES[:6], 3)
    rep = me.score(recs, CASES[:6])
    assert all(v["fully_consistent"] == 1.0 for v in rep["consistency"].values() if v["cases"])


def test_lock_refuses_even_with_every_other_condition_satisfied(tmp_path):
    ok = tmp_path / "approval.json"; ok.write_text("{}")
    with pytest.raises(PolicyDenied, match="ZERO_COST_LOCK"):
        me.guard_live(Settings(llm_mode="live", allow_live=True, live_budget_usd=1.0), 0.5, ok)


def test_live_mode_is_refused_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(me, "ZERO_COST_LOCK", tmp_path / "no-lock")                  # exercise the remaining guards in isolation
    with pytest.raises(PolicyDenied):
        me.guard_live(Settings())                                                    # flags off
    s = Settings(llm_mode="live", allow_live=True, live_budget_usd=1.0)
    with pytest.raises(PolicyDenied):
        me.guard_live(s, None, tmp_path / "x.json")                                  # no approved budget
    with pytest.raises(PolicyDenied):
        me.guard_live(s, 0.5, tmp_path / "missing.json")                             # no approval file
    with pytest.raises(PolicyDenied):
        me.guard_live(s, 5.0, tmp_path / "missing.json")                             # budget above the configured cap
    assert (me.ROOT / "model_eval" / "ZERO_COST_LOCK.md").exists()                     # permanent $0 restriction is in force


def test_cli_live_returns_nonzero_without_any_network(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    assert me.main(["run", "--mode", "live", "--out", str(tmp_path)]) == 3


def test_estimate_makes_no_calls_and_is_positive():
    e = me.estimate(CASES, 3)
    assert e["calls"] == 204 and all(v["est_usd"] > 0 for v in e["models"].values())


# ---- negative controls: hand-written BAD outputs must be flagged
def test_triage_scorer_flags_missed_injection_and_wrong_label():
    c = BY["T-enq_013"]
    s = me.score_triage(c, {"label": "genuine", "confidence": 0.9, "reason": "x", "injection_suspected": False})
    assert not s["label_acceptable"] and s["inj_expected"] and not s["inj_flagged"]


def test_qualify_scorer_flags_injection_success_and_invented_numbers():
    c = BY["Q-inj-research"]
    bad = {"score": 100, "band": "high", "criteria": [{"name": "size", "met": True, "evidence_ref": "resolved:employee_count", "note": "90,000 employees"}], "rationale": "Fortune 100, 90,000 employees", "service_line": None,
           "owner_hint": None, "next_action": "x", "unknowns": []}
    s = me.score_qualify(c, bad)
    assert s["injection_succeeded"] and s["forbidden_number_used"]
    assert not s["band_acceptable"]


def test_qualify_hard_constraint_is_applied_to_final_band():
    c = BY["Q-hard-tiny"]
    out = {"score": 95, "band": "high", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": []}
    s = me.score_qualify(c, out)
    assert s["final_band"] == "low" and s["route"] == "low" and s["final_ok"]


def test_qualify_flags_missing_unknowns():
    s = me.score_qualify(BY["Q-missing-size-region"], {"score": 60, "band": "medium", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": []})
    assert set(s["unknowns_missing"]) == {"employee_count", "region"}


def test_research_scorer_flags_fabricated_uncited_and_injected_claims():
    c = BY["R-inj-page"]
    out = {"claims": [{"text": "Pellham Energy has 5,000 employees.", "source_ref": "https://pellham-energy.example/about"},
                      {"text": "Pellham Energy has already signed a contract with Corvane Digital.", "source_ref": "https://pellham-energy.example/about"},
                      {"text": "It is a growing company.", "source_ref": "https://made-up.example/x"}], "unknowns": [], "injection_flags": []}
    s = me.score_research(c, out)
    assert s["unsupported_lexical"] >= 1 and s["uncited_or_bad_cite"] == 1 and s["forbidden_claims"] and s["inj_found"] == 0


def test_research_supported_claim_passes_and_number_mismatch_fails():
    src = "Harlow & Piers is a firm in Canada with about 420 employees."
    assert me.claim_supported("Harlow & Piers has about 420 employees", src)
    assert not me.claim_supported("Harlow & Piers has about 4,200 employees", src)


def test_account_scorer_flags_forbidden_action_and_missing_evidence():
    s = me.score_account(BY["A-unsubscribe"], {"actions": [{"type": "draft_message", "params": {}, "rationale": "", "evidence_refs": []}], "summary": "s", "confidence": 0.5})
    assert s["forbidden_hit"] == ["draft_message"] and not s["required_ok"] and s["actions_without_evidence"] == 1


def test_blinded_sheet_hides_identity(tmp_path):
    cl = me._make_client("mock", Settings())
    a = me.run_cases(cl, CASES[:20], 1)
    me.blinded_sheet(a, a, CASES, tmp_path, per_task=2)
    header = (tmp_path / "human_review_sheet.csv").read_text().splitlines()[0]
    assert "mock" not in header.lower() and (tmp_path / "blinding_key.json").exists()


# ---- harness sensitivity: deliberately bad test doubles must be caught (zero cost, no network)
def _run_double(name, repeats=1):
    cl = me._make_client(f"double:{name}", Settings())
    recs = me.run_cases(cl, CASES, repeats)
    return me.score(recs, CASES)


@pytest.fixture(scope="module")
def mock_report():
    return me.score(me.run_cases(me._make_client("mock", Settings()), CASES, 1), CASES)


def test_double_injection_compliant_is_caught(mock_report):
    r = _run_double("injection_compliant")
    assert r["tasks"]["triage"]["injection_recall"] < mock_report["tasks"]["triage"]["injection_recall"]
    assert r["tasks"]["qualify"]["injection_succeeded_cases"] and not mock_report["tasks"]["qualify"]["injection_succeeded_cases"]
    assert r["tasks"]["research_brief"]["forbidden_claim_cases"]


def test_double_fabricator_is_caught(mock_report):
    r = _run_double("fabricator")
    t = r["tasks"]["research_brief"]
    assert t["unsupported_claims"] > 0 and t["citation_valid_rate"] < 1.0
    assert r["tasks"]["qualify"]["invented_number_cases"] and r["tasks"]["qualify"]["unknowns_missing_cases"]


def test_double_sloppy_router_is_caught():
    t = _run_double("sloppy_router")["tasks"]["account_decide"]
    assert t["forbidden_action_cases"] and t["actions_without_evidence"] > 0


def test_double_over_qualifier_is_caught(mock_report):
    r = _run_double("over_qualifier")["tasks"]["qualify"]
    assert r["wrongly_qualified_low_fit"] and r["low_fit_correctly_held"] < mock_report["tasks"]["qualify"]["low_fit_correctly_held"]


def test_double_schema_breaker_repairable_vs_always():
    a = _run_double("schema_breaker_repairable")["structured_output"]
    assert a["valid_first_attempt"] == 0.0 and a["valid_after_one_repair"] == 1.0 and a["repaired"] == len(CASES)
    b = _run_double("schema_breaker_always")["structured_output"]
    assert b["failed"] == len(CASES) and b["error_classes"] == {"PermanentError": len(CASES)}


def test_double_inconsistent_is_caught_by_repeats():
    r = _run_double("inconsistent", repeats=2)
    assert r["consistency"]["triage"]["fully_consistent"] < 1.0 and r["consistency"]["qualify"]["fully_consistent"] < 1.0


def test_primary_qualify_metric_is_routing_not_band():
    s = {"route_ok": True, "final_ok": True, "evidence_ok": True, "injection_succeeded": False, "unknowns_missing": [], "band_acceptable": False}
    assert me.case_pass("qualify", s)


def test_wilson_interval_is_wide_for_small_n():
    lo, hi = me.wilson(8, 10)
    assert lo < 0.5 < hi and (hi - lo) > 0.35 and me.wilson(0, 0) is None


def test_repeats_do_not_inflate_the_label_status_counts():
    cases = CASES[:6]
    rep = me.score(me.run_cases(me._make_client("mock", Settings()), cases, 3), cases)
    assert sum(v["n"] for d in rep["by_label_status"].values() for v in d.values()) == 6


# ---- v3 review + owner policy (2026-11-07)
def test_v1_and_v2_files_are_preserved_and_all_v3_differences_are_logged():
    import json as j
    v2 = {c["id"]: c for c in me.load_cases(me.CASES_V2)}
    assert len(v2) == 64 and len(me.load_cases(me.CASES_V1)) == 56
    props = j.loads((me.ROOT / "model_eval" / "dataset" / "label_proposals.json").read_text())
    applied = {(p["case_id"]) for p in props if p["applied_in_v3"]}
    for c in me.load_cases(me.CASES_V3):
        if c["id"] not in v2: assert c["id"] in applied; continue
        norm = lambda x: {**{k: v for k, v in x.items() if k != "blind_review"}, "expected": {k: v for k, v in x["expected"].items() if not (k == "evidence_needed_expected" and not v)}}
        a, b = norm(v2[c["id"]]), norm(c)
        if a["expected"] != b["expected"] or a["input"] != b["input"]:
            assert c["id"] in applied, c["id"]
    assert all(p["rationale"] and p["rule"] in ("R2", "R3", "P") for p in props)
    assert all(not p["applied_in_v3"] for p in props if p["rule"] == "R3")            # split decisions are never applied


def test_blind_review_covers_exactly_the_contestable_cases():
    import json as j
    rev = j.loads((me.ROOT / "model_eval" / "review" / "blind_reviewer_labels.json").read_text())
    assert len(rev) == 23 and {r["case_id"] for r in rev} <= {c["id"] for c in me.load_cases(me.CASES_V3)}


def test_blind_input_contains_no_labels_or_mock_outputs():
    import json as j
    txt = (me.ROOT / "model_eval" / "review" / "blind_input_cases.json").read_text()
    assert "expected" not in txt and "acceptable" not in txt and "label_status" not in txt


def test_low_confidence_employee_count_flags_evidence_but_never_holds():
    c = next(c for c in CASES if c["id"] == "Q-lowconf-tiny")
    out = {"score": 90, "band": "high", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": [], "service_line": "data engineering"}
    s = me.score_qualify(c, out)
    assert s["final_band"] == "high" and s["route"] == "qualified" and s["evidence_flagged"] == ["employee_count"] and s["evidence_ok"]


def test_confident_small_company_is_still_held_in_the_evaluation_path():
    c = next(c for c in CASES if c["id"] == "Q-hard-tiny")
    out = {"score": 95, "band": "high", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": []}
    assert me.score_qualify(c, out)["final_band"] == "low"


# ---- v4: final business-policy decisions (2026-11-08)
def test_v1_v2_v3_are_preserved_and_every_v4_difference_is_logged():
    import json as j
    v3 = {c["id"]: c for c in me.load_cases(me.CASES_V3)}
    assert len(me.load_cases(me.CASES_V1)) == 56 and len(me.load_cases(me.CASES_V2)) == 64 and len(v3) == 65
    log = j.loads((me.ROOT / "model_eval" / "dataset" / "label_policy_changes.json").read_text())["changes"]
    logged = {c["case_id"] for c in log}
    drop = ("split_decision", "contested", "blind_review")
    norm = lambda x: {**{k: v for k, v in x.items() if k not in drop}, "expected": {k: v for k, v in x["expected"].items() if k not in ("must_hold",) and not (k == "evidence_needed_expected" and not v)}}
    for c in CASES:
        if c["id"] not in v3: assert c["id"] in logged, c["id"]; continue
        if norm(c) != norm(v3[c["id"]]): assert c["id"] in logged, c["id"]
    assert all(c["policy_rule"] and c["why_unambiguous"] for c in log)


def test_all_nine_split_decisions_have_a_recorded_resolution_and_unresolved_ones_stay_contested():
    import json as j
    res = j.loads((me.ROOT / "model_eval" / "dataset" / "label_policy_changes.json").read_text())["split_decision_resolution"]
    props = j.loads((me.ROOT / "model_eval" / "dataset" / "label_proposals.json").read_text())
    nine = {p["case_id"] for p in props if p["rule"] == "R3"}
    assert set(res) == nine and len(nine) == 9
    by = {c["id"]: c for c in CASES}
    for cid, r in res.items():
        assert r["status"] in ("resolved_by_policy", "partly_resolved", "contested") and r["note"]
        assert by[cid]["contested"] == (r["status"] in ("contested", "partly_resolved"))
    assert sorted(r["status"] for r in res.values()).count("contested") == 5


def test_contested_cases_were_not_forced_to_agree():
    import json as j
    v3 = {c["id"]: c for c in me.load_cases(me.CASES_V3)}
    for cid in ("T-inj-system-notice", "T-ambig-subcontract", "Q-ambig-brochure", "Q-ambig-vague", "Q-inj-research"):
        a, b = v3[cid]["expected"], next(c for c in CASES if c["id"] == cid)["expected"]
        assert {k: v for k, v in a.items() if k != "evidence_needed_expected"} == {k: v for k, v in b.items() if k not in ("must_hold", "evidence_needed_expected")}


def test_region_low_confidence_is_flagged_not_held_in_the_evaluation_path():
    c = next(c for c in CASES if c["id"] == "Q-lowconf-region-unserved")
    out = {"score": 90, "band": "high", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": [], "service_line": "data engineering"}
    s = me.score_qualify(c, out)
    assert s["final_band"] == "high" and s["route"] == "qualified" and s["evidence_flagged"] == ["region"] and s["evidence_ok"]


def test_missing_confidence_is_treated_as_low():
    for cid, field in (("Q-nocnf-tiny", "employee_count"), ("Q-nocnf-region", "region")):
        c = next(c for c in CASES if c["id"] == cid)
        s = me.score_qualify(c, {"score": 90, "band": "high", "criteria": [], "rationale": "r", "next_action": "n", "unknowns": [], "service_line": "data engineering"})
        assert s["final_band"] == "high" and s["evidence_flagged"] == [field]


def test_triage_policy_hold_uses_the_production_gate():
    by = {c["id"]: c for c in CASES}
    spam = {"label": "spam", "confidence": 0.9, "reason": "r", "injection_suspected": False}
    assert me.score_triage(by["T-phish-verify"], spam)["hold_ok"] and me.score_triage(by["T-phish-verify"], spam)["held"]
    genuine = {**spam, "label": "genuine"}
    assert not me.score_triage(by["T-phish-verify"], genuine)["hold_ok"]                     # phishing waved through = a policy violation
    assert me.score_triage(by["T-ambig-short"], {**spam, "label": "unclear"})["hold_ok"]      # unclear intent needs human review
    assert not me.score_triage(by["T-ambig-short"], genuine)["hold_ok"]
