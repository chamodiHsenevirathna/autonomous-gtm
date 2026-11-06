"""Data layer: waterfall enrichment, survivorship, entity resolution, soft merge. See README.md."""
from .waterfall import EnrichmentResult, enrich_entity, fetch_provider, record_first_party
from .survivorship import get_resolved, record_observation, resolve_fields
from .entity_resolution import (MatchDecision, attach_parent, attach_parent_from_resolved, ensure_account, ensure_contact, propose_match,
                                resolve_account, resolve_contact, scan_duplicates)
from .merge import (MatchConfirmationExecutor, MergeError, MergeExecutor, propose_merge, record_match_rejection, soft_merge, undo_merge)

__all__ = [n for n in dir() if not n.startswith("_")]
