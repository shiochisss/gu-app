import math
from datetime import timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from app.config import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_FAILURE_WINDOW_MINUTES,
    REFRESH_REUSE_GRACE_SECONDS,
)
from app.errors import ApiError
from app.models import RateLimitCounter, RefreshToken, User
from app.security.auth import issue_tokens, token_hash

HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash("unused-fixed-dummy-for-absent-user")


def register(db, settings, clock, email, password):
    now = clock.now()
    user = User(
        id=str(uuid4()),
        email=email,
        password_hash=HASHER.hash(password),
        role="CUSTOMER",
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(user)
        db.flush()
        result = issue_tokens(db, user, settings, now)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        if exc.orig.args[0] == 1062:
            raise ApiError(409, "EMAIL_ALREADY_REGISTERED") from None
        raise


def login(db, session_factory, settings, clock, email, password):
    now = clock.now()
    key = "login:" + token_hash(email)
    failure = None
    user_id = None
    with session_factory.begin() as counters:
        statement = mysql_insert(RateLimitCounter).values(key=key, window_started_at=now, count=0)
        counters.execute(statement.on_duplicate_key_update(key=key))
        counter = counters.execute(
            select(RateLimitCounter).where(RateLimitCounter.key == key).with_for_update()
        ).scalar_one()
        window = timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES)
        if counter.window_started_at + window < now:
            counter.count = 0
            counter.window_started_at = now
        if counter.count >= LOGIN_FAILURE_LIMIT:
            remaining = max(
                1, math.ceil((counter.window_started_at + window - now).total_seconds())
            )
            failure = ApiError(429, "RATE_LIMITED", headers={"Retry-After": str(remaining)})
        else:
            user = counters.execute(select(User).where(User.email == email)).scalar_one_or_none()
            try:
                valid = HASHER.verify(user.password_hash if user else DUMMY_HASH, password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or user is None or user.status != "ACTIVE":
                counter.count += 1
                failure = ApiError(401, "INVALID_CREDENTIALS")
            else:
                user_id = user.id
                counters.delete(counter)
    if failure:
        raise failure
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise ApiError(401, "INVALID_CREDENTIALS")
    result = issue_tokens(db, user, settings, now)
    db.commit()
    return result


def refresh(db, settings, clock, raw):
    now = clock.now()
    row = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw)).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(401, "UNAUTHENTICATED")
    if row.revoked_at is not None:
        grace = row.replaced_by_id and row.revoked_at > now - timedelta(
            seconds=REFRESH_REUSE_GRACE_SECONDS
        )
        if not grace:
            db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        db.commit()
        raise ApiError(401, "UNAUTHENTICATED")
    user = db.get(User, row.user_id)
    if row.expires_at <= now or user is None or user.status != "ACTIVE":
        raise ApiError(401, "UNAUTHENTICATED")
    result = issue_tokens(db, user, settings, now)
    replacement = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash(result.refresh_token))
    ).scalar_one()
    row.revoked_at = now
    row.replaced_by_id = replacement.id
    db.commit()
    return result


def logout(db, clock, raw):
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )
    db.commit()
