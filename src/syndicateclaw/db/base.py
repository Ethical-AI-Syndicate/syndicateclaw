from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, NullPool, Text, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _generate_ulid() -> str:
    return str(ULID())


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_generate_ulid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


def get_engine(url: str, **kwargs: Any) -> AsyncEngine:
    import os

    if os.environ.get("SYNDICATECLAW_ENVIRONMENT") == "test":
        # NullPool avoids the "Future attached to a different loop" error that
        # arises in pytest-asyncio tests when SQLAlchemy's pool tries to close
        # asyncpg connections whose Futures were bound to the test's event loop.
        # With NullPool every acquire/release creates and closes a connection
        # immediately, so there is nothing to terminate on engine disposal.
        return create_async_engine(
            url,
            echo=kwargs.pop("echo", False),
            poolclass=NullPool,
        )
    return create_async_engine(
        url,
        echo=kwargs.pop("echo", False),
        pool_size=kwargs.pop("pool_size", 20),
        max_overflow=kwargs.pop("max_overflow", 30),
        pool_timeout=kwargs.pop("pool_timeout", 30),
        pool_recycle=kwargs.pop("pool_recycle", 3600),
        pool_pre_ping=True,
        **kwargs,
    )


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
