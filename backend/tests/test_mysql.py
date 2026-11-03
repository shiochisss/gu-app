import ssl
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql

from app.config import Settings
from app.db import create_db_engine
from app.models.types import UTCDateTime


def build_settings(settings, **overrides):
    values = settings.model_dump()
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_separate_credentials_preserve_url_special_characters(settings):
    password = "test@:/#?%'+日本語"
    value = build_settings(
        settings,
        database_url=None,
        database_host="example.mysql.database.azure.com",
        database_name="gu_app_shiochi",
        database_user="test_user",
        database_password=password,
        database_ssl=True,
    )
    url = value.connection_url()
    assert url.drivername == "mysql+pymysql"
    assert url.username == "test_user"
    assert url.password == password
    assert url.database == "gu_app_shiochi"
    assert url.query["charset"] == "utf8mb4"
    assert password not in repr(value)
    assert password not in str(url)


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": None, "database_host": None, "database_user": None},
        {"database_url": "postgresql+psycopg://test:pw@localhost/pickup"},
        {"database_url": "mysql+pymysql://test:pw@localhost/pickup?ssl_disabled=true"},
        {"database_url": "mysql+pymysql://test:pw@localhost/pickup?charset=latin1"},
        {"database_port": 0},
        {"database_port": 65536},
        {"database_url": "mysql+pymysql://test:pw@remote.example/pickup", "database_ssl": False},
    ],
)
def test_unsafe_mysql_settings_rejected(settings, changes):
    with pytest.raises(ValidationError):
        build_settings(settings, **changes)


def test_remote_connection_verifies_tls_and_uses_utc(monkeypatch, settings):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        return "engine"

    monkeypatch.setattr("app.db.create_engine", fake_create_engine)
    config = build_settings(
        settings,
        database_url="mysql+pymysql://test:pw@remote.example/pickup",
        database_ssl=True,
    )
    assert create_db_engine(config) == "engine"
    args = captured["connect_args"]
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert context.cert_store_stats()["x509_ca"] > 0
    assert args["init_command"] == "SET time_zone = '+00:00'"
    assert args["charset"] == "utf8mb4"
    assert captured["isolation_level"] == "READ COMMITTED"
    assert captured["hide_parameters"] is True


def test_mysql_datetime_round_trip_preserves_utc_microseconds():
    value = datetime(2026, 11, 1, 23, 59, 58, 123456, tzinfo=timezone(timedelta(hours=9)))
    column = UTCDateTime()
    stored = column.process_bind_param(value, mysql.dialect())
    assert stored == datetime(2026, 11, 1, 14, 59, 58, 123456)
    assert stored.tzinfo is None
    assert column.process_result_value(stored, mysql.dialect()) == value.astimezone(UTC)
    assert str(column.compile(dialect=mysql.dialect())) == "DATETIME(6)"
    assert column.process_bind_param(None, mysql.dialect()) is None
    assert column.process_result_value(None, mysql.dialect()) is None
    with pytest.raises(ValueError):
        column.process_bind_param(datetime(2026, 11, 1), mysql.dialect())
