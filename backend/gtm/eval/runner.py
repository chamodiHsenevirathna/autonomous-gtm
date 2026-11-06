"""Scenario runner: drives a SystemHarness through scenarios/*.yaml, judges expectations, compares to baselines, reports.

    python -m gtm.eval.runner --help

The mini-DSL for expectations is documented in gtm/eval/README.md. The runner never imports the system under test
directly; it takes a harness (gtm.contracts.harness.SystemHarness) so it can be tested with a fake.
"""
from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml
from psycopg.types.json import Jsonb

from gtm.contracts.errors import PolicyDenied
from gtm.contracts.scenario import Expectation, Scenario, ScriptEvent
from gtm.contracts.sims import FaultSpec
from gtm.eval import invariants, metrics as metrics_mod

BACKEND = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SCENARIOS_DIR = BACKEND / "scenarios"
DEFAULT_BASELINE_DIR = BACKEND / "fixtures" / "baselines"

PROVENANCE_STATEMENT = (
    "All data in this run is synthetic (a generated world with known ground truth). Providers, CRM, outreach tool and "
    "prospect replies are simulators and replies are scripted. Model output is a deterministic mock or a recorded replay, "
    "so it says nothing about real model quality. Reviewer decisions are scripted or simulated unless labelled HUM-real. "
    "Results are measured on the simulation only: they show that the system behaves as designed, not how it would perform "
    "on real customers. No real-world conversion, revenue or time-saving claim is made."
)
EVIDENCE_NOTE = {
    "measured_on_simulation": "Compares model/simulator output to generated ground truth. Valid for the simulated world only.",
    "machinery_check": "The answer was planted or scripted. Shows the machinery works; not an accuracy or effect-size result.",
    "modelled_impact": "Computed from stated assumptions. Illustrative only.",
}


class ScenarioError(Exception):
    """A scenario cannot be executed as written (unresolved selector, bad spec). Reported as a failure of kind 'error'."""


# =============================================================== loading
def load_scenarios(directory: pathlib.Path | str | None = None, ids: list[str] | None = None) -> list[Scenario]:
    d = pathlib.Path(directory or DEFAULT_SCENARIOS_DIR)
    out = [Scenario.model_validate(yaml.safe_load(f.read_text())) for f in sorted(d.glob("*.yaml"))]
    out.sort(key=lambda s: s.id)
    if ids:
        known = {s.id for s in out}
        missing = [i for i in ids if i not in known]
        if missing:
            raise ScenarioError(f"unknown scenario ids: {missing}")
        out = [s for s in out if s.id in set(ids)]
    return out


# =============================================================== symbolic world selectors
def _enq(world, eid):
    return next(e for e in world.enquiries if e.id == eid)


_SHARED_LOCALS = {"info", "sales", "hello", "contact", "office", "admin", "support", "team", "enquiries", "enquiry"}


def _dup_of(world, eid, same_email: bool):
    base = _enq(world, eid).email.lower()
    return [e.id for e in world.enquiries if e.duplicate_of == eid and (e.email.lower() == base) == same_email]


ENQUIRY_SELECTORS: dict[str, Callable[[Any], list[str]]] = {
    "exact_duplicate_of_enq_001": lambda w: _dup_of(w, "enq_001", True),
    "fuzzy_duplicate_of_enq_001": lambda w: _dup_of(w, "enq_001", False),
    "shared_mailbox": lambda w: [e.id for e in w.enquiries if e.email.split("@")[0].lower() in _SHARED_LOCALS],
    "vendor_pitch": lambda w: [e.id for e in w.enquiries if e.kind == "vendor"],
    "recruiter": lambda w: [e.id for e in w.enquiries if e.kind == "recruiter"],
    "spam": lambda w: [e.id for e in w.enquiries if e.kind == "spam"],
    "injection_in_enquiry": lambda w: [e.id for e in w.enquiries if e.injection],
    "genuine_high": lambda w: [e.id for e in w.enquiries if e.kind == "genuine" and e.expected_band == "high"],
    "genuine_medium": lambda w: [e.id for e in w.enquiries if e.kind == "genuine" and e.expected_band == "medium"],
    "genuine_low": lambda w: [e.id for e in w.enquiries if e.kind == "genuine" and e.expected_band == "low"],
    "enquiry_with_injected_web_page": lambda w: [e.id for e in w.enquiries if e.truth_company_id in
                                                 {pg.company_id for pg in w.web_pages if pg.contains_injection}],
    "genuine_known_account": lambda w: [e.id for e in w.enquiries if e.kind == "genuine" and e.truth_company_id and
                                        sum(x.truth_company_id == e.truth_company_id for x in w.enquiries) > 1],
}


def resolve_selector(world, name: str, nth: int = 0) -> str:
    """Enquiry selector -> enquiry id, or ``reply:<kind>[@<enquiry id>]`` -> scripted reply id. Literal ids pass through."""
    if any(e.id == name for e in world.enquiries) or any(r.id == name for r in world.replies):
        return name
    if name.startswith("reply:"):
        kind, _, enq_id = name[6:].partition("@")
        ids = [r.id for r in world.replies if r.kind == kind and (not enq_id or r.to_enquiry_id == enq_id)]
    elif name in ENQUIRY_SELECTORS:
        ids = ENQUIRY_SELECTORS[name](world)
    else:
        raise ScenarioError(f"unknown selector or id {name!r} (see scenarios/README.md)")
    if len(ids) <= nth:
        raise ScenarioError(f"selector {name!r} (nth={nth}) matched {len(ids)} world records; the world must provide it")
    return ids[nth]


def _match_proposals(conn, ref: str | int | None, default_status: str | None = None) -> tuple[list[int], int]:
    if ref is None or ref == "":
        raise ScenarioError("proposal selector missing (set ref)")
    s = str(ref).strip()
    if s.isdigit():
        return [int(s)], 0
    clauses: dict[str, str] = {}
    for part in s.split(","):
        part = part.strip()
        if part == "first_pending":
            clauses.update(status="pending", nth="0")
        elif part == "last_pending":
            clauses.update(status="pending", nth="-1")
        elif part == "last":
            clauses["nth"] = "-1"
        else:
            k, _, v = part.partition(":")
            clauses[k] = v
    where, params = [], []
    for key, col in (("type", "type"), ("gate", "gate_id"), ("status", "status")):
        val = clauses.get(key) or (default_status if key == "status" else None)
        if val:
            where.append(f"{col} = ANY(%s)")
            params.append(val.split("|"))
    rows = conn.execute("SELECT id FROM ops.proposal" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id", params).fetchall()
    return [r["id"] for r in rows], int(clauses.get("nth", 0))


def resolve_proposal(conn, ref: str | int | None, default_status: str | None = None) -> int:
    """Proposal selector: an id, or comma-separated clauses ``type:message,gate:G5|G4,status:pending|blocked,nth:-1``
    (``|`` = any of). Shorthands: ``first_pending``, ``last``, ``last_pending``. Matches ordered by id; ``nth`` defaults to 0."""
    ids, nth = _match_proposals(conn, ref, default_status)
    try:
        return ids[nth]
    except IndexError:
        raise ScenarioError(f"proposal selector {ref!r} matched {len(ids)} proposals (nth={nth})") from None


def resolve_proposals(conn, ref: str | int | None, default_status: str | None = None) -> list[int]:
    """Every proposal matching the selector (``nth`` ignored); may be empty."""
    return _match_proposals(conn, ref, default_status)[0]


# =============================================================== static validation
TAMPER_KINDS = {"audit_row", "proposal_payload", "recipient"}
_ENQ_ID = re.compile(r"^(enq|rep|rpl)_\w+$")


def _validate_expectation(kind: str, name: str, spec: dict, where: str) -> list[str]:
    errs = []
    judged = any(k in spec for k in JUDGE_KEYS)
    if kind == "invariant":
        if name != "all" and name not in invariants.CHECKS:
            errs.append(f"{where}: unknown invariant {name!r}")
        if spec.get("expect", "hold") not in ("hold", "violated"):
            errs.append(f"{where}: invariant expect must be hold|violated")
    elif kind == "state":
        if sum(k in spec for k in ("sql", "ctx", "snapshot")) != 1:
            errs.append(f"{where}: state spec needs exactly one of sql|ctx|snapshot")
        if not judged:
            errs.append(f"{where}: state spec needs a comparison ({', '.join(JUDGE_KEYS)})")
    elif kind == "metric":
        if not metrics_mod.is_known_metric(name):
            errs.append(f"{where}: unknown metric {name!r}")
    elif kind in ("event", "audit"):
        if not (judged or "verify_chain" in spec or spec):
            errs.append(f"{where}: {kind} spec is empty")
    elif kind == "no_effect":
        if not any(k in spec for k in ("adapter", "proposal", "snapshot_key", "sql")):
            errs.append(f"{where}: no_effect needs adapter|proposal|snapshot_key|sql")
    return errs


def validate_scenario(sc: Scenario) -> list[str]:
    """Static lint of a parsed scenario: returns a list of problems (empty = fine). Does not need a harness or a world."""
    errs = []
    if not re.fullmatch(r"S\d{2}", sc.id):
        errs.append(f"{sc.id}: id must look like S01")
    from gtm.contracts.provenance import DataOrigin
    bad = [o for o in sc.data_origins if o not in {d.value for d in DataOrigin}]
    if bad or not sc.data_origins:
        errs.append(f"{sc.id}: data_origins must be non-empty DataOrigin values (got {sc.data_origins})")
    for field_ in ("covers", "script", "expectations"):
        if not getattr(sc, field_):
            errs.append(f"{sc.id}: {field_} is empty")
    if not sc.milestone.startswith("M") or sc.milestone == "M?":
        errs.append(f"{sc.id}: milestone not set")
    for i, ev in enumerate(sc.script):
        w, p = f"{sc.id} script[{i}] {ev.kind}", ev.params or {}
        if ev.kind in ("enquiry", "reply"):
            sel = p.get("select") or ev.ref
            ok = sel and (sel == "all" if ev.kind == "enquiry" and sel == "all" else
                          sel in ENQUIRY_SELECTORS or _ENQ_ID.match(sel) or sel.startswith("reply:"))
            if not ok:
                errs.append(f"{w}: unknown selector {sel!r}")
        elif ev.kind in ("human_decision", "gateway_attempt") and not (ev.ref or p.get("proposal")):
            errs.append(f"{w}: needs ref (proposal selector)")
        elif ev.kind == "tamper" and p.get("what") not in TAMPER_KINDS:
            errs.append(f"{w}: tamper.what must be one of {sorted(TAMPER_KINDS)}")
        elif ev.kind == "inject_fault":
            try:
                FaultSpec(**p)
            except Exception as e:
                errs.append(f"{w}: invalid FaultSpec ({e})")
        elif ev.kind == "advance_clock" and float(p.get("seconds", 0)) <= 0:
            errs.append(f"{w}: seconds must be > 0")
        elif ev.kind == "custom":
            if p.get("name") == "check":
                errs += _validate_expectation(p.get("kind", ""), p.get("check_name", ""), p.get("spec", {}), w + " check")
            elif p.get("name") != "run_until_idle":
                errs.append(f"{w}: unknown custom event {p.get('name')!r}")
    for e in sc.expectations:
        errs += _validate_expectation(e.kind, e.name, e.spec, f"{sc.id} expectation {e.name!r}")
    return errs


# =============================================================== judging
JUDGE_KEYS = ("eq", "ne", "gt", "gte", "lt", "lte", "min", "max", "in", "not_in", "is_null", "not_null", "approx")


def judge(actual: Any, spec: dict, default: dict | None = None) -> tuple[bool, str]:
    """Apply every comparison key present in ``spec`` (or ``default`` if none) to ``actual``. All must hold."""
    keys = {k: spec[k] for k in JUDGE_KEYS if k in spec} or (default or {"gte": 1})
    problems = []
    for k, want in keys.items():
        try:
            ok = {
                "eq": lambda: actual == want, "ne": lambda: actual != want,
                "gt": lambda: actual > want, "gte": lambda: actual >= want, "min": lambda: actual >= want,
                "lt": lambda: actual < want, "lte": lambda: actual <= want, "max": lambda: actual <= want,
                "in": lambda: actual in want, "not_in": lambda: actual not in want,
                "is_null": lambda: (actual is None) == bool(want), "not_null": lambda: (actual is not None) == bool(want),
                "approx": lambda: abs(float(actual) - float(want)) <= float(spec.get("tol", 0.01)),
            }[k]()
        except TypeError:
            ok = False
        if not ok:
            problems.append(f"{k} {want!r}")
    return (not problems), (f"actual={actual!r}" + ("" if not problems else f"; failed: {', '.join(problems)}"))


def dig(obj: Any, path: str) -> Any:
    """Dotted path into dicts/lists: ``last_gateway.checks.0.name``. Missing -> None."""
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, (list, tuple)):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
    return obj


def _plain(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    return x


# =============================================================== results
@dataclass
class ExpectationResult:
    kind: str
    name: str
    passed: bool
    detail: str

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    evidence_basis: str
    data_origins: list[str]
    pass_criterion: str = ""
    truth_source: str = ""
    covers: list[str] = field(default_factory=list)
    milestone: str = ""
    llm_mode: str = "mock"
    metrics: dict = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)
    expectations: list[ExpectationResult] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self):
        d = self.__dict__.copy()
        d["expectations"] = [e.to_dict() for e in self.expectations]
        return d


# =============================================================== execution of the script
def _idle(h, params: dict) -> None:
    if params.get("run", True):
        h.run_until_idle(advance_clock=bool(params.get("idle_advance", False)))


def _run_event(h, ev: ScriptEvent, ctx: dict) -> None:
    p = ev.params or {}
    delta = ev.at_offset_s - ctx["t"]
    if delta > 0:
        h.advance(delta)
        ctx["t"] = ev.at_offset_s
        h.run_until_idle(advance_clock=False)
    if ev.kind == "enquiry":
        if p.get("select") == "all":   # every world enquiry (optionally only ``kinds``), in world order
            eids = [e.id for e in h.world.enquiries if not p.get("kinds") or e.kind in p["kinds"]]
        else:
            eids = [resolve_selector(h.world, p.get("select") or ev.ref or "", int(p.get("nth", 0)))]
        for eid in eids:
            lead_id = h.deliver_enquiry(eid)
            ctx.update({"lead_id": lead_id, f"lead_{eid}": lead_id, "enquiry_id": eid})
            ctx["enquiry_ids"].append(eid)
        _idle(h, p)
    elif ev.kind == "reply":
        rid = resolve_selector(h.world, p.get("select") or ev.ref or "", int(p.get("nth", 0)))
        h.deliver_reply(rid)
        ctx["reply_id"] = rid
        _idle(h, p)
    elif ev.kind == "advance_clock":
        secs = float(p.get("seconds", 0))
        if secs > 0:
            h.advance(secs)
            ctx["t"] += secs
        h.run_until_idle(advance_clock=bool(p.get("idle_advance", False)))
    elif ev.kind == "inject_fault":
        h.inject_fault(FaultSpec(**p))
    elif ev.kind == "clear_faults":
        h.clear_faults()
    elif ev.kind == "human_decision":
        _human_decision(h, ev, ctx)
    elif ev.kind == "gateway_attempt":
        pid = resolve_proposal(h.conn, ev.ref or p.get("proposal"))
        ctx["proposal_id"] = pid
        try:
            res = _plain(h.attempt_gateway(pid, bypass=p.get("bypass")))
        except PolicyDenied as e:
            res = {"status": "DENIED", "reason": str(e), "checks": []}
        ctx["last_gateway"] = res
        ctx["gateway"].append(res)
    elif ev.kind == "tamper":
        h.tamper(p["what"])
    elif ev.kind == "custom":
        name = p.get("name")
        if name == "run_until_idle":
            h.run_until_idle(advance_clock=bool(p.get("idle_advance", True)))
        elif name == "check":   # mid-script assertion: params = {kind, name, spec}
            h.conn.commit()
            ctx["checks"].append(_safe_eval(h, Expectation(kind=p["kind"], name=p["check_name"], spec=p.get("spec", {})), ctx, None))
        else:
            raise ScenarioError(f"unknown custom event {name!r}")
    else:  # pragma: no cover - schema restricts kinds
        raise ScenarioError(f"unknown event kind {ev.kind}")


def _decide_one(h, pid: int, p: dict, ctx: dict) -> None:
    edited = p.get("edited_payload")
    decision = p.get("decision", "approve")
    if p.get("edit"):
        cur = h.conn.execute("SELECT payload FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["payload"]
        edited = {**cur, **p["edit"]}
        decision = "approve_with_edits"
    ctx["proposal_id"] = pid
    by = p.get("by", "user:maya")
    if p.get("by_proposer"):
        by = h.conn.execute("SELECT proposed_by FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["proposed_by"]
    try:
        ctx["last_decision"] = _plain(h.decide(pid, decision, by=by, edited_payload=edited, reason_code=p.get("reason_code"))) or {}
        if ctx["last_decision"].get("ok") is False and not p.get("expect_denied"):   # the real harness reports refusals as ok=false
            raise ScenarioError(f"decision refused: {ctx['last_decision']}")
    except PolicyDenied as e:
        if not p.get("expect_denied"):
            raise
        ctx["last_decision"] = {"denied": True, "error": str(e)}


def _human_decision(h, ev: ScriptEvent, ctx: dict) -> None:
    """Params: decision, by, edit (shallow patch of the payload), edited_payload, reason_code, expect_denied, run,
    ``all`` (decide every match once) and ``drain`` (repeat ``all`` + run_until_idle until nothing matches, max 20 rounds)."""
    p = ev.params or {}
    ref = ev.ref or p.get("proposal")
    if p.get("drain"):
        for _ in range(20):
            ids = resolve_proposals(h.conn, ref or "status:pending", default_status="pending")
            if not ids:
                break
            for pid in ids:
                _decide_one(h, pid, p, ctx)
            h.run_until_idle(advance_clock=bool(p.get("idle_advance", False)))
        return
    pids = resolve_proposals(h.conn, ref, "pending") if p.get("all") else [resolve_proposal(h.conn, ref, default_status="pending")]
    for pid in pids:
        _decide_one(h, pid, p, ctx)
    _idle(h, p)


# =============================================================== expectations
def _sql_params(ctx: dict, h=None) -> dict:
    out = {k: v for k, v in ctx.items() if isinstance(v, (int, float, str, bool, type(None)))}
    if h is not None:
        out["now"] = h.clock.now()
    return out


def _scalar(conn, sql: str, params: dict | None = None):
    row = conn.execute(sql, params or None).fetchone()
    return None if row is None else next(iter(row.values()))


def _eval_expectation(h, exp: Expectation, ctx: dict, mets: dict) -> ExpectationResult:
    s, conn = exp.spec, h.conn
    res = lambda ok, detail: ExpectationResult(exp.kind, exp.name, bool(ok), detail)  # noqa: E731
    if exp.kind == "invariant":
        fns = invariants.CHECKS if exp.name == "all" else {exp.name: invariants.CHECKS.get(exp.name)}
        if None in fns.values():
            raise ScenarioError(f"unknown invariant {exp.name!r}; known: {sorted(invariants.CHECKS)}")
        results = [fn(conn) for fn in fns.values()]
        violated = [r for r in results if not r.passed]
        if s.get("expect", "hold") == "violated":
            return res(violated, f"expected a violation; violations={[v.name for v in violated] or 'none'}")
        return res(not violated, "holds" if not violated else f"violations: {[v.to_dict() for v in violated]}"[:600])
    if exp.kind == "state":
        if "sql" in s:
            actual = _scalar(conn, s["sql"], _sql_params(ctx, h))
        elif "ctx" in s:
            actual = dig(ctx, s["ctx"])
        elif "snapshot" in s:
            actual = dig(h.snapshot(), s["snapshot"])
        else:
            raise ScenarioError("state spec needs one of: sql, ctx, snapshot")
        return res(*judge(actual, s, {"eq": True}))
    if exp.kind == "metric":
        if mets is None:
            mets = metrics_mod.compute_all(conn, h.world, ctx["enquiry_ids"] or None)
        m = mets.get(exp.name)
        if m is None:
            raise ScenarioError(f"unknown metric {exp.name!r}")
        if m.value is None:
            return res(bool(s.get("allow_none")), f"not measurable (denominator {m.denominator})")
        if m.denominator < int(s.get("min_denominator", 1)):
            return res(False, f"denominator {m.denominator} < min_denominator {s.get('min_denominator', 1)}")
        return res(*judge(m.value, s, {"gte": 0}))
    if exp.kind in ("event", "audit"):
        table, tcol = ("ops.domain_event", "type") if exp.kind == "event" else ("ops.audit_event", "event_type")
        if exp.kind == "audit" and "verify_chain" in s:
            from gtm import audit
            ok, n, bad = audit.verify_chain(conn)
            return res(ok == bool(s["verify_chain"]), f"chain ok={ok} rows={n} first_bad={bad}")
        where, params = [], []
        key = "type" if exp.kind == "event" else "event_type"
        if key in s:
            where.append(f"{tcol} = %s"); params.append(s[key])
        for col in (("source",) if exp.kind == "event" else ("actor_type", "actor_id")):
            if col in s:
                where.append(f"{col} = %s"); params.append(s[col])
        if "data" in s or "payload" in s:
            where.append(("payload" if exp.kind == "event" else "data") + " @> %s"); params.append(Jsonb(s.get("data", s.get("payload"))))
        if exp.kind == "audit" and "proposal" in s:
            where.append("proposal_id = %s"); params.append(resolve_proposal(conn, s["proposal"]))
        n = _scalar(conn, f"SELECT count(*) FROM {table}" + (" WHERE " + " AND ".join(where) if where else ""), params)
        return res(*judge(n, s, {"gte": 1}))
    if exp.kind == "no_effect":
        found = []
        if "adapter" in s or "proposal" in s:
            where, params = ["status = 'succeeded'"], []
            if "adapter" in s:
                where.append("adapter = %s"); params.append(s["adapter"])
            if "proposal" in s:
                where.append("proposal_id = %s"); params.append(resolve_proposal(conn, s["proposal"]))
            n = _scalar(conn, "SELECT count(*) FROM ops.execution WHERE " + " AND ".join(where), params)
            if n:
                found.append(f"{n} successful execution(s)")
        if "snapshot_key" in s:
            v = dig(h.snapshot(), s["snapshot_key"])
            if v:
                found.append(f"snapshot {s['snapshot_key']}={v!r}")
        if "sql" in s:
            n = _scalar(conn, s["sql"], _sql_params(ctx, h))
            if n:
                found.append(f"sql returned {n!r}")
        if not any(k in s for k in ("adapter", "proposal", "snapshot_key", "sql")):
            raise ScenarioError("no_effect spec needs adapter, proposal, snapshot_key or sql")
        return res(not found, "no effect" if not found else "; ".join(found))
    raise ScenarioError(f"unknown expectation kind {exp.kind}")  # pragma: no cover


def _safe_eval(h, exp: Expectation, ctx: dict, mets) -> ExpectationResult:
    try:
        return _eval_expectation(h, exp, ctx, mets)
    except ScenarioError as e:
        return ExpectationResult(exp.kind, exp.name, False, f"scenario error: {e}")


def run_scenario(h, sc: Scenario, *, implicit_invariants: bool = True) -> ScenarioResult:
    """Reset the harness, play the script, judge expectations and (unless disabled) all invariants not explicitly
    handled by an ``invariant`` expectation. Never raises: errors become failures of kind 'error'."""
    t0 = time.perf_counter()
    r = ScenarioResult(sc.id, sc.title, False, sc.evidence_basis.value, list(sc.data_origins), sc.pass_criterion, sc.truth_source,
                       list(sc.covers), sc.milestone, sc.llm_mode)
    ctx: dict = {"t": 0, "enquiry_ids": [], "gateway": [], "checks": []}
    try:
        if sc.world_overrides:
            h.reset(sc.seed, sc.llm_mode, world_overrides=sc.world_overrides)  # type: ignore[call-arg]
        else:
            h.reset(sc.seed, sc.llm_mode)
        for ev in sorted(sc.script, key=lambda e: e.at_offset_s):  # stable: ties keep file order
            try:
                _run_event(h, ev, ctx)
            except Exception as e:
                raise ScenarioError(f"script event {ev.kind} ({ev.ref or ev.params}) failed: {type(e).__name__}: {e}") from e
        h.conn.commit()
        mets = metrics_mod.compute_all(h.conn, h.world, ctx["enquiry_ids"] or None)
        r.metrics = {k: {"value": m.value, "denominator": m.denominator, "evidence_basis": m.evidence_basis, "data_origins": m.data_origins}
                     for k, m in mets.items() if m.denominator}
        r.expectations.extend(ctx["checks"])
        r.expectations.extend(_safe_eval(h, exp, ctx, mets) for exp in sc.expectations)
        r.failures.extend({"kind": e.kind, "name": e.name, "detail": e.detail} for e in r.expectations if not e.passed)
        if implicit_invariants:
            handled = {e.name for e in sc.expectations if e.kind == "invariant"}
            if "all" not in handled:
                for ir in invariants.check_all(h.conn):
                    if not ir.passed and ir.name not in handled:
                        r.failures.append({"kind": "implicit_invariant", "name": ir.name, "detail": str(ir.violations)[:600]})
    except Exception as e:
        r.failures.append({"kind": "error", "name": type(e).__name__, "detail": str(e)[:600],
                           "where": traceback.format_exc().strip().splitlines()[-3:]})
    r.passed = not r.failures
    r.duration_ms = int((time.perf_counter() - t0) * 1000)
    return r


# =============================================================== baselines
LOWER_IS_BETTER = ("_rate", "cost", "latency", "wrong_merge", "false_negatives", "denied", "failure", "ece")


def load_baselines(directory: pathlib.Path | str | None = None) -> dict:
    """Merge fixtures/baselines/*.json. Format: {"tolerance": 0.02, "scenarios": {"S01": {"passed": true,
    "metrics": {"qualification_recall": 0.9 | {"value": 0.9, "direction": "higher", "tolerance": 0.05}}}}}"""
    d = pathlib.Path(directory or DEFAULT_BASELINE_DIR)
    merged: dict = {"tolerance": 0.02, "scenarios": {}}
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        doc = json.loads(f.read_text())
        merged["tolerance"] = doc.get("tolerance", merged["tolerance"])
        merged["scenarios"].update(doc.get("scenarios", {}))
    return merged


def compare_to_baseline(results: list[ScenarioResult], baseline: dict) -> dict:
    """Returns {"regressions": [...], "new_failures": [...], "known_failures": [...], "no_baseline": [...]}.
    A regression is a scenario that passed in the baseline and fails now, or a metric that worsened beyond tolerance."""
    reg, new_fail, known, nobase = [], [], [], []
    tol0 = baseline.get("tolerance", 0.02)
    for r in results:
        b = baseline["scenarios"].get(r.scenario_id)
        if b is None:
            nobase.append(r.scenario_id)
        if not r.passed:
            if b is not None and b.get("passed") is False:
                known.append(r.scenario_id)
            else:
                new_fail.append(r.scenario_id)
                if b is not None and b.get("passed"):
                    reg.append({"scenario": r.scenario_id, "kind": "status", "detail": "passed in baseline, fails now"})
        for name, spec in (b or {}).get("metrics", {}).items():
            spec = spec if isinstance(spec, dict) else {"value": spec}
            now = (r.metrics.get(name) or {}).get("value")
            if now is None:
                if spec.get("value") is not None:
                    reg.append({"scenario": r.scenario_id, "kind": "metric", "metric": name, "detail": "no longer measurable"})
                continue
            lower = spec.get("direction", "lower" if any(t in name for t in LOWER_IS_BETTER) else "higher") == "lower"
            tol = spec.get("tolerance", tol0)
            worse = (now - spec["value"]) if lower else (spec["value"] - now)
            if worse > tol:
                reg.append({"scenario": r.scenario_id, "kind": "metric", "metric": name, "baseline": spec["value"], "now": now,
                            "detail": f"worse by {worse:.4f} (tolerance {tol})"})
    return {"regressions": reg, "new_failures": new_fail, "known_failures": known, "no_baseline": nobase}


def make_baseline(results: list[ScenarioResult]) -> dict:
    return {"tolerance": 0.02, "scenarios": {r.scenario_id: {"passed": r.passed, "metrics": {
        k: m["value"] for k, m in r.metrics.items() if isinstance(m["value"], (int, float)) and m["denominator"] >= 5}} for r in results}}


# =============================================================== reports
def build_report(results: list[ScenarioResult], comparison: dict, extra: dict | None = None) -> dict:
    return {"provenance_statement": PROVENANCE_STATEMENT, "evidence_notes": EVIDENCE_NOTE,
            "summary": {"total": len(results), "passed": sum(r.passed for r in results), "failed": sum(not r.passed for r in results),
                        "regressions": len(comparison["regressions"]), "new_failures": comparison["new_failures"]},
            "comparison": comparison, "scenarios": [r.to_dict() for r in results], **(extra or {})}


def render_markdown(rep: dict) -> str:
    s = rep["summary"]
    L = ["# Evaluation report", "", "> " + rep["provenance_statement"], "",
         f"**{s['passed']}/{s['total']} scenarios passed**, {s['failed']} failed, {s['regressions']} regression(s) against baseline.", "",
         "| Scenario | Title | Result | Evidence basis | Data origins | ms |", "|---|---|---|---|---|---|"]
    for r in rep["scenarios"]:
        L.append(f"| {r['scenario_id']} | {r['title']} | {'PASS' if r['passed'] else '**FAIL**'} | {r['evidence_basis']} | "
                 f"{', '.join(r['data_origins'])} | {r['duration_ms']} |")
    bad = [r for r in rep["scenarios"] if not r["passed"]]
    if bad:
        L += ["", "## Failures"]
        for r in bad:
            L += [f"", f"### {r['scenario_id']} {r['title']}", f"Criterion: {r['pass_criterion']}", ""]
            L += [f"- `{f['kind']}` **{f['name']}**: {f['detail']}" for f in r["failures"]]
    if rep["comparison"]["regressions"]:
        L += ["", "## Regressions against baseline"]
        L += [f"- {g['scenario']} {g.get('metric', '')}: {g['detail']}" for g in rep["comparison"]["regressions"]]
    L += ["", "## How to read the evidence basis"]
    L += [f"- **{k}**: {v}" for k, v in rep["evidence_notes"].items()]
    L += ["", "Metric values with their denominators are in the JSON report. A metric with a small denominator is anecdote, not a rate.", ""]
    return "\n".join(L)


def persist(conn, results: list[ScenarioResult], started_at, ended_at, llm_mode: str, summary: dict, code_version: str | None = None) -> int:
    run_id = conn.execute("INSERT INTO ops.eval_run(started_at, ended_at, llm_mode, code_version, summary) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                          (started_at, ended_at, llm_mode, code_version, Jsonb(summary))).fetchone()["id"]
    for r in results:
        conn.execute("INSERT INTO ops.eval_result(eval_run_id, scenario_id, title, passed, evidence_basis, metrics, failures, duration_ms, data_origins) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (run_id, r.scenario_id, r.title, r.passed, r.evidence_basis, Jsonb(r.metrics), Jsonb(r.failures), r.duration_ms, r.data_origins))
    conn.commit()
    return run_id


def run_suite(h, scenarios: list[Scenario], *, baseline: dict | None = None, clock=None, write_db: bool = True) -> tuple[list[ScenarioResult], dict]:
    """Run all scenarios on one harness. DB rows are written at the end because harness.reset() truncates the database."""
    from gtm.clock import SystemClock
    clock = clock or SystemClock()
    started = clock.now()
    results = [run_scenario(h, sc) for sc in scenarios]
    comparison = compare_to_baseline(results, baseline or {"scenarios": {}})
    report = build_report(results, comparison)
    if write_db:
        modes = {s.llm_mode for s in scenarios}
        report["eval_run_id"] = persist(h.conn, results, started, clock.now(), modes.pop() if len(modes) == 1 else "mixed",
                                        {k: report["summary"][k] for k in ("total", "passed", "failed", "regressions")})
    return results, report


# =============================================================== CLI
def _load_factory(spec: str) -> Callable:
    mod, _, attr = spec.partition(":")
    return getattr(importlib.import_module(mod), attr or "Harness")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gtm.eval.runner", description="Run evaluation scenarios against the system harness. "
                                 "WARNING: harness.reset() empties the database, so only a test database is accepted by default.")
    ap.add_argument("--scenarios", help="comma-separated ids, e.g. S01,S05 (default: all)")
    ap.add_argument("--scenarios-dir", default=str(DEFAULT_SCENARIOS_DIR))
    ap.add_argument("--baseline-dir", default=str(DEFAULT_BASELINE_DIR))
    ap.add_argument("--out-dir", default="eval_reports", help="where report.json / report.md are written")
    ap.add_argument("--harness", default="gtm.harness:Harness", help="module:callable returning a SystemHarness; called as f(database_url=...)")
    ap.add_argument("--database-url", default=None, help="default: GTM_TEST_DATABASE_URL")
    ap.add_argument("--allow-non-test-db", action="store_true")
    ap.add_argument("--update-baseline", action="store_true", help="write fixtures/baselines/baseline.json from this run")
    ap.add_argument("--no-db-write", action="store_true", help="do not write ops.eval_run / ops.eval_result")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--validate", action="store_true", help="statically lint the scenario files and exit (no database needed)")
    a = ap.parse_args(argv)

    try:
        scenarios = load_scenarios(a.scenarios_dir, a.scenarios.split(",") if a.scenarios else None)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.validate:
        problems = [p for sc_ in scenarios for p in validate_scenario(sc_)]
        print("\n".join(problems) or f"{len(scenarios)} scenario(s) valid")
        return 1 if problems else 0
    if a.list:
        for s in scenarios:
            print(f"{s.id}\t{s.milestone}\t{s.evidence_basis.value}\t{s.title}")
        return 0
    from gtm import config
    url = a.database_url or config.get_settings().test_database_url
    if "test" not in url.rsplit("/", 1)[-1] and not a.allow_non_test_db:
        print(f"error: refusing to reset non-test database {url!r} (use --allow-non-test-db)", file=sys.stderr)
        return 2
    try:
        factory = _load_factory(a.harness)
    except (ImportError, AttributeError) as e:
        print(f"error: cannot load harness {a.harness!r}: {e}", file=sys.stderr)
        return 2
    try:
        h = factory(database_url=url)
    except TypeError:
        h = factory()
    results, report = run_suite(h, scenarios, baseline=load_baselines(a.baseline_dir), write_db=not a.no_db_write)
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(report))
    if a.update_baseline:
        bd = pathlib.Path(a.baseline_dir)
        bd.mkdir(parents=True, exist_ok=True)
        (bd / "baseline.json").write_text(json.dumps(make_baseline(results), indent=2))
    s = report["summary"]
    print(f"{s['passed']}/{s['total']} passed; {s['regressions']} regression(s); new failures: {s['new_failures'] or 'none'}; reports in {out}/")
    return 1 if (s["regressions"] or s["new_failures"]) and not a.update_baseline else 0


if __name__ == "__main__":
    sys.exit(main())
