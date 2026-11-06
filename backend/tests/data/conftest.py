import pytest
from gtm.clock import SimClock
from gtm.sims import build_sims
from gtm.world import generate_world

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def world():
    return generate_world(42)


@pytest.fixture()
def sims(world, clock):
    return build_sims(world, clock)


@pytest.fixture()
def providers(sims):
    return sims.clients().providers


def seed_accounts(conn, clock, world, *, with_domain=True, aliases=True, only=None):
    """Insert internal accounts mirroring the world's companies. Returns {world_id: account_id}."""
    now, ids = clock.now(), {}
    for co in world.companies:
        if only and co.id not in only:
            continue
        ids[co.id] = conn.execute("INSERT INTO gtm.account(name, primary_domain, data_origin, created_at, updated_at) VALUES (%s,%s,'GT',%s,%s) RETURNING id",
                                  (co.name, co.domain if with_domain else None, now, now)).fetchone()["id"]
        if with_domain:
            for d in [co.domain, *(co.alias_domains if aliases else [])]:
                conn.execute("INSERT INTO gtm.account_domain(account_id, domain, is_primary) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (ids[co.id], d, d == co.domain))
    conn.commit()
    return ids
