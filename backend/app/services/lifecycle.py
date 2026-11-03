import logging
from datetime import timedelta

from sqlalchemy import select

from app.errors import ApiError
from app.models import Inventory, Order, OrderDelay, OrderItem, Payment, Store
from app.security import pickup
from app.services.business_calendar import JST, business_hours, next_closing, pickup_deadline
from app.services.notifications import enqueue
from app.services.order_queries import can_cancel, sync_time
from app.services.payment_states import audit, release_held, reservations
from app.services.stock_pos import change_stock

logger = logging.getLogger("pickup")
DELAY_REASONS = dict(
    STAFF_SHORTAGE="人手が不足しているため",
    CONGESTION="店舗が混雑しているため",
    STOCK_CHECK="在庫を確認しているため",
    OTHER="その他",
)
CANCEL_REASONS = dict(
    BUYER_DELAY="お客様のご依頼（準備の遅れによる取消）",
    SHORTAGE_ALL="すべての商品が欠品したため",
    SHORTAGE_POLICY="欠品があり、ご希望に従って注文全体を取り消したため",
    ADMIN="店舗の事情により取り消したため",
)


def locked_order(db, ident, user, store_id=None):
    stmt = select(Order).where(Order.id == ident)
    stmt = (
        stmt.where(Order.store_id == store_id)
        if store_id
        else stmt.where(Order.purchaser_id == user.id)
    )
    order = db.scalar(stmt.with_for_update().execution_options(populate_existing=True))
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND")
    payment = db.scalar(
        select(Payment)
        .where(Payment.order_id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, payment


def check_version(db, order, data, settings, now):
    if order.version != data.version:
        raise ApiError(409, "CONFLICTING_UPDATE", latest_resource={"version": order.version})
    sync_time(db, order, settings, now)


def touch(order, now):
    order.version += 1
    order.updated_at = now


def stock_rows(db, order):
    items = db.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.line_no)
    ).all()
    held = reservations(db, order)
    invs = db.scalars(
        select(Inventory)
        .where(Inventory.id.in_([x.inventory_id for x in held]))
        .order_by(Inventory.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    inv_by_id = {x.id: x for x in invs}
    return items, {x.order_item_id: x for x in held}, inv_by_id


def history(db, inv, delta, kind, user, now, item_id):
    tx = change_stock(db, inv, delta, kind, user, now)
    tx.reference_type, tx.reference_id = "ORDER_ITEM", item_id


def begin_operation(payment, operation, now):
    if payment.last_operation == operation:
        payment.operation_attempt += 1
    else:
        payment.last_operation, payment.operation_attempt = operation, 1
    if payment.operation_attempt > 5:
        raise ApiError(409, "INVALID_STATE")
    payment.status = dict(CAPTURE="CAPTURING", RELEASE="RELEASING", REFUND="REFUNDING")[operation]
    payment.operation_started_at, payment.updated_at = now, now
    payment.failure_code = None
    if operation == "REFUND":
        payment.provider_refund_id = None
    payment.version += 1


def start(db, order, payment, user, data, settings, now):
    if order.status != "RECEIVED":
        raise ApiError(409, "INVALID_STATE")
    order.status, order.preparation_started_at = "PREPARING", now
    touch(order, now)
    audit(
        db,
        order,
        "PREPARATION_STARTED",
        "ORDER",
        {"status": "RECEIVED"},
        {"status": order.status},
        now,
        user=user,
    )


def register_delay(db, order, payment, user, data, settings, now):
    if order.status not in {"RECEIVED", "PREPARING", "ACTION_REQUIRED"}:
        raise ApiError(409, "INVALID_STATE")
    reason = (data.reason_text or "").strip()
    if data.reason_code == "OTHER" and not reason:
        raise ApiError(400, "VALIDATION_ERROR")
    reason = reason or DELAY_REASONS[data.reason_code]
    if data.updated_ready_at:
        store = db.get(Store, order.store_id)
        hours = business_hours(db, store, now.astimezone(JST).date())
        closing = (
            hours[1]
            if hours and now < hours[1]
            else next_closing(db, store, now.astimezone(JST).date() + timedelta(days=1))
        )
        if not now < data.updated_ready_at <= closing:
            raise ApiError(400, "VALIDATION_ERROR")
    before = dict(
        is_delayed=order.is_delayed,
        updated_ready_at=order.updated_ready_at.isoformat() if order.updated_ready_at else None,
    )
    order.is_delayed, order.delay_occurred, order.updated_ready_at = (
        True,
        True,
        data.updated_ready_at,
    )
    touch(order, now)
    db.add(
        OrderDelay(
            order_id=order.id,
            source="STAFF",
            reason_code=data.reason_code,
            reason_text=reason,
            new_ready_at=data.updated_ready_at,
            registered_by=user.id,
            registered_at=now,
        )
    )
    enqueue(db, order, "DELAYED", settings, now, reason=reason)
    audit(
        db,
        order,
        "DELAY_REGISTERED",
        "ORDER",
        before,
        dict(
            is_delayed=True,
            updated_ready_at=data.updated_ready_at.isoformat() if data.updated_ready_at else None,
        ),
        now,
        user=user,
    )


def cancel_order(
    db, order, payment, user, settings, now, reason, *, admin=False, release_allowed=True
):
    before = order.status
    if before == "READY":
        items, held, invs = stock_rows(db, order)
        for item in items:
            if item.prepared_quantity:
                history(
                    db,
                    invs[held[item.id].inventory_id],
                    item.prepared_quantity,
                    "EC_CANCEL_RETURN",
                    user,
                    now,
                    item.id,
                )
        pickup.revoke(db, order, now, "CANCELLED")
        operation = "REFUND"
    else:
        release_held(db, reservations(db, order), now)
        operation = (
            "REFUND"
            if payment.status == "CAPTURED"
            else (
                "RELEASE"
                if payment.status == "AUTHORIZED"
                or (payment.status == "FAILED" and payment.last_operation == "CAPTURE")
                else None
            )
        )
    order.status, order.cancelled_at, order.cancel_reason_code = "CANCELLED", now, reason
    order.is_delayed = False
    touch(order, now)
    if operation == "RELEASE" and not release_allowed:
        operation = None
    if operation:
        begin_operation(payment, operation, now)
    enqueue(db, order, "CANCELLED", settings, now, reason=CANCEL_REASONS[reason])
    audit(
        db,
        order,
        "ORDER_CANCELLED",
        "ORDER",
        {"status": before},
        {"status": order.status},
        now,
        user=user,
    )
    return operation


def cancel_customer(db, order, payment, user, data, settings, now):
    if not can_cancel(order, payment):
        raise ApiError(422, "CANCEL_NOT_ALLOWED")
    return cancel_order(db, order, payment, user, settings, now, "BUYER_DELAY")


def register_shortage(db, order, payment, user, data, settings, now):
    if order.status != "PREPARING" or payment.status != "AUTHORIZED":
        raise ApiError(409, "INVALID_STATE")
    items, held, invs = stock_rows(db, order)
    mapping = {x.id: x for x in items}
    for value in data.items:
        item = mapping.get(str(value.order_item_id))
        if (
            item is None
            or not item.shortage_quantity <= value.shortage_quantity <= item.ordered_quantity
        ):
            raise ApiError(400, "VALIDATION_ERROR")
    for value in data.items:
        item = mapping[str(value.order_item_id)]
        delta = value.shortage_quantity - item.shortage_quantity
        inv = invs[held[item.id].inventory_id]
        inv.reserved_quantity -= delta
        actual = min(delta, inv.on_hand_quantity)
        if actual:
            history(db, inv, -actual, "EC_SHORTAGE", user, now, item.id)
        elif delta:
            inv.version += 1
            inv.updated_at = now
        item.shortage_quantity = held[item.id].shortage_quantity = value.shortage_quantity
        held[item.id].updated_at = now
    touch(order, now)
    audit(
        db,
        order,
        "SHORTAGE_REGISTERED",
        "ORDER",
        None,
        {"items": [{"id": x.id, "shortage_quantity": x.shortage_quantity} for x in items]},
        now,
        user=user,
    )
    if all(x.ordered_quantity == x.shortage_quantity for x in items):
        return cancel_order(db, order, payment, user, settings, now, "SHORTAGE_ALL")
    if order.shortage_policy == "CANCEL_ALL" and any(x.shortage_quantity for x in items):
        return cancel_order(db, order, payment, user, settings, now, "SHORTAGE_POLICY")
    enqueue(db, order, "SHORTAGE_CHANGED", settings, now)


def prepare_capture(db, order, payment, user, data, settings, now):
    permitted = (order.status == "PREPARING" and payment.status == "AUTHORIZED") or (
        order.status == "ACTION_REQUIRED"
        and (
            payment.status == "AUTHORIZED"
            or (payment.status == "FAILED" and payment.last_operation == "CAPTURE")
        )
    )
    if not permitted:
        if payment.status in {"CAPTURING", "UNKNOWN"}:
            raise ApiError(
                409,
                "INVALID_STATE",
                message="決済確定の結果を確認しています。しばらくしてから再度ご確認ください。",
            )
        raise ApiError(409, "INVALID_STATE")
    items, held, invs = stock_rows(db, order)
    insufficient = [
        dict(
            orderItemId=x.id,
            onHandQuantity=invs[held[x.id].inventory_id].on_hand_quantity,
            requiredQuantity=x.ordered_quantity - x.shortage_quantity,
        )
        for x in items
        if x.ordered_quantity - x.shortage_quantity > invs[held[x.id].inventory_id].on_hand_quantity
    ]
    if insufficient:
        raise ApiError(409, "INSUFFICIENT_STOCK", details={"items": insufficient})
    begin_operation(payment, "CAPTURE", now)
    touch(order, now)
    return "CAPTURE"


def complete_capture(db, order, payment, settings, now):
    if order.status not in {"PREPARING", "ACTION_REQUIRED"}:
        return
    before = order.status
    items, held, invs = stock_rows(db, order)
    for item in items:
        row = held[item.id]
        if row.status == "SETTLED":
            continue
        inv = invs[row.inventory_id]
        quantity = item.ordered_quantity - item.shortage_quantity
        actual = min(quantity, inv.on_hand_quantity)
        inv.reserved_quantity -= quantity
        if actual:
            # System actor has no user; change_stock accepts a minimal actor below.
            history(db, inv, -actual, "EC_PICKUP_OUT", None, now, item.id)
        else:
            inv.version += 1
            inv.updated_at = now
        if actual < quantity:
            logger.warning("stock changed during capture; physical stock requires review")
        item.prepared_quantity = quantity
        row.status, row.consumed_quantity, row.expires_at, row.updated_at = (
            "SETTLED",
            quantity,
            None,
            now,
        )
    order.status, order.ready_at, order.is_delayed = "READY", now, False
    order.captured_amount_yen = payment.captured_amount_yen
    order.pickup_deadline_at = pickup_deadline(db, db.get(Store, order.store_id), now)
    touch(order, now)
    pickup.issue(db, order, now)
    enqueue(db, order, "READY", settings, now)
    audit(db, order, "ORDER_READY", "ORDER", {"status": before}, {"status": "READY"}, now)


def return_to_stock(db, order, payment, user, data, settings, now):
    if order.status != "EXPIRED":
        raise ApiError(409, "INVALID_STATE")
    items, held, invs = stock_rows(db, order)
    for item in items:
        if item.prepared_quantity:
            history(
                db,
                invs[held[item.id].inventory_id],
                item.prepared_quantity,
                "EC_EXPIRED_RETURN",
                user,
                now,
                item.id,
            )
    pickup.revoke(db, order, now, "RETURNED")
    order.status, order.returned_to_stock_at, order.is_delayed = "EXPIRED_RETURNED", now, False
    touch(order, now)
    audit(
        db,
        order,
        "RETURNED_TO_STOCK",
        "ORDER",
        {"status": "EXPIRED"},
        {"status": order.status},
        now,
        user=user,
    )


def reissue(db, order, payment, user, data, settings, now):
    if (
        order.status not in {"READY", "EXPIRED"}
        or payment.status != "CAPTURED"
        or not pickup.active_token(db, order.id)
    ):
        raise ApiError(409, "INVALID_STATE")
    pickup.revoke(db, order, now, "REISSUED")
    pickup.issue(db, order, now)
    touch(order, now)
    audit(
        db, order, "PICKUP_TOKEN_REISSUED", "ORDER", None, {"status": order.status}, now, user=user
    )


def handover(db, order, payment, user, data, settings, now):
    if order.status not in {"READY", "EXPIRED"} or payment.status != "CAPTURED":
        raise ApiError(409, "INVALID_STATE")
    token = pickup.active_token(db, order.id, lock=True)
    if token is None or token.token_id != str(data.pickup_verification_id) or token.used_at:
        raise ApiError(422, "INVALID_PICKUP_CODE")
    before = order.status
    order.status, order.picked_up_at, order.handed_over_by, order.is_delayed = (
        "PICKED_UP",
        now,
        user.id,
        False,
    )
    token.used_at = now
    touch(order, now)
    audit(
        db,
        order,
        "HANDED_OVER",
        "ORDER",
        {"status": before},
        {"status": order.status},
        now,
        user=user,
    )
