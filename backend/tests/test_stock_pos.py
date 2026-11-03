import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
import test_auth_catalog
from sqlalchemy import func, select, update
from test_auth_catalog import sign_in

from app.models import AuditLog, IdempotencyRecord, Inventory, InventoryTransaction, PosSale
from app.services.seed import seed_id


@pytest.fixture
def staff_api(clean_mysql, settings):
    fixture = test_auth_catalog.api.__wrapped__(clean_mysql, settings)
    client, clock, engine, app = next(fixture)
    clock.advance(timedelta(seconds=1))
    token = sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    client.headers["Authorization"] = "Bearer " + token
    inv = client.get("/api/v1/staff/inventories").json()["items"][0]
    with engine.begin() as conn:
        conn.execute(
            update(Inventory)
            .where(Inventory.id == inv["inventoryId"])
            .values(on_hand_quantity=5, reserved_quantity=0)
        )
    inv = client.get("/api/v1/staff/inventories").json()["items"][0]
    try:
        yield client, clock, engine, app, inv
    finally:
        next(fixture, None)


def post(client, path, body, key=None):
    return client.post(path, json=body, headers={"Idempotency-Key": key or str(uuid4())})


def sale_body(inv, quantity=2):
    return dict(
        items=[dict(productVariantId=inv["productVariantId"], quantity=quantity)],
        clientTotalAmountYen=inv["priceYen"] * quantity,
        paymentMethod="CASH",
    )


def tx_path(inv):
    return f"/api/v1/staff/inventories/{inv['inventoryId']}/transactions"


def test_it_pos_01_03_05_06_and_audit(staff_api):
    client, _, engine, _, inv = staff_api
    key = str(uuid4())
    first = post(client, "/api/v1/staff/pos/sales", sale_body(inv), key)
    assert first.status_code == 201, first.text
    replay = post(client, "/api/v1/staff/pos/sales", sale_body(inv), key)
    assert first.json() == replay.json()
    result = client.get(tx_path(inv)).json()
    assert result["inventory"]["onHandQuantity"] == 3
    assert result["inventory"]["version"] == inv["version"] + 1
    assert result["items"][0]["type"] == "POS_SALE"
    assert result["items"][0]["quantityDelta"] == -2
    assert result["items"][0]["referenceLabel"] == first.json()["saleNumber"]
    sales = client.get("/api/v1/staff/pos/sales").json()
    assert sales["summary"]["completedCount"] == 1
    assert sales["items"][0]["canVoid"] is True
    path = f"/api/v1/staff/pos/sales/{first.json()['saleId']}/void"
    body = dict(reason="入力誤り", version=0)
    void_key = str(uuid4())
    cancelled = post(client, path, body, void_key)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "VOIDED"
    assert post(client, path, body, void_key).json() == cancelled.json()
    assert post(client, path, body).json()["code"] == "INVALID_STATE"
    result = client.get(tx_path(inv)).json()
    assert result["inventory"]["onHandQuantity"] == 5
    assert sum(x["type"] == "POS_VOID" for x in result["items"]) == 1
    assert client.get("/api/v1/staff/pos/sales").json()["summary"] == dict(
        completedCount=0, completedAmountYen=0, voidedCount=1
    )
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(PosSale)) == 1
        actions = conn.execute(
            select(AuditLog.action, AuditLog.before_value, AuditLog.after_value)
        ).all()
        assert {x.action for x in actions} == {"POS_SALE_CREATED", "POS_SALE_VOIDED"}
        assert "@" not in json.dumps([x.after_value for x in actions])


def test_it_pos_02_04_and_missing_products(staff_api):
    client, _, engine, _, inv = staff_api
    with engine.begin() as conn:
        conn.execute(
            update(Inventory)
            .where(Inventory.id == inv["inventoryId"])
            .values(on_hand_quantity=2, reserved_quantity=2)
        )
    body = sale_body(inv, 1)
    estimate = client.post("/api/v1/staff/pos/sales/estimate", json={"items": body["items"]})
    assert estimate.json()["lines"][0]["reasonCode"] == "RESERVED_FOR_EC"
    result = post(client, "/api/v1/staff/pos/sales", body)
    assert result.status_code == 409
    assert result.json()["details"]["lines"][0]["reasonCode"] == "RESERVED_FOR_EC"
    with engine.begin() as conn:
        conn.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(reserved_quantity=0)
        )
    body["clientTotalAmountYen"] = 1
    assert post(client, "/api/v1/staff/pos/sales", body).json()["code"] == "CALCULATION_CHANGED"
    body["items"][0]["productVariantId"] = str(uuid4())
    result = post(client, "/api/v1/staff/pos/sales", body)
    assert result.status_code == 404
    assert result.json()["code"] == "PRODUCT_NOT_FOUND"
    assert client.get(tx_path(inv)).json()["inventory"]["onHandQuantity"] == 2


def test_it_pos_07_jst_boundary(staff_api):
    client, clock, engine, _, inv = staff_api
    sale = post(client, "/api/v1/staff/pos/sales", sale_body(inv)).json()
    with engine.begin() as conn:
        conn.execute(
            update(PosSale)
            .where(PosSale.id == sale["saleId"])
            .values(sold_at=clock.now().replace(hour=14, minute=59) - timedelta(days=1))
        )
    result = post(
        client, f"/api/v1/staff/pos/sales/{sale['saleId']}/void", dict(reason="入力誤り", version=0)
    )
    assert result.status_code == 409 and result.json()["code"] == "INVALID_STATE"
    assert client.get("/api/v1/staff/pos/sales").json()["totalCount"] == 0


def test_it_inv_01_04_05_version_and_stocktake_zero(staff_api):
    client, _, _, _, inv = staff_api
    base = f"/api/v1/staff/inventories/{inv['inventoryId']}"
    result = post(client, base + "/receipts", dict(quantity=3, version=0))
    assert result.status_code == 200, result.text
    assert result.json()["inventory"]["onHandQuantity"] == 8
    assert client.get(tx_path(inv)).json()["items"][0]["type"] == "RECEIVE"
    conflict = post(client, base + "/receipts", dict(quantity=3, version=0))
    assert conflict.status_code == 409
    assert conflict.json()["latestResource"]["version"] == 1
    bad = post(
        client, base + "/adjustments", dict(type="DAMAGE", quantity=9, reason="破損", version=1)
    )
    assert bad.json()["code"] == "INSUFFICIENT_STOCK"
    bad = post(client, base + "/adjustments", dict(type="STOCKTAKE", countedQuantity=2, version=1))
    assert bad.status_code == 400
    good = post(client, base + "/adjustments", dict(type="STOCKTAKE", countedQuantity=8, version=1))
    assert good.status_code == 200
    assert good.json()["inventory"]["version"] == 2
    history = client.get(tx_path(inv)).json()["items"]
    assert any(x["type"] == "STOCKTAKE" and x["quantityDelta"] == 0 for x in history)
    good = post(
        client,
        base + "/adjustments",
        dict(type="STOCKTAKE", countedQuantity=0, reason="棚卸", version=2),
    )
    assert good.status_code == 200 and good.json()["inventory"]["onHandQuantity"] == 0


@pytest.mark.parametrize(
    "quantity,expected", [(0, 400), (1, 200), (9999, 200), (10000, 400), (True, 400)]
)
def test_receipt_boundaries(staff_api, quantity, expected):
    client, _, _, _, inv = staff_api
    response = post(
        client,
        f"/api/v1/staff/inventories/{inv['inventoryId']}/receipts",
        dict(quantity=quantity, version=0),
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("quantity,expected", [(0, 400), (1, 200), (99, 200), (100, 400)])
def test_pos_quantity_boundaries_no_ec_ten_limit(staff_api, quantity, expected):
    client, _, engine, _, inv = staff_api
    with engine.begin() as conn:
        conn.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(on_hand_quantity=100)
        )
    result = client.post(
        "/api/v1/staff/pos/sales/estimate", json={"items": sale_body(inv, quantity)["items"]}
    )
    assert result.status_code == expected
    if expected == 200:
        assert result.json()["allOk"]


def test_scope_search_filters_and_validation(staff_api):
    client, _, _, _, inv = staff_api
    assert client.get("/api/v1/staff/products").status_code == 400
    found = client.get("/api/v1/staff/products", params={"sku": inv["sku"].lower()}).json()
    assert found["totalCount"] == 1
    assert found["items"][0]["inventoryId"] == inv["inventoryId"]
    assert client.get("/api/v1/staff/inventories?q=%").json()["totalCount"] == 0
    assert client.get("/api/v1/staff/inventories?pageSize=101").status_code == 400
    other = seed_id("inventory", f"SHIBUYA:{inv['sku']}")
    assert client.get(f"/api/v1/staff/inventories/{other}/transactions").status_code == 404
    body = sale_body(inv)
    body["items"] *= 2
    assert post(client, "/api/v1/staff/pos/sales", body).status_code == 400
    client.headers["Authorization"] = "Bearer " + sign_in(client).json()["accessToken"]
    assert client.get("/api/v1/staff/inventories").status_code == 403
    assert post(client, "/api/v1/staff/pos/sales", sale_body(inv)).status_code == 403


def test_shortage_warning_does_not_reject_adjustment(staff_api):
    client, _, engine, _, inv = staff_api
    with engine.begin() as conn:
        conn.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(reserved_quantity=5)
        )
    response = post(
        client,
        f"/api/v1/staff/inventories/{inv['inventoryId']}/adjustments",
        dict(type="DAMAGE", quantity=1, reason="破損", version=0),
    )
    assert response.status_code == 200
    assert response.json()["shortageRiskQuantity"] == 1
    result = client.get("/api/v1/staff/inventories?filter=SHORTAGE_RISK").json()
    assert result["items"][0]["inventoryId"] == inv["inventoryId"]


def test_idempotency_hash_errors_and_expired_lease(staff_api):
    client, clock, engine, _, inv = staff_api
    body = sale_body(inv)
    path = "/api/v1/staff/pos/sales"
    assert client.post(path, json=body).status_code == 400
    assert client.post(path, json=body, headers={"Idempotency-Key": "bad"}).status_code == 400
    key = str(uuid4())
    result = post(client, path, body, key)
    changed = dict(body, clientTotalAmountYen=1)
    assert post(client, path, changed, key).status_code == 422
    assert post(client, path, body, key).json() == result.json()
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    lease_key = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            IdempotencyRecord.__table__.insert().values(
                user_id=seed_id("user", "staff.shinjuku@example.com"),
                endpoint="POST " + path,
                idempotency_key=lease_key,
                request_hash=digest,
                created_at=clock.now(),
                locked_until=clock.now() + timedelta(seconds=1),
                expires_at=clock.now() + timedelta(hours=24),
            )
        )
    assert post(client, path, body, lease_key).json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    clock.advance(timedelta(seconds=1))
    assert post(client, path, body, lease_key).status_code == 201


def test_concurrent_pos_cannot_oversell_or_repeat(staff_api):
    client, _, engine, _, inv = staff_api
    with engine.begin() as conn:
        conn.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(on_hand_quantity=2)
        )
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return post(client, "/api/v1/staff/pos/sales", sale_body(inv))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(x.status_code for x in results) == [201, 409]
    assert client.get(tx_path(inv)).json()["inventory"]["onHandQuantity"] == 0


def test_audit_failure_rolls_back_every_change_and_allows_retry(staff_api, monkeypatch):
    from app.services import stock_pos

    client, _, engine, _, inv = staff_api
    original = stock_pos.audit

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(stock_pos, "audit", fail)
    key = str(uuid4())
    assert post(client, "/api/v1/staff/pos/sales", sale_body(inv), key).status_code == 500
    assert client.get(tx_path(inv)).json()["inventory"]["onHandQuantity"] == 5
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(PosSale)) == 0
        assert conn.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        assert (
            conn.scalar(
                select(func.count())
                .select_from(InventoryTransaction)
                .where(InventoryTransaction.type == "POS_SALE")
            )
            == 0
        )
    monkeypatch.setattr(stock_pos, "audit", original)
    assert post(client, "/api/v1/staff/pos/sales", sale_body(inv), key).status_code == 201


def test_same_key_concurrent_sale_is_recorded_once(staff_api):
    client, _, engine, _, inv = staff_api
    barrier = Barrier(2)
    key = str(uuid4())

    def run(_):
        barrier.wait()
        return post(client, "/api/v1/staff/pos/sales", sale_body(inv), key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert any(x.status_code == 201 for x in responses)
    assert all(x.status_code in (201, 409) for x in responses)
    replay = post(client, "/api/v1/staff/pos/sales", sale_body(inv), key)
    assert replay.status_code == 201
    assert client.get(tx_path(inv)).json()["inventory"]["onHandQuantity"] == 3
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(PosSale)) == 1


def test_concurrent_adjustment_requires_latest_version(staff_api):
    client, _, _, _, inv = staff_api
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return post(
            client,
            f"/api/v1/staff/inventories/{inv['inventoryId']}/receipts",
            dict(quantity=3, version=0),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert sorted(x.status_code for x in responses) == [200, 409]
    assert client.get(tx_path(inv)).json()["inventory"]["onHandQuantity"] == 8


@pytest.mark.parametrize("quantity,expected", [(-1, 400), (0, 200), (99999, 200), (100000, 400)])
def test_stocktake_boundaries(staff_api, quantity, expected):
    client, _, _, _, inv = staff_api
    response = post(
        client,
        f"/api/v1/staff/inventories/{inv['inventoryId']}/adjustments",
        dict(type="STOCKTAKE", countedQuantity=quantity, reason="棚卸", version=0),
    )
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["inventory"]["onHandQuantity"] == quantity


def test_inactive_or_missing_store_variant_cannot_be_sold(staff_api):
    from app.models import ProductVariant

    client, _, engine, _, inv = staff_api
    with engine.begin() as conn:
        conn.execute(
            update(ProductVariant)
            .where(ProductVariant.id == inv["productVariantId"])
            .values(is_active=False)
        )
    response = post(client, "/api/v1/staff/pos/sales", sale_body(inv))
    assert response.status_code == 404
    assert client.get("/api/v1/staff/products", params={"sku": inv["sku"]}).json()["items"] == []
    # Inactive stock remains visible to stock management, including its history.
    assert client.get(tx_path(inv)).status_code == 200


def test_business_failure_is_cached_and_body_hash_uses_raw_json(staff_api):
    client, _, engine, _, inv = staff_api
    path = "/api/v1/staff/pos/sales"
    body = sale_body(inv, 6)
    key = str(uuid4())
    failure = post(client, path, body, key)
    assert failure.status_code == 409
    with engine.begin() as conn:
        conn.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(on_hand_quantity=10)
        )
    assert post(client, path, body, key).json() == failure.json()
    assert post(client, path, dict(body, extra="new field"), key).status_code == 422
    reversed_body = dict(reversed(list(body.items())))
    assert post(client, path, reversed_body, key).json() == failure.json()
    assert post(client, path, body).status_code == 201


def test_shortage_warning_counts_only_confirmed_active_orders(staff_api):
    from sqlalchemy.orm import Session

    from app.models import InventoryReservation, Order, OrderEstimate, OrderItem

    client, clock, engine, _, inv = staff_api
    now = clock.now()
    store = seed_id("store", "SHINJUKU")
    buyer = seed_id("user", "buyer1@example.com")
    with Session(engine) as db:
        for index, (status, reservation_status) in enumerate(
            [
                ("RECEIVED", "CONFIRMED"),
                ("PREPARING", "CONFIRMED"),
                ("CANCELLED", "RELEASED"),
                ("PENDING_PAYMENT", "HELD"),
            ]
        ):
            estimate_id, order_id, item_id = (str(uuid4()) for _ in range(3))
            db.add(
                OrderEstimate(
                    id=estimate_id,
                    user_id=buyer,
                    store_id=store,
                    request_hash="a" * 64,
                    items=[],
                    shortage_policy="PURCHASE_AVAILABLE",
                    total_quantity=1,
                    total_amount_yen=inv["priceYen"],
                    work_minutes=12,
                    estimated_ready_at=now,
                    status="USED",
                    created_at=now,
                    expires_at=now,
                )
            )
            db.flush()
            db.add(
                Order(
                    id=order_id,
                    order_number=f"E{index:06d}",
                    purchaser_id=buyer,
                    store_id=store,
                    estimate_id=estimate_id,
                    status=status,
                    shortage_policy="PURCHASE_AVAILABLE",
                    total_quantity=1,
                    ordered_amount_yen=inv["priceYen"],
                    work_minutes=12,
                    pickup_terms_agreed_at=now,
                    hold_expires_at=now,
                    original_ready_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            db.add(
                OrderItem(
                    id=item_id,
                    order_id=order_id,
                    line_no=1,
                    product_variant_id=inv["productVariantId"],
                    product_name=inv["productName"],
                    sku=inv["sku"],
                    color_name=inv["colorName"],
                    size=inv["size"],
                    unit_price_yen=inv["priceYen"],
                    ordered_quantity=1,
                )
            )
            db.flush()
            db.add(
                InventoryReservation(
                    order_item_id=item_id,
                    inventory_id=inv["inventoryId"],
                    quantity=1,
                    status=reservation_status,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.execute(
            update(Inventory).where(Inventory.id == inv["inventoryId"]).values(reserved_quantity=3)
        )
        db.commit()
    response = post(
        client,
        f"/api/v1/staff/inventories/{inv['inventoryId']}/adjustments",
        dict(type="STOCKTAKE", countedQuantity=1, reason="棚卸", version=0),
    )
    assert response.status_code == 200, response.text
    assert response.json()["shortageRiskQuantity"] == 2
    assert response.json()["shortageRiskOrderCount"] == 2


def test_api_5xx_does_not_cache_a_failed_operation(staff_api, monkeypatch):
    from app.errors import ApiError
    from app.services import stock_pos

    client, _, engine, _, inv = staff_api

    def fail(*args, **kwargs):
        raise ApiError(500, "INTERNAL_ERROR")

    monkeypatch.setattr(stock_pos, "sell", fail)
    assert post(client, "/api/v1/staff/pos/sales", sale_body(inv)).status_code == 500
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
