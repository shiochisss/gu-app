import hmac
import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app.api.auth import router as auth_router
from app.api.internal import router as internal_router
from app.api.operations import router as operations_router
from app.api.orders import router as orders_router
from app.api.staff_stock import router as staff_stock_router
from app.api.stores import router as stores_router
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory, get_db
from app.errors import ApiError, api_error, error_response, http_error, validation_error
from app.logging import configure_logging
from app.payments.gateway import StripePaymentGateway
from app.schemas.common import HealthResponse


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or SystemClock()
    logger = configure_logging(settings.log_level)
    engine = create_db_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    local = settings.app_env == "local"
    app = FastAPI(
        title="店舗受取 API",
        docs_url="/docs" if local else None,
        redoc_url="/redoc" if local else None,
        openapi_url="/openapi.json" if local else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.payment_gateway = StripePaymentGateway(settings.stripe_secret_key.get_secret_value())
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.include_router(auth_router)
    app.include_router(internal_router)
    app.include_router(orders_router)
    app.include_router(operations_router)
    app.include_router(stores_router)
    app.include_router(staff_stock_router)
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        candidate = request.headers.get("X-Request-Id", "")
        try:
            request.state.request_id = str(UUID(candidate))
        except ValueError:
            request.state.request_id = str(uuid4())
        start = perf_counter()
        failed = False
        try:
            if (
                request.url.path.startswith("/api/v1/")
                and request.url.path != "/api/v1/payments/webhook"
            ):
                supplied = request.headers.get("X-BFF-Secret", "").encode()
                expected = settings.bff_shared_secret.get_secret_value().encode()
                if not hmac.compare_digest(supplied, expected):
                    response = error_response(request, 403, "FORBIDDEN")
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            failed = True
            response = error_response(request, 500, "INTERNAL_ERROR")
            log_request(request, response.status_code, start, logging.ERROR, exc_info=True)
        response.headers["X-Request-Id"] = request.state.request_id
        if not failed:
            log_request(request, response.status_code, start, logging.INFO)
        return response

    def log_request(request, status, start, level, exc_info=False):
        route = request.scope.get("route")
        # Route templates exclude arbitrary path values; never log query/header/body values.
        path = getattr(route, "path", "<unmatched>")
        logger.log(
            level,
            "request failed" if exc_info else "request completed",
            extra={
                "timestamp": clock.now().isoformat(),
                "request_id": request.state.request_id,
                "path": path,
                "status": status,
                "duration_ms": round((perf_counter() - start) * 1000, 3),
            },
            exc_info=exc_info,
        )

    @app.get("/healthz", response_model=HealthResponse)
    def healthz(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
        db.execute(select(1)).scalar_one()
        return HealthResponse()

    return app


app = create_app()
