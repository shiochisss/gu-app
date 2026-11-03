import json
import logging

from fastapi.responses import JSONResponse

from app.errors import ApiError, error_response
from app.models import IdempotencyRecord
from app.services.idempotency import claim
from app.services.lifecycle import check_version, locked_order
from app.services.payment_operations import perform

logger = logging.getLogger("pickup")


def execute(db, request, user, key, order_id, data, mutate, render, store_id=None):
    record, cached = claim(db, request, user, key)
    if cached is not None:
        return cached
    identity = (record.user_id, record.endpoint, record.idempotency_key)
    if not record.response_body:
        try:
            with db.begin_nested():
                order, payment = locked_order(db, order_id, user, store_id)
                check_version(
                    db, order, data, request.app.state.settings, request.app.state.clock.now()
                )
                operation = mutate(
                    db,
                    order,
                    payment,
                    user,
                    data,
                    request.app.state.settings,
                    request.app.state.clock.now(),
                )
                db.flush()
            record.response_body = {"orderId": order_id}
            db.commit()
        except ApiError as exc:
            response = error_response(request, exc.status, exc.code, **exc.payload)
            if exc.status >= 500:
                db.rollback()
                record = db.get(IdempotencyRecord, identity, with_for_update=True)
                db.delete(record)
            else:
                record.response_status, record.response_body = exc.status, json.loads(response.body)
            db.commit()
            return response
        except Exception:
            db.rollback()
            # A successful but unacknowledged COMMIT leaves the fallback orderId.
            record = db.get(
                IdempotencyRecord, identity, with_for_update=True, populate_existing=True
            )
            if record.response_body:
                db.commit()
                operation = None
            else:
                db.delete(record)
                db.commit()
                raise
        if operation:
            try:
                perform(request.app, order_id)
            except Exception:
                logger.error("committed order action will be reconciled", exc_info=True)
    else:
        db.commit()
    # Never repeat the business mutation after a committed stage. Subsequent
    # retries return the current order; payment reconciliation uses the provider key.
    record = db.get(IdempotencyRecord, identity, with_for_update=True, populate_existing=True)
    order, payment = locked_order(db, order_id, user, store_id)
    result = render(db, order)
    record.response_status, record.response_body = 200, result
    db.commit()
    return JSONResponse(result)
