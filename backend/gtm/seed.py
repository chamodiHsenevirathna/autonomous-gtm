"""Reference data every environment needs: principals, roles, gate catalogue, field-ownership policy, data sources.
Idempotent. Synthetic people only."""
from __future__ import annotations
from psycopg import Connection
from psycopg.types.json import Jsonb

PRINCIPALS = [
    ("user:maya", "human", "Maya Okafor (AE)"), ("user:dev", "human", "Dev Rao (BDR)"), ("user:priya", "human", "Priya Nair (RevOps)"),
    ("user:sam", "human", "Sam Whitfield (Director)"), ("user:gita", "human", "Gita Fernando (GTM Engineer)"),
    ("agent:account-agent", "agent_profile", "Account agent"), ("agent:research-agent", "agent_profile", "Research agent"),
    ("agent:pipeline-monitor", "agent_profile", "Pipeline monitor"), ("svc:insight", "service", "Insight service"),
    ("system:rules", "system", "Deterministic rules"), ("system:gateway", "system", "Execution gateway"),
    ("system:orchestrator", "system", "Orchestrator"), ("system:world", "system", "Simulated world"),
]
ROLES = [("user:maya", "ae"), ("user:dev", "bdr"), ("user:priya", "revops"), ("user:sam", "director"), ("user:gita", "gtm_engineer")]

# gate_id, proposal_type, approver roles, sla_hours, expiry_hours, distinct approver required
GATES = [
    ("G1", "match_confirmation", ["bdr", "revops"], 24, 14 * 24, False),
    ("G2", "merge", ["revops"], 48, 14 * 24, False),
    ("G3", "lead_disposition", ["bdr", "ae"], 4, 72, False),
    ("G4", "crm_write", ["bdr", "ae", "revops"], 24, 7 * 24, False),
    ("G5", "message", ["bdr", "ae"], 24, 72, False),
    ("G6", "field_change", ["ae", "director"], 24, 7 * 24, True),
    ("G7", "task", ["ae", "bdr"], 48, 5 * 24, False),
    ("G8", "opportunity_from_signal", ["ae"], 72, 14 * 24, False),
    ("G10", "sequence_step", ["ae", "bdr"], 24, 3, False),
]

# entity, field, owner_class, write_mode, exceptions
FIELD_POLICY = [
    ("opportunity", "stage", "human", "proposal", []), ("opportunity", "amount", "human", "proposal", []),
    ("opportunity", "close_date", "human", "proposal", []), ("opportunity", "owner_principal", "human", "proposal", []),
    ("opportunity", "forecast_category", "human", "proposal", []), ("opportunity", "next_step", "human", "proposal", []),
    ("opportunity", "is_stalled", "system", "direct", ["agent:pipeline-monitor", "system:rules"]),
    ("opportunity", "stall_reason", "system", "direct", ["agent:pipeline-monitor", "system:rules"]),
    ("opportunity", "days_in_stage", "system", "direct", ["agent:pipeline-monitor", "system:rules"]),
    ("account", "status", "human", "proposal", []), ("account", "owner_principal", "human", "proposal", []),
    ("account", "name", "shared", "proposal", []), ("account", "primary_domain", "provider", "direct", ["system:orchestrator"]),
    ("account", "ai_summary", "agent", "direct", ["agent:account-agent"]), ("account", "ai_risk_level", "agent", "direct", ["agent:account-agent"]),
    ("account", "ai_next_action", "agent", "direct", ["agent:account-agent"]), ("account", "ai_last_reviewed_at", "agent", "direct", ["agent:account-agent"]),
    ("contact", "email", "shared", "proposal", []), ("contact", "title", "provider", "direct", ["system:orchestrator"]),
    ("contact", "owner_principal", "human", "proposal", []),
]

SOURCES = [
    ("first_party", "first_party", 0, {"*": 0.99}), ("provider_a", "provider", 1, {"domain": 0.85, "industry": 0.75, "employee_count": 0.6, "region": 0.8}),
    ("provider_b", "provider", 10, {"employee_count": 0.95, "revenue_band": 0.92, "industry": 0.95, "parent_domain": 0.9, "region": 0.95}),
    ("provider_c", "provider", 5, {"tech_stack": 0.85, "hiring_signals": 0.8}), ("human", "human_entered", 0, {"*": 0.99}),
]


def seed_reference(conn: Connection) -> None:
    for pid, typ, name in PRINCIPALS:
        conn.execute("INSERT INTO ops.principal VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (pid, typ, name))
    for pid, role in ROLES:
        conn.execute("INSERT INTO ops.role_assignment(principal_id, role) VALUES (%s,%s) ON CONFLICT DO NOTHING", (pid, role))
    for g in GATES:
        conn.execute("INSERT INTO ops.gate_catalog VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", g)
    for e, f, oc, wm, ex in FIELD_POLICY:
        conn.execute("INSERT INTO ops.field_policy VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (e, f, oc, wm, ex))
    for name, kind, cost, rel in SOURCES:
        conn.execute("INSERT INTO gtm.data_source(name, kind, cost_per_call, field_reliability) VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                     (name, kind, cost, Jsonb(rel)))
    conn.commit()
