from datetime import timedelta
from uuid import uuid4

import pytest
import test_ordering
from sqlalchemy import func, select, update
from test_auth_catalog import sign_in

from app.models import (
    Inventory,
    InventoryReservation,
    InventoryTransaction,
    Notification,
    Payment,
    PickupToken,
)


@pytest.fixture
def ops_api(clean_mysql, settings):
    fixture = test_ordering.ordering_api.__wrapped__(clean_mysql, settings)
    client, clock, engine, app, body = next(fixture)
    preview = test_ordering.quote(client, body)
    created = test_ordering.send_order(client, test_ordering.order_body(body, preview))
    assert created.status_code == 201
    ident = created.json()["orderId"]
    buyer = client.headers["Authorization"]
    staff = "Bearer " + sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    client.headers["Authorization"] = staff
    try:
        yield client, clock, engine, app, ident, buyer, staff
    finally:
        next(fixture, None)


def call(client, ident, operation, extra=None, key=None):
    version = client.get(f"/api/v1/staff/orders/{ident}").json()["version"]
    return client.post(
        f"/api/v1/staff/orders/{ident}/{operation}",
        json=dict(version=version, **(extra or {})),
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def prepared(ops_api):
    client, _, _, _, ident, buyer, _ = ops_api
    first = call(client, ident, "preparation/start")
    assert first.status_code == 200, first.text
    response = call(client, ident, "ready")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "READY", response.text
    return response.json()


def test_prepare_capture_pickup_and_inventory_ledger(ops_api):
    client, _, engine, _, ident, buyer, staff = ops_api
    ready = prepared(ops_api)
    assert "pickup" not in ready
    assert ready["payment"]["capturedAmountYen"] == ready["orderedAmountYen"]
    with engine.connect() as conn:
        assert conn.scalar(select(InventoryReservation.status)) == "SETTLED"
        assert conn.scalar(select(func.count()).select_from(PickupToken)) == 1
        assert (
            conn.scalar(
                select(InventoryTransaction.quantity_delta).where(
                    InventoryTransaction.type == "EC_PICKUP_OUT"
                )
            )
            == -2
        )
        assert (
            conn.scalar(
                select(func.count()).select_from(Notification).where(Notification.type == "READY")
            )
            == 1
        )
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    assert detail["pickup"]["qrValue"].startswith("PA1.")
    client.headers["Authorization"] = staff
    verified = client.post(
        "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["canHandOver"]
    response = client.post(
        f"/api/v1/staff/orders/{ident}/handover",
        json=dict(
            version=verified.json()["version"],
            pickupVerificationId=verified.json()["pickupVerificationId"],
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200 and response.json()["status"] == "PICKED_UP", response.text
    assert (
        client.post(
            "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
        ).json()["reasonCode"]
        == "ALREADY_PICKED_UP"
    )


def test_partial_shortage_captures_remaining_and_releases_amount(ops_api):
    client, _, engine, _, ident, _, _ = ops_api
    with engine.begin() as conn:
        from app.models import Order

        conn.execute(update(Order).values(shortage_policy="PURCHASE_AVAILABLE"))
    first = call(client, ident, "preparation/start").json()
    response = call(
        client,
        ident,
        "shortages",
        {"items": [{"orderItemId": first["items"][0]["orderItemId"], "shortageQuantity": 1}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PREPARING"
    result = call(client, ident, "ready")
    assert result.status_code == 200 and result.json()["status"] == "READY", result.text
    with engine.connect() as conn:
        payment = conn.execute(select(Payment)).mappings().one()
        assert payment["captured_amount_yen"] == payment["released_amount_yen"]
        assert conn.scalar(select(InventoryReservation.shortage_quantity)) == 1


def test_shortage_cancel_and_delayed_customer_cancellation(ops_api):
    client, _, engine, _, ident, buyer, _ = ops_api
    client.headers["Authorization"] = buyer
    response = client.post(
        f"/api/v1/orders/{ident}/cancel",
        json={"version": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 422
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    )
    delayed = call(client, ident, "delay", dict(reasonCode="CONGESTION", updatedReadyAt=None))
    assert delayed.status_code == 200, delayed.text
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    cancelled = client.post(
        f"/api/v1/orders/{ident}/cancel",
        json={"version": detail["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert cancelled.status_code == 200 and cancelled.json()["paymentStatus"] == "RELEASED", (
        cancelled.text
    )
    with engine.connect() as conn:
        assert conn.scalar(select(InventoryReservation.status)) == "RELEASED"


def test_qr_reissue_other_store_manual_limit_and_refund(ops_api):
    client, clock, engine, _, ident, buyer, staff = ops_api
    # Preserve delay_occurred through READY so the customer may cancel.
    assert (
        call(client, ident, "delay", dict(reasonCode="CONGESTION", updatedReadyAt=None)).status_code
        == 200
    )
    prepared(ops_api)
    client.headers["Authorization"] = buyer
    old = client.get(f"/api/v1/orders/{ident}").json()
    new = client.post(
        f"/api/v1/orders/{ident}/pickup-token/reissue",
        json={"version": old["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert new.status_code == 200, new.text
    client.headers["Authorization"] = staff
    assert (
        client.post(
            "/api/v1/staff/pickups/verify", json={"qrValue": old["pickup"]["qrValue"]}
        ).status_code
        == 422
    )
    assert client.post(
        "/api/v1/staff/pickups/verify",
        json={"orderNumber": old["orderNumber"], "manualCode": new.json()["pickup"]["manualCode"]},
    ).json()["canHandOver"]
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shibuya@example.com").json()["accessToken"]
    )
    other = client.post(
        "/api/v1/staff/pickups/verify", json={"qrValue": new.json()["pickup"]["qrValue"]}
    ).json()
    assert other["reasonCode"] == "OTHER_STORE" and other["items"] is None
    client.headers["Authorization"] = buyer
    cancel = client.post(
        f"/api/v1/orders/{ident}/cancel",
        json={"version": new.json()["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert cancel.status_code == 200 and cancel.json()["paymentStatus"] == "REFUNDED", cancel.text
    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(InventoryTransaction.quantity_delta).where(
                    InventoryTransaction.type == "EC_CANCEL_RETURN"
                )
            )
            == 2
        )


def test_capture_failure_retry_and_stock_preflight(ops_api):
    client, _, engine, app, ident, _, _ = ops_api
    call(client, ident, "preparation/start")
    with engine.begin() as conn:
        conn.execute(update(Inventory).values(on_hand_quantity=0))
    assert call(client, ident, "ready").status_code == 409
    assert not any(x[0] == "CAPTURE" for x in app.state.payment_gateway.calls)
    with engine.begin() as conn:
        conn.execute(update(Inventory).values(on_hand_quantity=20))
    app.state.payment_gateway.outcomes["CAPTURE"] = "error"
    failed = call(client, ident, "ready")
    assert failed.status_code == 200 and failed.json()["status"] == "ACTION_REQUIRED", failed.text
    app.state.payment_gateway.outcomes.clear()
    success = call(client, ident, "ready")
    assert success.status_code == 200 and success.json()["status"] == "READY", success.text
    with engine.connect() as conn:
        assert conn.scalar(select(Payment.operation_attempt)) == 2


def test_expired_can_handover_until_returned(ops_api):
    client, clock, _, _, ident, buyer, staff = ops_api
    prepared(ops_api)
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    from datetime import datetime

    clock.set(datetime.fromisoformat(detail["pickupDeadlineAt"]) + timedelta(seconds=1))
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    )
    expired = client.get(f"/api/v1/staff/orders/{ident}").json()
    assert expired["status"] == "EXPIRED"
    verified = client.post(
        "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
    )
    assert verified.json()["canHandOver"]
    returned = call(client, ident, "return-to-stock")
    assert returned.status_code == 200 and returned.json()["status"] == "EXPIRED_RETURNED", (
        returned.text
    )
    assert (
        client.post(
            "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
        ).json()["reasonCode"]
        == "RETURNED_TO_STOCK"
    )


def test_manual_failure_limit_and_format_validation(ops_api):
    client, clock, _, _, ident, _, _ = ops_api
    order = client.get(f"/api/v1/staff/orders/{ident}").json()
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/staff/pickups/verify",
                json={"orderNumber": order["orderNumber"], "manualCode": "000000"},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/v1/staff/pickups/verify",
            json={"orderNumber": order["orderNumber"], "manualCode": "000000"},
        ).status_code
        == 429
    )
    clock.advance(timedelta(minutes=10))
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    )
    assert (
        client.post(
            "/api/v1/staff/pickups/verify",
            json={"orderNumber": order["orderNumber"], "manualCode": "000000"},
        ).status_code
        == 429
    )
    clock.advance(timedelta(microseconds=1))
    assert (
        client.post(
            "/api/v1/staff/pickups/verify",
            json={"orderNumber": order["orderNumber"], "manualCode": "000000"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/staff/pickups/verify",
            json={"orderNumber": order["orderNumber"], "manualCode": "12345"},
        ).status_code
        == 400
    )


def test_crossing_deadline_during_handover_accepts_own_time_sync(ops_api):
    from datetime import datetime

    client, clock, _, _, ident, buyer, staff = ops_api
    prepared(ops_api)
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    client.headers["Authorization"] = staff
    verified = client.post(
        "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
    ).json()
    clock.set(datetime.fromisoformat(detail["pickupDeadlineAt"]) + timedelta(seconds=1))
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    )
    response = client.post(
        f"/api/v1/staff/orders/{ident}/handover",
        json={
            "version": verified["version"],
            "pickupVerificationId": verified["pickupVerificationId"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200 and response.json()["status"] == "PICKED_UP", response.text


def test_competing_handover_and_customer_refund_only_one_wins(ops_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client, _, _, _, ident, buyer, staff = ops_api
    call(client, ident, "delay", dict(reasonCode="CONGESTION", updatedReadyAt=None))
    prepared(ops_api)
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    client.headers["Authorization"] = staff
    verified = client.post(
        "/api/v1/staff/pickups/verify", json={"qrValue": detail["pickup"]["qrValue"]}
    ).json()
    barrier = Barrier(2)

    def run(cancel):
        barrier.wait()
        path = (
            f"/api/v1/orders/{ident}/cancel" if cancel else f"/api/v1/staff/orders/{ident}/handover"
        )
        body = {"version": verified["version"]}
        if not cancel:
            body["pickupVerificationId"] = verified["pickupVerificationId"]
        return client.post(
            path,
            json=body,
            headers={"Authorization": buyer if cancel else staff, "Idempotency-Key": str(uuid4())},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(run, [True, False]))
    assert sorted(x.status_code for x in values) == [200, 409]


def test_store_hours_acceptance_and_access_scope(ops_api):
    client, clock, _, _, ident, buyer, staff = ops_api
    store = client.get("/api/v1/staff/store").json()
    stopped = client.put(
        "/api/v1/staff/store/acceptance",
        json={"version": store["version"], "acceptingOrders": False, "reason": "準備担当が不在"},
    )
    assert stopped.status_code == 200 and not stopped.json()["acceptingOrders"], stopped.text
    assert call(client, ident, "preparation/start").status_code == 200
    assert (
        client.put(
            "/api/v1/staff/store/acceptance",
            json={"version": store["version"], "acceptingOrders": True, "reason": None},
        ).status_code
        == 409
    )
    today = store["days"][0]["date"]
    changed = client.put(
        "/api/v1/staff/store/business-hours/" + today,
        json={
            "useDefault": False,
            "closed": False,
            "opensAt": "10:00",
            "closesAt": "17:01",
            "version": None,
        },
    )
    assert changed.status_code == 200 and changed.json()["warnings"], changed.text
    assert (
        client.put(
            "/api/v1/staff/store/business-hours/" + today,
            json={"useDefault": True, "version": None},
        ).status_code
        == 409
    )
    override = changed.json()["days"][0]["overrideVersion"]
    assert (
        client.put(
            "/api/v1/staff/store/business-hours/" + today,
            json={"useDefault": True, "version": override},
        ).status_code
        == 200
    )
    client.headers["Authorization"] = buyer
    assert client.get("/api/v1/staff/store").status_code == 403
    client.headers["Authorization"] = (
        "Bearer " + sign_in(client, "staff.shibuya@example.com").json()["accessToken"]
    )
    assert client.get(f"/api/v1/staff/orders/{ident}").status_code == 404
    assert (
        client.post(
            f"/api/v1/staff/orders/{ident}/preparation/start", json={"version": 2}
        ).status_code
        == 404
    )


def test_pickup_deadline_skips_closed_day_and_search_limit(ops_api):
    from sqlalchemy.orm import Session

    from app.errors import ApiError
    from app.models import BusinessHours, Order, Store
    from app.services.business_calendar import JST, pickup_deadline

    client, clock, engine, _, ident, _, _ = ops_api
    with Session(engine) as db:
        order = db.get(Order, ident)
        store = db.get(Store, order.store_id)
        start = clock.now().astimezone(JST).date() + timedelta(days=7)
        db.add(
            BusinessHours(
                store_id=store.id,
                business_date=start,
                closed=True,
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        db.flush()
        assert pickup_deadline(db, store, clock.now()).date() == start + timedelta(days=1)
        for offset in range(1, 31):
            db.add(
                BusinessHours(
                    store_id=store.id,
                    business_date=start + timedelta(days=offset),
                    closed=True,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
        db.flush()
        with pytest.raises(ApiError) as caught:
            pickup_deadline(db, store, clock.now())
        assert caught.value.code == "NO_BUSINESS_DAY"
