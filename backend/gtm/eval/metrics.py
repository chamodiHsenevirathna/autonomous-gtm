"""Evaluation metrics: pure functions over plain rows plus a World (ground truth), and thin SQL loaders.

Every metric is a ``MetricResult(name, value, denominator, evidence_basis, data_origins, details)``.
``value`` is None when the denominator is 0 (nothing to measure) - never a fake 0 or 1.

Mapping DB rows to ground truth (assumptions, see README):
  * account -> TrueCompany by ``primary_domain`` / ``account_domain`` matching ``domain`` (then ``alias_domains``);
  * contact -> TrueContact by lower-cased email;
  * lead -> Enquiry by ``raw_payload['enquiry_id']`` (else by e-mail in the payload).
Evidence basis: comparisons of MOD/SIM output to GT are ``measured_on_simulation`` (about the simulated world only);
cost/latency/tool-trace numbers are ``machinery_check`` (simulated units and simulated time).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable

from gtm.contracts.provenance import EvidenceBasis
from gtm.contracts.world import TrueCompany, World
from gtm.eval import invariants

MEASURED = EvidenceBasis.MEASURED_ON_SIMULATION.value
MACHINERY = EvidenceBasis.MACHINERY_CHECK.value


@dataclass
class MetricResult:
    name: str
    value: float | None
    denominator: int
    evidence_basis: str
    data_origins: list[str]
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "denominator": self.denominator, "evidence_basis": self.evidence_basis,
                "data_origins": self.data_origins, "details": self.details}


def _ratio(num: float, den: float) -> float | None:
    return None if not den else num / den


def _m(name, num, den, basis, origins, **details) -> MetricResult:
    return MetricResult(name, _ratio(num, den), int(den), basis, list(origins), details)


METRIC_NAMES = {
    "er_precision", "er_recall", "er_f1", "er_wrong_merge_rate", "resolved_field_accuracy", "calibration_ece",
    "qualification_accuracy", "qualification_precision", "qualification_recall", "qualification_false_negatives",
    "triage_accuracy", "triage_injection_accuracy", "hold_precision", "real_leads_held", "tool_call_correctness", "tool_calls_denied",
    "tool_call_recall", "cost_total", "cost_per_run", "run_latency_p50_s", "run_latency_p95_s", "step_latency_p95_s", "run_failure_rate",
}
METRIC_PREFIXES = ("provider_accuracy.", "provider_coverage.")


def is_known_metric(name: str) -> bool:
    return name in METRIC_NAMES or name.startswith(METRIC_PREFIXES)


# =============================================================== ground-truth mapping
def domain_index(world: World) -> dict[str, str]:
    """lower-case domain -> company id. Primary domains win over aliases."""
    idx: dict[str, str] = {}
    for c in world.companies:
        for d in c.alias_domains:
            idx.setdefault(d.lower(), c.id)
    for c in world.companies:
        idx[c.domain.lower()] = c.id
    return idx


def account_truth_map(accounts: Iterable[dict], account_domains: Iterable[dict], world: World) -> dict[int, str]:
    """account id -> company id. ``accounts``: {id, primary_domain}; ``account_domains``: {account_id, domain}."""
    idx = domain_index(world)
    doms: dict[int, list[str]] = defaultdict(list)
    for a in accounts:
        if a.get("primary_domain"):
            doms[a["id"]].append(a["primary_domain"].lower())
    for d in account_domains:
        doms[d["account_id"]].append(d["domain"].lower())
    out = {}
    for aid, ds in doms.items():
        for d in ds:
            if d in idx:
                out[aid] = idx[d]
                break
    return out


def lead_enquiry_map(leads: Iterable[dict], world: World) -> dict[int, str]:
    """lead id -> enquiry id."""
    by_email = {e.email.lower(): e.id for e in world.enquiries}
    known = {e.id for e in world.enquiries}
    out = {}
    for l in leads:
        p = l.get("raw_payload") or {}
        eid = p.get("enquiry_id") or p.get("world_id")
        if eid not in known:
            email = (p.get("email") or (p.get("contact") or {}).get("email") or "").lower()
            eid = by_email.get(email)
        if eid:
            out[l["id"]] = eid
    return out


# =============================================================== entity resolution
def truth_account_pairs(acct_to_company: dict[int, str], world: World) -> set[frozenset]:
    dup = {frozenset(p) for p in world.duplicate_company_pairs}
    out = set()
    for a, b in combinations(sorted(acct_to_company), 2):
        ca, cb = acct_to_company[a], acct_to_company[b]
        if ca == cb or frozenset((ca, cb)) in dup:
            out.add(frozenset((a, b)))
    return out


def er_metrics(predicted: Iterable, truth: Iterable, merged: Iterable = ()) -> dict[str, MetricResult]:
    """Pair precision/recall/F1 (predicted 'same' pairs vs truth-same pairs) and wrong-merge rate (executed merges
    that are not truth-same, reported separately because it is the dangerous error)."""
    P = {frozenset(p) for p in predicted if len(set(p)) == 2}
    T = {frozenset(p) for p in truth}
    M = {frozenset(p) for p in merged if len(set(p)) == 2}
    tp = len(P & T)
    prec, rec = _ratio(tp, len(P)), _ratio(tp, len(T))
    f1 = None if prec is None or rec is None or (prec + rec) == 0 else 2 * prec * rec / (prec + rec)
    o = ["GT", "MOD"]
    return {
        "er_precision": _m("er_precision", tp, len(P), MEASURED, o, true_positives=tp),
        "er_recall": _m("er_recall", tp, len(T), MEASURED, o, true_positives=tp, missed=[sorted(p) for p in T - P]),
        "er_f1": MetricResult("er_f1", f1, len(P | T), MEASURED, o, {}),
        "er_wrong_merge_rate": _m("er_wrong_merge_rate", len(M - T), len(M), MEASURED, o, wrong=[sorted(p) for p in M - T]),
    }


# =============================================================== provider accuracy
def _truth_value(c: TrueCompany, field_: str, by_id: dict[str, TrueCompany]):
    if field_ == "parent_domain":
        return by_id[c.parent_id].domain if c.parent_id in by_id else None
    return getattr(c, field_, None)


def value_matches(field_: str, observed: Any, truth: Any, numeric_tol: float = 0.10) -> bool:
    """Exact (case-insensitive) match; lists as sets; employee_count within +-numeric_tol relative."""
    if truth is None or observed is None:
        return False
    if field_ == "employee_count":
        try:
            return abs(float(observed) - float(truth)) <= numeric_tol * float(truth)
        except (TypeError, ValueError):
            return False
    if isinstance(truth, list):
        return isinstance(observed, list) and {str(x).lower() for x in observed} == {str(x).lower() for x in truth}
    return str(observed).strip().lower() == str(truth).strip().lower()


def provider_field_metrics(observations: Iterable[dict], acct_to_company: dict[int, str], world: World,
                           queried: dict[str, set] | None = None, numeric_tol: float = 0.10) -> dict[str, MetricResult]:
    """Per provider (and per provider+field) accuracy, and coverage = entities with any observation / entities queried.
    ``observations``: {entity_type, entity_id, field, value, provider}. All observations count, superseded or not."""
    by_id = {c.id: c for c in world.companies}
    hit, tot = Counter(), Counter()
    seen: dict[str, set] = defaultdict(set)
    all_entities: set = set()
    for o in observations:
        if o["entity_type"] != "account":
            continue
        all_entities.add(o["entity_id"])
        seen[o["provider"]].add(o["entity_id"])
        cid = acct_to_company.get(o["entity_id"])
        if cid is None:
            continue
        t = _truth_value(by_id[cid], o["field"], by_id)
        if t is None:
            continue
        ok = value_matches(o["field"], o["value"], t, numeric_tol)
        for key in ((o["provider"],), (o["provider"], o["field"])):
            tot[key] += 1
            hit[key] += ok
    out: dict[str, MetricResult] = {}
    for key in sorted(tot):
        name = "provider_accuracy." + ".".join(key)
        out[name] = _m(name, hit[key], tot[key], MEASURED, ["GT", "SIM"], numeric_tol=numeric_tol if "employee_count" in key else None)
    for prov in sorted(seen):
        q = (queried or {}).get(prov) or all_entities
        name = f"provider_coverage.{prov}"
        out[name] = _m(name, len(seen[prov] & q), len(q), MEASURED, ["GT", "SIM"])
    return out


# =============================================================== resolved fields and calibration
def resolved_field_metrics(rows: Iterable[dict], acct_to_company: dict[int, str], world: World, n_bins: int = 5,
                           numeric_tol: float = 0.10) -> dict[str, MetricResult]:
    """Accuracy of gtm.resolved_field vs truth, and a reliability table (confidence bins) with expected calibration error."""
    by_id = {c.id: c for c in world.companies}
    graded = []
    for r in rows:
        if r["entity_type"] != "account" or r.get("confidence") is None:
            continue
        cid = acct_to_company.get(r["entity_id"])
        t = _truth_value(by_id[cid], r["field"], by_id) if cid else None
        if t is None:
            continue
        graded.append((float(r["confidence"]), value_matches(r["field"], r["value"], t, numeric_tol)))
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        sel = [(c, ok) for c, ok in graded if lo <= c < hi or (i == n_bins - 1 and c == 1.0)]
        bins.append({"lo": lo, "hi": hi, "n": len(sel), "mean_confidence": _ratio(sum(c for c, _ in sel), len(sel)),
                     "accuracy": _ratio(sum(ok for _, ok in sel), len(sel))})
    n = len(graded)
    ece = None if not n else sum(b["n"] * abs(b["mean_confidence"] - b["accuracy"]) for b in bins if b["n"]) / n
    o = ["GT", "SIM", "MOD"]
    return {"resolved_field_accuracy": _m("resolved_field_accuracy", sum(ok for _, ok in graded), n, MEASURED, o),
            "calibration_ece": MetricResult("calibration_ece", ece, n, MEASURED, o, {"bins": bins})}


# =============================================================== qualification and triage
QUALIFIED_BANDS = ("high", "medium")


def qualification_metrics(pairs: Iterable[tuple[str, str, str]], positive: tuple[str, ...] = QUALIFIED_BANDS) -> dict[str, MetricResult]:
    """``pairs``: (enquiry_id, expected_band, predicted_band). Accuracy is exact band match; precision/recall are for the
    binary 'qualified' class (``positive`` bands). ``qualification_false_negatives`` lists enquiry ids."""
    pairs = list(pairs)
    n = len(pairs)
    acc = sum(e == p for _, e, p in pairs)
    tp = [i for i, e, p in pairs if e in positive and p in positive]
    fp = [i for i, e, p in pairs if e not in positive and p in positive]
    fn = [i for i, e, p in pairs if e in positive and p not in positive]
    o = ["GT", "MOD"]
    return {"qualification_accuracy": _m("qualification_accuracy", acc, n, MEASURED, o),
            "qualification_precision": _m("qualification_precision", len(tp), len(tp) + len(fp), MEASURED, o, false_positives=fp),
            "qualification_recall": _m("qualification_recall", len(tp), len(tp) + len(fn), MEASURED, o, false_negatives=fn),
            "qualification_false_negatives": MetricResult("qualification_false_negatives", float(len(fn)), len(tp) + len(fn), MEASURED, o,
                                                          {"enquiry_ids": fn})}


def triage_metrics(pairs: Iterable[tuple[str, str, str, bool]]) -> dict[str, MetricResult]:
    """``pairs``: (enquiry_id, true_kind, predicted_class, injection). Confusion matrix is in ``details['confusion']``."""
    pairs = list(pairs)
    conf: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _, t, p, _ in pairs:
        conf[t][p] += 1
    inj = [(t, p) for _, t, p, i in pairs if i]
    o = ["GT", "MOD"]
    return {"triage_accuracy": _m("triage_accuracy", sum(t == p for _, t, p, _ in pairs), len(pairs), MEASURED, o,
                                  confusion={k: dict(v) for k, v in conf.items()}),
            "triage_injection_accuracy": _m("triage_injection_accuracy", sum(t == p for t, p in inj), len(inj), MEASURED, o)}


HELD_STATUSES = ("held", "archived", "disqualified")


def hold_metrics(rows: Iterable[tuple[str, str, str]]) -> dict[str, MetricResult]:
    """``rows``: (enquiry_id, true_kind, lead_status). hold_precision = share of held/archived leads that are truly not
    genuine (vendor/recruiter/spam); real_leads_held = genuine enquiries that were held (should be 0, or released/digested)."""
    rows = list(rows)
    held = [(i, k) for i, k, st in rows if st in HELD_STATUSES]
    real = [i for i, k in held if k == "genuine"]
    o = ["GT", "MOD"]
    return {"hold_precision": _m("hold_precision", len(held) - len(real), len(held), MEASURED, o, wrongly_held=real),
            "real_leads_held": MetricResult("real_leads_held", float(len(real)), sum(k == "genuine" for _, k, _ in rows), MEASURED, o,
                                            {"enquiry_ids": real})}


# =============================================================== tool calls
def tool_call_metrics(rows: Iterable[dict], expected_tools: dict[str, set] | None = None) -> dict[str, MetricResult]:
    """``rows``: ops.tool_call rows. Correct = permitted and inside the principal's profile. ``expected_tools``
    (principal -> tool names that a good trace must contain) adds ``tool_call_recall``."""
    rows = list(rows)
    agent_rows = [r for r in rows if r["principal"].startswith("agent:")]

    def in_profile(r):
        allowed = invariants.PROFILES.get(r["principal"].removeprefix("agent:"), set())
        return r["tool_name"] in allowed and r["tool_name"] not in invariants.ABSENT_TOOLS

    correct = sum(1 for r in agent_rows if r["permitted"] and in_profile(r))
    denied = [r for r in rows if not r["permitted"]]
    out = {"tool_call_correctness": _m("tool_call_correctness", correct, len(agent_rows), MACHINERY, ["SIM", "MOD"]),
           "tool_calls_denied": MetricResult("tool_calls_denied", float(len(denied)), len(rows), MACHINERY, ["SIM", "MOD"],
                                             {"by_tool": dict(Counter(r["tool_name"] for r in denied))})}
    if expected_tools:
        used = defaultdict(set)
        for r in rows:
            used[r["principal"]].add(r["tool_name"])
        want = sum(len(v) for v in expected_tools.values())
        got = sum(len(v & used[k]) for k, v in expected_tools.items())
        out["tool_call_recall"] = _m("tool_call_recall", got, want, MACHINERY, ["SIM", "MOD"])
    return out


# =============================================================== cost and latency
def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def cost_latency_metrics(agent_runs: Iterable[dict], run_steps: Iterable[dict]) -> dict[str, MetricResult]:
    """Cost units are mixed: provider cost is simulated units, model cost is mock ($0) unless live. Latency is in
    SIMULATED seconds (shared SimClock), not wall time."""
    runs, steps = list(agent_runs), list(run_steps)
    cost = sum(float(r["cost"] or 0) for r in runs)
    run_lat = [(r["ended_at"] - r["started_at"]).total_seconds() for r in runs if r.get("ended_at")]
    step_lat = [(s["ended_at"] - s["started_at"]).total_seconds() for s in steps if s.get("ended_at")]
    o = ["SIM", "MOD"]
    by_wf = defaultdict(float)
    for r in runs:
        by_wf[r["workflow"]] += float(r["cost"] or 0)
    return {
        "cost_total": MetricResult("cost_total", cost, len(runs), MACHINERY, o,
                                   {"by_workflow": dict(by_wf), "tokens_in": sum(r["tokens_in"] or 0 for r in runs),
                                    "tokens_out": sum(r["tokens_out"] or 0 for r in runs), "unit": "simulated provider units + model cost"}),
        "cost_per_run": MetricResult("cost_per_run", _ratio(cost, len(runs)), len(runs), MACHINERY, o),
        "run_latency_p50_s": MetricResult("run_latency_p50_s", percentile(run_lat, .5), len(run_lat), MACHINERY, o),
        "run_latency_p95_s": MetricResult("run_latency_p95_s", percentile(run_lat, .95), len(run_lat), MACHINERY, o),
        "step_latency_p95_s": MetricResult("step_latency_p95_s", percentile(step_lat, .95), len(step_lat), MACHINERY, o),
        "run_failure_rate": _m("run_failure_rate", sum(r["status"] in ("failed", "budget_exceeded") for r in runs), len(runs), MACHINERY, o),
    }


# =============================================================== DB loaders and one-call aggregate
def _all(conn, sql, params=None) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def compute_all(conn, world: World, enquiry_ids: Iterable[str] | None = None) -> dict[str, MetricResult]:
    """Every metric over the current database, flat dict keyed by metric name. ``enquiry_ids`` restricts qualification
    and triage to the enquiries delivered in the scenario (default: those that have a lead)."""
    accounts = _all(conn, "SELECT id, primary_domain FROM gtm.account")
    a2c = account_truth_map(accounts, _all(conn, "SELECT account_id, domain FROM gtm.account_domain"), world)
    out: dict[str, MetricResult] = {}

    # entity resolution (account level)
    predicted = [(r["left_id"], r["right_id"]) for r in _all(
        conn, "SELECT left_id, right_id FROM gtm.entity_match WHERE entity_type='account' AND decision='same'")]
    merged = [(r["loser_id"], r["survivor_id"]) for r in _all(conn, "SELECT loser_id, survivor_id FROM gtm.merge_log WHERE entity_type='account' AND undone_at IS NULL")]
    out.update(er_metrics(set(map(frozenset, predicted)) | set(map(frozenset, merged)), truth_account_pairs(a2c, world), merged))

    obs = _all(conn, "SELECT o.entity_type, o.entity_id, o.field, o.value, ds.name AS provider FROM gtm.observation o "
                     "JOIN gtm.data_source ds ON ds.id=o.data_source_id WHERE ds.kind='provider'")
    queried: dict[str, set] = defaultdict(set)
    for r in _all(conn, "SELECT entity_id, unnest(providers_tried) AS p FROM gtm.enrichment_request WHERE entity_type='account'"):
        queried[r["p"]].add(r["entity_id"])
    out.update(provider_field_metrics(obs, a2c, world, dict(queried)))
    out.update(resolved_field_metrics(_all(conn, "SELECT entity_type, entity_id, field, value, confidence FROM gtm.resolved_field"), a2c, world))

    leads = _all(conn, "SELECT id, raw_payload, triage_class, fit_band, status, held_reason FROM gtm.lead")
    l2e = lead_enquiry_map(leads, world)
    enq = {e.id: e for e in world.enquiries}
    wanted = set(enquiry_ids) if enquiry_ids is not None else None
    q_pairs, t_pairs, h_rows = [], [], []
    for l in leads:
        e = enq.get(l2e.get(l["id"]))
        if e is None or (wanted is not None and e.id not in wanted):
            continue
        q_pairs.append((e.id, e.expected_band, l["fit_band"] or "none"))
        st = l["status"]
        if st == "held" and not (l.get("held_reason") or "").startswith(("triage:", "injection")):
            st = "awaiting_human"   # low-fit disposition / possible-duplicate: pending a human decision, not a triage hold
        h_rows.append((e.id, e.kind, st))
        if l["triage_class"]:
            t_pairs.append((e.id, e.kind, l["triage_class"], e.injection))
    out.update(qualification_metrics(q_pairs))
    out.update(triage_metrics(t_pairs))
    out.update(hold_metrics(h_rows))

    out.update(tool_call_metrics(_all(conn, "SELECT principal, tool_name, permitted FROM ops.tool_call")))
    out.update(cost_latency_metrics(_all(conn, "SELECT workflow, status, cost, tokens_in, tokens_out, started_at, ended_at FROM ops.agent_run"),
                                    _all(conn, "SELECT started_at, ended_at FROM ops.run_step")))
    return out
