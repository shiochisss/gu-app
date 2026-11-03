from datetime import timedelta

from sqlalchemy import select

from app.errors import ApiError
from app.models import Order, OrderDelay, OrderItem, Payment, Store
from app.services.notifications import enqueue
from app.services.payment_states import audit
from app.services.stock_pos import timestamp

STATUS = dict(
    PENDING_PAYMENT="支払確認中",
    NOT_ACCEPTED="注文不成立",
    RECEIVED="受付済み",
    PREPARING="準備中",
    READY="受け取り可能",
    ACTION_REQUIRED="確認中（店舗対応中）",
    PICKED_UP="受け取り済み",
    CANCELLED="取消済み",
    EXPIRED="受取期限切れ",
    EXPIRED_RETURNED="受取期限切れ（終了）",
)
PAYMENT_LABELS = dict(
    AUTHORIZING="支払確認中",
    REQUIRES_ACTION="支払確認中",
    UNKNOWN="支払確認中",
    AUTHORIZED="カード利用枠確保済み",
    CAPTURING="お支払い確定処理中",
    CAPTURED="お支払い確定",
    RELEASING="利用枠を解放",
    RELEASED="利用枠を解放",
    REFUNDING="返金処理中",
    REFUNDED="返金済み",
    FAILED="お支払いできませんでした",
    NOT_STARTED="未処理",
)
CANCEL_LABELS = dict(
    BUYER_DELAY="お客様のご依頼（準備の遅れによる取消）",
    SHORTAGE_ALL="すべての商品が欠品したため",
    SHORTAGE_POLICY="欠品があり、ご希望に従って注文全体を取り消したため",
    ADMIN="店舗の事情により取り消したため",
)


def owned_order(db, user, ident, lock=False):
    stmt = select(Order).where(Order.id == ident, Order.purchaser_id == user.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(stmt)
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND")
    return order


def sync_time(db, order, settings, now):
    if (
        order.status in {"RECEIVED", "PREPARING", "ACTION_REQUIRED"}
        and now > (order.updated_ready_at or order.original_ready_at)
        and not (order.is_delayed and order.updated_ready_at is None)
    ):
        reason = "予定時刻を過ぎています（店舗で確認中）"
        db.add(
            OrderDelay(
                order_id=order.id,
                source="AUTO",
                reason_code="AUTO_OVERDUE",
                reason_text=reason,
                registered_at=now,
            )
        )
        before = dict(
            updated_ready_at=timestamp(order.updated_ready_at), is_delayed=order.is_delayed
        )
        order.is_delayed, order.delay_occurred, order.updated_ready_at = True, True, None
        order.version += 1
        order.updated_at = now
        enqueue(db, order, "DELAYED", settings, now, reason=reason)
        audit(
            db,
            order,
            "DELAY_AUTO",
            "ORDER",
            before,
            dict(updated_ready_at=None, is_delayed=True),
            now,
        )
    if order.status == "READY" and now > order.pickup_deadline_at:
        order.status, order.expired_at = "EXPIRED", now
        order.version += 1
        order.updated_at = now
        enqueue(db, order, "EXPIRED", settings, now)
        audit(db, order, "ORDER_EXPIRED", "ORDER", {"status": "READY"}, {"status": "EXPIRED"}, now)


def summary(db, order):
    store = db.get(Store, order.store_id)
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    return dict(
        orderId=order.id,
        orderNumber=order.order_number,
        storeName=store.name,
        status=order.status,
        statusLabel=STATUS[order.status],
        paymentStatus=payment.status,
        totalQuantity=order.total_quantity,
        orderedAmountYen=order.ordered_amount_yen,
        capturedAmountYen=order.captured_amount_yen,
        originalReadyAt=timestamp(order.original_ready_at),
        currentReadyAt=timestamp(
            order.updated_ready_at if order.is_delayed else order.original_ready_at
        ),
        isDelayed=order.is_delayed,
        createdAt=timestamp(order.created_at),
    )


def can_cancel(order, payment):
    return bool(
        order.delay_occurred
        and (
            (order.status in {"RECEIVED", "PREPARING"} and payment.status == "AUTHORIZED")
            or (order.status == "READY" and payment.status == "CAPTURED")
        )
    )


def detail(db, order, settings=None):
    store = db.get(Store, order.store_id)
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    items = db.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.line_no)
    ).all()
    delays = db.scalars(
        select(OrderDelay)
        .where(OrderDelay.order_id == order.id)
        .order_by(OrderDelay.registered_at.desc(), OrderDelay.id)
    ).all()
    pickup_info = None
    if settings and order.status in {"READY", "EXPIRED"} and payment.status == "CAPTURED":
        from app.security import pickup

        token = pickup.active_token(db, order.id)
        if token:
            secret = settings.qr_secret.get_secret_value()
            pickup_info = dict(
                qrValue=pickup.qr_value(secret, token),
                manualCode=pickup.manual_code(secret, token.token_id),
            )
    return dict(
        orderId=order.id,
        orderNumber=order.order_number,
        status=order.status,
        statusLabel=STATUS[order.status],
        paymentStatus=payment.status,
        paymentStatusLabel=PAYMENT_LABELS[payment.status],
        store=dict(storeId=store.id, name=store.name, address=store.address),
        items=[
            dict(
                orderItemId=x.id,
                productName=x.product_name,
                sku=x.sku,
                colorName=x.color_name,
                size=x.size,
                unitPriceYen=x.unit_price_yen,
                orderedQuantity=x.ordered_quantity,
                shortageQuantity=x.shortage_quantity,
                preparedQuantity=x.prepared_quantity,
            )
            for x in items
        ],
        totalQuantity=order.total_quantity,
        orderedAmountYen=order.ordered_amount_yen,
        capturedAmountYen=order.captured_amount_yen,
        shortagePolicy=order.shortage_policy,
        **{
            name: timestamp(getattr(order, column))
            for name, column in dict(
                createdAt="created_at",
                acceptedAt="accepted_at",
                originalReadyAt="original_ready_at",
                updatedReadyAt="updated_ready_at",
                readyAt="ready_at",
                pickupDeadlineAt="pickup_deadline_at",
                pickedUpAt="picked_up_at",
                cancelledAt="cancelled_at",
            ).items()
        },
        cancelReasonLabel=CANCEL_LABELS.get(order.cancel_reason_code),
        isDelayed=order.is_delayed,
        delayOccurred=order.delay_occurred,
        delays=[
            dict(
                source=x.source,
                reasonText=x.reason_text,
                newReadyAt=timestamp(x.new_ready_at),
                registeredAt=timestamp(x.registered_at),
            )
            for x in delays
        ],
        pickup=pickup_info,
        canCancel=can_cancel(order, payment),
        canReissuePickupCode=pickup_info is not None,
        version=order.version,
    )


def list_query(user, now):
    return select(Order).where(
        Order.purchaser_id == user.id,
        (Order.status != "NOT_ACCEPTED") | (Order.created_at >= now - timedelta(hours=24)),
    )
