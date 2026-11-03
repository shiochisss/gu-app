import hmac
import math
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.errors import ApiError
from app.models import Order, OrderItem, Payment, PickupToken, RateLimitCounter
from app.security import pickup
from app.services.order_queries import sync_time
from app.services.stock_pos import timestamp

REASONS = dict(
    OTHER_STORE="別の店舗の注文です",
    NOT_READY="まだ準備が完了していません",
    CANCELLED="取り消された注文です",
    ALREADY_PICKED_UP="受け取り済みです",
    RETURNED_TO_STOCK="受取期限を過ぎ、商品を棚に戻した注文です",
    PAYMENT_NOT_CAPTURED="お支払いが確定していません",
)


def limited(factory, key, limit, now, count=False):
    failure = None
    with factory.begin() as db:
        stmt = mysql_insert(RateLimitCounter).values(key=key, count=0, window_started_at=now)
        db.execute(stmt.on_duplicate_key_update(key=key))
        row = db.scalar(
            select(RateLimitCounter).where(RateLimitCounter.key == key).with_for_update()
        )
        if row.window_started_at + timedelta(minutes=10) < now:
            row.count, row.window_started_at = 0, now
        if row.count >= limit:
            remaining = max(
                1, math.ceil((row.window_started_at + timedelta(minutes=10) - now).total_seconds())
            )
            failure = ApiError(429, "RATE_LIMITED", headers={"Retry-After": str(remaining)})
        elif count:
            row.count += 1
    if failure:
        raise failure


def verify(db, app, user, store_id, data):
    now, factory = app.state.clock.now(), app.state.session_factory
    secret = app.state.settings.qr_secret.get_secret_value()
    key = ("pickup_qr:" if data.qr_value is not None else "pickup_manual:") + user.id
    limit = 60 if data.qr_value is not None else 5
    limited(factory, key, limit, now, count=data.qr_value is not None)
    try:
        if data.qr_value is not None:
            payload = pickup.decode(secret, data.qr_value)
            token = db.get(PickupToken, payload["t"])
            if (
                not token
                or token.order_id != payload["o"]
                or int(token.issued_at.timestamp()) != payload["i"]
                or token.revoked_reason == "REISSUED"
            ):
                raise ApiError(422, "INVALID_PICKUP_CODE")
            order = db.get(Order, token.order_id)
            if order.store_id != store_id:
                return dict(
                    canHandOver=False,
                    reasonCode="OTHER_STORE",
                    reasonMessage=REASONS["OTHER_STORE"],
                    orderNumber=order.order_number,
                )
        else:
            order = db.scalar(
                select(Order).where(
                    Order.order_number == data.order_number, Order.store_id == store_id
                )
            )
            token = (
                db.scalar(
                    select(PickupToken)
                    .where(
                        PickupToken.order_id == order.id,
                        (PickupToken.revoked_reason.is_(None))
                        | (PickupToken.revoked_reason != "REISSUED"),
                    )
                    .order_by(PickupToken.issued_at.desc(), PickupToken.token_id.desc())
                    .limit(1)
                )
                if order
                else None
            )
            if token is None or not hmac.compare_digest(
                pickup.manual_code(secret, token.token_id), data.manual_code
            ):
                raise ApiError(422, "INVALID_PICKUP_CODE")
    except ApiError:
        if data.qr_value is None:
            limited(factory, key, limit, now, count=True)
        raise
    ident, token_id = order.id, token.token_id
    # Refresh token after the order lock: reissue/cancel/handover cannot race the snapshot.
    order = db.scalar(
        select(Order)
        .where(Order.id == ident)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    token = db.get(PickupToken, token_id, populate_existing=True)
    if token.revoked_reason == "REISSUED":
        if data.qr_value is None:
            limited(factory, key, limit, now, count=True)
        raise ApiError(422, "INVALID_PICKUP_CODE")
    sync_time(db, order, app.state.settings, now)
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    reason = (
        "ALREADY_PICKED_UP"
        if token.used_at or order.status == "PICKED_UP"
        else "CANCELLED"
        if order.status == "CANCELLED"
        else "RETURNED_TO_STOCK"
        if order.status == "EXPIRED_RETURNED"
        else "NOT_READY"
        if order.status not in {"READY", "EXPIRED"}
        else "PAYMENT_NOT_CAPTURED"
        if payment.status != "CAPTURED"
        else None
    )
    items = db.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.line_no)
    ).all()
    result = dict(
        canHandOver=reason is None,
        reasonCode=reason,
        reasonMessage=REASONS.get(reason),
        pickupVerificationId=token.token_id if not reason else None,
        orderId=order.id,
        orderNumber=order.order_number,
        status=order.status,
        items=[
            dict(
                productName=x.product_name,
                colorName=x.color_name,
                size=x.size,
                preparedQuantity=x.prepared_quantity or 0,
            )
            for x in items
        ],
        capturedAmountYen=order.captured_amount_yen,
        pickupDeadlineAt=timestamp(order.pickup_deadline_at),
        version=order.version,
    )
    db.commit()
    return result
