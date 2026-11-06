-- Core schema for Autonomous GTM. All data is synthetic. See docs/data-model.md (sections 3, 10, 11).
CREATE SCHEMA IF NOT EXISTS gtm;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ principals and roles (ops) ============
CREATE TABLE ops.principal (
  id text PRIMARY KEY,                       -- e.g. 'user:maya', 'agent:account-agent', 'svc:insight', 'system:rules'
  type text NOT NULL CHECK (type IN ('human','agent_profile','service','system')),
  display_name text NOT NULL
);
CREATE TABLE ops.role_assignment (
  principal_id text NOT NULL REFERENCES ops.principal(id),
  role text NOT NULL CHECK (role IN ('bdr','ae','delivery_lead','revops','gtm_engineer','director')),
  scope text,
  PRIMARY KEY (principal_id, role)
);

-- ============ data sources and observations (gtm) ============
CREATE TABLE gtm.data_source (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text UNIQUE NOT NULL,                 -- 'first_party','provider_a','provider_b','provider_c','human'
  kind text NOT NULL CHECK (kind IN ('first_party','provider','human_entered','inferred')),
  cost_per_call numeric NOT NULL DEFAULT 0,
  field_reliability jsonb NOT NULL DEFAULT '{}',
  ttl_policy jsonb NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true
);

-- ============ accounts, contacts, leads, opportunities (gtm) ============
CREATE TABLE gtm.account (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  primary_domain text,
  status text NOT NULL DEFAULT 'prospect' CHECK (status IN ('prospect','customer','former','disqualified')),
  owner_principal text REFERENCES ops.principal(id),
  hierarchy_role text NOT NULL DEFAULT 'standalone' CHECK (hierarchy_role IN ('ultimate_parent','subsidiary','division','standalone')),
  parent_account_id bigint REFERENCES gtm.account(id),   -- derived from account_relationship by code
  merged_into_id bigint REFERENCES gtm.account(id),
  external_ids jsonb NOT NULL DEFAULT '{}',              -- e.g. {"crm": "company_123"}
  -- agent-owned fields (ai_*): written only by the account agent / its tools
  ai_summary text, ai_risk_level text, ai_next_action text, ai_last_reviewed_at timestamptz,
  data_origin text NOT NULL DEFAULT 'SCR',
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE INDEX account_name_trgm ON gtm.account USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX account_domain_uq ON gtm.account (primary_domain) WHERE merged_into_id IS NULL AND primary_domain IS NOT NULL;

CREATE TABLE gtm.account_domain (
  account_id bigint NOT NULL REFERENCES gtm.account(id), domain text NOT NULL, is_primary boolean NOT NULL DEFAULT false,
  PRIMARY KEY (account_id, domain)
);
CREATE TABLE gtm.account_relationship (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  from_account_id bigint NOT NULL REFERENCES gtm.account(id), to_account_id bigint NOT NULL REFERENCES gtm.account(id),
  type text NOT NULL CHECK (type IN ('parent_of','partner_of','competitor_of')),
  source text, confidence numeric
);

CREATE TABLE gtm.contact (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id bigint REFERENCES gtm.account(id),
  full_name text NOT NULL, email text, title text, seniority text, persona text,
  owner_principal text REFERENCES ops.principal(id),
  email_status text NOT NULL DEFAULT 'unverified' CHECK (email_status IN ('unverified','verified','bounced','stale')),
  merged_into_id bigint REFERENCES gtm.contact(id),
  external_ids jsonb NOT NULL DEFAULT '{}',
  data_origin text NOT NULL DEFAULT 'SCR',
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX contact_email_uq ON gtm.contact (lower(email)) WHERE merged_into_id IS NULL AND email IS NOT NULL;

CREATE TABLE gtm.lead (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  contact_id bigint REFERENCES gtm.contact(id), account_id bigint REFERENCES gtm.account(id),
  channel text NOT NULL CHECK (channel IN ('form','email','referral','outbound_reply')),
  raw_payload jsonb NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  triage_class text, triage_confidence numeric,
  fit_score numeric, fit_band text, fit_rationale jsonb,
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','held','enriching','qualified','proposed','routed','disqualified','archived')),
  held_reason text,
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);

CREATE TABLE gtm.opportunity (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id bigint NOT NULL REFERENCES gtm.account(id),
  name text NOT NULL, service_line text,
  stage text NOT NULL DEFAULT 'qualified',   -- human-owned: stage, amount, close_date, owner, forecast_category
  amount numeric, close_date date, owner_principal text REFERENCES ops.principal(id), forecast_category text, next_step text,
  source_lead_id bigint REFERENCES gtm.lead(id),
  is_stalled boolean NOT NULL DEFAULT false, stall_reason text, days_in_stage integer,   -- system-owned (pipeline monitor)
  last_activity_at timestamptz,
  external_ids jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE TABLE gtm.opportunity_contact (
  opportunity_id bigint NOT NULL REFERENCES gtm.opportunity(id), contact_id bigint NOT NULL REFERENCES gtm.contact(id),
  role text, PRIMARY KEY (opportunity_id, contact_id)
);
CREATE TABLE gtm.stage_history (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, opportunity_id bigint NOT NULL REFERENCES gtm.opportunity(id),
  from_stage text, to_stage text NOT NULL, changed_by text, at timestamptz NOT NULL
);

CREATE TABLE gtm.buying_signal (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, account_id bigint NOT NULL REFERENCES gtm.account(id),
  type text NOT NULL, description text, strength numeric, observed_at timestamptz NOT NULL, expires_at timestamptz,
  data_source_id bigint REFERENCES gtm.data_source(id), evidence_ref text
);
CREATE TABLE gtm.interaction (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id bigint REFERENCES gtm.account(id), contact_id bigint REFERENCES gtm.contact(id),
  channel text NOT NULL, direction text NOT NULL CHECK (direction IN ('inbound','outbound','internal')),
  occurred_at timestamptz NOT NULL, subject text, body text, thread_id text, classification text,
  external_ref text, data_origin text NOT NULL DEFAULT 'SCR'
);
CREATE INDEX interaction_account ON gtm.interaction (account_id, occurred_at);
CREATE TABLE gtm.activity (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  opportunity_id bigint REFERENCES gtm.opportunity(id), account_id bigint REFERENCES gtm.account(id),
  type text NOT NULL, actor text NOT NULL, due_at timestamptz, status text NOT NULL DEFAULT 'open', detail jsonb,
  created_at timestamptz NOT NULL
);

-- observations (immutable, superseded not updated), enrichment, resolved fields
CREATE TABLE gtm.observation (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_type text NOT NULL CHECK (entity_type IN ('account','contact')), entity_id bigint NOT NULL,
  field text NOT NULL, value jsonb NOT NULL, value_normalised text,
  data_source_id bigint NOT NULL REFERENCES gtm.data_source(id),
  observed_at timestamptz NOT NULL, fetched_at timestamptz NOT NULL,
  confidence numeric NOT NULL, raw_ref text, run_id bigint, superseded_by bigint REFERENCES gtm.observation(id),
  data_origin text NOT NULL DEFAULT 'SIM'
);
CREATE INDEX observation_entity ON gtm.observation (entity_type, entity_id, field);
CREATE TABLE gtm.enrichment_request (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, entity_type text NOT NULL, entity_id bigint NOT NULL,
  fields_wanted text[] NOT NULL, status text NOT NULL DEFAULT 'pending', providers_tried text[] NOT NULL DEFAULT '{}',
  cost_total numeric NOT NULL DEFAULT 0, cost_cap numeric, run_id bigint, created_at timestamptz NOT NULL, completed_at timestamptz
);
CREATE TABLE gtm.resolved_field (
  entity_type text NOT NULL, entity_id bigint NOT NULL, field text NOT NULL,
  value jsonb, confidence numeric, freshness_state text CHECK (freshness_state IN ('fresh','stale','expired','unknown')),
  winning_observation_id bigint REFERENCES gtm.observation(id), conflict_flag boolean NOT NULL DEFAULT false, resolved_at timestamptz NOT NULL,
  PRIMARY KEY (entity_type, entity_id, field)
);

-- entity resolution
CREATE TABLE gtm.entity_match (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, entity_type text NOT NULL,
  left_id bigint NOT NULL, right_id bigint NOT NULL, score numeric NOT NULL, features jsonb,
  band text NOT NULL CHECK (band IN ('same','possible','distinct')),
  decision text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','same','distinct')),
  decided_by text, is_negative boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL,
  UNIQUE (entity_type, left_id, right_id)
);
CREATE TABLE gtm.merge_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, entity_type text NOT NULL, loser_id bigint NOT NULL, survivor_id bigint NOT NULL,
  moved_observation_count integer, approval_id bigint, merged_at timestamptz NOT NULL, undone_at timestamptz
);

-- feedback (MVP: structured capture only)
CREATE TABLE gtm.lost_deal_review (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, opportunity_id bigint NOT NULL REFERENCES gtm.opportunity(id),
  primary_reason text NOT NULL, secondary_reasons text[] NOT NULL DEFAULT '{}', competitor text, debrief_held boolean NOT NULL DEFAULT false,
  notes text, captured_by text NOT NULL, ai_suggested_tags jsonb, created_at timestamptz NOT NULL
);
CREATE TABLE gtm.feedback_item (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  interaction_id bigint REFERENCES gtm.interaction(id), lost_deal_review_id bigint REFERENCES gtm.lost_deal_review(id),
  account_id bigint REFERENCES gtm.account(id), source_type text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('objection','pain_point','request','competitor_mention','lost_reason','praise','risk')),
  topic text, label text, quote text NOT NULL, quote_start integer, quote_end integer,
  speaker_role text, sentiment text, segment_snapshot jsonb, confidence numeric,
  review_status text NOT NULL DEFAULT 'suggested' CHECK (review_status IN ('suggested','confirmed','edited','rejected')),
  extracted_by_run_id bigint, created_at timestamptz NOT NULL
);

-- execution support
CREATE TABLE gtm.suppression (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope text NOT NULL CHECK (scope IN ('contact','address','domain','account')), value text NOT NULL,
  reason text NOT NULL CHECK (reason IN ('unsubscribe','bounce','complaint','dnc','manual')),
  source_event_id bigint, created_at timestamptz NOT NULL, expires_at timestamptz,
  lifted_by text, lifted_evidence text, lifted_at timestamptz
);
CREATE INDEX suppression_lookup ON gtm.suppression (scope, lower(value)) WHERE lifted_at IS NULL;
CREATE TABLE gtm.outreach_claim (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, entity_type text NOT NULL, entity_id bigint NOT NULL,
  purpose text NOT NULL, priority integer NOT NULL, holder_ref text NOT NULL, created_at timestamptz NOT NULL, expires_at timestamptz,
  released_at timestamptz
);
CREATE TABLE gtm.draft_store (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, proposal_id bigint, version integer NOT NULL DEFAULT 1,
  channel text NOT NULL, contact_id bigint REFERENCES gtm.contact(id), resolved_recipient text, sender_identity text,
  subject text, body text, links text[] NOT NULL DEFAULT '{}', attachments text[] NOT NULL DEFAULT '{}',
  claims jsonb, content_hash text, status text NOT NULL DEFAULT 'draft', created_at timestamptz NOT NULL
);
CREATE TABLE gtm.sync_state (
  entity_type text NOT NULL, entity_id bigint NOT NULL, system text NOT NULL,
  state text NOT NULL CHECK (state IN ('unknown','pending','visible','enrolled','failed','timed_out')),
  external_ref text, last_checked_at timestamptz, deadline_at timestamptz, PRIMARY KEY (entity_type, entity_id, system)
);
CREATE TABLE gtm.sending_domain_stats (
  domain text PRIMARY KEY, sends integer NOT NULL DEFAULT 0, bounces integer NOT NULL DEFAULT 0, complaints integer NOT NULL DEFAULT 0,
  breaker_state text NOT NULL DEFAULT 'closed' CHECK (breaker_state IN ('closed','open'))
);

-- persistent account intelligence
CREATE TABLE gtm.account_agent_state (
  account_id bigint PRIMARY KEY REFERENCES gtm.account(id), version integer NOT NULL DEFAULT 1,
  lifecycle text NOT NULL DEFAULT 'unprovisioned' CHECK (lifecycle IN ('unprovisioned','active','quiet','dormant','archived','needs_attention')),
  summary text, stakeholder_map jsonb NOT NULL DEFAULT '[]', commitments jsonb NOT NULL DEFAULT '[]', risks jsonb NOT NULL DEFAULT '[]',
  hypotheses jsonb NOT NULL DEFAULT '[]', open_questions jsonb NOT NULL DEFAULT '[]', next_actions jsonb NOT NULL DEFAULT '[]',
  feedback_digest jsonb NOT NULL DEFAULT '[]', context_hash text, last_woken_at timestamptz, next_wake_at timestamptz,
  consecutive_failures integer NOT NULL DEFAULT 0, untrusted_derived boolean NOT NULL DEFAULT true
);

-- ============ field ownership and gates (ops) ============
CREATE TABLE ops.field_policy (
  entity text NOT NULL, field text NOT NULL,
  owner_class text NOT NULL CHECK (owner_class IN ('human','system','provider','agent','shared')),
  write_mode text NOT NULL CHECK (write_mode IN ('direct','proposal','never')),
  principal_exceptions text[] NOT NULL DEFAULT '{}', PRIMARY KEY (entity, field)
);
CREATE TABLE ops.gate_catalog (
  gate_id text PRIMARY KEY, proposal_type text NOT NULL, approver_roles text[] NOT NULL, sla_hours integer, expiry_hours integer,
  requires_distinct_approver boolean NOT NULL DEFAULT false
);
CREATE TABLE ops.version_registry (
  kind text NOT NULL, name text NOT NULL, version text NOT NULL, content_hash text NOT NULL, PRIMARY KEY (kind, name, version)
);

-- ============ events, jobs, scheduling (ops) ============
CREATE TABLE ops.domain_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, seq bigserial,
  type text NOT NULL, account_id bigint, entity_ref text, payload jsonb NOT NULL DEFAULT '{}',
  occurred_at timestamptz NOT NULL, recorded_at timestamptz NOT NULL, source text NOT NULL, source_version bigint,
  schema_version integer NOT NULL DEFAULT 1, dedupe_key text NOT NULL UNIQUE, ordering_key text
);
CREATE TABLE ops.subscription (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_type text NOT NULL, workflow text NOT NULL, filter jsonb, enabled boolean NOT NULL DEFAULT true,
  UNIQUE (event_type, workflow)
);
CREATE TABLE ops.dispatch (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_id bigint NOT NULL REFERENCES ops.domain_event(id),
  subscription_id bigint NOT NULL REFERENCES ops.subscription(id),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','enqueued','done','ignored_stale','dead')),
  attempts integer NOT NULL DEFAULT 0, UNIQUE (event_id, subscription_id)
);
CREATE TABLE ops.agent_run (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, workflow text NOT NULL, workflow_version text NOT NULL,
  trigger_event_id bigint, account_id bigint, parent_run_id bigint,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','waiting','completed','failed','needs_attention','budget_exceeded','cancelled')),
  state jsonb NOT NULL DEFAULT '{}', versions jsonb NOT NULL DEFAULT '{}', model_ids text[] NOT NULL DEFAULT '{}',
  tokens_in integer NOT NULL DEFAULT 0, tokens_out integer NOT NULL DEFAULT 0, cost numeric NOT NULL DEFAULT 0, cost_cap numeric,
  idempotency_key text UNIQUE, started_at timestamptz NOT NULL, ended_at timestamptz, error text
);
CREATE TABLE ops.job (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, run_id bigint REFERENCES ops.agent_run(id), workflow text NOT NULL,
  target text NOT NULL,                                -- node name or wake target
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','leased','done','failed','dead')),
  lease_owner text, lease_expires_at timestamptz, attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL,
  idempotency_key text UNIQUE, payload jsonb NOT NULL DEFAULT '{}', last_error text
);
CREATE INDEX job_ready ON ops.job (status, available_at);
CREATE TABLE ops.schedule (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, kind text NOT NULL, target text NOT NULL, cadence_seconds integer,
  next_run_at timestamptz NOT NULL, enabled boolean NOT NULL DEFAULT true, UNIQUE (kind, target)
);
CREATE TABLE ops.account_lease (
  account_id bigint PRIMARY KEY, holder_run_id bigint, fencing_token integer NOT NULL, expires_at timestamptz NOT NULL, renewed_at timestamptz NOT NULL
);
CREATE TABLE ops.run_step (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, run_id bigint NOT NULL REFERENCES ops.agent_run(id),
  node_id text NOT NULL, node_type text NOT NULL, item_key text, attempt integer NOT NULL DEFAULT 1,
  status text NOT NULL CHECK (status IN ('running','succeeded','failed','retrying','parked','skipped')),
  input jsonb, output jsonb, error_class text, error text, started_at timestamptz NOT NULL, ended_at timestamptz, cost numeric NOT NULL DEFAULT 0
);
CREATE INDEX run_step_run ON ops.run_step (run_id, id);
CREATE TABLE ops.tool_call (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, step_id bigint REFERENCES ops.run_step(id), run_id bigint,
  principal text NOT NULL, tool_name text NOT NULL, args jsonb, result_ref text, permitted boolean NOT NULL DEFAULT true,
  deny_reason text, latency_ms integer, at timestamptz NOT NULL
);
CREATE TABLE ops.idempotency_record (
  key text PRIMARY KEY, result jsonb NOT NULL, created_at timestamptz NOT NULL
);

-- ============ proposals, approvals, executions (ops) ============
CREATE TABLE ops.proposal (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, group_id bigint, depends_on_proposal_id bigint REFERENCES ops.proposal(id),
  type text NOT NULL, gate_id text NOT NULL REFERENCES ops.gate_catalog(gate_id), account_id bigint,
  target_entity jsonb, payload jsonb NOT NULL, payload_hash text NOT NULL, evidence jsonb NOT NULL DEFAULT '[]', rationale text, confidence numeric,
  proposed_by_run_id bigint, proposed_by text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','approved_edited','rejected','expired','superseded','executing','parked','blocked','executed','failed')),
  block_class text CHECK (block_class IN ('soft','hard')), block_reason text,
  required_role text, idempotency_key text UNIQUE, created_at timestamptz NOT NULL, expires_at timestamptz
);
CREATE INDEX proposal_status ON ops.proposal (status, created_at);
CREATE TABLE ops.approval_decision (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, proposal_id bigint NOT NULL REFERENCES ops.proposal(id),
  decided_by text NOT NULL REFERENCES ops.principal(id),
  decision text NOT NULL CHECK (decision IN ('approve','approve_with_edits','reject')),
  approved_payload jsonb, approved_payload_hash text, reason_code text, comment text,
  decided_at timestamptz NOT NULL, expires_at timestamptz, consumed_at timestamptz
);
CREATE TABLE ops.execution (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, proposal_id bigint NOT NULL REFERENCES ops.proposal(id),
  approval_id bigint REFERENCES ops.approval_decision(id), idempotency_key text NOT NULL UNIQUE, adapter text NOT NULL,
  status text NOT NULL CHECK (status IN ('succeeded','failed','blocked')), external_ref text, attempts integer NOT NULL DEFAULT 1,
  error text, result jsonb, executed_at timestamptz NOT NULL
);
CREATE TABLE ops.decision_record (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, gate_id text NOT NULL, subject_ref text NOT NULL, decision text NOT NULL,
  reason_code text, decided_by text NOT NULL, at timestamptz NOT NULL
);
CREATE TABLE ops.notification (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, recipient text NOT NULL, type text NOT NULL, ref text, status text NOT NULL DEFAULT 'new', created_at timestamptz NOT NULL
);

-- ============ audit (append-only, hash chained) ============
CREATE TABLE ops.audit_event (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL, actor_type text NOT NULL, actor_id text NOT NULL, event_type text NOT NULL,
  entity_ref text, run_id bigint, proposal_id bigint, data jsonb NOT NULL DEFAULT '{}',
  prev_hash text NOT NULL, hash text NOT NULL
);
CREATE FUNCTION ops.audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_event is append-only'; END $$;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON ops.audit_event FOR EACH ROW EXECUTE FUNCTION ops.audit_immutable();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON ops.audit_event FOR EACH STATEMENT EXECUTE FUNCTION ops.audit_immutable();

-- ============ evaluation (ops) ============
CREATE TABLE ops.eval_run (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, started_at timestamptz NOT NULL, ended_at timestamptz,
  llm_mode text NOT NULL, code_version text, summary jsonb
);
CREATE TABLE ops.eval_result (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, eval_run_id bigint NOT NULL REFERENCES ops.eval_run(id),
  scenario_id text NOT NULL, title text, passed boolean NOT NULL, evidence_basis text NOT NULL
    CHECK (evidence_basis IN ('measured_on_simulation','machinery_check','modelled_impact')),
  metrics jsonb NOT NULL DEFAULT '{}', failures jsonb NOT NULL DEFAULT '[]', duration_ms integer, data_origins text[] NOT NULL DEFAULT '{}'
);
