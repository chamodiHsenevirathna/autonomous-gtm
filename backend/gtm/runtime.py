"""The assembled system (world + simulators + adapters + LLM + runner + workflows) over one DB connection.
Used by the evaluation harness (gtm.harness) and by the dashboard API (gtm.api)."""
from __future__ import annotations
import dataclasses, importlib
from . import db, seed
from .clock import SimClock
from .config import Settings, get_settings
from .contracts.world import World
from .orchestration import Runner

GRAPH_MODULES = ("gtm.agents", "gtm.pipeline", "gtm.feedback")


def load_graphs() -> list:
    graphs = []
    for mod in GRAPH_MODULES:
        try:
            m = importlib.import_module(mod)
        except ModuleNotFoundError:
            continue
        if hasattr(m, "build_graphs"):
            graphs += m.build_graphs()
    return graphs


class Runtime:
    def __init__(self, database_url: str, *, seed_value: int = 42, llm_mode: str = "mock", settings: Settings | None = None,
                 world_overrides: dict | None = None, reset: bool = True):
        self.database_url = database_url
        db.ensure_database(database_url)
        db.migrate(database_url)
        self.conn = db.connect(database_url)
        self.base_settings = settings or get_settings()
        self.build(seed_value, llm_mode, world_overrides, reset)

    def build(self, seed_value: int = 42, llm_mode: str = "mock", world_overrides: dict | None = None, reset: bool = True) -> None:
        from .services import build_services
        from .world import generate_world
        if reset:
            self.conn.rollback()
            db.truncate_all(self.conn)
            seed.seed_reference(self.conn)
        self.settings = dataclasses.replace(self.base_settings, llm_mode=llm_mode, world_seed=seed_value)
        self.clock = SimClock()
        params = (world_overrides or {}).get("world_params")
        self.world: World = generate_world(seed_value, params)
        self.services, self.sims = build_services(self.settings, self.clock, self.world, self.conn)
        lifecycle = None
        try:
            lifecycle = importlib.import_module('gtm.agents.account').lifecycle_filter
        except Exception:
            pass
        self.runner = Runner(self.conn, self.clock, self.services, lifecycle=lifecycle)
        for g in load_graphs():
            self.runner.register(g)
        from .orchestration import add_schedule
        add_schedule(self.conn, self.clock, 'pipeline.scan', 'global', 86400, first_at=self.clock.now() + __import__('datetime').timedelta(days=1))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
