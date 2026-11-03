from typing import Annotated
from uuid import UUID

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import MESSAGES, ApiError
from app.models import Notification, Order, Payment, StaffProfile, User
from app.schemas.ordering import (
    EstimateInput,
    EstimateResponse,
    MailList,
    OrderCreated,
    OrderDetail,
    OrderInput,
    OrderList,
    PaymentConfirmation,
)
from app.security.auth import current_user
from app.services import estimate, notifications, order_queries, ordering, webhooks
from app.services.payment_states import apply_payment_intent, locked_payment
from app.services.stock_pos import timestamp

router = APIRouter(prefix="/api/v1", tags=["customer orders and payments"])
DB = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(current_user)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def customer(user: UserDep):
    if user.role != "CUSTOMER":
        raise ApiError(403, "FORBIDDEN")
    return user


Customer = Annotated[User, Depends(customer)]


async def raw_body(request: Request):
    request.state.idempotency_body = await request.json()


def schedule(request, tasks):
    state = request.app.state
    tasks.add_task(notifications.dispatch, state.session_factory, state.settings, state.clock)


@router.post("/orders/estimate", response_model=EstimateResponse)
def create_estimate(data: EstimateInput, request: Request, db: DB, user: Customer):
    return estimate.create_estimate(
        db, user, data, request.app.state.clock.now(), request.app.state.settings
    )


@router.post(
    "/orders", response_model=OrderCreated, status_code=201, dependencies=[Depends(raw_body)]
)
def create_order(
    data: OrderInput,
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    user: Customer,
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    response = ordering.create_order(db, request, user, key, data)
    schedule(request, tasks)
    return response


@router.post("/orders/{order_id}/payment/refresh", response_model=PaymentConfirmation)
def confirm(order_id: UUID, request: Request, tasks: BackgroundTasks, db: DB, user: Customer):
    order = order_queries.owned_order(db, user, str(order_id))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    ident = payment.provider_payment_intent_id if order.status == "PENDING_PAYMENT" else None
    db.commit()
    intent = None
    if ident:
        try:
            intent = request.app.state.payment_gateway.retrieve(ident)
        except Exception:
            pass  # Unknown provider outcome must not be presented as a decline.
    order, payment = locked_payment(db, str(order_id))
    if intent:
        apply_payment_intent(
            db, order, payment, intent, request.app.state.settings, request.app.state.clock.now()
        )
    result = dict(
        orderId=order.id,
        status=order.status,
        paymentStatus=payment.status,
        failureMessage=MESSAGES["PAYMENT_DECLINED"] if payment.status == "FAILED" else None,
    )
    db.commit()
    schedule(request, tasks)
    return result


@router.get("/orders", response_model=OrderList)
def orders(
    request: Request,
    tasks: BackgroundTasks,
    db: DB,
    user: Customer,
    page: Page = 1,
    pageSize: PageSize = 20,
):
    now = request.app.state.clock.now()
    stmt = order_queries.list_query(user, now)
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .with_for_update()
    ).all()
    for row in rows:
        order_queries.sync_time(db, row, request.app.state.settings, now)
    result = dict(
        items=[order_queries.summary(db, row) for row in rows],
        page=page,
        pageSize=pageSize,
        totalCount=count,
    )
    db.commit()
    schedule(request, tasks)
    return result


@router.get("/orders/{order_id}", response_model=OrderDetail)
def detail(order_id: UUID, request: Request, tasks: BackgroundTasks, db: DB, user: Customer):
    order = order_queries.owned_order(db, user, str(order_id), lock=True)
    order_queries.sync_time(db, order, request.app.state.settings, request.app.state.clock.now())
    result = order_queries.detail(db, order, request.app.state.settings)
    db.commit()
    schedule(request, tasks)
    return result


@router.post("/payments/webhook")
async def webhook(request: Request, tasks: BackgroundTasks):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload,
            request.headers.get("Stripe-Signature", ""),
            request.app.state.settings.stripe_webhook_secret.get_secret_value(),
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise ApiError(400, "VALIDATION_ERROR") from None
    try:
        await run_in_threadpool(webhooks.process_event, request.app, event.to_dict())
    except Exception:
        return JSONResponse({"received": False}, status_code=500)
    schedule(request, tasks)
    return {"received": True}


def dev_enabled(request: Request):
    if not request.app.state.settings.dev_tools_enabled:
        raise ApiError(404, "NOT_FOUND")


@router.get("/dev/mails", response_model=MailList, dependencies=[Depends(dev_enabled)])
def mailbox(db: DB, user: UserDep):
    stmt = select(Notification, Order.order_number).join(Order, Notification.order_id == Order.id)
    if user.role == "CUSTOMER":
        stmt = stmt.where(Notification.user_id == user.id)
    else:
        stmt = stmt.where(Order.store_id == db.get(StaffProfile, user.id).store_id)
    rows = db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc())).all()
    return dict(
        items=[
            dict(
                notificationId=x.id,
                type=x.type,
                recipientEmail=x.recipient_email,
                subject=x.subject,
                bodyText=x.body_text,
                status=x.status,
                attemptCount=x.attempt_count,
                sentAt=timestamp(x.sent_at),
                createdAt=timestamp(x.created_at),
                orderId=x.order_id,
                orderNumber=number,
            )
            for x, number in rows
        ]
    )
