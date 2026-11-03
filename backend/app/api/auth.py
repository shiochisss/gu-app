from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas.auth import Credentials, RefreshInput, SessionTokens, UserInfo
from app.security.auth import current_user, user_info
from app.services import authentication

router = APIRouter(prefix="/api/v1/auth", tags=["認証"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/register", response_model=SessionTokens, status_code=201)
def register(body: Credentials, request: Request, db: DB):
    return authentication.register(
        db,
        request.app.state.settings,
        request.app.state.clock,
        body.email,
        body.password.get_secret_value(),
    )


@router.post("/login", response_model=SessionTokens)
def login(body: Credentials, request: Request, db: DB):
    return authentication.login(
        db,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.clock,
        body.email,
        body.password.get_secret_value(),
    )


@router.post("/refresh", response_model=SessionTokens)
def refresh(body: RefreshInput, request: Request, db: DB):
    return authentication.refresh(
        db,
        request.app.state.settings,
        request.app.state.clock,
        body.refresh_token.get_secret_value(),
    )


@router.post("/logout", status_code=204)
def logout(body: RefreshInput, request: Request, db: DB):
    authentication.logout(db, request.app.state.clock, body.refresh_token.get_secret_value())
    return Response(status_code=204)


@router.get("/me", response_model=UserInfo)
def me(db: DB, user: Annotated[User, Depends(current_user)]):
    return user_info(db, user)
