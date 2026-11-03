import logging
from datetime import timedelta

from app.services.lifecycle import begin_operation
from app.services.payment_operations import operation_snapshot, perform
from app.services.payment_states import (
    apply_payment_intent,
    apply_refund,
    locked_payment,
    reject_pending,
)

logger = logging.getLogger("pickup")


def reconcile(app, order_id, *, expire=False, force=False):
    factory, gateway, settings, now = (
        app.state.session_factory,
        app.state.payment_gateway,
        app.state.settings,
        app.state.clock.now(),
    )
    with factory() as db:
        order, payment = locked_payment(db, order_id)
        if payment is None:
            return False
        intent_id, refund_id, operation = (
            payment.provider_payment_intent_id,
            payment.provider_refund_id,
            payment.last_operation,
        )
        if payment.operation_attempt >= 5 and not force:
            logger.warning("payment operation attempt limit reached; manual review required")
            return False
        if expire:
            if order.status != "PENDING_PAYMENT" or order.hold_expires_at > now:
                return False
        elif payment.status not in {
            "FAILED",
            "UNKNOWN",
            "AUTHORIZING",
            "REQUIRES_ACTION",
            "CAPTURING",
            "RELEASING",
            "REFUNDING",
        }:
            return False
        elif (
            not force
            and payment.status != "FAILED"
            and (
                payment.operation_started_at is None
                or payment.operation_started_at > now - timedelta(minutes=5)
            )
        ):
            return False
        if payment.status == "FAILED" and (
            payment.failure_code == "CANCELED_BEFORE_AUTHORIZATION"
            or payment.last_operation == "AUTHORIZE"
        ):
            return False
        if intent_id is None and order.created_at > now - timedelta(minutes=5):
            return False
        db.commit()
    # All provider reads, including search and refunds, run outside transactions.
    try:
        intent = (
            gateway.retrieve(intent_id)
            if intent_id
            else next(iter(gateway.search_by_order(order_id)), None)
        )
        refund, refund_list = None, []
        if operation == "REFUND" and intent:
            if refund_id:
                refund = gateway.retrieve_refund(refund_id)
            else:
                refund_list = gateway.list_refunds(intent["id"])
                refund = refund_list[0] if refund_list else None
    except Exception:
        logger.warning("payment lookup unavailable; retry on next reconciliation")
        return False
    retry = None
    with factory() as db:
        order, payment = locked_payment(db, order_id)
        if expire and (order.status != "PENDING_PAYMENT" or order.hold_expires_at > now):
            return False
        if intent is None:
            if expire:
                payment.status, payment.failure_code = "FAILED", "NOT_CREATED"
                payment.version += 1
                payment.updated_at = now
                reject_pending(db, order, now)
            db.commit()
            return expire
        # A concurrent webhook/API may have completed the operation during lookup.
        if payment.status in {"CAPTURED", "RELEASED", "REFUNDED"} and not expire:
            return False
        if expire:
            if intent["status"] == "requires_capture":
                apply_payment_intent(db, order, payment, intent, settings, now)
                payment.authorized_confirmed = True
            if intent["status"] in {"canceled", "requires_payment_method"}:
                if intent["status"] == "canceled" and payment.status == "AUTHORIZED":
                    begin_operation(payment, "RELEASE", now)
                apply_payment_intent(db, order, payment, intent, settings, now)
                reject_pending(db, order, now)
            else:
                payment.provider_payment_intent_id = intent["id"]
                begin_operation(payment, "RELEASE", now)
                retry = operation_snapshot(db, order, payment)
        elif operation == "REFUND":
            if refund:
                apply_refund(db, order, payment, refund, now)
            if payment.status == "FAILED" and payment.operation_attempt < 5:
                begin_operation(payment, "REFUND", now)
                retry = operation_snapshot(db, order, payment)
            elif not refund and payment.operation_attempt < 5:
                retry = operation_snapshot(db, order, payment)
        else:
            apply_payment_intent(db, order, payment, intent, settings, now)
            if (
                operation in {"CAPTURE", "RELEASE"}
                and intent["status"] == "requires_capture"
                and payment.status in {"CAPTURING", "RELEASING", "UNKNOWN", "FAILED"}
                and payment.operation_attempt < 5
            ):
                if payment.status == "FAILED":
                    if operation == "CAPTURE" and order.status != "ACTION_REQUIRED":
                        db.commit()
                        return False
                    begin_operation(payment, operation, now)
                retry = operation_snapshot(db, order, payment)
            elif payment.status == "REFUNDING" and payment.last_operation == "REFUND":
                retry = operation_snapshot(db, order, payment)
        db.commit()
    if retry:
        perform(app, order_id, retry)
    return True
