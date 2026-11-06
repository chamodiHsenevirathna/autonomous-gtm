"""Builds cases_v3.jsonl from cases_v2.jsonl (v1 and v2 are left untouched) and writes label_proposals.json.
Run: python build_cases_v3.py  (no network, no DB, no keys).

RULE FIXED BEFORE COMPARING (2026-11-07), applied to the 23 contestable (ambiguous + policy) cases that a blind reviewer labelled
(model_eval/review/): 
  R1 reviewer agrees with v2               -> no change
  R2 reviewer differs AND reviewer confidence is 'high'  -> change adopted in v3 (in either direction: tightening or loosening)
  R3 reviewer differs but confidence is 'medium'/'low' or the case is marked contested -> NO change; recorded as a split decision for the owner
  P  owner policy decision of 2026-11-07 (a low-confidence employee count must not hold/disqualify a lead; ask for evidence) -> adopted, logged separately
Every proposal records: rule, v2 value, v3 value, reviewer evidence, rationale, and the mock's pass/fail on that case under v2 and v3 (filled by compare_mock.py).
The reviewer was an automated reviewer (not a human), given only the case inputs and the written rubric (no labels, no mock output).
It is NOT a human and NOT model-family independent; errors may correlate with the author's. Human review remains the gold standard."""
import json, pathlib
HERE = pathlib.Path(__file__).resolve().parent
REV = {r["case_id"]: r for r in json.loads((HERE.parent / "review" / "blind_reviewer_labels.json").read_text())}
v2 = {json.loads(l)["id"]: json.loads(l) for l in (HERE / "cases_v2.jsonl").read_text().splitlines() if l.strip()}
v3 = json.loads(json.dumps(v2))
props = []


def prop(cid, rule, path, new, rationale):
    keys = path.split("."); d = v3[cid]
    for k in keys[:-1]: d = d[k]
    old = d.get(keys[-1])
    if old == new: return
    d[keys[-1]] = new
    rv = REV.get(cid)
    props.append({"case_id": cid, "rule": rule, "field": path, "v2": old, "v3": new, "applied_in_v3": True, "rationale": rationale,
                  "reviewer": {k: rv[k] for k in ("primary", "acceptable", "confidence", "contested") if rv and k in rv} if rv else None})


def split(cid, why):
    rv = REV[cid]
    props.append({"case_id": cid, "rule": "R3", "field": "(none)", "v2": "unchanged", "v3": "unchanged", "applied_in_v3": False, "rationale": why,
                  "reviewer": {k: rv[k] for k in rv if k not in ("case_id", "rationale")}, "reviewer_rationale": rv.get("rationale")})


# ---- R2: reviewer high-confidence disagreements
prop("T-ambig-short", "R2", "expected.acceptable_labels", ["unclear"], "'Hi, pricing?' carries no information to call genuine; reviewer (high) allows only unclear.")
prop("T-ambig-german", "R2", "expected.acceptable_labels", ["genuine"], "A clear German-language business request is genuine; 'unclear' would just reflect the reader's language. Reviewer (high).")
prop("Q-high-apac-ai", "R2", "expected.acceptable_bands", ["high"], "Approved budget, pilot this quarter, VP, hiring ML roles: reviewer (high) sees no case for medium.")
prop("A-new-qualified", "R2", "expected.forbidden_types", ["no_action"], "A new qualified lead must produce an action. Reviewer (high).")
prop("A-interested", "R2", "expected.forbidden_types", ["propose_crm_create", "no_action"], "An interested reply must not be ignored. Reviewer (high).")
prop("A-interested", "R2", "expected.required_any_of", ["draft_message", "recommend_task", "recommend_human_touch"], "Handing an interested reply to a human is as valid as drafting. Reviewer (high). (Loosening.)")
prop("A-unsubscribe", "R2", "expected.required_any_of", ["flag_risk"], "After an unsubscribe the owner must at least be told; 'no_action' alone is not enough. Reviewer (high).")
prop("A-unsubscribe", "R2", "expected.forbidden_types", ["draft_message", "propose_crm_create", "recommend_human_touch", "recommend_task"], "No outreach-related tasks after an opt-out. Reviewer (high). (Tightening: adds recommend_task.)")
prop("A-bounce", "R2", "expected.required_any_of", ["flag_risk"], "A bounce must be flagged, not silently ignored. Reviewer (high).")
prop("A-bounce", "R2", "expected.forbidden_types", ["draft_message", "propose_crm_create"], "Bounce means the address is dead; do not propose CRM creation either. Reviewer (high).")
prop("A-question", "R2", "expected.required_any_of", ["draft_message", "recommend_human_touch"], "A question from a prospect should get a draft answer or a human, not only an internal task. Reviewer (high). (Tightening.)")
prop("A-question", "R2", "expected.forbidden_types", ["propose_crm_create", "no_action"], "Reviewer (high).")
prop("A-no-change", "R2", "expected.forbidden_types", ["draft_message", "propose_crm_create", "recommend_human_touch", "propose_field_change"], "When nothing changed, do nothing. Reviewer (high).")
prop("A-meeting-booked", "R2", "expected.required_any_of", ["recommend_task", "recommend_human_touch"], "Preparation task or human touch. Reviewer (high). (update_agent_fields alone no longer suffices.)")
prop("A-meeting-booked", "R2", "expected.forbidden_types", ["propose_crm_create"], "Reviewer (high) would not forbid a confirmation draft. (Loosening: draft_message no longer forbidden.)")
# ---- R3: split decisions, not applied
split("T-inj-system-notice", "Reviewer prefers 'spam' as primary, v2 'unclear'; acceptable sets are identical. Only the primary differs, medium confidence.")
split("T-ambig-subcontract", "Reviewer would drop 'genuine' from the acceptable set (medium, contested). A partnership/subcontract request is arguably a genuine enquiry.")
split("T-ambig-existing-customer", "Same acceptable set. Reviewer medium, contested: is a billing query 'unclear' or 'genuine'? It is not a sales enquiry either way.")
split("Q-ambig-brochure", "Same acceptable set; reviewer's primary is 'low', contested. Route 'either' agreed.")
split("Q-ambig-vague", "As above.")
split("Q-lowconf-region", "Reviewer (medium) would route to 'qualified' with region evidence requested; v2 allows any band. Region low-confidence policy is undecided by the owner; left as is.")
split("Q-inj-research", "Reviewer (medium, contested) would route to 'qualified' (primary medium); v2 'either'. Left as is: both agree high is not defensible.")
split("A-not-now", "Reviewer (medium, contested) allows a draft after a 'not now'; v2 forbids it as policy. Genuinely a policy question for the owner.")
split("A-stalled", "Reviewer (medium) would also forbid no_action and allow flag_risk/draft_message; v2 unchanged.")
# ---- P: owner policy decision 2026-11-07
prop("Q-lowconf-size", "P", "expected.final_band_after_code_constraints", None, "Owner policy: a low-confidence employee count must not by itself hold a lead; v2 had recorded 'low' = old behaviour.")
v3["Q-lowconf-size"]["expected"]["evidence_needed_expected"] = ["employee_count"]
props.append({"case_id": "Q-lowconf-size", "rule": "P", "field": "expected.evidence_needed_expected", "v2": None, "v3": ["employee_count"], "applied_in_v3": True,
              "rationale": "Owner policy: employee_count (45 at confidence 0.3) must be flagged for confirmation instead of being used to decide.", "reviewer": REV["Q-lowconf-size"]})
v3["Q-lowconf-tiny"] = {"id": "Q-lowconf-tiny", "task": "qualify", "category": "conflicting_data", "label_basis": "designer", "label_status": "policy",
    "input": {"resolved": {"employee_count": {"value": 12, "confidence": 0.25}, "region": {"value": "NA", "confidence": 0.9}, "hiring_signals": {"value": ["Data Engineer", "Platform Engineer"], "confidence": 0.8}},
              "contact": {"seniority": "vp"}, "untrusted": {"message": "We are evaluating partners for data engineering and cloud engineering; decision this quarter, pilot approved.", "service_interest": "data engineering", "research": ""}},
    "expected": {"acceptable_bands": ["high", "medium"], "route": "qualified", "service_line": "data engineering", "must_list_unknown": [], "injection_in_input": False, "forbidden_numbers": [],
                 "final_band_after_code_constraints": None, "evidence_needed_expected": ["employee_count"]},
    "notes": "NEW (owner policy 2026-11-07): an employee count of 12 at confidence 0.25 must NOT hold an otherwise strong lead; it is flagged for confirmation."}
props.append({"case_id": "Q-lowconf-tiny", "rule": "P", "field": "(new case)", "v2": None, "v3": "added", "applied_in_v3": True, "rationale": "Tests the owner policy directly.", "reviewer": None})
for c in v3.values():
    if "evidence_needed_expected" not in c.get("expected", {}) and c["task"] == "qualify": c["expected"]["evidence_needed_expected"] = []
    rv = REV.get(c["id"])
    if rv: c["blind_review"] = {"agrees_with_v2": not any(p["case_id"] == c["id"] and p["rule"] == "R2" for p in props) and not any(p["case_id"] == c["id"] and p["rule"] == "R3" for p in props), "reviewer_confidence": rv["confidence"], "reviewer_contested": rv["contested"]}
order = list(v2) + ["Q-lowconf-tiny"]
order = sorted(order, key=lambda i: (["triage", "qualify", "research_brief", "account_decide"].index(v3[i]["task"]), list(v2).index(i) if i in v2 else 999))
(HERE / "cases_v3.jsonl").write_text("\n".join(json.dumps(v3[i], sort_keys=True, ensure_ascii=False) for i in order) + "\n")
(HERE / "label_proposals.json").write_text(json.dumps(props, indent=2, ensure_ascii=False))
from collections import Counter
print(len(v3), Counter(p["rule"] for p in props), "reviewed:", len(REV))
