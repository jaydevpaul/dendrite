from contextlib import asynccontextmanager

from fastapi import FastAPI

from arq import create_pool
from arq.connections import RedisSettings

from app.api.routes import auth,health,conversations,messages
from app.core.db import engine
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One pool of Redis connections for the server's whole life, not one per
    # request.
    app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.queue.aclose()
    # Dispose the connection pool cleanly on shutdown.
    await engine.dispose()


app = FastAPI(title="Dendrite", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(messages.router)


