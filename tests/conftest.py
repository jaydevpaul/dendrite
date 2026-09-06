import os
from contextlib import contextmanager

import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - importing registers every table on Base.metadata
from app.core.config import settings
from app.core.db import Base

# One database per pytest process, not one shared "dendrite_test".
#
# The session fixture cleans up between tests with TRUNCATE, which takes an
# ACCESS EXCLUSIVE lock on every table. Two pytest runs against one database
# therefore fight: one truncates while the other holds row locks, Postgres
# spots the circular wait and kills a transaction with "deadlock detected".
# The knock-on failures are worse than the deadlock, because they look like
# application bugs - a truncate landing mid-test wipes the signed-up user, so
# a later response.json()["message"] raises KeyError, and two runs signing up
# the same fixture email collide on UniqueViolation.
#
# Isolating by pid means "pytest while the other window is also running
# pytest" is simply safe, which is worth six lines.
TEST_DB_NAME = f"dendrite_test_{os.getpid()}"
TEST_DB_URL = settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


async def _drop_stale_test_databases(conn):
    """Remove databases left behind by runs that were killed mid-flight.

    A dendrite_test_* database with no active connections cannot belong to a
    running pytest process, so it is a leftover. The pg_stat_activity check is
    what makes this safe to do while another run is in progress - a live one is
    never touched.
    """
    stale = await conn.scalars(
        text(
            """
            select datname from pg_database
            where datname like 'dendrite_test%'
              and datname <> :mine
              and not exists (
                  select 1 from pg_stat_activity
                  where pg_stat_activity.datname = pg_database.datname
              )
            """
        ),
        {"mine": TEST_DB_NAME},
    )
    for name in list(stale):
        await conn.execute(text(f'drop database if exists "{name}" with (force)'))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    """A private test database with the full schema, built once per run."""
    # CREATE DATABASE cannot run inside a transaction block, so this needs a
    # connection in AUTOCOMMIT mode - pointed at the dev database, since you
    # have to be connected to *something* to create a database.
    admin = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await _drop_stale_test_databases(conn)
        await conn.execute(text(f'drop database if exists "{TEST_DB_NAME}" with (force)'))
        await conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    await admin.dispose()

    test_engine = create_async_engine(TEST_DB_URL)
    async with test_engine.begin() as conn:
        await conn.execute(text("create extension if not exists vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine

    # Dispose first: DROP DATABASE cannot run while this engine's pool still
    # holds connections to it. WITH (FORCE) covers anything else lingering.
    await test_engine.dispose()
    admin = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'drop database if exists "{TEST_DB_NAME}" with (force)'))
    await admin.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine):
    """One AsyncSession per test, with every table emptied afterwards."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"truncate {tables} restart identity cascade"))


@contextmanager
def counting_queries(engine):
    """Count the statements actually sent while the block runs.

    Not a fixture - it wraps the part of a test that is under scrutiny, so it
    has to be entered inside the test body rather than around the whole of it.
    """
    sent = []

    def record(*_args):
        sent.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


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
