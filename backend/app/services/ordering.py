import json
import logging
from datetime import timedelta
from uuid import uuid4

from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.errors import ApiError, error_response
from app.models import (
    IdempotencyRecord,
    InventoryReservation,
    NumberCounter,
    Order,
    OrderEstimate,
    OrderItem,
    Payment,
    Store,
)
from app.payments.gateway import GatewayError
from app.services import estimate
from app.services.business_calendar import JST
from app.services.idempotency import claim
from app.services.payment_states import (
    apply_payment_intent,
    audit,
    fail_authorization,
    locked_payment,
    mark_unknown,
)
from app.services.stock_pos import estimate as calculate_lines
from app.services.stock_pos import pos_rows

logger = logging.getLogger("pickup")


def created_response(order, payment, intent=None):
    action = None
    if (
        order.status == "PENDING_PAYMENT"
        and payment.status == "REQUIRES_ACTION"
        and intent
        and intent.get("client_secret")
    ):
        action = dict(type="STRIPE_HANDLE_NEXT_ACTION", clientSecret=intent["client_secret"])
    return dict(
        orderId=order.id,
        orderNumber=order.order_number,
        status=order.status,
        paymentStatus=payment.status,
        originalReadyAt=order.original_ready_at.astimezone(JST).isoformat(),
        nextAction=action,
    )


def stage_one(db, user, data, now):
    # Store -> estimate -> inventories (sorted) -> counter; new order rows are private.
    store = db.scalar(
        select(Store)
        .where(Store.id == str(data.store_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND")
    quoted = db.scalar(
        select(OrderEstimate).where(OrderEstimate.id == str(data.estimate_id)).with_for_update()
    )
    if (
        quoted is None
        or quoted.user_id != user.id
        or quoted.store_id != store.id
        or quoted.status != "HELD"
        or quoted.expires_at <= now
    ):
        raise ApiError(409, "ESTIMATE_EXPIRED")
    if quoted.request_hash != estimate.request_hash(data):
        raise ApiError(409, "CALCULATION_CHANGED")
    if not data.agreed_to_pickup_terms:
        raise ApiError(422, "TERMS_NOT_AGREED")
    hours, rejection = estimate.acceptance(db, store, now)
    if rejection:
        raise ApiError(422, rejection)
    rows = pos_rows(db, store.id, data.items, lock=True)
    quote = calculate_lines(rows, data.items)
    if not quote["allOk"]:
        raise ApiError(
            422, "OUT_OF_STOCK", details={"lines": [x for x in quote["lines"] if not x["ok"]]}
        )
    queue = estimate.queue_work(db, store.id, now, own=quoted, exclude_ids=[quoted.id])
    ready, _ = estimate.ready_time(
        max(quoted.created_at, hours[0]), queue, quoted.work_minutes, hours[1]
    )
    latest = dict(
        totalAmountYen=quote["totalAmountYen"], estimatedReadyAt=ready.astimezone(JST).isoformat()
    )
    if (
        quote["totalAmountYen"] != data.client_total_amount_yen
        or ready > quoted.estimated_ready_at + timedelta(minutes=5)
        or data.client_estimated_ready_at != quoted.estimated_ready_at
    ):
        raise ApiError(409, "CALCULATION_CHANGED", latest_resource=latest)
    seq = db.scalar(
        select(NumberCounter).where(NumberCounter.name == "order_number_seq").with_for_update()
    )
    number, seq.next_value = seq.next_value, seq.next_value + 1
    order = Order(
        id=str(uuid4()),
        order_number=f"P{number:06d}",
        purchaser_id=user.id,
        store_id=store.id,
        estimate_id=quoted.id,
        status="PENDING_PAYMENT",
        shortage_policy=data.shortage_policy,
        total_quantity=quote["totalQuantity"],
        ordered_amount_yen=quote["totalAmountYen"],
        work_minutes=quoted.work_minutes,
        pickup_terms_agreed_at=now,
        hold_expires_at=now + timedelta(minutes=15),
        original_ready_at=quoted.estimated_ready_at,
        created_at=now,
        updated_at=now,
        version=0,
    )
    db.add(order)
    db.flush()
    for index, (row, item) in enumerate(zip(rows, data.items, strict=True), 1):
        inv, variant, product = row
        detail = OrderItem(
            id=str(uuid4()),
            order_id=order.id,
            line_no=index,
            product_variant_id=variant.id,
            product_name=product.name,
            sku=variant.sku,
            color_name=variant.color_name,
            size=variant.size,
            unit_price_yen=variant.price_yen,
            ordered_quantity=item.quantity,
            shortage_quantity=0,
        )
        db.add(detail)
        db.flush()
        db.add(
            InventoryReservation(
                order_item_id=detail.id,
                inventory_id=inv.id,
                quantity=item.quantity,
                status="HELD",
                expires_at=order.hold_expires_at,
                created_at=now,
                updated_at=now,
            )
        )
        inv.reserved_quantity += item.quantity
        inv.version += 1
        inv.updated_at = now
    payment = Payment(
        id=str(uuid4()),
        order_id=order.id,
        status="AUTHORIZING",
        last_operation="AUTHORIZE",
        operation_attempt=1,
        authorized_amount_yen=order.ordered_amount_yen,
        operation_started_at=now,
        created_at=now,
        updated_at=now,
        version=0,
    )
    db.add(payment)
    quoted.status = "USED"
    db.flush()
    audit(db, order, "ORDER_REQUESTED", "ORDER", None, {"status": order.status}, now, user=user)
    return (
        order,
        payment,
        dict(order_id=order.id, order_number=order.order_number, store_code=store.code),
    )


def create_order(db, request, user, key, data):
    record, cached = claim(db, request, user, key)
    if cached is not None:
        return cached
    identity = (record.user_id, record.endpoint, record.idempotency_key)
    settings, clock = request.app.state.settings, request.app.state.clock
    gateway = request.app.state.payment_gateway
    # The fallback orderId is written atomically with stage 1. A crashed worker
    # can resume after lease expiry without using the ConfirmationToken again.
    if record.response_body:
        order, payment = locked_payment(db, record.response_body["orderId"])
        mark_unknown(db, order, payment, clock.now())
        body = created_response(order, payment)
        record.response_status, record.response_body = 202, body
        db.commit()
        return JSONResponse(body, status_code=202)
    committing = False
    try:
        with db.begin_nested():
            order, payment, metadata = stage_one(db, user, data, clock.now())
        record.response_body = created_response(order, payment)
        order_id, payment_id = order.id, payment.id
        amount = payment.authorized_amount_yen
        committing = True
        db.commit()
    except ApiError as exc:
        if exc.status >= 500:
            db.rollback()
            record = db.get(IdempotencyRecord, identity, with_for_update=True)
            db.delete(record)
            db.commit()
            raise
        response = error_response(request, exc.status, exc.code, **exc.payload)
        record.response_status, record.response_body = exc.status, json.loads(response.body)
        db.commit()
        return response
    except Exception:
        db.rollback()
        if committing:
            # COMMIT itself can succeed on MySQL while its acknowledgement is lost.
            # Recover the persisted order before deciding that stage one failed.
            fallback = dict(
                orderId=order_id,
                orderNumber=metadata["order_number"],
                status="PENDING_PAYMENT",
                paymentStatus="UNKNOWN",
                nextAction=None,
                originalReadyAt=data.client_estimated_ready_at.astimezone(JST).isoformat(),
            )
            fallback["paymentStatus"] = "UNKNOWN"
            try:
                record = db.get(
                    IdempotencyRecord, identity, with_for_update=True, populate_existing=True
                )
                if record.response_body:
                    order, payment = locked_payment(db, order_id)
                    mark_unknown(db, order, payment, clock.now())
                    fallback = created_response(order, payment)
                    record.response_status, record.response_body = 202, fallback
                    db.commit()
                    return JSONResponse(fallback, status_code=202)
            except Exception:
                db.rollback()
                logger.error("order commit outcome is unknown; preserve the operation key")
                return JSONResponse(fallback, status_code=202)
        record = db.get(IdempotencyRecord, identity, with_for_update=True)
        db.delete(record)
        db.commit()
        raise
    intent, failure = None, None
    try:
        # No DB reads or transactions between stage-one commit and this call.
        intent = gateway.authorize(
            amount, data.confirmation_token_id, metadata, f"{payment_id}:AUTHORIZE:1"
        )
    except GatewayError as exc:
        failure = exc
    except Exception:
        logger.error("unexpected authorization failure after order creation")
        failure = GatewayError()
    try:
        record = db.get(IdempotencyRecord, identity, with_for_update=True, populate_existing=True)
        order, payment = locked_payment(db, order_id)
        if intent:
            apply_payment_intent(db, order, payment, intent, settings, clock.now())
        elif failure and not failure.unknown:
            fail_authorization(db, order, payment, failure.code, settings, clock.now())
        else:
            mark_unknown(db, order, payment, clock.now())
        if payment.status == "FAILED" and order.status == "NOT_ACCEPTED":
            response = error_response(request, 422, "PAYMENT_DECLINED")
            status, body = 422, json.loads(response.body)
        else:
            status = 201 if order.status == "RECEIVED" else 202
            body = created_response(order, payment, intent)
        record.response_status, record.response_body = status, body
        db.commit()
        return JSONResponse(body, status_code=status)
    except Exception:
        db.rollback()
        logger.error("payment result could not be applied after order creation")
        # Preserve the committed order and recoverable key, even when stage 3 fails.
        body = dict(
            orderId=order_id,
            orderNumber=metadata["order_number"],
            status="PENDING_PAYMENT",
            paymentStatus="UNKNOWN",
            originalReadyAt=data.client_estimated_ready_at.astimezone(JST).isoformat(),
            nextAction=None,
        )
        try:
            record = db.get(
                IdempotencyRecord, identity, with_for_update=True, populate_existing=True
            )
            order, payment = locked_payment(db, order_id)
            mark_unknown(db, order, payment, clock.now())
            body = created_response(order, payment)
            record.response_status, record.response_body = 202, body
            db.commit()
        except Exception:
            db.rollback()
            logger.error("payment remains recoverable from committed order")
        return JSONResponse(body, status_code=202)
