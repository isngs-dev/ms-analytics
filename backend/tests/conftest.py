import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
import app.models  # noqa: F401
from app.seed.mapping import seed_mappings

TEST_DB = "ms_analytics_test"


@pytest.fixture(scope="session")
def engine():
    """A separate database so tests never touch real data."""
    base = sa.engine.make_url(os.environ.get("DATABASE_URL", settings.database_url))
    admin = sa.create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(sa.text("select 1 from pg_database where datname=:n"), {"n": TEST_DB}).scalar()
        if not exists:
            c.execute(sa.text(f'create database "{TEST_DB}"'))
    admin.dispose()
    eng = sa.create_engine(base.set(database=TEST_DB))
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_mappings(s)
        s.commit()
        yield s
