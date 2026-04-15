from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import load_config


def require_database_url(database_url: str | None) -> str:
    if database_url:
        return database_url
    raise RuntimeError("缺少 LTW_DATABASE_URL，无法连接 MySQL。")


@lru_cache(maxsize=None)
def get_engine(database_url: str) -> Engine:
    url = require_database_url(database_url)
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=None)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    resolved_database_url = require_database_url(database_url or load_config().database_url)
    return get_session_factory(resolved_database_url)


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
