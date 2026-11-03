from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from app.config import (
    BUFFER_MINUTES,
    CLOSE_MARGIN_MINUTES,
    MAX_LEAD_MINUTES,
    ORDER_CUTOFF_MINUTES,
    TIMEZONE,
    WORK_MINUTES_PER_ITEM,
    WORK_MINUTES_PER_ORDER,
)
from app.models import BusinessHours, Order, OrderEstimate

JST = ZoneInfo(TIMEZONE)


def business_hours(db, store, day):
    override = db.execute(
        select(BusinessHours).where(
            BusinessHours.store_id == store.id, BusinessHours.business_date == day
        )
    ).scalar_one_or_none()
    if override:
        if override.closed:
            return None
        opening, closing = override.opens_at, override.closes_at
    else:
        if day.isoweekday() in store.regular_closed_weekdays:
            return None
        opening, closing = store.default_opens_at, store.default_closes_at
    return datetime.combine(day, opening, JST), datetime.combine(day, closing, JST)


def preview_store(db, store, now):
    local = now.astimezone(JST)
    hours = business_hours(db, store, local.date())
    cutoff = hours[1] - timedelta(minutes=ORDER_CUTOFF_MINUTES) if hours else None
    can_order = bool(store.accepting_orders and hours and local <= cutoff)
    earliest = None
    if can_order:
        start = datetime.combine(local.date(), datetime.min.time(), JST)
        end = start + timedelta(days=1)
        today = (
            OrderEstimate.created_at >= start,
            OrderEstimate.created_at < end,
            OrderEstimate.created_at <= now,
        )
        queued_orders = db.execute(
            select(func.coalesce(func.sum(Order.work_minutes), 0))
            .join(OrderEstimate, Order.estimate_id == OrderEstimate.id)
            .where(
                Order.store_id == store.id,
                *today,
                or_(
                    Order.status.in_(["RECEIVED", "PREPARING", "ACTION_REQUIRED"]),
                    (Order.status == "PENDING_PAYMENT") & (Order.hold_expires_at > now),
                ),
            )
        ).scalar_one()
        queued_estimates = db.execute(
            select(func.coalesce(func.sum(OrderEstimate.work_minutes), 0)).where(
                OrderEstimate.store_id == store.id,
                *today,
                OrderEstimate.status == "HELD",
                OrderEstimate.expires_at > now,
            )
        ).scalar_one()
        base = max(local, hours[0])
        ready = base + timedelta(
            minutes=int(queued_orders)
            + int(queued_estimates)
            + WORK_MINUTES_PER_ITEM
            + WORK_MINUTES_PER_ORDER
            + BUFFER_MINUTES
        )
        if ready.second or ready.microsecond:
            ready = ready.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if ready <= base + timedelta(minutes=MAX_LEAD_MINUTES) and ready <= hours[1] - timedelta(
            minutes=CLOSE_MARGIN_MINUTES
        ):
            earliest = ready
    return {
        "store_id": store.id,
        "code": store.code,
        "name": store.name,
        "address": store.address,
        "today": {
            "date": local.date(),
            "closed": hours is None,
            "opens_at": hours[0].strftime("%H:%M") if hours else None,
            "closes_at": hours[1].strftime("%H:%M") if hours else None,
        },
        "accepting_orders": store.accepting_orders,
        "order_cutoff_at": cutoff,
        "can_order_now": can_order,
        "earliest_ready_at": earliest,
    }


def next_closing(db, store, start_day):
    from app.errors import ApiError

    for offset in range(31):
        hours = business_hours(db, store, start_day + timedelta(days=offset))
        if hours:
            return hours[1]
    raise ApiError(500, "NO_BUSINESS_DAY")


def pickup_deadline(db, store, ready_at):
    return next_closing(db, store, ready_at.astimezone(JST).date() + timedelta(days=7))
