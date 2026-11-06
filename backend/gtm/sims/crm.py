"""HubSpot-shaped CRM simulator: contacts / companies / deals. In memory; ids are strings."""
from __future__ import annotations
from fastapi import FastAPI, Header, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from gtm.clock import Clock
from gtm.contracts.sims import CRM_OBJECTS, CrmCreate, CrmObject, CrmSearch
from gtm.contracts.world import World
from .faults import FaultStore, gate


class CrmState:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, CrmObject]] = {t: {} for t in CRM_OBJECTS}
        self.idem: dict[tuple[str, str], str] = {}
        self.next_id = 1000

    def summary(self) -> dict:
        return {t: len(v) for t, v in self.objects.items()}


def make_crm_app(world: World, clock: Clock, faults: FaultStore, state: CrmState | None = None) -> FastAPI:
    st = state or CrmState()
    app = FastAPI(title="sim crm")
    app.state.crm = st
    base = "/crm/v3/objects/{otype}"

    def check(otype: str) -> None:
        if otype not in CRM_OBJECTS:
            raise HTTPException(404, {"message": f"unknown object type {otype}"})

    def view(o: CrmObject, partial: bool) -> dict:
        d = o.model_dump(mode="json")
        if partial:
            d["properties"] = {k: v for i, (k, v) in enumerate(sorted(d["properties"].items())) if i % 2 == 0}
        return d

    @app.post(base)
    def create(otype: str, body: CrmCreate, response: Response, idempotency_key: str | None = Header(default=None)):
        check(otype)
        gate(faults, "crm", response, [f"/{otype}", str(body.properties.get("email", "")), str(body.properties.get("domain", ""))])
        if idempotency_key and (otype, idempotency_key) in st.idem:
            response.status_code = 200
            return st.objects[otype][st.idem[(otype, idempotency_key)]].model_dump(mode="json")
        if otype == "contacts" and body.properties.get("email"):
            email = str(body.properties["email"]).lower()
            for o in st.objects["contacts"].values():
                if str(o.properties.get("email", "")).lower() == email:
                    return JSONResponse({"message": f"Contact already exists. Existing ID: {o.id}", "existingId": o.id}, status_code=409)
        st.next_id += 1
        now = clock.now()
        obj = CrmObject(id=str(st.next_id), properties=dict(body.properties), createdAt=now, updatedAt=now)
        st.objects[otype][obj.id] = obj
        if idempotency_key:
            st.idem[(otype, idempotency_key)] = obj.id
        response.status_code = 201
        return obj.model_dump(mode="json")

    @app.post(base + "/search")
    def search(otype: str, body: CrmSearch, response: Response):
        check(otype)
        o = gate(faults, "crm", response, [f"/{otype}/search", *[str(f.value) for f in body.filters]])
        hits = [x for x in st.objects[otype].values()
                if all(str(x.properties.get(f.propertyName, "")).lower() == str(f.value).lower() for f in body.filters)]
        return {"total": len(hits), "results": [view(x, o.partial) for x in hits[: body.limit]]}

    @app.get(base + "/{oid}")
    def get(otype: str, oid: str, response: Response):
        check(otype)
        o = gate(faults, "crm", response, [f"/{otype}/{oid}"])
        obj = st.objects[otype].get(oid)
        if obj is None:
            raise HTTPException(404, {"message": "not found"})
        return view(obj, o.partial)

    @app.patch(base + "/{oid}")
    def patch(otype: str, oid: str, body: dict, response: Response):
        check(otype)
        gate(faults, "crm", response, [f"/{otype}/{oid}", str(body.get("properties", {}).get("email", ""))])
        obj = st.objects[otype].get(oid)
        if obj is None:
            raise HTTPException(404, {"message": "not found"})
        obj.properties.update(body.get("properties", {}))
        obj.updatedAt = clock.now()
        return obj.model_dump(mode="json")

    return app
