from datetime import timedelta

import pytest
import test_operations
import test_ordering
from sqlalchemy import func, select, update

from app.models import Inventory, InventoryTransaction, JobRun, Order, Payment
from app.services.jobs import run_jobs
from app.services.reconciliation import reconcile


@pytest.fixture
def job_api(clean_mysql, settings):
    fixture = test_ordering.ordering_api.__wrapped__(clean_mysql, settings)
    value = next(fixture)
    try:
        yield value
    finally:
        next(fixture, None)


@pytest.fixture
def ops_api(clean_mysql, settings):
    fixture = test_operations.ops_api.__wrapped__(clean_mysql, settings)
    value = next(fixture)
    try:
        yield value
    finally:
        next(fixture, None)


def test_unknown_authorization_search_and_hold_expiry(job_api):
    client, clock, engine, app, body = job_api
    app.state.payment_gateway.outcome = "lost_response"
    response = test_ordering.send_order(
        client, test_ordering.order_body(body, test_ordering.quote(client, body))
    )
    assert response.json()["paymentStatus"] == "UNKNOWN"
    clock.advance(timedelta(minutes=5))
    result = run_jobs(app, ["J-03", "J-04"])
    assert all(x["result"] == "SUCCESS" for x in result["results"]), result
    with engine.connect() as conn:
        assert conn.scalar(select(Order.status)) == "RECEIVED"
    assert len(app.state.payment_gateway.calls) == 1
    assert run_jobs(app, ["J-03"])["results"][0]["processedCount"] == 0


@pytest.mark.parametrize(
    "outcome,expected",
    [("requires_action", "FAILED"), ("lost_response", "RELEASED"), ("unexpected", "FAILED")],
)
def test_j02_expired_pending_never_accepts_late(job_api, outcome, expected):
    client, clock, engine, app, body = job_api
    app.state.payment_gateway.outcome = outcome
    test_ordering.send_order(
        client, test_ordering.order_body(body, test_ordering.quote(client, body))
    )
    clock.advance(timedelta(minutes=15))
    result = run_jobs(app, ["J-02"])
    assert result["results"][0]["result"] == "SUCCESS", result
    with engine.connect() as conn:
        assert conn.scalar(select(Order.status)) == "NOT_ACCEPTED"
        assert conn.scalar(select(Payment.status)) == expected
    calls = len(app.state.payment_gateway.calls)
    run_jobs(app, ["J-02", "J-03"])
    assert len(app.state.payment_gateway.calls) == calls


def test_capture_lost_response_reconciles_once(ops_api):
    client, clock, engine, app, ident, _, _ = ops_api
    test_operations.call(client, ident, "preparation/start")
    app.state.payment_gateway.outcomes["CAPTURE"] = "lost_response"
    response = test_operations.call(client, ident, "ready")
    assert response.json()["status"] == "ACTION_REQUIRED", response.text
    clock.advance(timedelta(minutes=5))
    assert reconcile(app, ident)
    with engine.connect() as conn:
        assert conn.scalar(select(Order.status)) == "READY"
        assert (
            conn.scalar(
                select(func.count())
                .select_from(InventoryTransaction)
                .where(InventoryTransaction.type == "EC_PICKUP_OUT")
            )
            == 1
        )
    run_jobs(app, ["J-03"])
    assert sum(x[0] == "CAPTURE" for x in app.state.payment_gateway.calls) == 1


def test_failed_refund_gets_new_provider_key_and_lost_refund_is_recovered(ops_api):
    client, clock, engine, app, ident, buyer, _ = ops_api
    test_operations.call(client, ident, "delay", dict(reasonCode="CONGESTION", updatedReadyAt=None))
    test_operations.prepared(ops_api)
    app.state.payment_gateway.outcomes["REFUND"] = "failed"
    client.headers["Authorization"] = buyer
    detail = client.get(f"/api/v1/orders/{ident}").json()
    response = client.post(
        f"/api/v1/orders/{ident}/cancel",
        json={"version": detail["version"]},
        headers={"Idempotency-Key": "11111111-1111-4111-8111-111111111111"},
    )
    assert response.json()["paymentStatus"] == "FAILED", response.text
    app.state.payment_gateway.outcomes["REFUND"] = "lost_response"
    assert reconcile(app, ident)
    clock.advance(timedelta(minutes=5))
    assert reconcile(app, ident)
    with engine.connect() as conn:
        assert conn.scalar(select(Payment.status)) == "REFUNDED"
        assert conn.scalar(select(Payment.operation_attempt)) == 2
        assert (
            conn.scalar(
                select(func.count())
                .select_from(InventoryTransaction)
                .where(InventoryTransaction.type == "EC_CANCEL_RETURN")
            )
            == 1
        )
    assert sum(x[0] == "REFUND" for x in app.state.payment_gateway.calls) == 2


def test_jobs_api_secret_and_advisory_lock(job_api):
    client, _, engine, app, _ = job_api
    assert client.post("/internal/jobs/run", json={}).status_code == 403
    with engine.connect() as lock:
        name = "pickup:pickup_test:J-01"
        assert lock.scalar(select(func.get_lock(name, 0))) == 1
        result = run_jobs(app, ["J-01"])
        assert result["results"][0]["result"] == "SKIPPED_LOCKED"
        assert lock.scalar(select(func.release_lock(name))) == 1
    response = client.post(
        "/internal/jobs/run", json={"jobs": ["J-01"]}, headers={"X-Job-Secret": "o" * 64}
    )
    assert response.status_code == 200 and response.json()["results"][0]["result"] == "SUCCESS"
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(JobRun)) == 2


def test_inventory_reconciliation_detects_without_repair(job_api):
    _, clock, engine, app, _ = job_api
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        for inv in db.scalars(select(Inventory)):
            previous = db.scalar(
                select(func.coalesce(func.sum(InventoryTransaction.quantity_delta), 0)).where(
                    InventoryTransaction.inventory_id == inv.id
                )
            )
            delta = inv.on_hand_quantity - int(previous)
            db.add(
                InventoryTransaction(
                    inventory_id=inv.id,
                    type="STOCKTAKE",
                    quantity_delta=delta,
                    on_hand_after=inv.on_hand_quantity,
                    counted_quantity=inv.on_hand_quantity,
                    occurred_at=clock.now(),
                )
            )
        db.commit()
    assert run_jobs(app, ["J-07"])["results"][0]["processedCount"] == 0
    with engine.begin() as conn:
        ident = conn.scalar(select(Inventory.id).order_by(Inventory.id))
        conn.execute(update(Inventory).where(Inventory.id == ident).values(on_hand_quantity=21))
    assert run_jobs(app, ["J-07"])["results"][0]["processedCount"] == 1
    with engine.connect() as conn:
        assert conn.scalar(select(Inventory.on_hand_quantity).where(Inventory.id == ident)) == 21


def test_j06_cleans_only_stale_data(job_api):
    client, clock, engine, app, _ = job_api
    from uuid import uuid4

    from app.models import IdempotencyRecord, RefreshToken
    from app.services.seed import seed_id

    now = clock.now()
    with engine.begin() as conn:
        for hours in [-1, 1]:
            conn.execute(
                IdempotencyRecord.__table__.insert().values(
                    user_id=seed_id("user", "buyer1@example.com"),
                    endpoint="POST /test",
                    idempotency_key=str(uuid4()),
                    request_hash="a" * 64,
                    created_at=now,
                    locked_until=now,
                    expires_at=now + timedelta(hours=hours),
                )
            )
        conn.execute(update(RefreshToken).values(expires_at=now - timedelta(days=8)))
    result = run_jobs(app, ["J-06"])
    assert result["results"][0]["result"] == "SUCCESS"
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
        assert conn.scalar(select(func.count()).select_from(RefreshToken)) == 0


def test_admin_resume_cancel_and_mail_retry(ops_api):
    from app.models import Notification
    from app.services.administration import change_order, mails, resend, show

    client, _, engine, app, ident, _, _ = ops_api
    test_operations.call(client, ident, "preparation/start")
    app.state.payment_gateway.outcomes["CAPTURE"] = "error"
    failed = test_operations.call(client, ident, "ready").json()
    number = failed["orderNumber"]
    assert show(app, number)["status"] == "ACTION_REQUIRED"
    assert change_order(app, number, "resume")["status"] == "PREPARING"
    assert test_operations.call(client, ident, "ready").json()["status"] == "ACTION_REQUIRED"
    app.state.payment_gateway.outcomes.clear()
    assert change_order(app, number, "cancel", "店舗都合の試験")["status"] == "CANCELLED"
    assert mails(app)
    with engine.begin() as conn:
        mail_id = conn.scalar(select(Notification.id).order_by(Notification.id))
        conn.execute(
            update(Notification)
            .where(Notification.id == mail_id)
            .values(status="FAILED", attempt_count=5)
        )
    assert resend(app, mail_id)["notificationId"] == mail_id
    with engine.connect() as conn:
        assert (
            conn.scalar(select(Notification.status).where(Notification.id == mail_id))
            == "SIMULATED"
        )


def test_capture_retry_stops_after_five_attempts(ops_api):
    client, _, engine, app, ident, _, _ = ops_api
    test_operations.call(client, ident, "preparation/start")
    app.state.payment_gateway.outcomes["CAPTURE"] = "error"
    test_operations.call(client, ident, "ready")
    for _ in range(6):
        reconcile(app, ident)
    with engine.connect() as conn:
        assert conn.scalar(select(Payment.operation_attempt)) == 5
    assert sum(x[0] == "CAPTURE" for x in app.state.payment_gateway.calls) == 5


def test_declined_authorizations_do_not_starve_reconciliation_queue(job_api, monkeypatch):
    from unittest.mock import Mock

    client, clock, _, app, body = job_api
    app.state.payment_gateway.outcome = "declined"
    test_ordering.send_order(
        client, test_ordering.order_body(body, test_ordering.quote(client, body))
    )
    clock.advance(timedelta(minutes=5))
    search = Mock(wraps=app.state.payment_gateway.search_by_order)
    monkeypatch.setattr(app.state.payment_gateway, "search_by_order", search)
    result = run_jobs(app, ["J-03"])
    assert result["results"][0]["processedCount"] == 0
    search.assert_not_called()


def test_manual_reconciliation_can_read_final_outcome_at_retry_limit(ops_api):
    from types import SimpleNamespace

    from app.services.administration import command

    client, _, engine, app, ident, _, _ = ops_api
    test_operations.call(client, ident, "preparation/start")
    app.state.payment_gateway.outcomes["CAPTURE"] = "lost_response"
    failed = test_operations.call(client, ident, "ready").json()
    with engine.begin() as conn:
        conn.execute(update(Payment).values(operation_attempt=5))
    assert reconcile(app, ident) is False
    result = command(app, SimpleNamespace(command="payments", order_number=failed["orderNumber"]))
    assert result["status"] == "READY"
    assert sum(x[0] == "CAPTURE" for x in app.state.payment_gateway.calls) == 1
