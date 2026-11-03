from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.models import Inventory, InventoryReservation, Order, OrderItem, Payment
from app.services.business_calendar import JST
from app.services.order_queries import detail, summary, sync_time
from app.services.stock_pos import timestamp

TABS = ("ACTIVE", "DELAYED", "ACTION_REQUIRED", "READY", "EXPIRED", "DONE")


def inventory_values(db, order):
    rows = db.execute(
        select(OrderItem.id, Inventory)
        .join(InventoryReservation, InventoryReservation.order_item_id == OrderItem.id)
        .join(Inventory, InventoryReservation.inventory_id == Inventory.id)
        .where(OrderItem.order_id == order.id)
    ).all()
    return {ident: inv for ident, inv in rows}


def staff_detail(db, order):
    result = detail(db, order)
    for key in ("pickup", "canCancel", "canReissuePickupCode"):
        result.pop(key)
    values = inventory_values(db, order)
    for item in result["items"]:
        inv = values[item["orderItemId"]]
        item.update(
            onHandQuantity=inv.on_hand_quantity,
            shortageRiskQuantity=max(0, inv.reserved_quantity - inv.on_hand_quantity),
        )
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    result["payment"] = dict(
        status=payment.status,
        authorizedAmountYen=payment.authorized_amount_yen,
        capturedAmountYen=payment.captured_amount_yen,
        failureCode=payment.failure_code,
    )
    actions = []
    if order.status == "RECEIVED":
        actions = ["START_PREPARATION", "REGISTER_DELAY"]
    elif order.status == "PREPARING":
        actions = ["REGISTER_DELAY"]
        if payment.status == "AUTHORIZED":
            actions += ["REGISTER_SHORTAGE", "MARK_READY"]
    elif order.status == "ACTION_REQUIRED":
        actions = ["REGISTER_DELAY"]
        if payment.status == "AUTHORIZED" or (
            payment.status == "FAILED" and payment.last_operation == "CAPTURE"
        ):
            actions += ["MARK_READY"]
    elif order.status == "EXPIRED":
        actions = ["RETURN_TO_STOCK"]
    result["allowedActions"] = actions
    return result


def tab_query(store_id, tab, now):
    stmt = select(Order).where(Order.store_id == store_id)
    if tab == "ACTIVE":
        stmt = stmt.where(Order.status.in_(["RECEIVED", "PREPARING"]))
    elif tab == "DELAYED":
        stmt = stmt.where(
            Order.is_delayed.is_(True),
            Order.status.in_(["RECEIVED", "PREPARING", "ACTION_REQUIRED"]),
        )
    elif tab == "DONE":
        day = datetime.combine(now.astimezone(JST).date(), datetime.min.time(), JST)
        done_at = func.coalesce(Order.picked_up_at, Order.cancelled_at, Order.returned_to_stock_at)
        stmt = stmt.where(
            Order.status.in_(["PICKED_UP", "CANCELLED", "EXPIRED_RETURNED"]),
            done_at >= day,
            done_at < day + timedelta(days=1),
        )
        return stmt.order_by(done_at.desc(), Order.id)
    else:
        stmt = stmt.where(Order.status == tab)
    column = {"READY": Order.ready_at, "EXPIRED": Order.expired_at}.get(tab, Order.accepted_at)
    return stmt.order_by(column, Order.id)


def list_orders(db, store_id, tab, page, page_size, settings, now):
    active = db.scalars(
        select(Order)
        .where(
            Order.store_id == store_id,
            Order.status.in_(["RECEIVED", "PREPARING", "ACTION_REQUIRED", "READY"]),
        )
        .order_by(Order.id)
        .with_for_update()
    ).all()
    for order in active:
        sync_time(db, order, settings, now)
    db.flush()
    counts = {
        code: db.scalar(
            select(func.count()).select_from(
                tab_query(store_id, code, now).order_by(None).subquery()
            )
        )
        for code in TABS
    }
    orders = db.scalars(
        tab_query(store_id, tab, now).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for order in orders:
        result = summary(db, order)
        values = inventory_values(db, order)
        items.append(
            dict(
                orderId=order.id,
                orderNumber=order.order_number,
                status=order.status,
                statusLabel=result["statusLabel"],
                acceptedAt=timestamp(order.accepted_at),
                originalReadyAt=result["originalReadyAt"],
                currentReadyAt=result["currentReadyAt"],
                isDelayed=order.is_delayed,
                delayPending=order.is_delayed and order.updated_ready_at is None,
                totalQuantity=order.total_quantity,
                shortageRisk=any(x.on_hand_quantity < x.reserved_quantity for x in values.values()),
                pickupDeadlineAt=timestamp(order.pickup_deadline_at),
            )
        )
    db.commit()
    return dict(
        items=items, tabCounts=counts, page=page, pageSize=page_size, totalCount=counts[tab]
    )
