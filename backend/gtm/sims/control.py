"""Control plane and the SimBundle that wires every simulator into one in-process app."""
from __future__ import annotations
from datetime import datetime
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from gtm.clock import Clock
from gtm.contracts.sims import (FaultSpec, MOUNT_CONTROL, MOUNT_CRM, MOUNT_OUTREACH, MOUNT_PROVIDER, MOUNT_WEB)
from gtm.contracts.world import World
from .crm import CrmState, make_crm_app
from .faults import FaultStore
from .outreach import OutreachState, make_outreach_app
from .providers import make_provider_app
from .web import make_web_app


class ControlPlane:
    def __init__(self, world: World, clock: Clock, faults: FaultStore, crm: CrmState, outreach: OutreachState):
        self.world, self.clock, self.faults, self.crm, self.outreach = world, clock, faults, crm, outreach

    def inject(self, spec: FaultSpec) -> None:
        self.faults.inject(spec)

    def clear(self) -> None:
        self.faults.clear()

    def script(self, reply_id: str, at: datetime, to_email: str | None = None, to_message_id: str | None = None) -> dict:
        return self.outreach.schedule_reply(reply_id, at, to_email, to_message_id)

    def state(self) -> dict:
        return {"now": self.clock.now().isoformat(), "faults": self.faults.active(), "requests": dict(self.faults.requests),
                "faults_fired": dict(self.faults.fired), "simulated_latency_ms": dict(self.faults.latency_ms),
                "crm": self.crm.summary(), "outreach": self.outreach.summary()}


def make_control_app(cp: ControlPlane) -> FastAPI:
    app = FastAPI(title="sim control")

    @app.post("/faults")
    def inject(spec: FaultSpec):
        cp.inject(spec)
        return {"ok": True, "active": len(cp.faults.active())}

    @app.delete("/faults")
    def clear():
        cp.clear()
        return {"ok": True}

    @app.get("/state")
    def state():
        cp.outreach.tick()
        return cp.state()

    @app.post("/script")
    def script(body: dict):
        try:
            at = datetime.fromisoformat(str(body["at"]).replace("Z", "+00:00"))
            return cp.script(body["reply_id"], at, body.get("to_email"), body.get("to_message_id"))
        except KeyError as e:
            raise HTTPException(404, {"message": f"unknown reply or missing field: {e}"})
        except LookupError as e:
            raise HTTPException(404, {"message": f"unknown message: {e}"})

    return app


class SimBundle:
    def __init__(self, world: World, clock: Clock, auto_replies: bool = False):
        self.world, self.clock = world, clock
        self.faults = FaultStore()
        self.crm_state = CrmState()
        self.outreach_state = OutreachState(world, clock, self.faults, auto_replies)
        self.control = ControlPlane(world, clock, self.faults, self.crm_state, self.outreach_state)
        app = FastAPI(title="Autonomous GTM simulators")
        for name, mount in MOUNT_PROVIDER.items():
            app.mount(mount, make_provider_app(world, clock, self.faults, name))
        app.mount(MOUNT_CRM, make_crm_app(world, clock, self.faults, self.crm_state))
        app.mount(MOUNT_OUTREACH, make_outreach_app(world, clock, self.faults, self.outreach_state))
        app.mount(MOUNT_WEB, make_web_app(world, clock, self.faults))
        app.mount(MOUNT_CONTROL, make_control_app(self.control))
        self.app = app

    def http(self, mount: str) -> TestClient:
        return TestClient(self.app, base_url="http://sim" + mount)

    def clients(self, token_secret: bytes = b"sim-token-secret"):
        from gtm.contracts.gateway import TokenVerifier
        from gtm.adapters import AdapterSet, CrmClient, OutreachClient, ProviderClient, WebClient
        verifier = TokenVerifier(token_secret, self.clock)
        return AdapterSet(providers={n: ProviderClient(n, self.http(m)) for n, m in MOUNT_PROVIDER.items()},
                          crm=CrmClient(self.http(MOUNT_CRM), verifier),
                          outreach=OutreachClient(self.http(MOUNT_OUTREACH), verifier), web=WebClient(self.http(MOUNT_WEB)))

    def script_reply(self, reply_id: str, to_email: str | None = None, at: datetime | None = None,
                     to_message_id: str | None = None) -> dict:
        return self.control.script(reply_id, at or self.clock.now(), to_email, to_message_id)


def build_sims(world: World, clock: Clock, *, auto_replies: bool = False) -> SimBundle:
    return SimBundle(world, clock, auto_replies)
