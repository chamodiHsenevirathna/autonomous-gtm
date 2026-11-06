"""Durable discrete-event runner. One job per run; every node attempt is a run_step row; state lives in agent_run.state."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..clock import Clock, SimClock
from ..contracts.errors import ErrorClass, NotReady, PermanentError, RetryableError
from ..contracts.events import EventEnvelope, EventType
from . import events as ev, leases, scheduler
from .ctx import Ctx, Services
from .dispatcher import Dispatcher
from .graph import Graph, Node, Retry

NO_IDEM = ("wait", "approval", "trigger", "conditional")
PARK_RETRY = Retry(99, 5, 60)


def _iso(d: datetime) -> str:
    return d.isoformat()


class Runner:
    def __init__(self, conn: Connection, clock: Clock, services: Services, *, worker_id: str = "worker-1", lease_seconds: float = 300,
                 max_job_attempts: int = 5, lifecycle=None):
        self.conn, self.clock, self.services, self.worker_id = conn, clock, services, worker_id
        self.lease_seconds, self.max_job_attempts = lease_seconds, max_job_attempts
        self.graphs: dict[str, Graph] = {}
        self.dispatcher = Dispatcher(conn, clock, self.graphs, lifecycle=lifecycle)

    # ------------------------------------------------------------------ public
    def register(self, graph: Graph) -> None:
        graph.validate()
        self.graphs[graph.name] = graph
        for evs, flt in graph.triggers:
            for t in evs:
                ev.subscribe(self.conn, t, graph.name, flt)
        self.conn.commit()

    def start(self, workflow: str, env: EventEnvelope) -> int | None:
        """Manual start: store the event (dedupe applies) and enqueue a job without waiting for a subscription."""
        eid = ev.emit(self.conn, self.clock, env)
        if eid is None:
            eid = self.conn.execute("SELECT id FROM ops.domain_event WHERE dedupe_key=%s", (env.dedupe_key,)).fetchone()["id"]
        j = self.conn.execute("INSERT INTO ops.job(workflow, target, available_at, idempotency_key, payload) VALUES (%s,'start',%s,%s,%s) "
                              "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                              (workflow, self.clock.now(), f"start:{workflow}:{eid}", Jsonb({"event_ids": [eid]}))).fetchone()
        self.conn.commit()
        return j["id"] if j else None

    def resume(self, run_id: int) -> None:
        """One-click retry of a needs_attention run: fresh attempts and wait deadlines, same state."""
        r = self.conn.execute("SELECT * FROM ops.agent_run WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
        if r["status"] != "needs_attention":
            raise PermanentError(f"run {run_id} is {r['status']}, not needs_attention")
        st = r["state"]; st["_meta"] = {"attempts": {}, "waits": {}}; st["_event_waits"] = []
        prev = self.conn.execute("SELECT payload FROM ops.job WHERE run_id=%s ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        self.conn.execute("UPDATE ops.agent_run SET status='running', state=%s, error=NULL, ended_at=NULL WHERE id=%s", (Jsonb(st), run_id))
        self.conn.execute("INSERT INTO ops.job(run_id, workflow, target, available_at, idempotency_key, payload) VALUES (%s,%s,'resume',%s,%s,%s)",
                          (run_id, r["workflow"], self.clock.now(), f"resume:{run_id}:{_iso(self.clock.now())}", Jsonb(prev["payload"] if prev else {})))
        self._audit("run.resumed", run_id)
        self.conn.commit()

    def run_until_idle(self, max_steps: int = 1000, advance_clock: bool = True, horizon: datetime | None = None) -> dict:
        """Drive scheduler, dispatcher and jobs. With a SimClock and advance_clock, jump to the next future job/lease expiry
        (and, only when `horizon` is given, the next schedule) until nothing is left or `horizon` is reached."""
        jobs = adv = disp = sched = 0
        idle = False
        while jobs < max_steps:
            s, d = scheduler.tick(self.conn, self.clock), self.dispatcher.process()
            sched, disp = sched + s, disp + d
            job = self._claim()
            if job:
                self._process(job); jobs += 1
                continue
            if s or d:
                continue
            nxt = self._next_time(horizon is not None)
            idle = nxt is None
            if nxt is None or not advance_clock or not isinstance(self.clock, SimClock) or nxt <= self.clock.now() or (horizon and nxt > horizon):
                break
            self.clock.set(nxt); adv += 1
        runs = {r["status"]: r["n"] for r in self.conn.execute("SELECT status, count(*) n FROM ops.agent_run GROUP BY status")}
        self.conn.commit()
        return {"jobs": jobs, "dispatched": disp, "scheduled": sched, "clock_advances": adv, "idle": idle, "now": _iso(self.clock.now()), "runs": runs}

    def check_lease(self, run_id: int, account_id: int | None, token: int | None) -> None:
        if token is not None and account_id is not None:
            leases.check(self.conn, self.clock, account_id, run_id, token, self.lease_seconds)

    # ------------------------------------------------------------------ jobs
    def _next_time(self, with_schedules: bool):
        q = ("SELECT MIN(t) AS t FROM (SELECT available_at t FROM ops.job WHERE status='queued' UNION ALL "
             "SELECT lease_expires_at FROM ops.job WHERE status='leased'" +
             (" UNION ALL SELECT next_run_at FROM ops.schedule WHERE enabled" if with_schedules else "") + ") x")
        return self.conn.execute(q).fetchone()["t"]

    def _claim(self) -> dict | None:
        now = self.clock.now()
        job = self.conn.execute(
            "UPDATE ops.job SET status='leased', lease_owner=%s, lease_expires_at=%s, attempts=attempts+1 WHERE id=("
            "SELECT id FROM ops.job WHERE (status='queued' AND available_at<=%s) OR (status='leased' AND lease_expires_at<=%s) "
            "ORDER BY available_at, id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *",
            (self.worker_id, now + timedelta(seconds=self.lease_seconds), now, now)).fetchone()
        if job and job["attempts"] > self.max_job_attempts:
            self.conn.execute("UPDATE ops.job SET status='dead' WHERE id=%s", (job["id"],))
            if job["run_id"]:
                self.conn.execute("UPDATE ops.agent_run SET status='needs_attention', error='job dead-lettered' WHERE id=%s", (job["run_id"],))
            ev.emit(self.conn, self.clock, EventEnvelope(type=EventType.JOB_DEAD, entity_ref=f"job:{job['id']}", occurred_at=now, source="runner",
                                                         dedupe_key=f"job.dead:job:{job['id']}", payload={"kind": "job", "job_id": job["id"], "last_error": job["last_error"]}))
            self.conn.commit()
            return self._claim()
        self.conn.commit()
        return job

    def _process(self, job: dict) -> None:
        try:
            run = self.conn.execute("SELECT * FROM ops.agent_run WHERE id=%s", (job["run_id"],)).fetchone() if job["run_id"] else self._start_run(job)
            if run is None:
                self.conn.execute("UPDATE ops.job SET status='done' WHERE id=%s", (job["id"],)); self.conn.commit()
                return
            if run["status"] in ("completed", "cancelled", "failed", "budget_exceeded"):
                self.conn.execute("UPDATE ops.job SET status='done' WHERE id=%s", (job["id"],)); self.conn.commit()
                return
            self._advance(job, run)
        except Exception as e:      # runner/infrastructure error (node errors are handled inside): retry the job, dead-letter eventually
            self.conn.rollback()
            self.conn.execute("UPDATE ops.job SET status='queued', lease_owner=NULL, available_at=%s, last_error=%s WHERE id=%s",
                              (self.clock.now() + timedelta(seconds=self._backoff(Retry(9, 5, 120), job["attempts"], f"job{job['id']}")), repr(e)[:500], job["id"]))
            self.conn.commit()

    def _start_run(self, job: dict) -> dict | None:
        g = self.graphs.get(job["workflow"])
        if g is None:
            raise PermanentError(f"workflow {job['workflow']!r} is not registered")
        ids = job["payload"]["event_ids"]
        env = ev.load_event(self.conn, ids[0])
        run = self.conn.execute(
            "INSERT INTO ops.agent_run(workflow, workflow_version, trigger_event_id, account_id, status, state, versions, cost_cap, idempotency_key, started_at) "
            "VALUES (%s,%s,%s,%s,'running',%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING RETURNING *",
            (g.name, g.version, ids[0], env.account_id, Jsonb({}), Jsonb({"workflow": g.version}), g.cost_cap,
             f"{g.name}:{env.dedupe_key}", self.clock.now())).fetchone()
        if run is None:
            return None
        self.conn.execute("UPDATE ops.job SET run_id=%s WHERE id=%s", (run["id"], job["id"]))
        self._audit("run.started", run["id"], {"workflow": g.name, "version": g.version, "trigger": env.type, "events": len(ids)}, env.entity_ref)
        self.conn.commit()
        return run

    # ------------------------------------------------------------------ advancing a run
    def _advance(self, job: dict, run: dict) -> None:
        g = self.graphs[run["workflow"]]
        self.g, self.run, self.job = g, run, job
        st = self.st = run["state"]
        st.setdefault("_skipped", []); st.setdefault("_event_waits", []); st.setdefault("_meta", {"attempts": {}, "waits": {}})
        self.events = [ev.load_event(self.conn, i) for i in job["payload"]["event_ids"]]
        self.trigger, self.token, self._sid = self.events[0], None, None
        now = self.clock.now()
        self.conn.execute("UPDATE ops.run_step SET status='failed', error_class='crash', error='interrupted before commit', ended_at=%s "
                          "WHERE run_id=%s AND status='running'", (now, run["id"]))
        if g.lease and run["account_id"] is not None:
            self.token = leases.acquire(self.conn, self.clock, run["account_id"], run["id"], self.lease_seconds)
            if self.token is None:      # another run holds the account: retry shortly
                self.conn.commit()
                return self._reschedule(10, "waiting")
        self.conn.execute("UPDATE ops.agent_run SET status='running' WHERE id=%s", (run["id"],))
        self.conn.commit()
        yields, blocked = [], set()
        while True:
            node = next((n for n in g.order() if not self._terminal(n.name) and n.name not in blocked
                         and all(self._terminal(a) for a in n.after)), None)
            if node is None:
                break
            r = self._do_node(node)
            if r[0] == "yield":
                blocked.add(node.name); yields.append(r)
            elif r[0] == "stop":
                return self._end(r[1], r[2], r[3] if len(r) > 3 else "run.failed")
        if all(self._terminal(n.name) for n in g.order()):
            return self._end("completed", None, "run.finished")
        if not yields:
            return self._end("failed", "no runnable node (blocked dependency)", "run.failed")
        when = min(y[1] for y in yields)
        self._reschedule((when - self.clock.now()).total_seconds(), "waiting" if any(y[2] in ("wait", "park") for y in yields) else "running")

    def _terminal(self, name: str) -> bool:
        return name in self.st or name in self.st["_skipped"]

    def _reschedule(self, seconds: float, status: str) -> None:
        r = self.run
        self.conn.execute("UPDATE ops.agent_run SET status=%s WHERE id=%s", (status, r["id"]))
        self.conn.execute("UPDATE ops.job SET status='queued', lease_owner=NULL, attempts=0, available_at=%s WHERE id=%s",
                          (self.clock.now() + timedelta(seconds=max(0, seconds)), self.job["id"]))
        self._release()
        self.conn.commit()

    def _release(self) -> None:
        if self.token is not None:
            leases.release(self.conn, self.clock, self.run["account_id"], self.run["id"], self.token)

    def _end(self, status: str, error: str | None, audit_type: str) -> None:
        r = self.run
        done = status != "needs_attention"
        self.conn.execute("UPDATE ops.agent_run SET status=%s, error=%s, ended_at=%s WHERE id=%s",
                          (status, error, self.clock.now() if done else None, r["id"]))
        self.conn.execute("UPDATE ops.job SET status='done', lease_owner=NULL WHERE id=%s", (self.job["id"],))
        self._audit(audit_type, r["id"], {"status": status, "error": error}, None)
        self._release()
        self.conn.commit()

    def _over_budget(self) -> bool:
        r = self.conn.execute("SELECT cost, cost_cap FROM ops.agent_run WHERE id=%s", (self.run["id"],)).fetchone()
        return r["cost_cap"] is not None and r["cost"] > r["cost_cap"]

    def _save(self) -> None:
        self.conn.execute("UPDATE ops.agent_run SET state=%s WHERE id=%s", (Jsonb(self.st), self.run["id"]))
        self.conn.commit()

    def _audit(self, event_type: str, run_id: int, data: dict | None = None, entity_ref: str | None = None) -> None:
        audit.append(self.conn, self.clock, actor_type="system", actor_id="system:orchestrator", event_type=event_type,
                     entity_ref=entity_ref or f"run:{run_id}", run_id=run_id, data=data or {})

    def _backoff(self, rp: Retry, attempt: int, key: str) -> float:
        d = min(rp.cap, rp.base * 2 ** (attempt - 1))
        u = int(hashlib.sha256(f"{self.services.settings.world_seed}:{key}:{attempt}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return d * (0.5 + 0.5 * u)          # deterministic "equal jitter"

    # ------------------------------------------------------------------ nodes
    def _do_node(self, n: Node):
        if self._over_budget():
            return ("stop", "budget_exceeded", "run cost cap exceeded", "run.budget_exceeded")
        st = self.st
        sk = [a for a in n.after if a in st["_skipped"]]
        if (n.when and st.get(n.when[0], {}).get("branch") != n.when[1]) or (n.join and len(sk) == len(n.after)) or (sk and not n.join):
            self.conn.execute("INSERT INTO ops.run_step(run_id,node_id,node_type,status,started_at,ended_at) VALUES (%s,%s,%s,'skipped',%s,%s)",
                              (self.run["id"], n.name, n.kind, self.clock.now(), self.clock.now()))
            st["_skipped"].append(n.name); self._save()
            return ("ok",)
        if n.kind in ("wait", "approval"):
            return self._wait(n)
        if n.kind == "map":
            return self._map(n)
        call = (lambda ctx: {"event": ctx.trigger.model_dump(mode="json"), "coalesced": len(ctx.events)}) if n.kind == "trigger" else n.fn
        r = self._try(n, None, call)
        if r[0] == "ok":
            st[n.name] = r[1]; self._save()
            return ("ok",)
        return self._outcome(n, r)

    def _outcome(self, n: Node, r: tuple):
        if r[0] in ("retry", "park"):
            return ("yield", r[1], r[0])
        if n.on_error == "continue":
            self.st[n.name] = {"error": r[2], "error_class": str(r[1])}; self._save()
            return ("ok",)
        return ("stop", "needs_attention", f"{n.name}: {r[2]}", "run.failed")

    def _try(self, n: Node, item: str | None, call) -> tuple:
        """One attempt: returns ('ok', out) with writes UNCOMMITTED (caller saves), or a committed failure outcome
        ('retry'|'park', when) / ('fail', class, message)."""
        st, run, now = self.st, self.run, self.clock.now()
        key = f"{n.name}|{item or ''}"
        att = st["_meta"]["attempts"].get(key, 0) + 1
        ctx = Ctx(self, run, self.trigger, self.events, st, n.name, item, self.token)
        if n.kind not in NO_IDEM:
            rec = self.conn.execute("SELECT result FROM ops.idempotency_record WHERE key=%s", (ctx.idem_key,)).fetchone()
            if rec:
                self.conn.execute("INSERT INTO ops.run_step(run_id,node_id,node_type,item_key,attempt,status,output,error,started_at,ended_at) "
                                  "VALUES (%s,%s,%s,%s,%s,'succeeded',%s,'idempotent replay',%s,%s)",
                                  (run["id"], n.name, n.kind, item, att, Jsonb(rec["result"]), now, now))
                return ("ok", rec["result"])
        sid = self._sid = self.conn.execute(
            "INSERT INTO ops.run_step(run_id,node_id,node_type,item_key,attempt,status,started_at) VALUES (%s,%s,%s,%s,%s,'running',%s) RETURNING id",
            (run["id"], n.name, n.kind, item, att, now)).fetchone()["id"]
        self.conn.commit()
        try:
            self.check_lease(run["id"], run["account_id"], self.token)
            self.conn.commit()          # do not hold the lease row lock while the node runs; the pre-commit check below re-takes it
            out = call(ctx)
            if not isinstance(out, dict):
                raise PermanentError(f"node {n.name} must return a dict, got {type(out).__name__}")
            out = json.loads(json.dumps(out))
            if n.timeout and (self.clock.now() - now).total_seconds() > n.timeout:
                raise RetryableError(f"timeout after {n.timeout}s")
            self.check_lease(run["id"], run["account_id"], self.token)
            self.conn.execute("UPDATE ops.run_step SET status='succeeded', output=%s, ended_at=%s, cost=%s WHERE id=%s",
                              (Jsonb(out), self.clock.now(), ctx._cost["usd"], sid))
            if n.kind not in NO_IDEM:
                self.conn.execute("INSERT INTO ops.idempotency_record(key,result,created_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                                  (ctx.idem_key, Jsonb(out), self.clock.now()))
            self._flush(ctx, sid)
            return ("ok", out)
        except Exception as e:
            self.conn.rollback()
            cls = getattr(e, "error_class", ErrorClass.PERMANENT)
            msg = f"{type(e).__name__}: {e}"
            now = self.clock.now()
            retry_after = getattr(e, "retry_after", None) or 0
            status, ret = "failed", None
            if cls == ErrorClass.NOT_READY:
                w = st["_meta"]["waits"].setdefault(key, {"since": _iso(now), "n": 0})
                dl = self.g.park_deadline or self.services.settings.sync_wait_deadline_minutes * 60
                if (now - datetime.fromisoformat(w["since"])).total_seconds() >= dl:
                    ret = ("fail", "not_ready", f"still not ready after {dl:.0f}s: {e}")
                else:
                    w["n"] += 1
                    status, ret = "parked", ("park", now + timedelta(seconds=max(retry_after, self._backoff(PARK_RETRY, w["n"], f"{run['id']}:{key}"))))
            elif cls == ErrorClass.RETRYABLE and att < n.retry.max_attempts:
                st["_meta"]["attempts"][key] = att
                status, ret = "retrying", ("retry", now + timedelta(seconds=max(retry_after, self._backoff(n.retry, att, f"{run['id']}:{key}"))))
            else:
                ret = ("fail", cls, msg)
            self.conn.execute("UPDATE ops.run_step SET status=%s, error_class=%s, error=%s, ended_at=%s, cost=%s WHERE id=%s",
                              (status, str(cls), msg[:1000], now, ctx._cost["usd"], sid))
            self._flush(ctx, sid)
            self._save()
            return ret

    def _flush(self, ctx: Ctx, sid: int) -> None:
        c = ctx._cost
        if c["apply"] or c["apply_in"] or c["apply_out"] or c["models"]:
            self.conn.execute("UPDATE ops.agent_run SET cost=cost+%s, tokens_in=tokens_in+%s, tokens_out=tokens_out+%s, "
                              "model_ids=ARRAY(SELECT DISTINCT unnest(model_ids || %s::text[])) WHERE id=%s",
                              (c["apply"], c["apply_in"], c["apply_out"], c["models"], self.run["id"]))
        for t in ctx._tools:
            self.conn.execute("INSERT INTO ops.tool_call(step_id,run_id,principal,tool_name,args,permitted,deny_reason,latency_ms,at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                              (sid, self.run["id"], t["principal"], t["tool_name"], Jsonb(t["args"], dumps=lambda o: json.dumps(o, default=str)),
                               t["permitted"], t["deny_reason"], t.get("latency_ms"), t["at"]))

    def _map(self, n: Node):
        st, o = self.st, n.opts
        m = st.setdefault("_map", {}).get(n.name)
        if m is None:
            r = self._try(n, "__items__", lambda ctx: {"items": list(o["items"](ctx))})
            if r[0] != "ok":
                return self._outcome(n, r)
            keys, mp = [], {}
            for i, it in enumerate(r[1]["items"]):
                k = str(o["key"](it)) if o["key"] else str(i)
                keys.append(k); mp[k] = it
            m = st["_map"][n.name] = {"keys": keys, "items": mp, "results": {}}
            self._save()
        todo, pend = [k for k in m["keys"] if k not in m["results"]], []
        for i in range(0, len(todo), o["concurrency"]):         # logical concurrency: one batch of items per pass
            for k in todo[i:i + o["concurrency"]]:
                r = self._try(n, k, lambda ctx, k=k: n.fn(ctx, m["items"][k]))
                if r[0] == "ok":
                    m["results"][k] = {"ok": True, "output": r[1]}; self._save()
                elif r[0] in ("retry", "park"):
                    pend.append(r)
                else:
                    m["results"][k] = {"ok": False, "error": r[2], "error_class": str(r[1])}; self._save()
        if pend:
            return ("yield", min(p[1] for p in pend), pend[0][0])
        res = m["results"]
        st[n.name] = {"items": res, "ok": sum(v["ok"] for v in res.values()), "failed": sum(not v["ok"] for v in res.values())}
        self._save()
        return ("ok",)

    def _wait(self, n: Node):
        st, o, now = self.st, n.opts, self.clock.now()
        w = st["_meta"]["waits"].get(n.name)
        if w is None:
            dl = o["deadline"] if o["deadline"] >= 0 else self.services.settings.approval_ttl_hours * 3600
            w = st["_meta"]["waits"][n.name] = {"n": 0, "deadline": _iso(now + timedelta(seconds=dl))}
            st["_event_waits"] = sorted(set(st["_event_waits"]) | set(o["events"]))

        def check(ctx):
            if o["events"]:
                for e in self.conn.execute("SELECT * FROM ops.domain_event WHERE type=ANY(%s) AND recorded_at>=%s ORDER BY id",
                                           (o["events"], self.run["started_at"])).fetchall():
                    env = ev.row_to_env(e)
                    if self.run["account_id"] is not None and env.account_id not in (None, self.run["account_id"]):
                        continue
                    if o["match"] is None or o["match"](ctx, env):
                        res = o["result"](ctx, env) if o["result"] else {"event_type": env.type, "payload": env.payload}
                        return {"done": True, "via": "event", "event_id": e["id"], **res}
            if o["until"]:
                r = o["until"](ctx)
                if r:
                    return {"done": True, "via": "poll", **(r if isinstance(r, dict) else {"result": r})}
            return {"done": False}

        r = self._try(n, None, check)
        if r[0] != "ok":
            return self._outcome(n, r)
        if r[1]["done"]:
            st["_event_waits"] = [t for t in st["_event_waits"] if t not in o["events"]]
            st[n.name] = r[1]; self._save()
            return ("ok",)
        self.conn.execute("UPDATE ops.run_step SET status='parked' WHERE id=%s", (self._sid,))
        deadline = datetime.fromisoformat(w["deadline"])
        if now >= deadline:
            st["_event_waits"] = [t for t in st["_event_waits"] if t not in o["events"]]
            self._save()
            return ("stop", "needs_attention", f"wait_deadline: {n.name} not satisfied by {w['deadline']}", "run.parked")
        w["n"] += 1
        when = deadline
        if o["poll"]:
            ini, fac, cap = o["poll"]
            when = min(deadline, now + timedelta(seconds=min(cap, ini * fac ** (w["n"] - 1))))
        self._save()
        return ("yield", when, "wait")
