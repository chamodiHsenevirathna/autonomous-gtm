"""Evaluation endpoints. The suite runs against a SEPARATE test database (it truncates it); a copy of the summary is stored in the demo DB."""
from __future__ import annotations
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from gtm import db
from gtm.config import get_settings
from .views import iso, ORIGINS

NOTICE = ("Measured on a simulated world with scripted prospects and a deterministic mock model. Shows the machinery behaves as designed, "
          "not real-world performance. Invariants are evaluated on the final scenario state.")


def _metric(name: str, m) -> dict:
    v = m.get("value") if isinstance(m, dict) else m
    return {"name": name, "value": v if isinstance(v, (int, float, str)) else str(v), "target": None,
            "unit": "ratio" if isinstance(v, float) and 0 <= v <= 1 else None, "passed": None,
            "evidence_basis": (m.get("evidence_basis") if isinstance(m, dict) else None) or "measured_on_simulation"}


def _scenario(sid, title, desc, passed, basis, origins, metrics, failures) -> dict:
    return {"id": sid, "title": title or sid, "description": desc or "", "passed": bool(passed), "evidence_basis": basis,
            "data_origins": [o for o in (origins or []) if o in ORIGINS], "metrics": [_metric(k, v) for k, v in (metrics or {}).items()],
            "detail": "; ".join(f"{f.get('name')}: {f.get('detail')}" for f in (failures or []))[:600] or None}


def empty() -> dict:
    return {"run_id": 0, "ran_at": None, "mode": "mock", "notice": "No evaluation has been run yet.",
            "totals": {"passed": 0, "failed": 0, "total": 0}, "invariants": [], "scenarios": [], "baseline": {"compared": False, "regressions": 0}}


def latest_summary(c) -> dict:
    r = c.execute("SELECT * FROM ops.eval_run ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return empty()
    s = r["summary"] or {}
    if "scenarios" in s:
        return {**s, "run_id": r["id"]}
    rows = c.execute("SELECT * FROM ops.eval_result WHERE eval_run_id=%s ORDER BY scenario_id", (r["id"],)).fetchall()
    scs = [_scenario(x["scenario_id"], x["title"], "", x["passed"], x["evidence_basis"], x["data_origins"], x["metrics"], x["failures"]) for x in rows]
    p = sum(x["passed"] for x in scs)
    return {"run_id": r["id"], "ran_at": iso(r["started_at"]), "mode": r["llm_mode"], "notice": NOTICE, "totals": {"passed": p, "failed": len(scs) - p, "total": len(scs)},
            "invariants": [], "scenarios": scs, "baseline": {"compared": False, "regressions": int(s.get("regressions", 0))}}


def run_eval(st, ids=None) -> dict:
    settings = get_settings()
    test_url = settings.test_database_url
    if test_url == st.url:
        raise HTTPException(503, "Evaluation needs a separate test database (GTM_TEST_DATABASE_URL differs from the demo database); refusing to reset the demo DB.")
    try:
        from gtm.eval import invariants, runner
        from gtm.harness import Harness
        scenarios = runner.load_scenarios(None, ids)
        if not scenarios:
            raise ValueError("no scenarios found")
        db.ensure_database(test_url)
        db.migrate(test_url)
        h = Harness(test_url)
    except Exception as e:
        raise HTTPException(503, f"Evaluation suite unavailable: {type(e).__name__}: {e}")
    try:
        baseline = runner.load_baselines()
        results, report = runner.run_suite(h, scenarios, baseline=baseline, clock=st.rt.clock, write_db=False)
        inv = [{"name": i.name, "passed": bool(i.passed), "violations": [dict(v) if isinstance(v, dict) else {"detail": str(v)} for v in i.violations][:20]}
               for i in invariants.check_all(h.conn)]
    except Exception as e:
        raise HTTPException(503, f"Evaluation suite failed to run: {type(e).__name__}: {e}")
    finally:
        h.rt.close()
    byid = {s.id: s for s in scenarios}
    scs = [_scenario(r.scenario_id, r.title, byid[r.scenario_id].pass_criterion, r.passed, r.evidence_basis, r.data_origins, r.metrics, r.failures) for r in results]
    p = sum(x["passed"] for x in scs)
    modes = {s.llm_mode for s in scenarios}
    out = {"ran_at": iso(st.rt.clock.now()), "mode": modes.pop() if len(modes) == 1 else "mixed", "notice": NOTICE,
           "totals": {"passed": p, "failed": len(scs) - p, "total": len(scs)}, "invariants": inv, "scenarios": scs,
           "baseline": {"compared": bool((baseline or {}).get("scenarios")), "regressions": int(report["summary"]["regressions"])}}
    with st.lock:
        c = st.conn
        try:
            rid = c.execute("INSERT INTO ops.eval_run(started_at, ended_at, llm_mode, summary) VALUES (%s,%s,%s,%s) RETURNING id",
                            (st.rt.clock.now(), st.rt.clock.now(), out["mode"], Jsonb(out))).fetchone()["id"]
            for r in results:
                c.execute("INSERT INTO ops.eval_result(eval_run_id, scenario_id, title, passed, evidence_basis, metrics, failures, duration_ms, data_origins) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (rid, r.scenario_id, r.title, r.passed, r.evidence_basis, Jsonb(r.metrics), Jsonb(r.failures), r.duration_ms, r.data_origins))
            c.commit()
        finally:
            c.rollback()
    return {**out, "run_id": rid}
