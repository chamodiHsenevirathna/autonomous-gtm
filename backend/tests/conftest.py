import os, pytest
from gtm import config, db, seed
from gtm.clock import SimClock


@pytest.fixture(scope="session")
def test_url():
    url = config.get_settings().test_database_url
    try:
        db.ensure_database(url)
        db.migrate(url)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"PostgreSQL test database unavailable ({e}); run scripts/db_up.sh")
    return url


@pytest.fixture()
def conn(test_url):
    c = db.connect(test_url)
    db.truncate_all(c)
    seed.seed_reference(c)
    yield c
    c.rollback()
    c.close()


@pytest.fixture()
def clock():
    return SimClock()
