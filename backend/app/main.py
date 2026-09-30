from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_json_logging
from app.db.database import get_db
from app.http.error_handlers import domain_error_handler
from app.http.request_middleware import RequestIdMiddleware
from app.routers.analytics import router as analytics_router
from app.routers.menu import router as menu_router
from app.routers.menu_item import router as menu_item_router
from app.routers.order import router as order_router
from app.routers.restaurant import router as restaurant_router


settings = get_settings()
configure_json_logging(level=settings.log_level)

app = FastAPI(
    title="RestaurantOS API",
    version="0.1.0",
)

app.include_router(restaurant_router)
app.include_router(menu_router)
app.include_router(menu_item_router)
app.include_router(order_router)
app.include_router(analytics_router)


async def handle_domain_error(request: Request, error: Exception) -> Response:
    if not isinstance(error, DomainError):
        raise error
    return await domain_error_handler(request, error)


app.add_exception_handler(DomainError, handle_domain_error)
app.add_middleware(RequestIdMiddleware)

#-------- CORS --------#
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {
        "message": "Hello from RestaurantOS API"
    }

# Test database connection
@app.get("/api/test-db")
async def test_db(db: AsyncSession = Depends(get_db)) -> dict[str, int | None]:
    result = await db.execute(text("SELECT 1"))
    return {"database": result.scalar()}
