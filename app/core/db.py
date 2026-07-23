import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def get_database_url() -> str:
    return os.environ["DATABASE_URL"]


engine = create_async_engine(get_database_url())

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
