from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth,health,conversations,messages
from app.core.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Dispose the connection pool cleanly on shutdown.
    await engine.dispose()


app = FastAPI(title="Dendrite", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(messages.router)


