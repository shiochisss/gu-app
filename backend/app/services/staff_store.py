from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.errors import ApiError
from app.models import AuditLog, BusinessHours, Order, Store
from app.services.business_calendar import JST, business_hours
from app.services.stock_pos import timestamp


def info(db, store, now):
    days = []
    for offset in range(14):
        day = now.astimezone(JST).date() + timedelta(days=offset)
        override = db.scalar(
            select(BusinessHours).where(
                BusinessHours.store_id == store.id, BusinessHours.business_date == day
            )
        )
        hours = business_hours(db, store, day)
        days.append(
            dict(
                date=day.isoformat(),
                closed=hours is None,
                opensAt=hours[0].strftime("%H:%M") if hours else None,
                closesAt=hours[1].strftime("%H:%M") if hours else None,
                source="OVERRIDE" if override else "DEFAULT",
                overrideVersion=override.version if override else None,
            )
        )
    return dict(
        storeId=store.id,
        name=store.name,
        acceptingOrders=store.accepting_orders,
        acceptanceReason=store.acceptance_reason,
        acceptanceChangedAt=timestamp(store.acceptance_changed_at),
        version=store.version,
        defaultHours=dict(
            opensAt=store.default_opens_at.strftime("%H:%M"),
            closesAt=store.default_closes_at.strftime("%H:%M"),
            regularClosedWeekdays=store.regular_closed_weekdays,
        ),
        days=days,
        warnings=[],
    )


def audit(db, user, store, target, ident, action, before, after, now, reason=None):
    db.add(
        AuditLog(
            store_id=store.id,
            target_type=target,
            target_id=ident,
            action=action,
            actor_user_id=user.id,
            actor_type="STAFF",
            before_value=before,
            after_value=after,
            reason=reason,
            occurred_at=now,
        )
    )


def acceptance(db, user, store_id, data, now):
    store = db.scalar(
        select(Store)
        .where(Store.id == store_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if store.version != data.version:
        raise ApiError(409, "CONFLICTING_UPDATE", latest_resource=info(db, store, now))
    if not data.accepting_orders and not (data.reason or "").strip():
        raise ApiError(400, "VALIDATION_ERROR")
    before = dict(accepting_orders=store.accepting_orders)
    store.accepting_orders = data.accepting_orders
    store.acceptance_reason = None if data.accepting_orders else data.reason.strip()
    store.acceptance_changed_at = store.updated_at = now
    store.version += 1
    audit(
        db,
        user,
        store,
        "STORE",
        store.id,
        "STORE_ACCEPTANCE_CHANGED",
        before,
        dict(accepting_orders=store.accepting_orders),
        now,
        store.acceptance_reason,
    )
    db.flush()
    result = info(db, store, now)
    db.commit()
    return result


def change_hours(db, user, store_id, day, data, now):
    today = now.astimezone(JST).date()
    if not today <= day <= today + timedelta(days=60):
        raise ApiError(400, "VALIDATION_ERROR")
    store = db.scalar(select(Store).where(Store.id == store_id).with_for_update())
    row = db.scalar(
        select(BusinessHours)
        .where(BusinessHours.store_id == store_id, BusinessHours.business_date == day)
        .with_for_update()
    )
    if (row and row.version != data.version) or (not row and data.version is not None):
        raise ApiError(409, "CONFLICTING_UPDATE")
    before = (
        dict(closed=row.closed, opens_at=str(row.opens_at), closes_at=str(row.closes_at))
        if row
        else None
    )
    ident = row.id if row else store.id
    if data.use_default:
        if row:
            db.delete(row)
    else:
        if row is None:
            row = BusinessHours(store_id=store_id, business_date=day, created_at=now, version=0)
            db.add(row)
        else:
            row.version += 1
        row.closed, row.updated_by, row.updated_at = data.closed, user.id, now
        row.opens_at, row.closes_at = (
            (None, None) if data.closed else (data.opens_at, data.closes_at)
        )
        db.flush()
        ident = row.id
    audit(
        db,
        user,
        store,
        "BUSINESS_HOURS",
        ident,
        "BUSINESS_HOURS_CHANGED",
        before,
        dict(
            use_default=data.use_default,
            closed=data.closed,
            opens_at=str(data.opens_at),
            closes_at=str(data.closes_at),
        ),
        now,
    )
    db.flush()
    result = info(db, store, now)
    hours = business_hours(db, store, day)
    if day == today:
        end = hours[1] if hours else datetime.combine(day, datetime.min.time(), JST)
        start = datetime.combine(day, datetime.min.time(), JST)
        count = db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.store_id == store_id,
                Order.status.in_(["RECEIVED", "PREPARING"]),
                Order.accepted_at >= start,
                Order.accepted_at < start + timedelta(days=1),
                func.coalesce(Order.updated_ready_at, Order.original_ready_at) > end,
            )
        )
        if count:
            result["warnings"] = [f"今日の受付済み注文のうち{count}件の予定時刻が閉店後になります"]
    db.commit()
    return result
