from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    # Created lazily so importing the models (e.g. for migrations or DDL checks) never
    # requires a working database driver.
    return create_engine(settings.database_url, pool_pre_ping=True)


def SessionLocal() -> Session:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
