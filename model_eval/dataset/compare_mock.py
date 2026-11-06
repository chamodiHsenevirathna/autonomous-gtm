"""For every proposal in label_proposals.json, records whether the MOCK passes that case under the v2 labels and under the v3 labels (same scorer, same code),
so a reader can see whether any label change moved the mock toward a better or worse score. Run from backend/: python ../model_eval/dataset/compare_mock.py"""
import json, pathlib
from gtm.config import Settings
from gtm.eval import model_eval as me
H = pathlib.Path(__file__).resolve().parent
def passes(path):
    cases = me.load_cases(path)
    recs = me.run_cases(me._make_client("mock", Settings()), cases, 1)
    by = {c["id"]: c for c in cases}
    return {r["case_id"]: me.case_pass(by[r["case_id"]]["task"], me.SCORERS[by[r["case_id"]]["task"]](by[r["case_id"]], r["output"])) for r in recs}
p2, p3 = passes(H / "cases_v2.jsonl"), passes(H / "cases_v3.jsonl")
props = json.loads((H / "label_proposals.json").read_text())
for p in props:
    p["mock_pass_v2"], p["mock_pass_v3"] = p2.get(p["case_id"]), p3.get(p["case_id"])
(H / "label_proposals.json").write_text(json.dumps(props, indent=2, ensure_ascii=False))
chg = sorted({p["case_id"] for p in props if p["applied_in_v3"]})
print("mock pass count v2:", sum(p2.values()), "/", len(p2), " v3:", sum(p3.values()), "/", len(p3))
for c in chg: print(c.ljust(24), "v2:", p2.get(c), "v3:", p3.get(c))
