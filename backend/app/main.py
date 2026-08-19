from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db

from app.routers.restaurant import router as restaurant_router

app = FastAPI(
    title="RestaurantOS API",
    version="0.1.0",
)

app.include_router(restaurant_router)

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
def health_check():
    return {
        "status": "ok",
        "service": "restaurantos-api",
    }

#Test frontend connection
@app.get("/api/test")
def test():
    return {
        "message": "Hello from RestaurantOS API"
    }

#test database connection
@app.get("/api/test-db")
async def test_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"database": result.scalar()}