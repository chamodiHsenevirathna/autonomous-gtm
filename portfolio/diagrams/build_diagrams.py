"""Generates the four portfolio diagrams as SVG. Run from the backend venv: python build_diagrams.py
The evaluation chart reads the real report model_eval/results/mock_v4/model_eval_report.json; nothing in it is typed by hand except labels."""
import json, pathlib, sys
from xml.sax.saxutils import escape as esc
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

STYLE = {  # fill, stroke
    "code": ("#eef1f5", "#5b6b7b"), "ai": ("#e6effd", "#3b6fd4"), "human": ("#fff3dc", "#d98a00"), "gate": ("#e3f4e9", "#2e8b57"),
    "sim": ("#f1ecfb", "#7d56c2"), "store": ("#f4f4f4", "#8a8a8a"), "locked": ("#fdeceb", "#c0392b"), "plain": ("#ffffff", "#9aa5b1")}
FONT = "font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif\""


class Svg:
    def __init__(self, w, h, title, subtitle=None):
        self.w, self.h, self.e = w, h, []
        self.e.append(f'<rect width="{w}" height="{h}" fill="#ffffff"/>')
        self.text(24, 36, title, size=22, weight=700, fill="#1b2430")
        if subtitle: self.text(24, 58, subtitle, size=13, fill="#5a6675")

    def text(self, x, y, s, size=13, weight=400, fill="#1b2430", anchor="start", italic=False):
        st = ' font-style="italic"' if italic else ""
        self.e.append(f'<text x="{x}" y="{y}" {FONT} font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}>{esc(s)}</text>')

    def box(self, x, y, w, h, title, lines=(), kind="code", dashed=False, tsize=13.5):
        f, s = STYLE[kind]
        d = ' stroke-dasharray="6 4"' if dashed else ""
        self.e.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{f}" stroke="{s}" stroke-width="1.6"{d}/>')
        self.text(x + 12, y + 22, title, size=tsize, weight=650, fill="#1b2430")
        for i, l in enumerate(lines):
            self.text(x + 12, y + 42 + i * 17, l, size=12, fill="#3a4654")

    def container(self, x, y, w, h, title, kind="plain"):
        f, s = STYLE[kind]
        self.e.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" stroke="{s}" stroke-width="1.4" stroke-dasharray="3 5"/>')
        self.text(x + 12, y + 20, title, size=12, weight=700, fill=s)

    def arrow(self, pts, label=None, dashed=False, color="#44515f", lx=None, ly=None, anchor="middle"):
        d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
        da = ' stroke-dasharray="6 4"' if dashed else ""
        self.e.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{da} marker-end="url(#ah)"/>')
        if label:
            mx = lx if lx is not None else (pts[0][0] + pts[-1][0]) / 2
            my = ly if ly is not None else (pts[0][1] + pts[-1][1]) / 2 - 6
            self.text(mx, my, label, size=11.5, fill="#44515f", anchor=anchor, italic=True)

    def legend(self, x, y, items):
        for i, (k, label) in enumerate(items):
            f, s = STYLE[k]
            self.e.append(f'<rect x="{x + i * 236}" y="{y}" width="16" height="16" rx="4" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
            self.text(x + i * 236 + 24, y + 13, label, size=12, fill="#3a4654")

    def save(self, name):
        defs = '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#44515f"/></marker></defs>'
        out = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img">{defs}' + "".join(self.e) + "</svg>"
        (HERE / name).write_text(out)
        print("wrote", name)


LEG = [("code", "Deterministic code"), ("ai", "Model-backed step (mock here)"), ("human", "Human decision"), ("gate", "Execution gateway"), ("sim", "Simulated system")]


def architecture():
    s = Svg(1240, 830, "Solution architecture", "Everything outside the company is simulated. Agents can only propose; one gateway is the only door out.")
    s.container(24, 78, 232, 560, "SIMULATED WORLD (SIM)", "sim")
    for i, (t, l) in enumerate([("Data provider sims", ["3 providers, differing accuracy", "fault injection, rate limits"]), ("CRM sim", ["HubSpot-shaped records", "no real CRM"]),
                                ("Outreach tool sim", ["eventually consistent contacts", "token-enforcing adapter"]), ("Web sim", ["search + fetch pages", "includes injected pages"]), ("Scripted replies", ["customer replies on a script", "opt-out, bounce, interest"])]):
        s.box(40, 108 + i * 104, 200, 92, t, l, "sim")
    s.container(284, 78, 300, 560, "DATA AND ORCHESTRATION", "plain")
    s.box(300, 108, 268, 168, "Data layer", ["Observations with provenance", "Multi-provider waterfall", "Entity resolution: same / possible / distinct", "Survivorship + freshness rules", "Soft merge with undo"], "code")
    s.box(300, 292, 268, 168, "Event bus + durable runner", ["Outbox events, gap-safe dispatcher", "Graph runner: retries by error class", "Leases with fencing tokens", "Scheduler, simulated clock", "Park-and-resume (sync pending)"], "code")
    s.box(300, 476, 268, 148, "PostgreSQL 16", ["gtm + ops schemas", "append-only audit table (trigger)", "idempotency records, job state"], "store")
    s.container(612, 78, 280, 560, "AGENTS: PROPOSE ONLY", "plain")
    s.box(628, 108, 248, 132, "Intake workflow", ["triage, resolve, enrich, research,", "qualify, decide (code can only", "downgrade the model's band)"], "ai")
    s.box(628, 252, 248, 108, "Account agent", ["persistent per-account state", "next-action proposals,", "writes its own ai_* fields only"], "ai")
    s.box(628, 372, 248, 108, "Tool session", ["run-scoped, permissioned", "no send / merge / decide tool", "out-of-scope calls denied + logged"], "code")
    s.box(628, 492, 248, 132, "Model wrapper", ["mock (used for everything here)", "replay (recorded)", "live: never run, LOCKED"], "locked")
    s.container(916, 78, 300, 560, "CONTROL PLANE", "plain")
    s.box(932, 108, 268, 92, "Approval service", ["proposal + SHA-256 payload hash", "single-use, expiring approvals"], "code")
    s.box(932, 212, 268, 76, "Human reviewer (dashboard)", ["approve / edit / reject with reason"], "human")
    s.box(932, 300, 268, 128, "Execution gateway", ["13 canonical checks (some n/a per type)", "re-verifies approval, hash, suppression,", "contact state; mints execution token"], "gate")
    s.box(932, 440, 268, 76, "Adapter clients", ["refuse calls without a signed token", "(in-process control in this demo)"], "gate")
    s.box(932, 528, 268, 96, "Audit log", ["append-only, hash-chained", "verify endpoint + tamper test"], "store")
    # flows
    s.arrow([(256, 190), (284, 190)], "enrich", lx=270, ly=182)
    s.arrow([(584, 190), (612, 190)], "facts", lx=598, ly=182)
    s.arrow([(584, 380), (612, 380)], "events", lx=598, ly=372)
    s.arrow([(876, 175), (932, 150)], "proposals", lx=904, ly=148)
    s.arrow([(1066, 200), (1066, 212)])
    s.arrow([(1066, 288), (1066, 300)], "decision", lx=1100, ly=296)
    s.arrow([(1066, 428), (1066, 440)], "token", lx=1100, ly=436)
    s.arrow([(1200, 478), (1228, 478), (1228, 652), (140, 652), (140, 638)], None, dashed=True, color="#7d56c2")
    s.text(640, 646, "approved actions reach the simulated systems only through the adapters", size=11.5, fill="#7d56c2", anchor="middle", italic=True)
    s.arrow([(1066, 516), (1066, 528)], "every step", lx=1112, ly=524)
    s.box(24, 668, 480, 78, "FastAPI (about 24 endpoints) + React / TypeScript dashboard", ["Overview, leads, accounts, approvals, runs, audit, evaluation, demo control"], "code")
    s.box(520, 668, 696, 78, "Evaluation harness", ["28 end-to-end scenarios; 10 invariants checked after each; metrics vs ground truth;", "7 faulty test doubles; model-evaluation dataset of 68 synthetic cases"], "code")
    s.legend(24, 768, LEG)
    s.text(1216, 812, "Simulated data. Mock model. Not production-ready.", size=11.5, fill="#8a3b34", anchor="end", italic=True)
    s.save("architecture.svg")


def golden_thread():
    s = Svg(1240, 575, "Golden-thread demonstration", "One enquiry, end to end, on simulated data. The thread is the same in the dashboard, the audit log and the scenarios.")
    steps = [("1", "Enquiry arrives", "scripted inbound form", "sim"), ("2", "Resolve + enrich", "entity resolution,", "code"), ("3", "Research", "evidence-linked claims only;", "ai"), ("4", "Qualify", "score vs ICP rubric (mock);", "ai"),
             ("5", "Route", "hard limits only downgrade;", "code"), ("6", "Human review", "sees exact payload + hash", "human"), ("7", "Approve one action", "approve / edit / reject", "human"),
             ("8", "Gateway re-validates", "approval, hash, suppression,", "gate"), ("9", "Adapter executes (SIM)", "token required;", "gate"), ("10", "Scripted reply", "router: hard signals first", "sim"),
             ("11", "Account intelligence", "agent state updates, next", "ai"), ("12", "Dashboard", "workflow, decisions, audit,", "code")]
    sub2 = {"2": "3 providers + provenance", "3": "page text is untrusted data", "4": "unknowns listed", "5": "unclear / spam held", "6": "nothing sent before approval",
            "7": "single-use, expires", "8": "contact state, 13 checks", "9": "contact sync first", "10": "opt-out / bounce suppress", "11": "action proposed", "12": "evaluation results"}
    w, h, gx = 178, 108, 20
    for i, (n, t, l1, k) in enumerate(steps):
        row, col = divmod(i, 6)
        x, y = 24 + col * (w + gx), 96 + row * 190
        s.box(x, y, w, h, f"{n}. {t}", [l1, sub2.get(n, "")] if n in sub2 else [l1], k, tsize=13)
        if col < 5:
            s.arrow([(x + w, y + h / 2), (x + w + gx, y + h / 2)])
    s.arrow([(24 + 5 * (w + gx) + w / 2, 96 + h), (24 + 5 * (w + gx) + w / 2, 96 + 190 - 28), (24 + w / 2, 96 + 190 - 28), (24 + w / 2, 96 + 190)], None, color="#44515f")
    s.text(560, 96 + 190 - 34, "second row continues", size=11.5, fill="#44515f", anchor="middle", italic=True)
    s.box(24, 432, 1192, 62, "Where the evidence is", ["Each step writes an audit event; the scenario S01 asserts this thread, and the browser tests drive it through the real UI (see portfolio/screenshots/)."], "plain")
    s.legend(24, 520, LEG)
    s.text(1216, 565, "Mock model and simulated systems throughout.", size=11.5, fill="#8a3b34", anchor="end", italic=True)
    s.save("golden-thread.svg")


def approval_execution():
    s = Svg(1240, 760, "Approval and execution flow", "Why an approved message cannot reach a different address, be sent twice, or bypass the gateway.")
    s.box(24, 90, 250, 100, "1. Agent proposes", ["proposal = type + full payload", "hash = SHA-256(proposal id, type,", "payload, screen policy version)"], "ai")
    s.box(24, 230, 250, 108, "2. Human reviews", ["sees exact payload and hash", "approve, edit (new hash) or reject", "role + separation of duties (service-level;", "the demo UI uses one fixed reviewer)"], "human")
    s.box(24, 370, 250, 100, "3. Approval recorded", ["single-use, expires (72 h default)", "edited payload gets a NEW hash", "content screen blocks price / promises"], "code")
    s.arrow([(149, 190), (149, 230)]); s.arrow([(149, 330), (149, 370)])
    s.box(330, 90, 400, 450, "4. Execution gateway: 13 canonical checks", [], "gate")
    checks = ["Approval valid: role, expiry, hash match, unconsumed", "Experiment holdout (reserved; not enabled)", "Content screens on the final hash (no price / promises)",
              "Recipient resolution and data quality", "Suppression and do-not-contact pre-check", "Outreach claims and priority", "Frequency caps and duplicate-outreach key",
              "Human-touch lock", "Domain breaker", "Sync precondition: contact visible in the outreach tool (else PARK)",
              "Suppression re-read under lock (last check before sending)", "Adapter call with token; then consume approval, write row", "Audit event and domain event written"]
    for i, c in enumerate(checks):
        s.text(346, 138 + i * 26, f"{i + 1:>2}. {c}", size=12, fill="#24303c")
    for j, t in enumerate(["Check 1 recomputes the hash from the CURRENT recipient.", "A reply that depends on a CRM write waits for it.", "CRM writes skip the message-only checks."]):
        s.text(346, 138 + 13 * 26 + 6 + j * 15, t, size=11, fill="#3a6b4a", italic=True)
    s.arrow([(274, 420), (330, 420)], "approved", lx=302, ly=412)
    s.box(790, 90, 220, 110, "5. Adapter client", ["verifies the signed token", "(HMAC, expiry, adapter)", "no token = refused; in-process"], "gate")
    s.box(790, 240, 220, 90, "6. Simulated system", ["outreach tool / CRM sim", "no real message, no real CRM"], "sim")
    s.box(790, 370, 220, 140, "7. Audit + result", ["execution record with hash", "append-only audit event", "hash chain extends", "dashboard shows it"], "store")
    s.arrow([(730, 145), (790, 145)], "token", lx=760, ly=138); s.arrow([(900, 200), (900, 240)]); s.arrow([(900, 330), (900, 370)])
    s.box(1050, 90, 166, 420, "Blocked paths (tested)", ["changed recipient", "expired approval", "replayed approval", "wrong hash", "suppression added", "  during the wait", "price in edited text", "call without token", "forged token", "direct adapter call", "", "Each is a scenario", "with an expected", "denial."], "locked", dashed=True, tsize=13)
    s.box(24, 540, 1192, 120, "Design intent", ["The approval is bound to what the human saw: for a message the gateway recomputes the hash from the live recipient at execution, so a change after approval is caught.",
                                                "Safety comes from absent capability, not from prompt instructions: agents have no send, merge or decide tool, and adapter clients need a gateway token (demo-grade, in-process).",
                                                "Verified by the scenario suite (28/28) and 416 backend tests: technical results on simulated data, not evidence of commercial effect."], "plain")
    s.legend(24, 690, LEG)
    s.text(1216, 740, "Simulated systems only. No real message is ever sent.", size=11.5, fill="#8a3b34", anchor="end", italic=True)
    s.save("approval-execution.svg")


def evaluation_results():
    from gtm.eval.model_eval import wilson
    rep = json.loads((ROOT / "model_eval/results/mock_v4/model_eval_report.json").read_text())
    t = rep["tasks"]
    tr, q, r, a = t["triage"], t["qualify"], t["research_brief"], t["account_decide"]
    nt, nq, na = tr["n_cases"], q["n_cases"], a["n_cases"]
    k = lambda rate, n: round(rate * n)
    rows = [("Triage: label exactly as expected", tr["accuracy_exact"], nt, False), ("Triage: label within acceptable set", tr["accuracy_acceptable"], nt, False),
            ("Triage: injected text flagged", tr["injection_recall"], 5, False), ("Triage: spam / unclear / injection held for review", tr["must_hold_held_rate"], tr["must_hold_cases"], False),
            ("Qualify: routing decision correct", q["route_ok_rate"], nq, False), ("Qualify: band agrees with label", q["band_acceptable_rate"], nq, False),
            ("Account routing: required action (policy labels)", a["required_action_rate"], na, False), ("Research: claims cite a supplied page", r["citation_valid_rate"], r["claims_total"], True)
]
    s = Svg(1240, 640, "Mock-model results on the 68-case synthetic set (subsets per task)", "Deterministic mock logic, NOT Claude or any commercial model. 3 repeats; rates are over distinct cases; bars show 95% Wilson intervals.")
    x0, wbar = 470, 560
    for gx in (0, .25, .5, .75, 1):
        xx = x0 + gx * wbar
        s.e.append(f'<line x1="{xx}" y1="92" x2="{xx}" y2="{92 + len(rows) * 46}" stroke="#e1e5ea" stroke-width="1"/>')
        s.text(xx, 88, f"{int(gx * 100)}%", size=11, fill="#5a6675", anchor="middle")
    for i, (lab, rate, n, byc) in enumerate(rows):
        y = 104 + i * 46
        lo, hi = wilson(k(rate, n), n)
        s.text(24, y + 17, lab, size=13)
        s.text(24, y + 33, f"n = {n}" + ("  (1.0 by construction: not a finding)" if byc else ""), size=11, fill="#8a3b34" if byc else "#5a6675")
        col = "#b9c3cf" if byc else "#3b6fd4"
        s.e.append(f'<rect x="{x0}" y="{y + 4}" width="{rate * wbar}" height="22" rx="4" fill="{col}"' + (' opacity="0.8"' if byc else "") + "/>")
        s.e.append(f'<line x1="{x0 + lo * wbar}" y1="{y + 15}" x2="{x0 + hi * wbar}" y2="{y + 15}" stroke="#1b2430" stroke-width="2"/>')
        for e in (lo, hi): s.e.append(f'<line x1="{x0 + e * wbar}" y1="{y + 9}" x2="{x0 + e * wbar}" y2="{y + 21}" stroke="#1b2430" stroke-width="2"/>')
        s.text(x0 + wbar + 14, y + 20, f"{rate:.2f}  [{lo:.2f}, {hi:.2f}]", size=12, fill="#1b2430")
    yb = 104 + len(rows) * 46 + 14
    s.box(24, yb, 590, 104, "Technical test results (not commercial effectiveness)", ["28 of 28 end-to-end scenarios pass, 0 regressions vs the frozen baseline", "416 backend tests pass; 13 unit + 9 browser tests (last run 2026-11-06)", "Only 41 of 151 requirements have a runnable scenario"], "plain")
    s.box(630, yb, 586, 104, "What these numbers do not show", ["Real commercial model performance is untested (no live call was ever made).", "Labels are partly the author's judgement; 5 cases are deliberately left contested.", "No conversion, revenue or productivity effect is measured."], "locked")
    s.text(24, 628, "Source: model_eval/results/mock_v4/model_eval_report.json (generated by build_diagrams.py). Synthetic data. The account-routing row follows labels derived from the same policy the mock implements.", size=11, fill="#5a6675")
    s.save("evaluation-results.svg")


if __name__ == "__main__":
    architecture(); golden_thread(); approval_execution(); evaluation_results()
