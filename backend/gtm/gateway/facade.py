"""Binds the Gateway's ExecutionFacade protocol to the simulated CRM/outreach adapters (gtm.adapters)."""
from __future__ import annotations


class SimFacade:
    def __init__(self, adapters):
        self.a = adapters

    def crm_find_company(self, domain: str):
        hits = self.a.crm.search("companies", {"domain": domain}, limit=1)
        return hits[0].id if hits else None

    def crm_find_contact(self, email: str):
        hits = self.a.crm.search("contacts", {"email": email}, limit=1)
        return hits[0].id if hits else None

    def crm_create(self, obj: str, properties: dict, *, token, idempotency_key: str) -> str:
        return self.a.crm.create(obj, properties, token=token, idempotency_key=idempotency_key, payload_hash=token.payload_hash).id

    def crm_update(self, obj: str, obj_id: str, properties: dict, *, token, idempotency_key: str) -> None:
        self.a.crm.update(obj, obj_id, properties, token=token, idempotency_key=idempotency_key, payload_hash=token.payload_hash)

    def outreach_import(self, crm_contact_id, email, full_name, *, token, idempotency_key) -> dict:
        return self.a.outreach.import_contact(crm_contact_id, email, full_name, token=token, idempotency_key=idempotency_key, payload_hash=token.payload_hash)

    def outreach_lookup(self, *, external_key=None, email=None):
        return self.a.outreach.lookup(external_key=external_key, email=email)

    def outreach_send(self, outreach_contact_id, from_address, to_address, subject, body, *, token, idempotency_key) -> dict:
        return self.a.outreach.send(outreach_contact_id, from_address, to_address, subject, body, token=token, idempotency_key=idempotency_key, payload_hash=token.payload_hash)
