import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, tuple_

from app.errors import ApiError
from app.models import Order, OrderEstimate, Store
from app.services.business_calendar import JST, business_hours
from app.services.stock_pos import estimate as calculate_lines
from app.services.stock_pos import pos_rows

PICKUP_RULE = "準備完了日の1週間後の閉店時刻まで（休業日の場合は次の営業日の閉店時刻まで）"
OVERDUE = (
    "受取期限を過ぎた場合も、店舗が商品を棚に戻すまでは受け取れます。"
    "棚に戻した後は受け取れず、代金は返金されません。"
)


def request_hash(data):
    body = dict(
        storeId=str(data.store_id),
        shortagePolicy=data.shortage_policy,
        items=sorted(
            [
                dict(productVariantId=str(x.product_variant_id), quantity=x.quantity)
                for x in data.items
            ],
            key=lambda x: x["productVariantId"],
        ),
    )
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def ready_time(base, queue_minutes, work_minutes, closes):
    ready = base + timedelta(minutes=queue_minutes + work_minutes + 15)
    if ready.second or ready.microsecond:
        ready = ready.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if ready - base > timedelta(minutes=60) or ready > closes - timedelta(minutes=15):
        return ready, "CAPACITY_FULL"
    return ready, None


def queue_work(db, store_id, now, *, own=None, exclude_ids=()):
    start = datetime.combine(now.astimezone(JST).date(), datetime.min.time(), JST)
    conditions = [
        OrderEstimate.store_id == store_id,
        OrderEstimate.created_at >= start,
        OrderEstimate.created_at < start + timedelta(days=1),
    ]
    if exclude_ids:
        conditions.append(OrderEstimate.id.not_in(exclude_ids))
    conditions.append(
        tuple_(OrderEstimate.created_at, OrderEstimate.id) < tuple_(own.created_at, own.id)
        if own
        else OrderEstimate.created_at <= now
    )
    estimates = db.scalar(
        select(func.coalesce(func.sum(OrderEstimate.work_minutes), 0)).where(
            *conditions, OrderEstimate.status == "HELD", OrderEstimate.expires_at > now
        )
    )
    orders = db.scalar(
        select(func.coalesce(func.sum(Order.work_minutes), 0))
        .join(OrderEstimate, Order.estimate_id == OrderEstimate.id)
        .where(
            *conditions,
            or_(
                Order.status.in_(["RECEIVED", "PREPARING", "ACTION_REQUIRED"]),
                (Order.status == "PENDING_PAYMENT") & (Order.hold_expires_at > now),
            ),
        )
    )
    return int(estimates + orders)


def acceptance(db, store, now):
    if not store.accepting_orders:
        return None, "STORE_NOT_ACCEPTING"
    hours = business_hours(db, store, now.astimezone(JST).date())
    if hours is None or now > hours[1] - timedelta(minutes=60):
        return hours, "ORDER_CLOSED"
    return hours, None


def validated_rows(db, data):
    store = db.get(Store, str(data.store_id))
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND")
    if sum(x.quantity for x in data.items) > 10:
        raise ApiError(422, "ORDER_LIMIT_EXCEEDED")
    rows = pos_rows(db, store.id, data.items)
    return store, rows


def create_estimate(db, user, data, now, settings):
    store, rows = validated_rows(db, data)
    store = db.scalar(
        select(Store)
        .where(Store.id == store.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Re-read after obtaining the store lock; previews do not reserve inventory.
    rows = pos_rows(db, store.id, data.items)
    quote = calculate_lines(rows, data.items)
    hours, rejection = acceptance(db, store, now)
    previous = db.scalars(
        select(OrderEstimate).where(
            OrderEstimate.user_id == user.id,
            OrderEstimate.store_id == store.id,
            OrderEstimate.status == "HELD",
        )
    ).all()
    details = None
    if not rejection and not quote["allOk"]:
        rejection, details = "OUT_OF_STOCK", {"lines": [x for x in quote["lines"] if not x["ok"]]}
    work = 2 * quote["totalQuantity"] + 10
    ready = None
    if not rejection:
        queue = queue_work(db, store.id, now, exclude_ids=[x.id for x in previous])
        ready, rejection = ready_time(max(now, hours[0]), queue, work, hours[1])
    result = dict(
        accepted=not rejection,
        rejectionCode=rejection,
        rejectionDetails=details,
        storeId=store.id,
        storeName=store.name,
        items=quote["lines"],
        totalQuantity=quote["totalQuantity"],
        totalAmountYen=quote["totalAmountYen"],
        shortagePolicy=data.shortage_policy,
        estimateId=None,
        estimatedReadyAt=None,
        estimateExpiresAt=None,
        pickupDeadlineRuleText=PICKUP_RULE,
        overduePolicyText=settings.overdue_policy_text or OVERDUE,
    )
    if not rejection:
        for old in previous:
            old.status = "EXPIRED"
        new = OrderEstimate(
            id=str(uuid4()),
            user_id=user.id,
            store_id=store.id,
            request_hash=request_hash(data),
            items=[x.model_dump(mode="json", by_alias=True) for x in data.items],
            shortage_policy=data.shortage_policy,
            total_quantity=quote["totalQuantity"],
            total_amount_yen=quote["totalAmountYen"],
            work_minutes=work,
            estimated_ready_at=ready,
            status="HELD",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        db.add(new)
        result.update(
            estimateId=new.id,
            estimatedReadyAt=ready.astimezone(JST),
            estimateExpiresAt=new.expires_at.astimezone(JST),
        )
    db.commit()
    return result
