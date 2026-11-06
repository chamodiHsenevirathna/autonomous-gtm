from __future__ import annotations
from .facade import SimFacade
from .gateway import Gateway


def gateway_for(conn, clock, services, emit=None) -> Gateway:
    """Build a Gateway from orchestration Services (uses services.crm / services.outreach / services.token_secret)."""
    return Gateway(conn, clock, services.settings, SimFacade(services), services.token_secret, emit=emit)
