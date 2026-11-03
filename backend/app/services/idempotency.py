"""Persist a lease first; commit each local mutation and its response atomically."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError, error_response
from app.models import IdempotencyRecord


def claim(db, request, user, key):
    try:
        key = str(UUID(key or ""))
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR") from None
    now = request.app.state.clock.now()
    digest = hashlib.sha256(
        json.dumps(
            request.state.idempotency_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    identity = (user.id, f"{request.method} {request.url.path}", key)
    record = IdempotencyRecord(
        user_id=identity[0],
        endpoint=identity[1],
        idempotency_key=key,
        request_hash=digest,
        created_at=now,
        locked_until=now + timedelta(minutes=2),
        expires_at=now + timedelta(hours=24),
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError as exc:
        if exc.orig.args[0] != 1062:
            raise
        record = db.get(IdempotencyRecord, identity, with_for_update=True, populate_existing=True)
        if record.request_hash != digest:
            raise ApiError(422, "IDEMPOTENCY_KEY_REUSED") from None
        if record.response_status is not None:
            return None, JSONResponse(record.response_body, status_code=record.response_status)
        if record.locked_until > now:
            raise ApiError(409, "IDEMPOTENCY_IN_PROGRESS") from None
        record.locked_until = now + timedelta(minutes=2)
    db.commit()
    # The business transaction holds the lease row lock. A competing expired lease
    # cannot start another mutation while this worker is still running.
    record = db.get(IdempotencyRecord, identity, with_for_update=True, populate_existing=True)
    if record.response_status is not None:
        return None, JSONResponse(record.response_body, status_code=record.response_status)
    return record, None


def execute(db, request, user, key, operation):
    record, cached = claim(db, request, user, key)
    if cached is not None:
        return cached
    identity = (record.user_id, record.endpoint, record.idempotency_key)
    try:
        try:
            with db.begin_nested():
                status, body = operation()
        except ApiError as exc:
            if exc.status >= 500:
                raise
            response = error_response(request, exc.status, exc.code, **exc.payload)
            status, body = exc.status, json.loads(response.body)
        record.response_status, record.response_body = status, body
        db.commit()
        return JSONResponse(body, status_code=status)
    except Exception:
        db.rollback()
        record = db.get(IdempotencyRecord, identity, with_for_update=True)
        if record and record.response_status is None:
            db.delete(record)
            db.commit()
        raise
