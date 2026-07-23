from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, engine

# Tables truncated between tests, listed with CASCADE so FK-dependent rows
# (e.g. tasks -> projects -> users) are cleared regardless of which table
# a given test wrote to. Isolation model: truncate-after-each-test against
# the shared dev Postgres instance (docker-compose, localhost:5433) --
# integration tests in this suite are NOT safe to run in parallel with each
# other (see Parallelism Assessment in tasks.md). Future integration test
# files (T8, T11, and later routers) should reuse this same fixture/file.
_ALL_TABLES = "refresh_tokens, attachments, tasks, projects, users"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
