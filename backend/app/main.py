from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging
from threading import Lock

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_json_logging
from app.db.database import get_db
from app.redis.adapter import RedisAdapter, RedisFailure
from app.http.error_handlers import domain_error_handler
from app.http.request_middleware import RequestIdMiddleware
from app.http.auth_middleware import AuthBoundaryMiddleware
from app.modules.auth.repo import models as auth_models  # noqa: F401 - register metadata
from app.modules.tenancy.repo import models as tenancy_models  # noqa: F401
from app.modules.audit.repo import models as audit_models  # noqa: F401
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.errors import (
    AuthenticationError,
    AuthStorageError,
    RateLimitError,
)
from app.modules.auth.router import router as auth_router, clear_cookies
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.modules.analytics.router import router as analytics_router
from app.modules.catalog.menu_router import router as menu_router
from app.modules.catalog.item_router import router as menu_item_router
from app.modules.tenancy.router import router as tenancy_router
from app.modules.audit.router import router as audit_router
from app.modules.inventory.router import router as inventory_router
from app.modules.recipes.router import router as recipes_router
from app.modules.orders.router import router as order_router
from app.modules.restaurants.router import router as restaurant_router


settings = get_settings()
configure_json_logging(level=settings.log_level)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    adapter = RedisAdapter(settings)
    await adapter.open()
    # Test clients may nest/overlap lifespans and shut down out of order. Track
    # active owners rather than restore a possibly already closed predecessor.
    with application.state.redis_lifecycle_lock:
        application.state.redis_lifespans.append(adapter)
        application.state.redis = adapter
    try:
        yield
    finally:
        try:
            await adapter.close()
        except RedisFailure as error:
            logging.getLogger(__name__).warning(
                "Redis shutdown failed (%s)", error.kind.value
            )
        finally:
            with application.state.redis_lifecycle_lock:
                application.state.redis_lifespans.remove(adapter)
                if application.state.redis_lifespans:
                    application.state.redis = application.state.redis_lifespans[-1]
                elif hasattr(application.state, "redis"):
                    del application.state.redis


app = FastAPI(
    title="RestaurantOS API",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.redis_lifespans = []
app.state.redis_lifecycle_lock = Lock()

app.include_router(auth_router)
for business_router in (
    restaurant_router,
    menu_router,
    menu_item_router,
    order_router,
    analytics_router,
    tenancy_router,
    audit_router,
    inventory_router,
    recipes_router,
):
    app.include_router(business_router, dependencies=[Depends(get_current_principal)])


async def auth_error_handler(request: Request, error: Exception) -> Response:
    headers = {"Cache-Control": "no-store"}
    if isinstance(error, RateLimitError):
        headers["Retry-After"] = str(error.retry_after)
        return JSONResponse(
            {"detail": "Too many attempts"}, status_code=429, headers=headers
        )
    if isinstance(error, AuthStorageError):
        return JSONResponse(
            {"detail": "Authentication service unavailable"},
            status_code=503,
            headers=headers,
        )
    response = JSONResponse(
        {"detail": "Invalid credentials or session"}, status_code=401, headers=headers
    )
    if request.url.path == "/auth/refresh":
        clear_cookies(response)
    return response


async def safe_validation_handler(request: Request, error: Exception) -> Response:
    # Never echo request input values, especially passwords/cookies.
    return JSONResponse({"detail": "Invalid request data"}, status_code=422)


for error_class in (AuthenticationError, AuthStorageError, RateLimitError):
    app.add_exception_handler(error_class, auth_error_handler)
app.add_exception_handler(RequestValidationError, safe_validation_handler)


async def handle_domain_error(request: Request, error: Exception) -> Response:
    if not isinstance(error, DomainError):
        raise error
    return await domain_error_handler(request, error)


app.add_exception_handler(DomainError, handle_domain_error)
app.add_middleware(AuthBoundaryMiddleware)
app.add_middleware(RequestIdMiddleware)

# -------- CORS --------#
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.auth_trusted_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Protection", "X-Request-ID"],
    expose_headers=["Retry-After", "X-Request-ID"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "restaurantos-api",
    }


# Test frontend connection
@app.get("/api/test")
def test() -> dict[str, str]:
    return {"message": "Hello from RestaurantOS API"}


# Test database connection
@app.get(
    "/api/test-db",
    dependencies=[Depends(get_current_principal)],
    include_in_schema=False,
)
async def test_db(db: AsyncSession = Depends(get_db)) -> dict[str, int | None]:
    if settings.environment == "production":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not found")
    result = await db.execute(text("SELECT 1"))
    return {"database": result.scalar()}
