"""Unified database access layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from typing import AsyncIterator


class Store:
    """
    Unified database access layer.

    Provides a single entry point for database operations with:
    - Session management
    - Transaction handling
    - Connection pooling
    """

    def __init__(
        self,
        database_url: str,
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> None:
        self._database_url = database_url
        self._engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory for repository use."""
        return self._session_factory

    @property
    def engine(self):
        """Return the SQLAlchemy engine."""
        return self._engine

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Context manager for a single session."""
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """Dispose of the engine and all connections."""
        await self._engine.dispose()


# Singleton instance
_store: Store | None = None


def get_store() -> Store:
    """Get the global Store instance."""
    global _store
    if _store is None:
        from syndicateclaw.config import Settings

        settings = Settings()
        _store = Store(settings.database_url)
    return _store


def set_store(store: Store) -> None:
    """Set the global Store instance (for testing)."""
    global _store
    _store = store
