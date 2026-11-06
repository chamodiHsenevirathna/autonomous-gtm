import dataclasses
import pytest
from gtm import config
from gtm.agents import build_graphs
from gtm.agents.account import lifecycle_filter
from gtm.orchestration import Runner
from gtm.services import build_services
from gtm.world import generate_world


class System:
    def __init__(self, conn, clock):
        self.conn, self.clock = conn, clock
        self.settings = dataclasses.replace(config.get_settings(), llm_mode="mock")
        self.world = generate_world(42)
        self.services, self.sims = build_services(self.settings, clock, self.world, conn)
        self.runner = Runner(conn, clock, self.services, lifecycle=lifecycle_filter)
        for g in build_graphs():
            self.runner.register(g)

    def enquiry(self, eid):
        from gtm.agents.intake import submit_enquiry
        e = next(x for x in self.world.enquiries if x.id == eid)
        lid = submit_enquiry(self.conn, self.clock, e)
        self.conn.commit()
        return lid

    def run(self, **kw):
        return self.runner.run_until_idle(**kw)

    def q(self, sql, *a):
        return self.conn.execute(sql, a).fetchall()


@pytest.fixture()
def system(conn, clock):
    return System(conn, clock)
