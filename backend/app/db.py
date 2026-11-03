import ssl
from collections.abc import Iterator

import certifi
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


def create_db_engine(settings: Settings) -> Engine:
    connect_args = {
        "connect_timeout": 5,
        "read_timeout": 15,
        "write_timeout": 15,
        "charset": "utf8mb4",
        "init_command": "SET time_zone = '+00:00'",
    }
    if settings.database_ssl:
        context = ssl.create_default_context(cafile=certifi.where())
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connect_args["ssl"] = context
    else:
        connect_args["ssl_disabled"] = True
    return create_engine(
        settings.connection_url(),
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        connect_args=connect_args,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    # Closing rolls back unfinished transactions; services explicitly commit successful changes.
    with request.app.state.session_factory() as session:
        yield session
