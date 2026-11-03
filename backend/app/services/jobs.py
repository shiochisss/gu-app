import logging
from datetime import timedelta
from time import perf_counter

from sqlalchemy import delete, func, or_, select, update

from app.models import (
    IdempotencyRecord,
    Inventory,
    InventoryReservation,
    InventoryTransaction,
    JobRun,
    Order,
    OrderEstimate,
    Payment,
    RefreshToken,
)
from app.payments.budget import budget
from app.services import notifications
from app.services.order_queries import sync_time
from app.services.reconciliation import reconcile

logger = logging.getLogger("pickup")
DEFAULT_JOBS = ["J-01", "J-02", "J-03", "J-04", "J-05"]


def work(app, code, deadline):
    factory, now = app.state.session_factory, app.state.clock.now()
    if code in {"J-01", "J-05"}:
        stmt = select(Order.id)
        if code == "J-01":
            stmt = stmt.where(
                Order.status.in_(["RECEIVED", "PREPARING", "ACTION_REQUIRED"]),
                now > func.coalesce(Order.updated_ready_at, Order.original_ready_at),
                or_(Order.is_delayed.is_(False), Order.updated_ready_at.is_not(None)),
            )
        else:
            stmt = stmt.where(Order.status == "READY", Order.pickup_deadline_at < now)
        with factory() as db:
            ids = db.scalars(stmt.order_by(Order.id).limit(100)).all()
        count = 0
        for ident in ids:
            if perf_counter() >= deadline:
                break
            with factory() as db:
                order = db.scalar(select(Order).where(Order.id == ident).with_for_update())
                version = order.version
                sync_time(db, order, app.state.settings, now)
                db.commit()
                count += order.version != version
        return count
    if code in {"J-02", "J-03"}:
        count, remaining = 0, 100
        if code == "J-02":
            with factory() as db:
                rows = db.scalars(
                    select(OrderEstimate)
                    .where(OrderEstimate.status == "HELD", OrderEstimate.expires_at <= now)
                    .order_by(OrderEstimate.id)
                    .limit(100)
                    .with_for_update()
                ).all()
                for row in rows:
                    row.status = "EXPIRED"
                count, remaining = len(rows), 100 - len(rows)
                db.commit()
        with factory() as db:
            if code == "J-02":
                stmt = select(Order.id).where(
                    Order.status == "PENDING_PAYMENT", Order.hold_expires_at <= now
                )
            else:
                stmt = (
                    select(Payment.order_id)
                    .join(Order, Payment.order_id == Order.id)
                    .where(
                        Payment.operation_attempt < 5,
                        or_(
                            (Payment.status == "FAILED")
                            & or_(
                                (Payment.last_operation == "CAPTURE")
                                & (Order.status == "ACTION_REQUIRED"),
                                Payment.last_operation == "REFUND",
                                (Payment.last_operation == "RELEASE")
                                & (
                                    (Payment.failure_code.is_(None))
                                    | (Payment.failure_code != "CANCELED_BEFORE_AUTHORIZATION")
                                ),
                            ),
                            (
                                Payment.status.in_(
                                    [
                                        "AUTHORIZING",
                                        "REQUIRES_ACTION",
                                        "UNKNOWN",
                                        "CAPTURING",
                                        "RELEASING",
                                        "REFUNDING",
                                    ]
                                )
                            )
                            & (Payment.operation_started_at <= now - timedelta(minutes=5)),
                        ),
                    )
                )
            ids = db.scalars(stmt.order_by(stmt.selected_columns[0]).limit(remaining)).all()
        for ident in ids:
            if perf_counter() >= deadline:
                break
            count += reconcile(app, ident, expire=code == "J-02")
        return count
    if code == "J-04":
        return notifications.dispatch(
            factory, app.state.settings, app.state.clock, limit=100, deadline=deadline
        )
    if code == "J-06":
        with factory() as db:
            keys = db.execute(
                select(
                    IdempotencyRecord.user_id,
                    IdempotencyRecord.endpoint,
                    IdempotencyRecord.idempotency_key,
                )
                .where(IdempotencyRecord.expires_at <= now)
                .limit(100)
            ).all()
            count = 0
            for key in keys:
                row = db.get(IdempotencyRecord, tuple(key), with_for_update=True)
                if row and row.expires_at <= now:
                    db.delete(row)
                    count += 1
            # Clear incoming self-references before deleting only stale refresh rows.
            ids = db.scalars(
                select(RefreshToken.id)
                .where(
                    or_(
                        RefreshToken.expires_at < now - timedelta(days=7),
                        RefreshToken.revoked_at < now - timedelta(days=7),
                    )
                )
                .order_by(RefreshToken.id)
                .limit(100 - count)
            ).all()
            if ids:
                db.execute(
                    update(RefreshToken)
                    .where(RefreshToken.replaced_by_id.in_(ids))
                    .values(replaced_by_id=None)
                )
                db.execute(delete(RefreshToken).where(RefreshToken.id.in_(ids)))
            db.commit()
            return count + len(ids)
    if code == "J-07":
        with factory() as db:
            total = db.scalar(select(func.count()).select_from(Inventory))
            previous = db.scalar(
                select(func.count())
                .select_from(JobRun)
                .where(JobRun.job_code == code, JobRun.result == "SUCCESS")
            )
            offset = (previous * 100) % total if total > 100 else 0
            ids = db.scalars(
                select(Inventory.id).order_by(Inventory.id).offset(offset).limit(100)
            ).all()
            if offset and len(ids) < 100:
                ids += db.scalars(
                    select(Inventory.id).order_by(Inventory.id).limit(100 - len(ids))
                ).all()
        differences = 0
        for ident in ids:
            if perf_counter() >= deadline:
                break
            with factory() as db:
                inv = db.scalar(select(Inventory).where(Inventory.id == ident).with_for_update())
                physical = db.scalar(
                    select(func.coalesce(func.sum(InventoryTransaction.quantity_delta), 0)).where(
                        InventoryTransaction.inventory_id == ident
                    )
                )
                reserved = db.scalar(
                    select(
                        func.coalesce(
                            func.sum(
                                InventoryReservation.quantity
                                - InventoryReservation.shortage_quantity
                            ),
                            0,
                        )
                    ).where(
                        InventoryReservation.inventory_id == ident,
                        InventoryReservation.status.in_(["HELD", "CONFIRMED"]),
                    )
                )
                if inv.on_hand_quantity != physical or inv.reserved_quantity != reserved:
                    differences += 1
                    logger.warning(
                        "inventory mismatch id=%s on_hand=%s ledger=%s reserved=%s reservations=%s",
                        ident,
                        inv.on_hand_quantity,
                        physical,
                        inv.reserved_quantity,
                        reserved,
                    )
        return differences
    raise ValueError("unknown job")


def run_jobs(app, codes=None):
    deadline, results = perf_counter() + 25, []
    for code in codes if codes is not None else DEFAULT_JOBS:
        if code not in {"J-01", "J-02", "J-03", "J-04", "J-05", "J-06", "J-07"}:
            raise ValueError("unknown job")
        if perf_counter() >= deadline:
            break
        started, result, count = app.state.clock.now(), "ERROR", 0
        with app.state.engine.connect() as lock:
            name = "pickup:" + app.state.engine.url.database + ":" + code
            acquired = lock.scalar(select(func.get_lock(name, 0)))
            lock.commit()
            try:
                if acquired is None:
                    raise RuntimeError("job lock unavailable")
                if acquired != 1:
                    result = "SKIPPED_LOCKED"
                else:
                    with budget(deadline):
                        count = work(app, code, deadline)
                    result = "SUCCESS"
            except Exception:
                logger.error("job failed", exc_info=True)
            finally:
                if acquired == 1:
                    try:
                        if lock.scalar(select(func.release_lock(name))) != 1:
                            lock.invalidate()
                    except Exception:
                        lock.invalidate()
            with app.state.session_factory() as db:
                db.add(
                    JobRun(
                        job_code=code,
                        started_at=started,
                        finished_at=app.state.clock.now(),
                        result=result,
                        processed_count=count,
                        error_message="ジョブに失敗しました。ログを確認してください。"
                        if result == "ERROR"
                        else None,
                    )
                )
                db.commit()
        results.append(dict(job=code, result=result, processedCount=count))
    return dict(results=results)
