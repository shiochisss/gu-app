import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Payment, PaymentEvent
from app.services.payment_states import apply_payment_intent, apply_refund, locked_payment

TYPES = {
    "payment_intent.amount_capturable_updated",
    "payment_intent.requires_action",
    "payment_intent.payment_failed",
    "payment_intent.canceled",
    "payment_intent.succeeded",
    "refund.updated",
    "charge.refunded",
}
logger = logging.getLogger("pickup")


def process_event(app, event):
    now = app.state.clock.now()
    factory, gateway = app.state.session_factory, app.state.payment_gateway
    with factory() as db:
        try:
            with db.begin_nested():
                db.add(
                    PaymentEvent(provider_event_id=event["id"], type=event["type"], received_at=now)
                )
                db.flush()
        except IntegrityError as exc:
            if exc.orig.args[0] != 1062:
                raise
        row = db.scalar(
            select(PaymentEvent)
            .where(PaymentEvent.provider_event_id == event["id"])
            .with_for_update()
        )
        if (row.processed_at is not None and row.result != "ERROR") or (
            row.processing_until is not None and row.processing_until >= now
        ):
            return
        row.processing_until = now + timedelta(minutes=2)
        event_id = row.id
        db.commit()
    try:
        obj, refund, refund_list, follow_up = None, None, [], None
        result = "IGNORED"
        kind = event["type"]
        if kind in TYPES and not event.get("livemode", False):
            raw = event["data"]["object"]
            if kind.startswith("payment_intent."):
                obj = gateway.retrieve(raw["id"])
            elif kind == "refund.updated":
                refund = gateway.retrieve_refund(raw["id"])
                obj = gateway.retrieve(refund["payment_intent"])
            else:
                # Fetch all refunds; future refund operations select the stored ID.
                refund_list = gateway.list_refunds(raw["payment_intent"])
                obj = gateway.retrieve(raw["payment_intent"])
        with factory() as db:
            if obj:
                payment = db.scalar(
                    select(Payment).where(Payment.provider_payment_intent_id == obj["id"])
                )
                if payment is None:
                    payment = db.scalar(
                        select(Payment).where(
                            Payment.order_id == obj.get("metadata", {}).get("order_id")
                        )
                    )
                if payment:
                    order_id = payment.order_id
                    db.rollback()
                    order, payment = locked_payment(db, order_id)
                    apply_payment_intent(
                        db, order, payment, obj, app.state.settings, app.state.clock.now()
                    )
                    if refund_list:
                        refund = next(
                            (x for x in refund_list if x["id"] == payment.provider_refund_id),
                            refund_list[0] if payment.provider_refund_id is None else None,
                        )
                    if refund:
                        apply_refund(db, order, payment, refund, app.state.clock.now())
                    if (
                        payment.status == "REFUNDING"
                        and payment.last_operation == "REFUND"
                        and kind.startswith("payment_intent.")
                    ):
                        follow_up = order.id
                    result = "APPLIED"
            row = db.get(PaymentEvent, event_id, with_for_update=True)
            row.result, row.processed_at, row.processing_until = result, app.state.clock.now(), None
            row.payment_intent_id = obj["id"] if obj else None
            db.commit()
        if follow_up:
            from app.services.payment_operations import perform

            perform(app, follow_up)
    except Exception:
        logger.error("webhook processing failed; event can be retried", exc_info=True)
        with factory() as db:
            row = db.get(PaymentEvent, event_id, with_for_update=True)
            row.result, row.processing_until = "ERROR", None
            db.commit()
        raise
