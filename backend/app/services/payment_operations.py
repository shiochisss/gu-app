import logging

from sqlalchemy import select

from app.models import OrderItem
from app.payments.gateway import GatewayError
from app.services.lifecycle import touch
from app.services.payment_states import apply_payment_intent, apply_refund, audit, locked_payment

logger = logging.getLogger("pickup")


def operation_snapshot(db, order, payment):
    operation = payment.last_operation
    amount = payment.captured_amount_yen
    if operation == "CAPTURE":
        items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        amount = sum(x.unit_price_yen * (x.ordered_quantity - x.shortage_quantity) for x in items)
    return dict(
        operation=operation,
        amount=amount,
        intent_id=payment.provider_payment_intent_id,
        key=f"{payment.id}:{operation}:{payment.operation_attempt}",
        attempt=payment.operation_attempt,
    )


def perform(app, order_id, snapshot=None):
    factory, gateway, settings, clock = (
        app.state.session_factory,
        app.state.payment_gateway,
        app.state.settings,
        app.state.clock,
    )
    if snapshot is None:
        with factory() as db:
            order, payment = locked_payment(db, order_id)
            if payment.status not in {"CAPTURING", "RELEASING", "REFUNDING", "UNKNOWN"}:
                return
            snapshot = operation_snapshot(db, order, payment)
            db.commit()
    operation = snapshot["operation"]
    if operation not in {"CAPTURE", "RELEASE", "REFUND"}:
        return
    result, failure = None, None
    try:
        if operation == "CAPTURE":
            result = gateway.capture(snapshot["intent_id"], snapshot["amount"], snapshot["key"])
        elif operation == "RELEASE":
            result = gateway.cancel(snapshot["intent_id"], snapshot["key"])
        else:
            result = gateway.refund(snapshot["intent_id"], snapshot["amount"], snapshot["key"])
    except GatewayError as exc:
        failure = exc
    except Exception:
        logger.error("payment operation outcome unknown", exc_info=True)
        failure = GatewayError()
    follow_up = False
    try:
        with factory() as db:
            order, payment = locked_payment(db, order_id)
            if (
                payment.last_operation != operation
                or payment.operation_attempt != snapshot["attempt"]
            ):
                return
            if result:
                if operation == "REFUND":
                    apply_refund(db, order, payment, result, clock.now())
                else:
                    apply_payment_intent(db, order, payment, result, settings, clock.now())
                follow_up = payment.status == "REFUNDING" and operation == "CAPTURE"
            elif payment.status in {"CAPTURING", "RELEASING", "REFUNDING", "UNKNOWN"}:
                old = payment.status
                payment.status = "UNKNOWN" if failure.unknown else "FAILED"
                payment.failure_code, payment.updated_at = failure.code[:64], clock.now()
                payment.version += 1
                audit(
                    db,
                    order,
                    "PAYMENT_STATUS_CHANGED",
                    "PAYMENT",
                    {"status": old},
                    {"status": payment.status},
                    clock.now(),
                )
            if (
                operation == "CAPTURE"
                and order.status == "PREPARING"
                and payment.status != "CAPTURED"
            ):
                order.status = "ACTION_REQUIRED"
                touch(order, clock.now())
                audit(
                    db,
                    order,
                    "CAPTURE_FAILED",
                    "ORDER",
                    {"status": "PREPARING"},
                    {"status": order.status},
                    clock.now(),
                )
            db.commit()
    except Exception:
        logger.error("payment result requires reconciliation", exc_info=True)
        with factory() as db:
            order, payment = locked_payment(db, order_id)
            expected = dict(CAPTURE="CAPTURING", RELEASE="RELEASING", REFUND="REFUNDING")[operation]
            if payment.last_operation == operation and payment.status == expected:
                payment.status, payment.updated_at = "UNKNOWN", clock.now()
                payment.version += 1
                if operation == "CAPTURE" and order.status == "PREPARING":
                    order.status = "ACTION_REQUIRED"
                    touch(order, clock.now())
                    audit(
                        db,
                        order,
                        "CAPTURE_FAILED",
                        "ORDER",
                        {"status": "PREPARING"},
                        {"status": "ACTION_REQUIRED"},
                        clock.now(),
                    )
            db.commit()
    if follow_up:
        perform(app, order_id)
