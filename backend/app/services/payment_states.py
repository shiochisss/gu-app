import logging

from sqlalchemy import select

from app.errors import ApiError
from app.models import AuditLog, Inventory, InventoryReservation, Order, Payment
from app.services.notifications import enqueue

logger = logging.getLogger("pickup")


def audit(db, order, kind, target, before, after, now, *, user=None):
    db.add(
        AuditLog(
            store_id=order.store_id,
            target_type=target,
            target_id=order.id
            if target == "ORDER"
            else db.scalar(select(Payment.id).where(Payment.order_id == order.id)),
            action=kind,
            actor_user_id=user.id if user else None,
            actor_type=user.role if user else "SYSTEM",
            before_value=before,
            after_value=after,
            occurred_at=now,
        )
    )


def locked_payment(db, order_id):
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    payment = db.scalar(
        select(Payment)
        .where(Payment.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, payment


def reservations(db, order):
    from app.models import OrderItem

    return db.scalars(
        select(InventoryReservation)
        .join(OrderItem, InventoryReservation.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order.id)
        .order_by(InventoryReservation.id)
        .with_for_update()
    ).all()


def release_held(db, rows, now):
    ids = [x.inventory_id for x in rows if x.status in {"HELD", "CONFIRMED"}]
    inventories = db.scalars(
        select(Inventory)
        .where(Inventory.id.in_(ids))
        .order_by(Inventory.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    mapping = {x.id: x for x in inventories}
    for row in rows:
        if row.status not in {"HELD", "CONFIRMED"}:
            continue
        inv = mapping[row.inventory_id]
        inv.reserved_quantity -= row.quantity - row.shortage_quantity
        inv.version += 1
        inv.updated_at = now
        row.status, row.expires_at, row.updated_at = "RELEASED", None, now


def fail_authorization(db, order, payment, code, settings, now):
    if (
        order.status != "PENDING_PAYMENT"
        or payment.status not in {"AUTHORIZING", "REQUIRES_ACTION", "UNKNOWN"}
        or payment.last_operation != "AUTHORIZE"
    ):
        return
    old = payment.status
    payment.status, payment.failure_code = "FAILED", code[:64]
    payment.version += 1
    payment.updated_at = now
    release_held(db, reservations(db, order), now)
    order.status = "NOT_ACCEPTED"
    order.version += 1
    order.updated_at = now
    audit(
        db,
        order,
        "ORDER_NOT_ACCEPTED",
        "ORDER",
        {"status": "PENDING_PAYMENT"},
        {"status": order.status},
        now,
    )
    audit(
        db,
        order,
        "PAYMENT_STATUS_CHANGED",
        "PAYMENT",
        {"status": old},
        {"status": payment.status},
        now,
    )


def apply_payment_intent(db, order, payment, intent, settings, now):
    # The provider object is fetched server-to-server. Bind it to this order and
    # amount before accepting it, including webhook metadata recovery.
    if (
        intent.get("livemode") is not False
        or intent.get("currency") != "jpy"
        or intent.get("amount") != payment.authorized_amount_yen
        or intent.get("metadata", {}).get("order_id") != order.id
        or (
            payment.provider_payment_intent_id
            and payment.provider_payment_intent_id != intent["id"]
        )
    ):
        raise ApiError(409, "INVALID_STATE")
    if payment.provider_payment_intent_id is None:
        payment.provider_payment_intent_id = intent["id"]
    status = intent["status"]
    old = payment.status
    authorizing = payment.last_operation == "AUTHORIZE" and old in {
        "AUTHORIZING",
        "REQUIRES_ACTION",
        "UNKNOWN",
    }
    capturing = payment.last_operation == "CAPTURE" and old in {"CAPTURING", "UNKNOWN", "FAILED"}
    releasing = payment.last_operation == "RELEASE" and old in {"RELEASING", "UNKNOWN", "FAILED"}
    if capturing and status == "succeeded":
        amount = intent.get("amount_received")
        if type(amount) is not int or not 0 < amount <= payment.authorized_amount_yen:
            raise ApiError(409, "INVALID_STATE")
        payment.status, payment.captured_amount_yen = "CAPTURED", amount
        payment.released_amount_yen = payment.authorized_amount_yen - amount
        payment.failure_code = None
        from app.services.lifecycle import begin_operation, complete_capture

        if order.status == "CANCELLED":
            begin_operation(payment, "REFUND", now)
        else:
            complete_capture(db, order, payment, settings, now)
    elif releasing and status == "canceled":
        payment.status = "RELEASED" if payment.authorized_confirmed else "FAILED"
        payment.released_amount_yen = (
            payment.authorized_amount_yen if payment.authorized_confirmed else 0
        )
        payment.failure_code = (
            None if payment.authorized_confirmed else "CANCELED_BEFORE_AUTHORIZATION"
        )
        reject_pending(db, order, now)
    elif authorizing and status == "requires_capture":
        payment.status, payment.authorized_confirmed = "AUTHORIZED", True
        if order.status == "PENDING_PAYMENT" and order.hold_expires_at > now:
            rows = reservations(db, order)
            for row in rows:
                if row.status == "HELD":
                    row.status, row.expires_at, row.updated_at = "CONFIRMED", None, now
            order.status, order.accepted_at = "RECEIVED", now
            order.version += 1
            order.updated_at = now
            enqueue(db, order, "ORDER_ACCEPTED", settings, now)
            audit(
                db,
                order,
                "ORDER_ACCEPTED",
                "ORDER",
                {"status": "PENDING_PAYMENT"},
                {"status": "RECEIVED"},
                now,
            )
        # Expired authorization stays pending for J-02; never accept it late.
    elif authorizing and status == "requires_action":
        if old in {"AUTHORIZING", "UNKNOWN"}:
            payment.status = "REQUIRES_ACTION"
    elif authorizing and status in {"requires_payment_method", "canceled"}:
        error = intent.get("last_payment_error") or {}
        fail_authorization(
            db,
            order,
            payment,
            "CANCELED"
            if status == "canceled"
            else error.get("decline_code") or error.get("code") or "PAYMENT_DECLINED",
            settings,
            now,
        )
        return
    elif status in {"processing", "requires_confirmation"}:
        pass
    elif status == "requires_capture" and old == "AUTHORIZED":
        pass
    else:
        logger.warning("ignored stale or unsupported payment state")
    if old != payment.status:
        payment.version += 1
        payment.updated_at = now
        audit(
            db,
            order,
            "PAYMENT_STATUS_CHANGED",
            "PAYMENT",
            {"status": old},
            {"status": payment.status},
            now,
        )


def mark_unknown(db, order, payment, now):
    # A webhook can finish authorization before the original request returns.
    if payment.status == "AUTHORIZING" and order.status == "PENDING_PAYMENT":
        payment.status, payment.updated_at = "UNKNOWN", now
        payment.version += 1
        audit(
            db,
            order,
            "PAYMENT_STATUS_CHANGED",
            "PAYMENT",
            {"status": "AUTHORIZING"},
            {"status": "UNKNOWN"},
            now,
        )


def reject_pending(db, order, now):
    if order.status != "PENDING_PAYMENT":
        return
    release_held(db, reservations(db, order), now)
    order.status, order.updated_at = "NOT_ACCEPTED", now
    order.version += 1
    audit(
        db,
        order,
        "ORDER_NOT_ACCEPTED",
        "ORDER",
        {"status": "PENDING_PAYMENT"},
        {"status": order.status},
        now,
    )


def apply_refund(db, order, payment, refund, now):
    if (
        refund.get("livemode") is not False
        or refund.get("payment_intent") != payment.provider_payment_intent_id
        or refund.get("amount") != payment.captured_amount_yen
        or (payment.provider_refund_id and payment.provider_refund_id != refund.get("id"))
    ):
        raise ApiError(409, "INVALID_STATE")
    if payment.last_operation != "REFUND" or payment.status not in {
        "REFUNDING",
        "UNKNOWN",
        "FAILED",
    }:
        return
    payment.provider_refund_id = refund["id"]
    old = payment.status
    status = refund["status"]
    if status == "succeeded":
        payment.status, payment.refunded_amount_yen, payment.failure_code = (
            "REFUNDED",
            refund["amount"],
            None,
        )
    elif status in {"pending", "requires_action"}:
        payment.status = "REFUNDING"
    elif status in {"failed", "canceled"}:
        payment.status, payment.failure_code = "FAILED", "REFUND_FAILED"
    if old != payment.status:
        payment.version += 1
        payment.updated_at = now
        audit(
            db,
            order,
            "PAYMENT_STATUS_CHANGED",
            "PAYMENT",
            {"status": old},
            {"status": payment.status},
            now,
        )
