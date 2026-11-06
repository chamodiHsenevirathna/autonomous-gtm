"""Records, for every case changed in v4, whether the MOCK passes under v3 labels and under v4 labels (same scorer/code), into label_policy_changes.json.
Run from backend/: python ../model_eval/dataset/compare_mock_v4.py"""
import json, pathlib
from gtm.config import Settings
from gtm.eval import model_eval as me
H = pathlib.Path(__file__).resolve().parent
def passes(path):
    cases = me.load_cases(path); by = {c["id"]: c for c in cases}
    recs = me.run_cases(me._make_client("mock", Settings()), cases, 1)
    return {r["case_id"]: me.case_pass(by[r["case_id"]]["task"], me.SCORERS[by[r["case_id"]]["task"]](by[r["case_id"]], r["output"])) for r in recs}
p3, p4 = passes(H / "cases_v3.jsonl"), passes(H / "cases_v4.jsonl")
d = json.loads((H / "label_policy_changes.json").read_text())
for c in d["changes"]: c["mock_pass_v3"], c["mock_pass_v4"] = p3.get(c["case_id"]), p4.get(c["case_id"])
for k, v in d["split_decision_resolution"].items(): v["mock_pass_v3"], v["mock_pass_v4"] = p3.get(k), p4.get(k)
d["mock_pass_totals"] = {"v3": [sum(p3.values()), len(p3)], "v4": [sum(p4.values()), len(p4)]}
d["mock_failures_v4"] = sorted(k for k, v in p4.items() if not v)
(H / "label_policy_changes.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
print(d["mock_pass_totals"], d["mock_failures_v4"])
for k, v in d["split_decision_resolution"].items(): print(k.ljust(26), v["status"].ljust(18), v["mock_pass_v3"], "->", v["mock_pass_v4"])
