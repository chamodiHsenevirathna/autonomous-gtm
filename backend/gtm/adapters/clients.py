"""Typed clients for the simulated external systems. Read methods take no token; writes need an ExecutionToken."""
from __future__ import annotations
from dataclasses import dataclass, field
import httpx
from gtm.contracts.gateway import ExecutionToken, TokenVerifier
from gtm.contracts.sims import (CrmObject, ProviderCompanyRequest, ProviderPersonRequest, ProviderResponse, SimEvent)
from .base import idem_headers, request, require_token


class ProviderClient:
    def __init__(self, name: str, http: httpx.Client):
        self.name, self.http = name, http

    def company(self, *, domain: str | None = None, name: str | None = None, fields: list[str]) -> ProviderResponse:
        body = ProviderCompanyRequest(domain=domain, name=name, fields=fields).model_dump()
        return ProviderResponse.model_validate(request(self.http, "POST", "/company", f"{self.name}.company", json=body).json())

    def person(self, *, email: str, fields: list[str]) -> ProviderResponse:
        body = ProviderPersonRequest(email=email, fields=fields).model_dump()
        return ProviderResponse.model_validate(request(self.http, "POST", "/person", f"{self.name}.person", json=body).json())


class CrmClient:
    def __init__(self, http: httpx.Client, verifier: TokenVerifier):
        self.http, self.verifier = http, verifier

    def create(self, object_type: str, properties: dict, *, token: ExecutionToken, idempotency_key: str,
               associations: list[dict] | None = None, payload_hash: str | None = None) -> CrmObject:
        require_token(self.verifier, token, "crm.write", payload_hash)
        r = request(self.http, "POST", f"/crm/v3/objects/{object_type}", "crm.create", headers=idem_headers(idempotency_key),
                    json={"properties": properties, "associations": associations or []})
        return CrmObject.model_validate(r.json())

    def update(self, object_type: str, object_id: str, properties: dict, *, token: ExecutionToken, idempotency_key: str,
               payload_hash: str | None = None) -> CrmObject:
        require_token(self.verifier, token, "crm.write", payload_hash)
        r = request(self.http, "PATCH", f"/crm/v3/objects/{object_type}/{object_id}", "crm.update",
                    headers=idem_headers(idempotency_key), json={"properties": properties})
        return CrmObject.model_validate(r.json())

    def get(self, object_type: str, object_id: str) -> CrmObject:
        return CrmObject.model_validate(request(self.http, "GET", f"/crm/v3/objects/{object_type}/{object_id}", "crm.get").json())

    def search(self, object_type: str, filters: dict, limit: int = 10) -> list[CrmObject]:
        body = {"filters": [{"propertyName": k, "operator": "EQ", "value": v} for k, v in filters.items()], "limit": limit}
        r = request(self.http, "POST", f"/crm/v3/objects/{object_type}/search", "crm.search", json=body)
        return [CrmObject.model_validate(x) for x in r.json()["results"]]


class OutreachClient:
    def __init__(self, http: httpx.Client, verifier: TokenVerifier):
        self.http, self.verifier = http, verifier

    def import_contact(self, crm_contact_id: str, email: str, full_name: str | None = None, *, token: ExecutionToken,
                       idempotency_key: str, payload_hash: str | None = None) -> dict:
        require_token(self.verifier, token, "outreach.import", payload_hash)
        return request(self.http, "POST", "/contacts/import", "outreach.import", headers=idem_headers(idempotency_key),
                       json={"crm_contact_id": crm_contact_id, "email": email, "full_name": full_name}).json()

    def lookup(self, *, external_key: str | None = None, email: str | None = None) -> dict | None:
        """First visible contact or None (not visible yet)."""
        params = {k: v for k, v in (("external_key", external_key), ("email", email)) if v is not None}
        hits = request(self.http, "GET", "/contacts", "outreach.lookup", params=params).json()["contacts"]
        return hits[0] if hits else None

    def send(self, contact_id: str, from_address: str, to_address: str, subject: str, body: str, *, token: ExecutionToken,
             idempotency_key: str, payload_hash: str | None = None) -> dict:
        """HTTP 422 (contact not yet visible) is mapped to NotReady so the orchestrator parks instead of failing."""
        from gtm.contracts.errors import NotReady, PermanentError
        require_token(self.verifier, token, "outreach.send", payload_hash)
        try:
            return request(self.http, "POST", "/messages", "outreach.send", headers=idem_headers(idempotency_key),
                           json={"contact_id": contact_id, "from_address": from_address, "to_address": to_address,
                                 "subject": subject, "body": body}).json()
        except PermanentError as e:
            if e.detail.get("status") == 422:
                raise NotReady("outreach.send: contact not yet visible in the outreach tool", retry_after=5.0, detail=e.detail) from e
            raise

    def events(self, since: int = 0) -> list[SimEvent]:
        r = request(self.http, "GET", "/events", "outreach.events", params={"since": since}).json()
        return [SimEvent.model_validate(e) for e in r["events"]]


class WebClient:
    def __init__(self, http: httpx.Client):
        self.http = http

    def search(self, q: str) -> list[dict]:
        return request(self.http, "GET", "/search", "web.search", params={"q": q}).json()["results"]

    def page(self, url: str) -> dict:
        return request(self.http, "GET", "/page", "web.page", params={"url": url}).json()


@dataclass
class AdapterSet:
    providers: dict[str, ProviderClient]
    crm: CrmClient
    outreach: OutreachClient
    web: WebClient
