from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from er_triage.config import get_settings
from er_triage.models import Base


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Recorded model responses are demo replay assets; keep them across resets.
PRESERVED_TABLES = {"llm_responses"}


def init_db(drop: bool = False, drop_cache: bool = False) -> None:
    engine = get_engine()
    if drop:
        tables = [t for t in Base.metadata.sorted_tables
                  if drop_cache or t.name not in PRESERVED_TABLES]
        Base.metadata.drop_all(engine, tables=tables)
    Base.metadata.create_all(engine)


def ping() -> bool:
    with get_engine().connect() as conn:
        return conn.execute(text("select 1")).scalar() == 1
