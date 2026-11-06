"""Configuration. Environment only; no secrets in files. Live model calls are OFF by default."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

DEFAULT_DB = "postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm"
DEFAULT_TEST_DB = "postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm_test"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("GTM_DATABASE_URL", DEFAULT_DB))
    test_database_url: str = field(default_factory=lambda: os.environ.get("GTM_TEST_DATABASE_URL", DEFAULT_TEST_DB))
    llm_mode: str = field(default_factory=lambda: os.environ.get("GTM_LLM_MODE", "mock"))  # replay|mock|live
    allow_live: bool = field(default_factory=lambda: os.environ.get("GTM_ALLOW_LIVE", "0") == "1")
    live_budget_usd: float = field(default_factory=lambda: float(os.environ.get("GTM_LIVE_BUDGET_USD", "0")))
    # Company/world parameters (assumptions; see docs/business-context.md). Config, not findings.
    world_seed: int = field(default_factory=lambda: int(os.environ.get("GTM_WORLD_SEED", "42")))
    # BUSINESS-POLICY threshold (owner decision 2026-11-07), NOT a statistically validated value. Evidence below it (or with no confidence) cannot by itself
    # hold or disqualify a lead; it is flagged for human verification instead. Change with GTM_HARD_CONSTRAINT_MIN_CONFIDENCE (0..1).
    hard_constraint_min_confidence: float = field(default_factory=lambda: float(os.environ.get("GTM_HARD_CONSTRAINT_MIN_CONFIDENCE", "0.6")))
    approval_ttl_hours: int = 72
    sequence_step_grace_minutes: int = 30
    execution_token_ttl_minutes: int = 15
    sync_wait_deadline_minutes: int = 30

    def live_enabled(self) -> bool:
        """Live model calls need explicit opt-in AND a positive budget AND mode=live. Default: False."""
        return self.llm_mode == "live" and self.allow_live and self.live_budget_usd > 0


def get_settings() -> Settings:
    return Settings()
