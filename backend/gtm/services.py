"""Wiring: build the simulated world, simulators, adapters, LLM client and orchestration Services."""
from __future__ import annotations
import importlib
from .config import Settings
from .orchestration import Services

DEFAULT_TOKEN_SECRET = b"gtm-demo-token-secret-not-a-credential"


def build_services(settings: Settings, clock, world, conn, *, token_secret: bytes = DEFAULT_TOKEN_SECRET, auto_replies: bool = False):
    from .llm import build_llm
    from .sims import build_sims
    try:  # the deterministic mock model registers itself (gtm.agents.mockmodel)
        importlib.import_module("gtm.agents.mockmodel").register_all()
    except ModuleNotFoundError:
        pass
    sims = build_sims(world, clock, auto_replies=auto_replies)
    ad = sims.clients(token_secret=token_secret)
    services = Services(settings, clock, llm=build_llm(settings, clock, conn=conn), crm=ad.crm, outreach=ad.outreach,
                        providers=ad.providers, web=ad.web, token_secret=token_secret, extras={"adapters": ad, "world": world, "sims": sims})
    return services, sims
