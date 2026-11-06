"""Weekly digest. Every number comes from SQL; an optional narrative is verified against those numbers."""
from __future__ import annotations
import re
from datetime import timedelta
from typing import Callable
from psycopg import Connection
from ..clock import Clock
from ..mcp.registry import CLOSED_STAGES

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def weekly_digest(conn: Connection, clock: Clock, *, narrative_fn: Callable[[dict], str] | None = None) -> dict:
    now, since, closed = clock.now(), clock.now() - timedelta(days=7), list(CLOSED_STAGES)
    q = lambda sql, *p: conn.execute(sql, p).fetchall()
    one = lambda sql, *p: conn.execute(sql, p).fetchone()
    base = "FROM gtm.opportunity WHERE lower(stage) <> ALL(%s)"
    n = {
        "open_opportunities": one(f"SELECT count(*) AS v {base}", closed)["v"],
        "open_amount": float(one(f"SELECT COALESCE(sum(amount),0) AS v {base}", closed)["v"]),
        "stalled": one(f"SELECT count(*) AS v {base} AND is_stalled", closed)["v"],
        "stalled_amount": float(one(f"SELECT COALESCE(sum(amount),0) AS v {base} AND is_stalled", closed)["v"]),
        "single_threaded": one(f"SELECT count(*) AS v {base} AND (SELECT count(*) FROM gtm.opportunity_contact oc WHERE oc.opportunity_id=opportunity.id)=1", closed)["v"],
        "missing_close_date": one(f"SELECT count(*) AS v {base} AND close_date IS NULL", closed)["v"],
        "missing_amount": one(f"SELECT count(*) AS v {base} AND amount IS NULL", closed)["v"],
        "missing_next_step": one(f"SELECT count(*) AS v {base} AND coalesce(trim(next_step),'')=''", closed)["v"],
        "created_last_7d": one("SELECT count(*) AS v FROM gtm.opportunity WHERE created_at > %s", since)["v"],
        "closed_lost_last_7d": one("SELECT count(DISTINCT opportunity_id) AS v FROM gtm.stage_history WHERE lower(to_stage) IN ('closed_lost','closed lost','lost') AND at > %s", since)["v"],
        "by_stage": {r["stage"]: r["v"] for r in q(f"SELECT stage, count(*) AS v {base} GROUP BY stage ORDER BY stage", closed)},
    }
    stalled_ids = [r["id"] for r in q(f"SELECT id {base} AND is_stalled ORDER BY id", closed)]
    out = {"as_of": now.isoformat(), "numbers": n, "stalled_opportunity_ids": stalled_ids, "source": "sql", "narrative": None, "narrative_check": None}
    out["template_narrative"] = (f"{n['open_opportunities']} open opportunities worth {n['open_amount']:.0f}; {n['stalled']} stalled "
                                 f"({n['stalled_amount']:.0f}); {n['single_threaded']} single-threaded.")
    if narrative_fn:
        text = narrative_fn(n)
        chk = check_narrative(text, n)
        out["narrative_check"] = chk
        out["narrative"] = text if chk["ok"] else None
    return out


def _flatten(v) -> list[float]:
    if isinstance(v, dict):
        return [x for y in v.values() for x in _flatten(y)]
    return [float(v)] if isinstance(v, (int, float)) and not isinstance(v, bool) else []


def check_narrative(text: str, numbers: dict) -> dict:
    """Every number in the narrative must equal a digest number (up to rounding to an integer). Returns {"ok", "unsupported"}."""
    allowed = _flatten(numbers)
    bad = []
    for m in _NUM.findall(text):
        v = float(m.replace(",", ""))
        if not any(abs(v - a) < 1e-9 or abs(v - round(a)) < 1e-9 for a in allowed):
            bad.append(m)
    return {"ok": not bad, "unsupported": bad}
