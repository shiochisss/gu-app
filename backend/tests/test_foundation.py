import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import Query
from fastapi.testclient import TestClient
from pydantic import Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.clock import FakeClock, SystemClock
from app.config import Settings
from app.db import create_session_factory, get_db
from app.logging import JsonFormatter
from app.main import create_app
from app.schemas.common import ApiModel


@pytest.mark.parametrize("env", ["azure-test", "production"])
@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
def test_it_sec_09_api_docs_hidden(settings, env, path):
    app = create_app(settings.model_copy(update={"app_env": env}))
    with TestClient(app) as client:
        result = client.get(path)
    assert result.status_code == 404
    assert result.json()["code"] == "NOT_FOUND"
    assert result.json()["traceId"] == result.headers["X-Request-Id"]


def test_local_docs_and_openapi(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_healthz_real_postgres(settings):
    import os

    url_text = os.getenv("TEST_DATABASE_URL")
    if not url_text:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration")
    url = make_url(url_text)
    # Reject unsafe targets before opening a connection. No app DB reset is performed.
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "pickup_test", "専用のpickup_testデータベースだけ使用できます"
    test_settings = settings.model_copy(
        update={"database_url": settings.database_url.__class__(url_text)}
    )
    app = create_app(test_settings)
    assert app.state.engine.dialect.name == "postgresql"
    assert not app.state.engine.dialect.is_async
    with TestClient(app) as client:
        with app.state.engine.connect() as conn:
            assert conn.execute(select(1)).scalar_one() == 1
            version = int(conn.execute(text("SHOW server_version_num")).scalar_one())
            assert 170000 <= version < 180000
        result = client.get("/healthz")
        assert result.status_code == 200
        assert result.json() == {"status": "ok"}
        UUID(result.headers["X-Request-Id"])
        # A failed transaction must not poison the next session.
        factory = create_session_factory(app.state.engine)
        with factory() as session:
            session.execute(select(1))
            assert session.in_transaction()
        with factory() as session:
            assert session.execute(select(1)).scalar_one() == 1


def test_health_failure_is_safe_and_logged(settings):
    secret = "sensitive@example.com sk_test_DO_NOT_LOG token=private"
    app = create_app(settings)

    def failed_db():
        raise OperationalError(secret, {}, Exception(secret))
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = failed_db
    stream = io.StringIO()
    logger = logging.getLogger("pickup")
    logger.handlers[0].setStream(stream)
    with TestClient(app) as client:
        result = client.get("/healthz?token=private", headers={"Authorization": secret})
    assert result.status_code == 500
    assert result.json()["code"] == "INTERNAL_ERROR"
    assert result.json()["traceId"] == result.headers["X-Request-Id"]
    assert secret not in result.text
    output = stream.getvalue()
    assert secret not in output
    assert "token=private" not in output
    entry = json.loads(output)
    assert entry["path"] == "/healthz"
    assert entry["status"] == 500
    assert entry["stackTrace"]
    assert entry["exceptionType"] == "OperationalError"
    assert all(
        k in entry
        for k in [
            "timestamp",
            "level",
            "requestId",
            "path",
            "status",
            "durationMs",
            "message",
        ]
    )


def test_request_id_and_no_cors(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        trace_id = str(uuid4())
        result = client.get(
            "/unknown", headers={"X-Request-Id": trace_id, "Origin": "https://evil.example"}
        )
        assert result.headers["X-Request-Id"] == trace_id
        assert "access-control-allow-origin" not in result.headers
        assert result.json() == {
            "code": "NOT_FOUND",
            "message": "対象が見つかりません。",
            "details": None,
            "fieldErrors": [],
            "traceId": trace_id,
            "latestResource": None,
        }
        result = client.get("/unknown", headers={"X-Request-Id": "sensitive@example.com"})
        UUID(result.headers["X-Request-Id"])
        assert result.headers["X-Request-Id"] != "sensitive@example.com"


def test_validation_errors_use_safe_common_format(settings):
    class Item(ApiModel):
        product_name: str = Field(max_length=3)
        quantity: int = Field(ge=1, le=10)
        kind: Literal["A"]

    class Body(ApiModel):
        items: list[Item]

    app = create_app(settings)

    # Test-only routes are never part of the application or generated API definitions.
    @app.post("/test-validation")
    def validate(body: Body):
        return body

    @app.get("/test-query")
    def query(page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)]):
        return page_size

    with TestClient(app) as client:
        response = client.post(
            "/test-validation",
            json={
                "items": [
                    {
                        "productName": "private@example.com",
                        "quantity": 0,
                        "kind": "private",
                    }
                ]
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["message"] == "入力内容を確認してください。"
        errors = {e["field"]: e["code"] for e in body["fieldErrors"]}
        assert errors == {
            "items[0].productName": "TOO_LONG",
            "items[0].quantity": "OUT_OF_RANGE",
            "items[0].kind": "INVALID_VALUE",
        }
        assert "private" not in response.text
        assert (
            client.post("/test-validation", json={}).json()["fieldErrors"][0]["code"] == "REQUIRED"
        )
        assert client.post("/test-validation", content="{").status_code == 400
        assert (
            client.get("/test-query?pageSize=101").json()["fieldErrors"][0]["code"]
            == "OUT_OF_RANGE"
        )
        assert (
            client.get("/test-query?pageSize=abc").json()["fieldErrors"][0]["code"]
            == "INVALID_FORMAT"
        )


def test_clock_is_utc_and_can_cross_japan_midnight():
    clock = FakeClock(datetime(2026, 11, 1, 23, 59, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert clock.now().tzinfo == UTC
    clock.advance(timedelta(minutes=2))
    assert clock.now().astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat() == "2026-11-02"
    assert SystemClock().now().tzinfo == UTC
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 11, 1))


def test_logging_uses_injected_clock_and_hides_unknown_paths(settings):
    clock = FakeClock(datetime(2026, 11, 1, tzinfo=UTC))
    app = create_app(settings, clock)
    stream = io.StringIO()
    logging.getLogger("pickup").handlers[0].setStream(stream)
    with TestClient(app) as client:
        client.get("/private@example.com?qr=123456")
    entry = json.loads(stream.getvalue())
    assert entry["timestamp"] == clock.now().isoformat()
    assert entry["path"] == "<unmatched>"
    assert "private" not in stream.getvalue()
    assert "123456" not in stream.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("stripe_secret_key", "sk_live_secret"),
        ("stripe_secret_key", "invalid"),
        ("jwt_secret", "short"),
        ("qr_secret", "j" * 64),
        ("database_url", "sqlite:///bad.db"),
        ("database_url", "not-a-url"),
        ("database_url", "postgresql+asyncpg://user:pw@localhost/pickup"),
        ("mail_mode", "smtp"),
    ],
)
def test_unsafe_configuration_rejected(settings, field, value):
    data = settings.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **data)


def test_secrets_masked(settings):
    assert settings.jwt_secret.get_secret_value() not in repr(settings)
    assert "pickup_local" not in repr(settings)


def test_json_formatter_is_one_line():
    record = logging.LogRecord("pickup", logging.INFO, "", 0, "request completed", (), None)
    result = JsonFormatter().format(record)
    assert "\n" not in result
    assert json.loads(result)["message"] == "request completed"
