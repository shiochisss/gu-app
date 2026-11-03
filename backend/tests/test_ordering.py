import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth_catalog
from sqlalchemy import func, select, update

from app.models import (
    Inventory,
    InventoryReservation,
    Notification,
    Order,
    OrderEstimate,
    Payment,
    PaymentEvent,
    Store,
)
from app.payments.gateway import FakePaymentGateway
from app.services.estimate import ready_time, request_hash
from app.services.seed import seed_id


@pytest.fixture
def ordering_api(clean_mysql, settings):
    fixture = test_auth_catalog.api.__wrapped__(clean_mysql, settings)
    client, clock, engine, app = next(fixture)
    clock.advance(timedelta(seconds=1))
    clock.set(datetime(2026, 11, 2, 8, tzinfo=UTC))
    app.state.payment_gateway = FakePaymentGateway()
    app.state.settings.dev_tools_enabled = True
    client.headers["Authorization"] = (
        "Bearer " + test_auth_catalog.sign_in(client).json()["accessToken"]
    )
    with engine.begin() as conn:
        conn.execute(update(Inventory).values(on_hand_quantity=20, reserved_quantity=0))
    variant = seed_id("variant", "P001-0-L")
    # Derive the actual seeded ID rather than assuming the variant seed key.
    from app.models import ProductVariant

    with engine.connect() as conn:
        variant = conn.scalar(select(ProductVariant.id).order_by(ProductVariant.sku))
    body = dict(
        storeId=seed_id("store", "SHINJUKU"),
        items=[dict(productVariantId=variant, quantity=2)],
        shortagePolicy="CANCEL_ALL",
    )
    try:
        yield client, clock, engine, app, body
    finally:
        next(fixture, None)


def quote(client, body):
    response = client.post("/api/v1/orders/estimate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def order_body(body, preview):
    return dict(
        body,
        estimateId=preview["estimateId"],
        clientTotalAmountYen=preview["totalAmountYen"],
        clientEstimatedReadyAt=preview["estimatedReadyAt"],
        confirmationTokenId="ctoken_test",
        agreedToPickupTerms=True,
    )


def send_order(client, body, key=None):
    return client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )


def event_request(client, intent, event_id=None, signature=True):
    payload = json.dumps(
        dict(
            id=event_id or "evt_" + uuid4().hex,
            object="event",
            type="payment_intent.amount_capturable_updated",
            livemode=False,
            data={"object": {"id": intent}},
        )
    ).encode()
    now = str(int(time.time()))
    digest = hmac.new(b"whsec_fixture", now.encode() + b"." + payload, hashlib.sha256).hexdigest()
    return client.post(
        "/api/v1/payments/webhook",
        content=payload,
        headers={"Stripe-Signature": f"t={now},v1={digest}" if signature else "bad"},
    )


@pytest.mark.parametrize(
    "hour,minute,second,queue,work,expected,code",
    [
        (17, 0, 0, 0, 30, "17:45", None),
        (17, 0, 0, 0, 16, "17:31", None),
        (17, 0, 0, 30, 30, "18:15", "CAPACITY_FULL"),
        (19, 50, 0, 0, 12, "20:17", None),
        (20, 0, 0, 10, 16, "20:41", None),
        (20, 0, 0, 15, 16, "20:46", "CAPACITY_FULL"),
        (10, 0, 0, 0, 12, "10:27", None),
        (17, 0, 1, 0, 12, "17:28", None),
        (17, 0, 0, 33, 12, "18:00", None),
        (17, 0, 1, 33, 12, "18:01", "CAPACITY_FULL"),
    ],
)
def test_ut_eta_rounding_and_capacity(hour, minute, second, queue, work, expected, code):
    from app.services.business_calendar import JST

    base = datetime(2026, 11, 2, hour, minute, second, tzinfo=JST)
    result, reason = ready_time(base, queue, work, base.replace(hour=21, minute=0, second=0))
    assert result.strftime("%H:%M") == expected
    assert reason == code


def test_it_ord_01_10_11_ownership_and_mail(ordering_api):
    client, _, engine, app, body = ordering_api
    preview = quote(client, body)
    assert preview["accepted"]
    request = order_body(body, preview)
    key = str(uuid4())
    response = send_order(client, request, key)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "RECEIVED"
    assert response.json()["paymentStatus"] == "AUTHORIZED"
    assert send_order(client, request, key).json() == response.json()
    assert send_order(client, dict(request, agreedToPickupTerms=False), key).status_code == 422
    assert len(app.state.payment_gateway.calls) == 1
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 1
        assert conn.scalar(select(InventoryReservation.status)) == "CONFIRMED"
        assert conn.scalar(select(InventoryReservation.expires_at)) is None
        assert conn.scalar(select(Notification.status)) == "SIMULATED"
        assert (
            conn.scalar(
                select(Inventory.reserved_quantity).where(
                    Inventory.product_variant_id == body["items"][0]["productVariantId"],
                    Inventory.store_id == body["storeId"],
                )
            )
            == 2
        )
    ident = response.json()["orderId"]
    detail = client.get("/api/v1/orders/" + ident).json()
    assert detail["originalReadyAt"] == preview["estimatedReadyAt"]
    assert detail["pickup"] is None
    assert client.get("/api/v1/orders").json()["totalCount"] == 1
    mail = client.get("/api/v1/dev/mails").json()["items"]
    assert len(mail) == 1 and "送信時点の情報" in mail[0]["bodyText"]
    client.headers["Authorization"] = (
        "Bearer " + test_auth_catalog.sign_in(client, "buyer2@example.com").json()["accessToken"]
    )
    assert client.get("/api/v1/orders/" + ident).status_code == 404
    assert client.post(f"/api/v1/orders/{ident}/payment/refresh").status_code == 404
    assert client.get("/api/v1/dev/mails").json()["items"] == []


@pytest.mark.parametrize(
    "outcome,status,payment,order,reserved",
    [
        ("requires_action", 202, "REQUIRES_ACTION", "PENDING_PAYMENT", 2),
        ("declined", 422, "FAILED", "NOT_ACCEPTED", 0),
        ("requires_payment_method", 422, "FAILED", "NOT_ACCEPTED", 0),
        ("lost_response", 202, "UNKNOWN", "PENDING_PAYMENT", 2),
        ("unexpected", 202, "UNKNOWN", "PENDING_PAYMENT", 2),
    ],
)
def test_it_ord_02_04_16_provider_outcomes(ordering_api, outcome, status, payment, order, reserved):
    client, _, engine, app, body = ordering_api
    app.state.payment_gateway.outcome = outcome
    request = order_body(body, quote(client, body))
    key = str(uuid4())
    response = send_order(client, request, key)
    assert response.status_code == status, response.text
    assert send_order(client, request, key).json() == response.json()
    with engine.connect() as conn:
        assert conn.scalar(select(Payment.status)) == payment
        assert conn.scalar(select(Order.status)) == order
        assert (
            conn.scalar(
                select(Inventory.reserved_quantity).where(
                    Inventory.product_variant_id == body["items"][0]["productVariantId"],
                    Inventory.store_id == body["storeId"],
                )
            )
            == reserved
        )
    if outcome == "requires_action":
        assert response.json()["nextAction"]["clientSecret"]


def test_it_ord_03_webhook_race_and_security(ordering_api):
    client, _, engine, app, body = ordering_api
    app.state.payment_gateway.outcome = "requires_action"
    response = send_order(client, order_body(body, quote(client, body)))
    ident = response.json()["orderId"]
    intent = next(iter(app.state.payment_gateway.intents))
    app.state.payment_gateway.intents[intent]["status"] = "requires_capture"
    assert event_request(client, intent, signature=False).status_code == 400
    event_id = "evt_" + uuid4().hex
    assert event_request(client, intent, event_id).status_code == 200
    assert event_request(client, intent, event_id).status_code == 200
    assert client.post(f"/api/v1/orders/{ident}/payment/refresh").json()["status"] == "RECEIVED"
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Notification)) == 1
        assert conn.scalar(select(func.count()).select_from(PaymentEvent)) == 1
    app.state.payment_gateway.intents[intent]["status"] = "requires_action"
    assert event_request(client, intent).status_code == 200
    assert client.get("/api/v1/orders/" + ident).json()["paymentStatus"] == "AUTHORIZED"


def test_it_sec_16_webhook_retry_and_lost_response_recovery(ordering_api, monkeypatch):
    client, _, engine, app, body = ordering_api
    app.state.payment_gateway.outcome = "lost_response"
    response = send_order(client, order_body(body, quote(client, body)))
    intent = next(iter(app.state.payment_gateway.intents))
    with engine.connect() as conn:
        assert conn.scalar(select(Payment.provider_payment_intent_id)) is None
    event = "evt_" + uuid4().hex
    original = app.state.payment_gateway.retrieve

    def fail(*args):
        raise RuntimeError("test-only provider connection failure")

    monkeypatch.setattr(app.state.payment_gateway, "retrieve", fail)
    assert event_request(client, intent, event).status_code == 500
    monkeypatch.setattr(app.state.payment_gateway, "retrieve", original)
    assert event_request(client, intent, event).status_code == 200
    result = client.get("/api/v1/orders/" + response.json()["orderId"]).json()
    assert result["status"] == "RECEIVED"
    with engine.connect() as conn:
        assert conn.scalar(select(PaymentEvent.result)) == "APPLIED"
        assert conn.scalar(select(Payment.provider_payment_intent_id)) == intent


@pytest.mark.parametrize(
    "change,expected",
    [
        ("amount", "CALCULATION_CHANGED"),
        ("time", "CALCULATION_CHANGED"),
        ("terms", "TERMS_NOT_AGREED"),
        ("expired", "ESTIMATE_EXPIRED"),
        ("stock", "OUT_OF_STOCK"),
        ("closed", "STORE_NOT_ACCEPTING"),
    ],
)
def test_it_ord_06_07_12_revalidation(ordering_api, change, expected):
    client, clock, engine, _, body = ordering_api
    request = order_body(body, quote(client, body))
    if change == "amount":
        request["clientTotalAmountYen"] += 1
    if change == "time":
        request["clientEstimatedReadyAt"] = "2026-11-02T09:00:00+09:00"
    if change == "terms":
        request["agreedToPickupTerms"] = False
    if change == "expired":
        clock.advance(timedelta(minutes=10))
    with engine.begin() as conn:
        if change == "stock":
            conn.execute(update(Inventory).values(on_hand_quantity=0))
        if change == "closed":
            conn.execute(update(Store).values(accepting_orders=False))
    response = send_order(client, request)
    assert response.json()["code"] == expected, response.text
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 0


def test_ut_eta_12_13_16_and_failed_reestimate_preserves_previous(ordering_api):
    client, clock, engine, _, body = ordering_api
    first = quote(client, body)
    clock.advance(timedelta(minutes=1))
    second = quote(client, body)
    assert second["estimatedReadyAt"] > first["estimatedReadyAt"]
    with engine.connect() as conn:
        assert (
            conn.scalar(select(OrderEstimate.status).where(OrderEstimate.id == first["estimateId"]))
            == "EXPIRED"
        )
    excessive = dict(body, items=[dict(body["items"][0], quantity=11)])
    assert (
        client.post("/api/v1/orders/estimate", json=excessive).json()["code"]
        == "ORDER_LIMIT_EXCEEDED"
    )
    with engine.begin() as conn:
        conn.execute(update(Inventory).values(on_hand_quantity=0))
    rejected = quote(client, body)
    assert not rejected["accepted"] and rejected["rejectionCode"] == "OUT_OF_STOCK"
    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(OrderEstimate.status).where(OrderEstimate.id == second["estimateId"])
            )
            == "HELD"
        )


def test_external_authorize_runs_after_commit_and_no_active_db_connection(
    ordering_api, monkeypatch
):
    client, _, engine, app, body = ordering_api
    original = app.state.payment_gateway.authorize

    def authorize(*args):
        assert engine.pool.checkedout() == 0
        with engine.connect() as conn:
            assert conn.scalar(select(Order.status)) == "PENDING_PAYMENT"
        return original(*args)

    monkeypatch.setattr(app.state.payment_gateway, "authorize", authorize)
    assert send_order(client, order_body(body, quote(client, body))).status_code == 201


@pytest.mark.parametrize(
    "local_time,expected", [("20:00:00", None), ("20:00:01", "ORDER_CLOSED"), ("09:00:00", None)]
)
def test_cutoff_and_opening_boundary(ordering_api, local_time, expected):
    client, clock, _, _, body = ordering_api
    from app.services.business_calendar import JST

    hour, minute, second = map(int, local_time.split(":"))
    clock.set(datetime(2026, 11, 2, hour, minute, second, tzinfo=JST))
    client.headers["Authorization"] = (
        "Bearer " + test_auth_catalog.sign_in(client).json()["accessToken"]
    )
    result = quote(client, body)
    assert result["rejectionCode"] == expected
    if local_time == "09:00:00":
        assert result["estimatedReadyAt"].endswith("10:29:00+09:00")


def test_hash_ignores_item_order_but_not_business_content():
    from app.schemas.ordering import EstimateInput

    store, a, b = (str(uuid4()) for _ in range(3))
    body = dict(
        storeId=store,
        shortagePolicy="CANCEL_ALL",
        items=[dict(productVariantId=a, quantity=1), dict(productVariantId=b, quantity=2)],
    )
    first = request_hash(EstimateInput(**body))
    assert request_hash(EstimateInput(**dict(body, items=list(reversed(body["items"]))))) == first
    assert request_hash(EstimateInput(**dict(body, shortagePolicy="PURCHASE_AVAILABLE"))) != first


def test_it_ord_15_later_estimates_and_elapsed_time_do_not_delay_original(ordering_api):
    client, clock, _, _, body = ordering_api
    first = quote(client, body)
    buyer1 = client.headers["Authorization"]
    clock.advance(timedelta(seconds=30))
    client.headers["Authorization"] = (
        "Bearer " + test_auth_catalog.sign_in(client, "buyer2@example.com").json()["accessToken"]
    )
    second = quote(client, body)
    assert second["estimatedReadyAt"] > first["estimatedReadyAt"]
    clock.advance(timedelta(minutes=5, seconds=30))
    client.headers["Authorization"] = buyer1
    response = send_order(client, order_body(body, first))
    assert response.status_code == 201, response.text
    assert response.json()["originalReadyAt"] == first["estimatedReadyAt"]


def test_it_ord_14_concurrent_buyers_cannot_double_reserve(ordering_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client, clock, engine, _, body = ordering_api
    one = dict(body, items=[dict(body["items"][0], quantity=1)])
    with engine.begin() as conn:
        conn.execute(update(Inventory).values(on_hand_quantity=1))
    first = quote(client, one)
    token1 = client.headers["Authorization"]
    token2 = (
        "Bearer " + test_auth_catalog.sign_in(client, "buyer2@example.com").json()["accessToken"]
    )
    client.headers["Authorization"] = token2
    clock.advance(timedelta(microseconds=1))
    second = quote(client, one)
    barrier = Barrier(2)

    def run(value):
        token, preview = value
        barrier.wait()
        return client.post(
            "/api/v1/orders",
            json=order_body(one, preview),
            headers={"Authorization": token, "Idempotency-Key": str(uuid4())},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [(token1, first), (token2, second)]))
    assert sorted(x.status_code for x in results) == [201, 422]
    assert next(x for x in results if x.status_code == 422).json()["code"] == "OUT_OF_STOCK"
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 1


def test_webhook_can_finish_before_authorize_response_without_duplicate_mail(
    ordering_api, monkeypatch
):
    from app.services.webhooks import process_event

    client, _, engine, app, body = ordering_api
    original = app.state.payment_gateway.authorize

    def authorize(*args):
        intent = original(*args)
        process_event(
            app,
            dict(
                id="evt_early",
                type="payment_intent.amount_capturable_updated",
                livemode=False,
                data={"object": {"id": intent["id"]}},
            ),
        )
        return intent

    monkeypatch.setattr(app.state.payment_gateway, "authorize", authorize)
    response = send_order(client, order_body(body, quote(client, body)))
    assert response.status_code == 201, response.text
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Notification)) == 1
        assert conn.scalar(select(Order.version)) == 1


def test_stage_three_error_returns_unknown_and_webhook_recovers(ordering_api, monkeypatch):
    from app.services import ordering

    client, _, _, app, body = ordering_api
    original = ordering.apply_payment_intent

    def fail(*args):
        raise RuntimeError("test-only apply failure")

    monkeypatch.setattr(ordering, "apply_payment_intent", fail)
    request = order_body(body, quote(client, body))
    key = str(uuid4())
    response = send_order(client, request, key)
    assert response.status_code == 202 and response.json()["paymentStatus"] == "UNKNOWN"
    assert send_order(client, request, key).json() == response.json()
    monkeypatch.setattr(ordering, "apply_payment_intent", original)
    intent = next(iter(app.state.payment_gateway.intents))
    assert event_request(client, intent).status_code == 200
    assert client.get("/api/v1/orders/" + response.json()["orderId"]).json()["status"] == "RECEIVED"


def test_mailbox_feature_flag_and_staff_scope(ordering_api):
    client, _, _, app, body = ordering_api
    assert send_order(client, order_body(body, quote(client, body))).status_code == 201
    client.headers["Authorization"] = (
        "Bearer "
        + test_auth_catalog.sign_in(client, "staff.shinjuku@example.com").json()["accessToken"]
    )
    assert len(client.get("/api/v1/dev/mails").json()["items"]) == 1
    client.headers["Authorization"] = (
        "Bearer "
        + test_auth_catalog.sign_in(client, "staff.shibuya@example.com").json()["accessToken"]
    )
    assert client.get("/api/v1/dev/mails").json()["items"] == []
    assert client.post("/api/v1/orders/estimate", json=body).status_code == 403
    app.state.settings.dev_tools_enabled = False
    assert client.get("/api/v1/dev/mails").status_code == 404
    client.headers.pop("Authorization")
    assert client.get("/api/v1/dev/mails").status_code == 404


def test_smtp_retry_schedule_without_external_mail(ordering_api):
    from app.services.notifications import dispatch

    client, clock, engine, app, body = ordering_api
    send_order(client, order_body(body, quote(client, body)))
    with engine.begin() as conn:
        conn.execute(update(Notification).values(status="PENDING", attempt_count=0, sent_at=None))
    settings = app.state.settings.model_copy(update={"mail_mode": "smtp"})
    calls = []

    def sender(*args):
        calls.append(1)
        raise TimeoutError("do not log recipient or connection details")

    for index in range(5):
        dispatch(app.state.session_factory, settings, clock, sender)
        with engine.connect() as conn:
            row = conn.execute(select(Notification)).mappings().one()
            assert row["attempt_count"] == index + 1
            assert row["next_attempt_at"] == clock.now() + timedelta(minutes=2**index)
            assert row["last_error_code"] == "TimeoutError"
            assert row["status"] == ("FAILED" if index == 4 else "PENDING")
        if index < 4:
            clock.advance(timedelta(minutes=2**index))
    dispatch(app.state.session_factory, settings, clock, sender)
    assert len(calls) == 5


def test_resume_committed_order_never_authorizes_twice(ordering_api):
    from app.models import IdempotencyRecord

    client, clock, engine, app, body = ordering_api
    app.state.payment_gateway.outcome = "unexpected"
    request = order_body(body, quote(client, body))
    key = str(uuid4())
    response = send_order(client, request, key)
    assert response.status_code == 202
    with engine.begin() as conn:
        conn.execute(
            update(IdempotencyRecord).values(response_status=None, locked_until=clock.now())
        )
        conn.execute(update(Payment).values(status="AUTHORIZING"))
    resumed = send_order(client, request, key)
    assert resumed.status_code == 202 and resumed.json()["orderId"] == response.json()["orderId"]
    assert len(app.state.payment_gateway.calls) == 1
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 1


def test_same_operation_concurrent_requests_authorize_once(ordering_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client, _, engine, app, body = ordering_api
    request = order_body(body, quote(client, body))
    key = str(uuid4())
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return send_order(client, request, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert any(x.status_code == 201 for x in responses)
    assert all(x.status_code in {201, 409} for x in responses)
    assert send_order(client, request, key).status_code == 201
    assert len(app.state.payment_gateway.calls) == 1
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 1


def test_lost_commit_acknowledgement_returns_unknown_and_keeps_order(ordering_api, monkeypatch):
    from sqlalchemy.orm import Session

    from app.models import IdempotencyRecord

    client, _, engine, app, body = ordering_api
    request = order_body(body, quote(client, body))
    original = Session.commit
    raised = False

    def commit(session):
        nonlocal raised
        staged = not raised and any(isinstance(x, Order) for x in session.identity_map.values())
        original(session)
        if staged:
            raised = True
            raise RuntimeError("test-only lost commit acknowledgement")

    monkeypatch.setattr(Session, "commit", commit)
    key = str(uuid4())
    response = send_order(client, request, key)
    assert response.status_code == 202, response.text
    assert response.json()["paymentStatus"] == "UNKNOWN"
    assert send_order(client, request, key).json() == response.json()
    assert app.state.payment_gateway.calls == []
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Order)) == 1
        assert conn.scalar(select(IdempotencyRecord.response_status)) == 202


@pytest.mark.parametrize(
    "mode,code", [("holiday", "ORDER_CLOSED"), ("stopped", "STORE_NOT_ACCEPTING")]
)
def test_estimate_rejects_closed_or_stopped_store(ordering_api, mode, code):
    from app.models import BusinessHours

    client, clock, engine, _, body = ordering_api
    from app.services.business_calendar import JST

    with engine.begin() as conn:
        if mode == "stopped":
            conn.execute(update(Store).values(accepting_orders=False))
        else:
            conn.execute(
                BusinessHours.__table__.insert().values(
                    store_id=body["storeId"],
                    business_date=clock.now().astimezone(JST).date(),
                    closed=True,
                    version=0,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
    result = quote(client, body)
    assert result["accepted"] is False and result["rejectionCode"] == code
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(OrderEstimate)) == 0


def test_expired_other_customer_estimate_does_not_take_queue_capacity(ordering_api):
    client, clock, _, _, body = ordering_api
    first = quote(client, body)
    clock.advance(timedelta(minutes=10))
    client.headers["Authorization"] = (
        "Bearer " + test_auth_catalog.sign_in(client, "buyer2@example.com").json()["accessToken"]
    )
    result = quote(client, body)
    assert result["accepted"]
    assert datetime.fromisoformat(result["estimatedReadyAt"]) == datetime.fromisoformat(
        first["estimatedReadyAt"]
    ) + timedelta(minutes=10)
