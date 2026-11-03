import os

import pytest

# Test-only values, never load a developer's real credentials.
os.environ.update(
    {
        "APP_ENV": "local",
        "DATABASE_URL": "mysql+pymysql://pickup_app:pickup_local@127.0.0.1:3306/pickup_test?charset=utf8mb4",
        "DATABASE_SSL": "false",
        "JWT_SECRET": "j" * 64,
        "QR_SECRET": "q" * 64,
        "BFF_SHARED_SECRET": "b" * 64,
        "JOB_SECRET": "o" * 64,
        "STRIPE_SECRET_KEY": "sk_test_fixture",
        "STRIPE_WEBHOOK_SECRET": "whsec_fixture",
        "FRONTEND_BASE_URL": "http://localhost:3000",
        "MAIL_MODE": "simulate",
    }
)


# Even app.main's module-level app must not read private developer files.
from app.config import Settings  # noqa: E402

Settings.model_config = {**Settings.model_config, "env_file": None}


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings(_env_file=None)


def pytest_addoption(parser):
    parser.addoption("--mysql-url", default=None, help="Local pickup_test URL for MySQL 8.4 tests")


@pytest.fixture(scope="session")
def mysql_engine(request):
    from pathlib import Path

    from alembic.config import Config
    from pydantic import SecretStr
    from sqlalchemy.engine import make_url

    from alembic import command
    from app.config import Settings
    from app.db import create_db_engine

    raw = request.config.getoption("--mysql-url") or os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("専用MySQL 8.4のpickup_testを指定すると実DB試験を実行できます")
    url = make_url(raw)
    if (
        url.drivername != "mysql+pymysql"
        or url.database != "pickup_test"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        pytest.fail("自動試験はローカル／CIのpickup_testだけで実行できます")
    settings = Settings(_env_file=None, database_url=SecretStr(raw), database_ssl=False)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.attributes["settings"] = settings
    engine = create_db_engine(settings)
    from sqlalchemy import MetaData, Table, inspect, text

    from app.db import Base

    with engine.connect() as connection:
        assert connection.execute(text("SELECT VERSION()")).scalar_one().startswith("8.4.")
    # An exclusive test DB starts empty; no URL outside loopback/pickup_test reaches here.
    Base.metadata.drop_all(engine)
    if "alembic_version" in inspect(engine).get_table_names():
        Table("alembic_version", MetaData(), autoload_with=engine).drop(engine)
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def clean_mysql(mysql_engine):
    from sqlalchemy import delete, update

    from app.db import Base
    from app.models import RefreshToken

    def clear():
        with mysql_engine.begin() as connection:
            connection.execute(update(RefreshToken).values(replaced_by_id=None))
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

    clear()
    yield mysql_engine
    clear()
