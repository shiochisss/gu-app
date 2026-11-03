import hashlib
import secrets
from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS, TIMEZONE, Settings
from app.db import get_db
from app.errors import ApiError
from app.models import RefreshToken, StaffProfile, Store, User
from app.schemas.auth import SessionTokens, UserInfo

BEARER = HTTPBearer(auto_error=False)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def user_info(db: Session, user: User) -> UserInfo:
    profile = db.get(StaffProfile, user.id) if user.role == "STAFF" else None
    store = db.get(Store, profile.store_id) if profile else None
    if user.role == "STAFF" and store is None:
        raise ApiError(401, "UNAUTHENTICATED")
    return UserInfo(
        user_id=user.id,
        email=user.email,
        role=user.role,
        store_id=store.id if store else None,
        store_name=store.name if store else None,
    )


def issue_tokens(db: Session, user: User, settings: Settings, now) -> SessionTokens:
    info = user_info(db, user)
    access_expires = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    refresh_expires = now + timedelta(days=REFRESH_TOKEN_DAYS)
    claims = {
        "iss": "pickup-app-backend",
        "aud": "pickup-app-bff",
        "sub": user.id,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int(access_expires.timestamp()),
        "jti": str(uuid4()),
    }
    if info.store_id:
        claims["store_id"] = info.store_id
    access = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    raw = secrets.token_urlsafe(32)
    refresh = RefreshToken(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=token_hash(raw),
        created_at=now,
        expires_at=refresh_expires,
    )
    db.add(refresh)
    db.flush()
    return SessionTokens(
        user=info,
        access_token=access,
        access_token_expires_at=access_expires.astimezone(ZoneInfo(TIMEZONE)),
        refresh_token=raw,
        refresh_token_expires_at=refresh_expires.astimezone(ZoneInfo(TIMEZONE)),
    )


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)],
) -> User:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED")
    try:
        claims = jwt.decode(
            credentials.credentials,
            request.app.state.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer="pickup-app-backend",
            audience="pickup-app-bff",
            options={
                "require": ["iss", "aud", "sub", "role", "iat", "exp", "jti"],
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        UUID(claims["sub"])
        UUID(claims["jti"])
        now = request.app.state.clock.now().timestamp()
        if type(claims["iat"]) is not int or claims["iat"] > now:
            raise ValueError("iat")
        if type(claims["exp"]) is not int:
            raise ValueError("exp")
        if claims["exp"] <= now:
            raise ApiError(401, "TOKEN_EXPIRED")
    except ApiError:
        raise
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise ApiError(401, "UNAUTHENTICATED") from None
    user = db.get(User, claims["sub"])
    if user is None or user.status != "ACTIVE" or user.role != claims["role"]:
        raise ApiError(401, "UNAUTHENTICATED")
    if user.role == "STAFF":
        profile = db.get(StaffProfile, user.id)
        if profile is None or profile.store_id != claims.get("store_id"):
            raise ApiError(401, "UNAUTHENTICATED")
    return user
