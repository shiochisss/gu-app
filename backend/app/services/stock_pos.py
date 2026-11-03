from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.errors import ApiError
from app.models import (
    AuditLog,
    Inventory,
    InventoryReservation,
    InventoryTransaction,
    NumberCounter,
    Order,
    OrderItem,
    PosSale,
    PosSaleItem,
    Product,
    ProductVariant,
    User,
)

JST = ZoneInfo("Asia/Tokyo")
LABELS = dict(
    INITIAL="初期登録",
    RECEIVE="入荷",
    POS_SALE="店頭販売",
    POS_VOID="店頭販売の取消",
    EC_PICKUP_OUT="EC注文の準備完了",
    EC_SHORTAGE="EC注文の欠品",
    EC_CANCEL_RETURN="EC注文の取消で戻し",
    EC_EXPIRED_RETURN="受取期限切れで戻し",
    STOCKTAKE="棚卸",
    DAMAGE="破損・紛失",
)


def timestamp(value):
    return value.astimezone(JST).isoformat() if value else None


def catalog_query(store_id, active=False):
    stmt = (
        select(Inventory, ProductVariant, Product)
        .join(ProductVariant, Inventory.product_variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(Inventory.store_id == store_id)
    )
    if active:
        stmt = stmt.where(ProductVariant.is_active.is_(True), Product.is_active.is_(True))
    return stmt


def inventory_info(row):
    inv, variant, product = row
    return dict(
        inventoryId=inv.id,
        productVariantId=variant.id,
        sku=variant.sku,
        productName=product.name,
        colorName=variant.color_name,
        size=variant.size,
        priceYen=variant.price_yen,
        onHandQuantity=inv.on_hand_quantity,
        reservedQuantity=inv.reserved_quantity,
        availableQuantity=max(0, inv.on_hand_quantity - inv.reserved_quantity),
        shortageRiskQuantity=max(0, inv.reserved_quantity - inv.on_hand_quantity),
        version=inv.version,
        updatedAt=timestamp(inv.updated_at),
    )


def inventory_row(db, store_id, inventory_id, lock=False):
    # Lock only inventory rows, consistently ordered across every mutation.
    stmt = select(Inventory).where(Inventory.id == inventory_id, Inventory.store_id == store_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    inv = db.scalar(stmt)
    if inv is None:
        raise ApiError(404, "NOT_FOUND")
    return (
        inv,
        db.get(ProductVariant, inv.product_variant_id),
        db.get(Product, db.get(ProductVariant, inv.product_variant_id).product_id),
    )


def paged(db, stmt, page, page_size, serialize):
    count = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return dict(
        items=[serialize(row) for row in rows], page=page, pageSize=page_size, totalCount=count
    )


def audit(db, user, store_id, target_type, target_id, action, before, after, now, reason=None):
    db.add(
        AuditLog(
            store_id=store_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            actor_user_id=user.id if user else None,
            actor_type="STAFF",
            before_value=before,
            after_value=after,
            reason=reason,
            occurred_at=now,
        )
    )


def change_stock(db, inv, delta, kind, user, now, *, counted=None, reason=None, sale_id=None):
    inv.on_hand_quantity += delta
    inv.version += 1
    inv.updated_at = now
    tx = InventoryTransaction(
        id=str(uuid4()),
        inventory_id=inv.id,
        type=kind,
        quantity_delta=delta,
        on_hand_after=inv.on_hand_quantity,
        counted_quantity=counted,
        reason=reason,
        actor_user_id=user.id if user else None,
        reference_type="POS_SALE" if sale_id else None,
        reference_id=sale_id,
        occurred_at=now,
    )
    db.add(tx)
    return tx


def adjust(db, user, store_id, inventory_id, data, now):
    row = inventory_row(db, store_id, inventory_id, lock=True)
    inv = row[0]
    if inv.version != data.version:
        raise ApiError(409, "CONFLICTING_UPDATE", latest_resource=inventory_info(row))
    kind = getattr(data, "type", "RECEIVE")
    before = inv.on_hand_quantity
    counted = None
    if kind == "STOCKTAKE":
        counted = data.counted_quantity
        delta = counted - before
        if delta and not (data.reason or "").strip():
            raise ApiError(400, "VALIDATION_ERROR")
    else:
        delta = data.quantity * (-1 if kind == "DAMAGE" else 1)
        if before + delta < 0:
            raise ApiError(409, "INSUFFICIENT_STOCK")
    tx = change_stock(db, inv, delta, kind, user, now, counted=counted, reason=data.reason)
    action = {
        "RECEIVE": "INVENTORY_RECEIVED",
        "STOCKTAKE": "INVENTORY_STOCKTAKE",
        "DAMAGE": "INVENTORY_DAMAGED",
    }[kind]
    audit(
        db,
        user,
        store_id,
        "INVENTORY",
        inv.id,
        action,
        {"on_hand_quantity": before},
        {"on_hand_quantity": inv.on_hand_quantity},
        now,
        data.reason,
    )
    risk = max(0, inv.reserved_quantity - inv.on_hand_quantity)
    count = 0
    if risk:
        count = db.scalar(
            select(func.count(func.distinct(Order.id)))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(InventoryReservation, InventoryReservation.order_item_id == OrderItem.id)
            .where(
                InventoryReservation.inventory_id == inv.id,
                InventoryReservation.status == "CONFIRMED",
                Order.status.in_(["RECEIVED", "PREPARING"]),
            )
        )
    db.flush()
    return 200, dict(
        inventory=inventory_info(row),
        transactionId=tx.id,
        shortageRiskQuantity=risk,
        shortageRiskOrderCount=count,
    )


def pos_rows(db, store_id, items, lock=False):
    ids = [str(item.product_variant_id) for item in items]
    if lock:
        db.scalars(
            select(Inventory)
            .where(Inventory.store_id == store_id, Inventory.product_variant_id.in_(ids))
            .order_by(Inventory.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    rows = db.execute(catalog_query(store_id, active=True).where(ProductVariant.id.in_(ids))).all()
    mapping = {row[1].id: row for row in rows}
    missing = [value for value in ids if value not in mapping]
    if missing:
        raise ApiError(404, "PRODUCT_NOT_FOUND", details={"productVariantId": missing[0]})
    return [mapping[value] for value in ids]


def estimate(rows, items):
    lines = []
    for row, item in zip(rows, items, strict=True):
        inv, variant, product = row
        available = max(0, inv.on_hand_quantity - inv.reserved_quantity)
        ok = item.quantity <= available
        reason = (
            None
            if ok
            else ("RESERVED_FOR_EC" if item.quantity <= inv.on_hand_quantity else "OUT_OF_STOCK")
        )
        lines.append(
            dict(
                productVariantId=variant.id,
                sku=variant.sku,
                productName=product.name,
                colorName=variant.color_name,
                size=variant.size,
                unitPriceYen=variant.price_yen,
                quantity=item.quantity,
                lineAmountYen=variant.price_yen * item.quantity,
                availableQuantity=available,
                reservedQuantity=inv.reserved_quantity,
                ok=ok,
                reasonCode=reason,
            )
        )
    return dict(
        lines=lines,
        totalQuantity=sum(x["quantity"] for x in lines),
        totalAmountYen=sum(x["lineAmountYen"] for x in lines),
        allOk=all(x["ok"] for x in lines),
    )


def sale_info(db, sale, now, extended=False):
    lines = db.scalars(
        select(PosSaleItem).where(PosSaleItem.pos_sale_id == sale.id).order_by(PosSaleItem.line_no)
    ).all()
    result = dict(
        saleId=sale.id,
        saleNumber=sale.sale_number,
        status=sale.status,
        totalQuantity=sale.total_quantity,
        totalAmountYen=sale.total_amount_yen,
        paymentMethod=sale.payment_method,
        soldAt=timestamp(sale.sold_at),
        lines=[
            dict(
                productVariantId=x.product_variant_id,
                sku=x.sku,
                productName=x.product_name,
                colorName=x.color_name,
                size=x.size,
                unitPriceYen=x.unit_price_yen,
                quantity=x.quantity,
                lineAmountYen=x.unit_price_yen * x.quantity,
            )
            for x in lines
        ],
    )
    if extended:
        result.update(
            voidedAt=timestamp(sale.voided_at),
            voidReason=sale.void_reason,
            staffEmail=db.get(User, sale.staff_user_id).email,
            version=sale.version,
            canVoid=sale.status == "COMPLETED"
            and sale.sold_at.astimezone(JST).date() == now.astimezone(JST).date(),
        )
    return result


def sell(db, user, store_id, data, now):
    rows = pos_rows(db, store_id, data.items, lock=True)
    quote = estimate(rows, data.items)
    if not quote["allOk"]:
        raise ApiError(409, "INSUFFICIENT_STOCK", details={"lines": quote["lines"]})
    if quote["totalAmountYen"] != data.client_total_amount_yen:
        raise ApiError(409, "CALCULATION_CHANGED")
    counter = db.scalar(
        select(NumberCounter).where(NumberCounter.name == "pos_sale_number_seq").with_for_update()
    )
    number = counter.next_value
    counter.next_value += 1
    sale = PosSale(
        id=str(uuid4()),
        sale_number=f"S{number:06d}",
        store_id=store_id,
        staff_user_id=user.id,
        status="COMPLETED",
        payment_method=data.payment_method,
        total_quantity=quote["totalQuantity"],
        total_amount_yen=quote["totalAmountYen"],
        sold_at=now,
        version=0,
    )
    db.add(sale)
    db.flush()
    for index, (row, item) in enumerate(zip(rows, data.items, strict=True), 1):
        inv, variant, product = row
        db.add(
            PosSaleItem(
                pos_sale_id=sale.id,
                line_no=index,
                product_variant_id=variant.id,
                product_name=product.name,
                sku=variant.sku,
                color_name=variant.color_name,
                size=variant.size,
                quantity=item.quantity,
                unit_price_yen=variant.price_yen,
            )
        )
        change_stock(db, inv, -item.quantity, "POS_SALE", user, now, sale_id=sale.id)
    audit(
        db,
        user,
        store_id,
        "POS_SALE",
        sale.id,
        "POS_SALE_CREATED",
        None,
        {"status": sale.status, "total_amount_yen": sale.total_amount_yen},
        now,
    )
    db.flush()
    return 201, sale_info(db, sale, now)


def void(db, user, store_id, sale_id, data, now):
    sale = db.scalar(
        select(PosSale)
        .where(PosSale.id == sale_id, PosSale.store_id == store_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if sale is None:
        raise ApiError(404, "NOT_FOUND")
    if (
        sale.status != "COMPLETED"
        or sale.sold_at.astimezone(JST).date() != now.astimezone(JST).date()
    ):
        raise ApiError(409, "INVALID_STATE")
    if sale.version != data.version:
        raise ApiError(409, "CONFLICTING_UPDATE", latest_resource=sale_info(db, sale, now, True))
    items = db.scalars(select(PosSaleItem).where(PosSaleItem.pos_sale_id == sale.id)).all()
    ids = [x.product_variant_id for x in items]
    invs = db.scalars(
        select(Inventory)
        .where(Inventory.store_id == store_id, Inventory.product_variant_id.in_(ids))
        .order_by(Inventory.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    quantities = {x.product_variant_id: x.quantity for x in items}
    for inv in invs:
        change_stock(
            db, inv, quantities[inv.product_variant_id], "POS_VOID", user, now, sale_id=sale.id
        )
    sale.status, sale.voided_at, sale.voided_by = "VOIDED", now, user.id
    sale.void_reason, sale.version = data.reason, sale.version + 1
    audit(
        db,
        user,
        store_id,
        "POS_SALE",
        sale.id,
        "POS_SALE_VOIDED",
        {"status": "COMPLETED", "total_amount_yen": sale.total_amount_yen},
        {"status": "VOIDED", "total_amount_yen": sale.total_amount_yen},
        now,
        data.reason,
    )
    db.flush()
    return 200, sale_info(db, sale, now, True)


def sales_for_date(store_id, day):
    start = datetime.combine(day, time(), JST)
    return select(PosSale).where(
        PosSale.store_id == store_id,
        PosSale.sold_at >= start,
        PosSale.sold_at < start + timedelta(days=1),
    )


def transaction_info(db, tx):
    label = None
    if tx.reference_type == "POS_SALE":
        sale = db.get(PosSale, tx.reference_id)
        label = sale.sale_number if sale else None
    elif tx.reference_type == "ORDER_ITEM":
        item = db.get(OrderItem, tx.reference_id)
        order = db.get(Order, item.order_id) if item else None
        label = order.order_number if order else None
    actor = db.get(User, tx.actor_user_id) if tx.actor_user_id else None
    return dict(
        transactionId=tx.id,
        type=tx.type,
        typeLabel=LABELS[tx.type],
        quantityDelta=tx.quantity_delta,
        onHandAfter=tx.on_hand_after,
        countedQuantity=tx.counted_quantity,
        referenceLabel=label,
        reason=tx.reason,
        actorEmail=actor.email if actor else None,
        occurredAt=timestamp(tx.occurred_at),
    )
