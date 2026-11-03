from sqlalchemy import select

from app.errors import ApiError
from app.models import AuditLog, InventoryReservation, Notification, Order, OrderDelay, Payment
from app.services import lifecycle, notifications
from app.services.payment_operations import perform
from app.services.payment_states import locked_payment
from app.services.reconciliation import reconcile


def order_id(app, number):
    with app.state.session_factory() as db:
        ident = db.scalar(select(Order.id).where(Order.order_number == number))
        if ident is None:
            raise ApiError(404, "ORDER_NOT_FOUND")
        return ident


def show(app, number):
    ident = order_id(app, number)
    with app.state.session_factory() as db:
        order = db.get(Order, ident)
        payment = db.scalar(select(Payment).where(Payment.order_id == ident))
        from app.models import OrderItem

        rows = db.scalars(
            select(InventoryReservation)
            .join(OrderItem, InventoryReservation.order_item_id == OrderItem.id)
            .where(OrderItem.order_id == ident)
        ).all()
        delays = db.scalars(select(OrderDelay).where(OrderDelay.order_id == ident)).all()
        return dict(
            orderNumber=number,
            status=order.status,
            version=order.version,
            paymentStatus=payment.status,
            lastOperation=payment.last_operation,
            operationAttempt=payment.operation_attempt,
            reservations=[
                dict(status=x.status, quantity=x.quantity, shortageQuantity=x.shortage_quantity)
                for x in rows
            ],
            delays=[dict(source=x.source, reason=x.reason_text) for x in delays],
        )


def change_order(app, number, command, reason=None):
    ident = order_id(app, number)
    with app.state.session_factory() as db:
        order, payment = locked_payment(db, ident)
        if order.status != "ACTION_REQUIRED":
            raise ApiError(409, "INVALID_STATE")
        if payment.status in {"UNKNOWN", "AUTHORIZING", "CAPTURING", "RELEASING", "REFUNDING"}:
            raise ApiError(409, "INVALID_STATE")
        intent_id, version = payment.provider_payment_intent_id, order.version
        db.commit()
    intent = app.state.payment_gateway.retrieve(intent_id) if intent_id else None
    operation = None
    with app.state.session_factory() as db:
        order, payment = locked_payment(db, ident)
        if order.version != version or order.status != "ACTION_REQUIRED":
            raise ApiError(409, "CONFLICTING_UPDATE")
        if command == "resume":
            if (
                payment.status != "FAILED"
                or payment.last_operation != "CAPTURE"
                or not intent
                or intent["status"] != "requires_capture"
            ):
                raise ApiError(409, "INVALID_STATE")
            payment.status, payment.failure_code, payment.updated_at = (
                "AUTHORIZED",
                None,
                app.state.clock.now(),
            )
            payment.version += 1
            order.status = "PREPARING"
            lifecycle.touch(order, app.state.clock.now())
            db.add(
                AuditLog(
                    store_id=order.store_id,
                    target_type="ORDER",
                    target_id=order.id,
                    action="PREPARATION_STARTED",
                    actor_type="SYSTEM",
                    before_value={"status": "ACTION_REQUIRED"},
                    after_value={"status": "PREPARING"},
                    occurred_at=app.state.clock.now(),
                )
            )
        else:
            if not reason or not reason.strip() or len(reason) > 200:
                raise ApiError(400, "VALIDATION_ERROR")
            operation = lifecycle.cancel_order(
                db,
                order,
                payment,
                None,
                app.state.settings,
                app.state.clock.now(),
                "ADMIN",
                admin=True,
                release_allowed=bool(intent and intent["status"] == "requires_capture"),
            )
            db.flush()
            row = db.scalar(
                select(AuditLog)
                .where(AuditLog.target_id == ident, AuditLog.action == "ORDER_CANCELLED")
                .order_by(AuditLog.occurred_at.desc())
                .limit(1)
            )
            row.reason = reason.strip()
        db.commit()
    if operation:
        perform(app, ident)
    notifications.dispatch(app.state.session_factory, app.state.settings, app.state.clock)
    return show(app, number)


def mails(app, status=None):
    with app.state.session_factory() as db:
        stmt = select(Notification)
        if status:
            stmt = stmt.where(Notification.status == status)
        return [
            dict(
                id=x.id, type=x.type, status=x.status, attempts=x.attempt_count, orderId=x.order_id
            )
            for x in db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100))
        ]


def resend(app, ident):
    with app.state.session_factory() as db:
        row = db.get(Notification, ident, with_for_update=True)
        if row is None:
            raise ApiError(404, "NOT_FOUND")
        if row.status != "FAILED":
            raise ApiError(409, "INVALID_STATE")
        row.status, row.attempt_count, row.next_attempt_at = "PENDING", 0, app.state.clock.now()
        row.last_error_code = None
        db.commit()
    notifications.dispatch(app.state.session_factory, app.state.settings, app.state.clock)
    return {"notificationId": ident}


def command(app, args):
    if args.command == "jobs":
        from app.services.jobs import run_jobs

        return run_jobs(app, args.codes or None)
    if args.command == "orders":
        if args.operation == "show":
            return show(app, args.order_number)
        return change_order(app, args.order_number, args.operation, getattr(args, "reason", None))
    if args.command == "payments":
        ident = order_id(app, args.order_number)
        reconcile(app, ident, force=True)
        notifications.dispatch(app.state.session_factory, app.state.settings, app.state.clock)
        return show(app, args.order_number)
    if args.operation == "list":
        return mails(app, args.status)
    return resend(app, args.notification_id)
