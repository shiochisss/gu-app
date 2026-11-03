from collections import Counter
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from argon2 import PasswordHasher
from sqlalchemy import event, func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from app.cli import main
from app.clock import FakeClock
from app.db import Base
from app.models import Inventory, NumberCounter, Product, Store, User
from app.services.seed import (
    SeedError,
    build_seed_rows,
    reset_demo,
    seed_database,
    seed_id,
    seed_preview,
)

CLOCK = FakeClock(datetime(2026, 11, 1, 12, tzinfo=UTC))
# This fixture password is test-only, never the password used for Azure demo accounts.
TEST_PASSWORD = "Test-only-seed-password-42!"
EXPECTED = {
    "stores": 2,
    "users": 4,
    "staff_profiles": 2,
    "products": 6,
    "product_variants": 24,
    "inventories": 48,
    "inventory_transactions": 41,
    "number_counters": 2,
}


def counts(engine):
    with engine.connect() as conn:
        return {
            name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in Base.metadata.tables.items()
        }


def test_small_preview_is_deterministic_and_has_all_categories():
    first = build_seed_rows(CLOCK)
    assert first == build_seed_rows(CLOCK)
    assert {k: len(v) for k, v in first.items()} == EXPECTED
    assert len({row["category"] for row in first["products"]}) == 6
    assert {row["size"] for row in first["product_variants"]} == {"M", "L"}
    for table, rows in first.items():
        pk = next(iter(Base.metadata.tables[table].primary_key)).name
        assert len({row[pk] for row in rows}) == len(rows)
    stock = Counter(row["on_hand_quantity"] for row in first["inventories"])
    assert stock[0] == 7 and stock[1] == 6
    preview = seed_preview(CLOCK)
    assert preview["totalRows"] == 129
    assert preview["totalStockUnits"] == 132
    assert all("password" not in key for row in first["users"] for key in row)


def test_cli_preview_has_no_connection_or_settings_dependency(monkeypatch, capsys):
    def forbidden():
        raise AssertionError("dry-run must not load secrets or connect")

    monkeypatch.setattr("app.cli.get_settings", forbidden)
    assert main(["seed", "--dry-run"]) == 0
    assert '"totalRows": 129' in capsys.readouterr().out


def test_cli_rejects_missing_confirmation_before_connect(settings, monkeypatch, capsys):
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)
    monkeypatch.setattr("app.cli.create_db_engine", lambda _: pytest.fail("must not connect"))
    assert main(["seed"]) == 1
    assert "--confirm-database" in capsys.readouterr().err


def test_reset_is_rejected_in_production_before_connect():
    with pytest.raises(SeedError, match="production"):
        reset_demo(None, CLOCK, TEST_PASSWORD, "production")


def test_remote_migration_requires_confirmation_before_connect(settings, monkeypatch):
    from pathlib import Path

    from pydantic import SecretStr

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["settings"] = settings.model_copy(
        update={
            "database_url": SecretStr("mysql+pymysql://test:pw@remote.example/guard_test"),
            "database_ssl": True,
        }
    )
    monkeypatch.setattr("app.db.create_db_engine", lambda _: pytest.fail("must not connect"))
    with pytest.raises(RuntimeError, match="confirm_database"):
        command.upgrade(config, "head")


def test_migration_schema_matches_models_and_has_no_seed(mysql_engine):
    inspector = inspect(mysql_engine)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    assert len(Base.metadata.tables) == 25
    with mysql_engine.connect() as connection:
        assert connection.execute(text("SELECT VERSION()")).scalar_one().startswith("8.4.")
        diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diffs == []


def test_seed_counts_hashes_and_stock_history_match(clean_mysql):
    result = seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    assert result["status"] == "inserted"
    actual = counts(clean_mysql)
    assert sum(actual.values()) == 129
    assert {k: actual[k] for k in EXPECTED} == EXPECTED
    assert all(count == 0 for table, count in actual.items() if table not in EXPECTED)
    with clean_mysql.connect() as connection:
        hashes = connection.execute(select(User.password_hash)).scalars().all()
        assert len(set(hashes)) == 4
        assert all(PasswordHasher().verify(value, TEST_PASSWORD) for value in hashes)
        assert all(value != TEST_PASSWORD for value in hashes)
        history = Base.metadata.tables["inventory_transactions"]
        balances = dict(
            connection.execute(
                select(history.c.inventory_id, func.sum(history.c.quantity_delta)).group_by(
                    history.c.inventory_id
                )
            ).all()
        )
        for row in connection.execute(select(Inventory.id, Inventory.on_hand_quantity)):
            assert row.on_hand_quantity == balances.get(row.id, 0)
        assert (
            connection.execute(select(Product.created_at).order_by(Product.created_at))
            .first()[0]
            .tzinfo
            == UTC
        )


def test_repeated_seed_preserves_changed_inventory_passwords_and_counters(clean_mysql):
    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    inventory_id = seed_id("inventory", "SHINJUKU/P001-0-M")
    with clean_mysql.begin() as conn:
        old_hashes = list(conn.execute(select(User.password_hash)).scalars())
        conn.execute(
            update(Inventory).where(Inventory.id == inventory_id).values(on_hand_quantity=9)
        )
        conn.execute(update(NumberCounter).values(next_value=12))
    assert (
        seed_database(clean_mysql, CLOCK, "another-private-test-password")["status"]
        == "already_present"
    )
    assert sum(counts(clean_mysql).values()) == 129
    with clean_mysql.connect() as conn:
        assert list(conn.execute(select(User.password_hash)).scalars()) == old_hashes
        assert (
            conn.execute(
                select(Inventory.on_hand_quantity).where(Inventory.id == inventory_id)
            ).scalar_one()
            == 9
        )
        assert set(conn.execute(select(NumberCounter.next_value)).scalars()) == {12}


def test_seed_failure_rolls_back_all_inserted_rows_and_releases_lock(clean_mysql):
    def fail(connection, cursor, statement, params, context, executemany):
        if statement.startswith("INSERT INTO products"):
            raise RuntimeError("test-only injected failure")

    event.listen(clean_mysql, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    finally:
        event.remove(clean_mysql, "before_cursor_execute", fail)
    assert sum(counts(clean_mysql).values()) == 0
    assert seed_database(clean_mysql, CLOCK, TEST_PASSWORD)["status"] == "inserted"


def test_partial_seed_is_reported_without_overwrite(clean_mysql):
    store = build_seed_rows(CLOCK)["stores"][0]
    with clean_mysql.begin() as connection:
        connection.execute(insert(Store).values(**store))
    with pytest.raises(SeedError, match="一部だけ"):
        seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    assert sum(counts(clean_mysql).values()) == 1


def test_reset_demo_restores_seed_and_counters(clean_mysql):
    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    with clean_mysql.begin() as connection:
        connection.execute(update(NumberCounter).values(next_value=40))
        connection.execute(update(Inventory).values(on_hand_quantity=0))
    assert reset_demo(clean_mysql, CLOCK, TEST_PASSWORD, "local")["status"] == "reset"
    assert sum(counts(clean_mysql).values()) == 129
    with clean_mysql.connect() as connection:
        assert set(connection.execute(select(NumberCounter.next_value)).scalars()) == {1}
        assert connection.execute(select(func.sum(Inventory.on_hand_quantity))).scalar_one() == 132


def test_real_db_rejects_invalid_quantity_enum_weekday_and_foreign_key(clean_mysql):
    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    bad_statements = [
        update(Inventory).values(on_hand_quantity=-1),
        update(User).values(role="ADMIN"),
        update(Store).values(regular_closed_weekdays=[8]),
        update(Store).values(regular_closed_weekdays=[1, 1]),
        update(Inventory).values(store_id="00000000-0000-0000-0000-000000000000"),
    ]
    for statement in bad_statements:
        with pytest.raises(DBAPIError) as rejected, clean_mysql.begin() as connection:
            connection.execute(statement)
        assert rejected.value.orig.args[0] in {3819, 1452}
    # A stock shortage is allowed; it is deliberately not a DB constraint.
    with clean_mysql.begin() as connection:
        connection.execute(update(Inventory).values(on_hand_quantity=0, reserved_quantity=9))


def test_reset_failure_restores_existing_data(clean_mysql):
    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    with clean_mysql.begin() as connection:
        connection.execute(update(NumberCounter).values(next_value=15))
        old_hashes = list(connection.execute(select(User.password_hash)).scalars())

    def fail(connection, cursor, statement, params, context, executemany):
        if statement.startswith("INSERT INTO products"):
            raise RuntimeError("reset failure")

    event.listen(clean_mysql, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="reset failure"):
            reset_demo(clean_mysql, CLOCK, TEST_PASSWORD, "local")
    finally:
        event.remove(clean_mysql, "before_cursor_execute", fail)
    assert sum(counts(clean_mysql).values()) == 129
    with clean_mysql.connect() as connection:
        assert set(connection.execute(select(NumberCounter.next_value)).scalars()) == {15}
        assert list(connection.execute(select(User.password_hash)).scalars()) == old_hashes


def test_seed_refuses_an_existing_initialization_lock(clean_mysql):
    with clean_mysql.connect() as connection:
        lock = connection.execute(
            select(func.concat("pickup:", func.database(), ":seed"))
        ).scalar_one()
        assert connection.execute(select(func.get_lock(lock, 0))).scalar_one() == 1
        try:
            with pytest.raises(SeedError, match="別の初期化"):
                seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
        finally:
            connection.execute(select(func.release_lock(lock)))
    assert sum(counts(clean_mysql).values()) == 0
    assert seed_database(clean_mysql, CLOCK, TEST_PASSWORD)["status"] == "inserted"


def test_reset_clears_self_referencing_refresh_tokens(clean_mysql):
    from app.models import RefreshToken

    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    first, second = seed_id("test", "token-first"), seed_id("test", "token-second")
    with clean_mysql.begin() as connection:
        for number, token_id in enumerate((first, second)):
            connection.execute(
                insert(RefreshToken).values(
                    id=token_id,
                    user_id=seed_id("user", "buyer1@example.com"),
                    token_hash=str(number) * 64,
                    expires_at=CLOCK.now(),
                    created_at=CLOCK.now(),
                )
            )
        connection.execute(
            update(RefreshToken).where(RefreshToken.id == first).values(replaced_by_id=second)
        )
    reset_demo(clean_mysql, CLOCK, TEST_PASSWORD, "local")
    assert counts(clean_mysql)["refresh_tokens"] == 0
    assert sum(counts(clean_mysql).values()) == 129


def test_active_pickup_token_is_unique_but_revoked_tokens_can_coexist(clean_mysql):
    from app.models import Order, OrderEstimate, PickupToken

    seed_database(clean_mysql, CLOCK, TEST_PASSWORD)
    estimate_id, order_id = seed_id("test", "estimate"), seed_id("test", "order")
    store_id = seed_id("store", "SHINJUKU")
    user_id = seed_id("user", "buyer1@example.com")
    now = CLOCK.now()
    with clean_mysql.begin() as connection:
        connection.execute(
            insert(OrderEstimate).values(
                id=estimate_id,
                user_id=user_id,
                store_id=store_id,
                request_hash="a" * 64,
                items=[],
                shortage_policy="CANCEL_ALL",
                total_quantity=1,
                total_amount_yen=990,
                work_minutes=12,
                estimated_ready_at=now,
                created_at=now,
                expires_at=now,
            )
        )
        connection.execute(
            insert(Order).values(
                id=order_id,
                order_number="P000001",
                purchaser_id=user_id,
                store_id=store_id,
                estimate_id=estimate_id,
                shortage_policy="CANCEL_ALL",
                total_quantity=1,
                ordered_amount_yen=990,
                work_minutes=12,
                pickup_terms_agreed_at=now,
                hold_expires_at=now,
                original_ready_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PickupToken).values(
                token_id=seed_id("test", "pickup-first"),
                order_id=order_id,
                issued_at=now,
            )
        )
    with pytest.raises(IntegrityError), clean_mysql.begin() as connection:
        connection.execute(
            insert(PickupToken).values(
                token_id=seed_id("test", "pickup-second"),
                order_id=order_id,
                issued_at=now,
            )
        )
    with clean_mysql.begin() as connection:
        connection.execute(update(PickupToken).values(revoked_at=now, revoked_reason="REISSUED"))
        connection.execute(
            insert(PickupToken).values(
                token_id=seed_id("test", "pickup-second"),
                order_id=order_id,
                issued_at=now,
            )
        )
        connection.execute(
            insert(PickupToken).values(
                token_id=seed_id("test", "pickup-revoked"),
                order_id=order_id,
                issued_at=now,
                revoked_at=now,
                revoked_reason="REISSUED",
            )
        )
        active = (
            connection.execute(
                select(PickupToken.active_order_id).where(PickupToken.active_order_id.is_not(None))
            )
            .scalars()
            .all()
        )
        assert active == [order_id]


def test_migration_downgrade_and_upgrade_again(clean_mysql, settings):
    from pathlib import Path

    from pydantic import SecretStr

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["settings"] = settings.model_copy(
        update={
            "database_url": SecretStr(clean_mysql.url.render_as_string(hide_password=False)),
        }
    )
    command.downgrade(config, "base")
    assert inspect(clean_mysql).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert len(inspect(clean_mysql).get_table_names()) == 26
    assert sum(counts(clean_mysql).values()) == 0
