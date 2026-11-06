"""Synthetic web for the research agent. Page text is returned verbatim (injection pages are NOT flagged to the caller)."""
from __future__ import annotations
import re
from fastapi import FastAPI, HTTPException, Response
from gtm.clock import Clock
from gtm.contracts.world import World
from .faults import FaultStore, gate


def make_web_app(world: World, clock: Clock, faults: FaultStore) -> FastAPI:
    app = FastAPI(title="sim web")
    pages = {p.url: p for p in world.web_pages}

    @app.get("/search")
    def search(q: str, response: Response):
        o = gate(faults, "web", response, ["/search", q])
        terms = set(re.findall(r"[a-z0-9]+", q.lower()))
        scored = []
        for p in world.web_pages:
            hay = set(re.findall(r"[a-z0-9]+", (p.title + " " + p.text + " " + p.url).lower()))
            s = len(terms & hay)
            if s:
                scored.append((-s, p.url, p))
        res = [{"url": p.url, "title": p.title, "snippet": p.text[:160]} for _, _, p in sorted(scored, key=lambda x: x[:2])[:5]]
        if o.partial:
            res = res[: max(1, len(res) // 2)] if res else res
        return {"results": res}

    @app.get("/page")
    def page(url: str, response: Response):
        gate(faults, "web", response, ["/page", url])
        p = pages.get(url)
        if p is None:
            raise HTTPException(404, {"message": "not found"})
        return {"url": p.url, "title": p.title, "text": p.text}

    return app
