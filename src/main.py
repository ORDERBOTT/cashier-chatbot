from fastapi import FastAPI
from contextlib import asynccontextmanager
from src.database import engine
from sqlalchemy import text


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    yield

    # Graceful shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

# Include all the routes