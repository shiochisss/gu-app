"""Small demo dataset. Importing this module never connects to a database."""

from contextlib import contextmanager
from datetime import datetime, time, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import Clock
from app.db import Base
from app.models import RefreshToken

STORES = (
    ("SHINJUKU", "テスト新宿店", "東京都新宿区（テスト用の架空住所）"),
    ("SHIBUYA", "テスト渋谷店", "東京都渋谷区（テスト用の架空住所）"),
)
PRODUCTS = (
    ("TOPS", "コットンT", 990),
    ("BOTTOMS", "ワイドパンツ", 1490),
    ("OUTER", "ライトジャケット", 1990),
    ("DRESS", "シャツワンピース", 2490),
    ("INNER", "エアリーインナー", 2990),
    ("ACCESSORY", "キャンバストート", 3990),
)
COLORS = (
    ("ホワイト", "#F5F5F5"),
    ("ブラック", "#222222"),
    ("ネイビー", "#1F2A44"),
    ("ベージュ", "#D8C3A5"),
    ("グレー", "#9AA0A6"),
)
SIZES = (("M", 2), ("L", 3))
SEED_TABLES = (
    "stores",
    "users",
    "staff_profiles",
    "products",
    "product_variants",
    "inventories",
    "inventory_transactions",
    "number_counters",
)


class SeedError(Exception):
    """Safe, fixed messages only: CLI must not expose SQL parameters or credentials."""


def seed_id(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"pickup-app/{kind}/{key}"))


def build_seed_rows(clock: Clock) -> dict[str, list[dict]]:
    now = clock.now()
    rows = {name: [] for name in SEED_TABLES}
    for code, name, address in STORES:
        rows["stores"].append(
            {
                "id": seed_id("store", code),
                "code": code,
                "name": name,
                "address": address,
                "timezone": "Asia/Tokyo",
                "default_opens_at": time(10),
                "default_closes_at": time(21),
                "regular_closed_weekdays": [],
                "accepting_orders": True,
                "version": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
    accounts = (
        ("buyer1@example.com", "CUSTOMER", None),
        ("buyer2@example.com", "CUSTOMER", None),
        ("staff.shinjuku@example.com", "STAFF", "SHINJUKU"),
        ("staff.shibuya@example.com", "STAFF", "SHIBUYA"),
    )
    for email, role, store in accounts:
        user_id = seed_id("user", email)
        rows["users"].append(
            {
                "id": user_id,
                "email": email,
                "role": role,
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
        )
        if store:
            rows["staff_profiles"].append({"user_id": user_id, "store_id": seed_id("store", store)})
    for number, (category, name, price) in enumerate(PRODUCTS, 1):
        product_id = seed_id("product", str(number))
        color_numbers = ((number - 1) % len(COLORS), number % len(COLORS))
        created = datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Tokyo")) + timedelta(minutes=number)
        rows["products"].append(
            {
                "id": product_id,
                "name": f"{name} {number:03}",
                "category": category,
                "description": "テスト用の商品です。",
                "image_color": COLORS[color_numbers[0]][1],
                "is_active": True,
                "created_at": created,
                "updated_at": created,
            }
        )
        for color_position, color_number in enumerate(color_numbers):
            color_name, color_hex = COLORS[color_number]
            for size_position, (size, size_number) in enumerate(SIZES):
                sku = f"P{number:03}-{color_number}-{size}"
                variant_id = seed_id("variant", sku)
                rows["product_variants"].append(
                    {
                        "id": variant_id,
                        "product_id": product_id,
                        "sku": sku,
                        "color_name": color_name,
                        "color_hex": color_hex,
                        "size": size,
                        "price_yen": price,
                        "sort_order": color_position * 2 + size_position,
                        "is_active": True,
                        "created_at": created,
                        "updated_at": created,
                    }
                )
                for store_number, (code, _, _) in enumerate(STORES):
                    inventory_id = seed_id("inventory", f"{code}/{sku}")
                    quantity = (number + color_number + size_number + store_number) % 6
                    rows["inventories"].append(
                        {
                            "id": inventory_id,
                            "store_id": seed_id("store", code),
                            "product_variant_id": variant_id,
                            "on_hand_quantity": quantity,
                            "reserved_quantity": 0,
                            "version": 0,
                            "updated_at": now,
                        }
                    )
                    if quantity:
                        rows["inventory_transactions"].append(
                            {
                                "id": seed_id("initial", inventory_id),
                                "inventory_id": inventory_id,
                                "type": "INITIAL",
                                "quantity_delta": quantity,
                                "on_hand_after": quantity,
                                "occurred_at": now,
                            }
                        )
    rows["number_counters"] = [
        {"name": name, "next_value": 1} for name in ("order_number_seq", "pos_sale_number_seq")
    ]
    return rows


def seed_preview(clock: Clock) -> dict:
    rows = build_seed_rows(clock)
    return {
        "counts": {name: len(values) for name, values in rows.items()},
        "totalRows": sum(map(len, rows.values())),
        "totalStockUnits": sum(row["on_hand_quantity"] for row in rows["inventories"]),
        "zeroStockRows": sum(row["on_hand_quantity"] == 0 for row in rows["inventories"]),
        "singleStockRows": sum(row["on_hand_quantity"] == 1 for row in rows["inventories"]),
        "stores": [{"code": row["code"], "name": row["name"]} for row in rows["stores"]],
        "products": [
            {"name": row["name"], "category": row["category"]} for row in rows["products"]
        ],
    }


@contextmanager
def seed_session(engine: Engine):
    # Named locks are scoped to this database and share one physical connection.
    with engine.connect() as connection:
        lock_name = connection.execute(
            select(func.concat("pickup:", func.database(), ":seed"))
        ).scalar_one()
        if len(lock_name) > 64:
            raise SeedError("初期化用ロック名が長すぎます。DB名を確認してください。")
        acquired = connection.execute(select(func.get_lock(lock_name, 0))).scalar_one()
        connection.commit()
        if acquired != 1:
            raise SeedError("別の初期化処理が動いています。しばらくしてから確認してください。")
        try:
            with Session(bind=connection) as session, session.begin():
                yield session
        finally:
            try:
                released = connection.execute(select(func.release_lock(lock_name))).scalar_one()
                connection.commit()
                if released != 1:
                    connection.invalidate()
            except Exception:
                connection.invalidate()


def _insert_seed(session: Session, rows: dict, password: str) -> str:
    present = []
    for name, values in rows.items():
        table = Base.metadata.tables[name]
        primary_key = next(iter(table.primary_key))
        ids = [row[primary_key.name] for row in values]
        count = session.execute(select(func.count()).select_from(table).where(primary_key.in_(ids)))
        present.append(count.scalar_one())
    expected = [len(values) for values in rows.values()]
    if present == expected:
        return "already_present"
    if any(present):
        raise SeedError("サンプルが一部だけ存在します。上書きせず中止しました。")
    if len(password) < 12:
        raise SeedError("SEED_PASSWORDに12文字以上の非公開パスワードを指定してください。")
    hasher = PasswordHasher()
    for user in rows["users"]:
        user["password_hash"] = hasher.hash(password)
    for name, values in rows.items():
        session.execute(insert(Base.metadata.tables[name]), values)
    return "inserted"


def seed_database(engine: Engine, clock: Clock, password: str) -> dict:
    try:
        with seed_session(engine) as session:
            status = _insert_seed(session, build_seed_rows(clock), password)
    except IntegrityError:
        raise SeedError("既存データと競合しました。投入分を取り消しました。") from None
    return {"status": status, **seed_preview(clock)}


def reset_demo(engine: Engine, clock: Clock, password: str, app_env: str) -> dict:
    if app_env == "production":
        raise SeedError("productionではreset-demoを実行できません。")
    try:
        with seed_session(engine) as session:
            # Resolve the only self-reference before deleting in reverse FK order.
            session.execute(update(RefreshToken).values(replaced_by_id=None))
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(delete(table))
            _insert_seed(session, build_seed_rows(clock), password)
    except IntegrityError:
        raise SeedError("初期化に失敗しました。削除と投入を取り消しました。") from None
    return {"status": "reset", **seed_preview(clock)}
