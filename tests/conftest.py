import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - importing registers every table on Base.metadata
from app.core.config import settings
from app.core.db import Base

TEST_DB_NAME = "dendrite_test"
TEST_DB_URL = settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    """A dendrite_test database with the full schema, built once per run."""
    # CREATE DATABASE cannot run inside a transaction block, so this needs a
    # connection in AUTOCOMMIT mode - pointed at the dev database, since you
    # have to be connected to *something* to create a database.
    admin = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :name"),
            {"name": TEST_DB_NAME},
        )
        if not exists:
            await conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    await admin.dispose()

    test_engine = create_async_engine(TEST_DB_URL)
    async with test_engine.begin() as conn:
        await conn.execute(text("create extension if not exists vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine):
    """One AsyncSession per test, with every table emptied afterwards."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"truncate {tables} restart identity cascade"))


@pytest_asyncio.fixture(loop_scope="session")
async def client(session):
    """An HTTP client driving the real app against the test database.

    dependency_overrides swaps the app's per-request get_session for the
    test session, so routes and assertions share one transaction view and
    the dev database is never touched.
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.db import get_session
    from app.main import app

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()
