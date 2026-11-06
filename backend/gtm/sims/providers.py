"""Provider simulators (a/b/c): POST /company and POST /person. Truth degraded by deterministic hashing (world.degrade)."""
from __future__ import annotations
from datetime import timedelta
from fastapi import FastAPI, Response
from gtm.clock import Clock
from gtm.contracts.sims import (ProviderCompanyRequest, ProviderField, ProviderPersonRequest, ProviderResponse)
from gtm.contracts.world import World
from gtm.world.degrade import covers, is_correct, rng_for, unit, wrong_value
from .faults import FaultStore, gate


def make_provider_app(world: World, clock: Clock, faults: FaultStore, name: str) -> FastAPI:
    params = next(p for p in world.providers if p.name == name)
    app = FastAPI(title=f"sim {name}")
    by_domain, by_name = {}, {}
    for c in world.companies:
        for d in [c.domain, *c.alias_domains]:
            by_domain.setdefault(d.lower(), c)
        by_name.setdefault(c.name.lower(), c)
    by_email = {ct.email.lower(): ct for ct in world.contacts}
    supported_co = {f for f in params.fields if not f.startswith("person.")}
    supported_pe = {f[len("person."):] for f in params.fields if f.startswith("person.")}

    def answer(entity_id: str, truth_obj, requested: list[str], supported: set[str], partial: bool) -> ProviderResponse:
        now = clock.now()
        if not covers(world.seed, name, params.coverage, entity_id):
            return ProviderResponse(provider=name, found=False, cost_units=params.cost_per_call)
        out: dict[str, ProviderField] = {}
        for f in sorted(set(requested) & supported):
            truth = getattr(truth_obj, f, None)
            if is_correct(world.seed, name, params.accuracy, entity_id, f):
                val = truth
            else:
                val = wrong_value(f, truth, rng_for(world.seed, name, entity_id, f, "wrong"))
            as_of = now - timedelta(days=unit(world.seed, name, entity_id, f, "stale") * params.staleness_days)
            out[f] = ProviderField(value=val, as_of=as_of)
        if partial:
            out = {k: v for i, (k, v) in enumerate(sorted(out.items())) if i % 2 == 0}
        return ProviderResponse(provider=name, found=True, fields=out, cost_units=params.cost_per_call, partial=partial)

    @app.post("/company")
    def company(req: ProviderCompanyRequest, response: Response) -> ProviderResponse:
        o = gate(faults, name, response, ["/company", req.domain or "", req.name or ""], params.latency_ms)
        c = by_domain.get((req.domain or "").lower()) or by_name.get((req.name or "").lower())
        if c is None:
            return ProviderResponse(provider=name, found=False, cost_units=params.cost_per_call)
        return answer(c.id, c, req.fields, supported_co, o.partial)

    @app.post("/person")
    def person(req: ProviderPersonRequest, response: Response) -> ProviderResponse:
        o = gate(faults, name, response, ["/person", req.email], params.latency_ms)
        ct = by_email.get(req.email.lower())
        if ct is None:
            return ProviderResponse(provider=name, found=False, cost_units=params.cost_per_call)
        return answer(ct.id, ct, req.fields, supported_pe, o.partial)

    return app
