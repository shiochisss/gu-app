import base64
import hashlib
import hmac
import json
from uuid import UUID, uuid4

from sqlalchemy import select

from app.errors import ApiError
from app.models import PickupToken


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def signature(secret, value):
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest()


def manual_code(secret, token_id):
    return f"{int.from_bytes(signature(secret, 'MANUAL.' + token_id)[:4], 'big') % 1000000:06d}"


def qr_value(secret, token):
    payload = json.dumps(
        dict(o=token.order_id, t=token.token_id, i=int(token.issued_at.timestamp())),
        separators=(",", ":"),
    ).encode()
    message = "PA1." + encoded(payload)
    return message + "." + encoded(signature(secret, message))


def decode(secret, value):
    try:
        prefix, body, supplied = value.split(".")
        if prefix != "PA1" or not hmac.compare_digest(
            encoded(signature(secret, prefix + "." + body)), supplied
        ):
            raise ValueError("signature")
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if set(data) != {"o", "t", "i"} or type(data["i"]) is not int:
            raise ValueError("payload")
        UUID(data["o"])
        UUID(data["t"])
        return data
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ApiError(422, "INVALID_PICKUP_CODE") from None


def active_token(db, order_id, lock=False):
    stmt = select(PickupToken).where(
        PickupToken.order_id == order_id, PickupToken.revoked_at.is_(None)
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def issue(db, order, now):
    token = PickupToken(token_id=str(uuid4()), order_id=order.id, issued_at=now)
    db.add(token)
    return token


def revoke(db, order, now, reason):
    token = active_token(db, order.id, lock=True)
    if token:
        token.revoked_at, token.revoked_reason = now, reason
        db.flush()  # Free the generated unique active_order_id before reissuing.
