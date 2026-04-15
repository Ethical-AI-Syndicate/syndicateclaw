"""Database migration runner and helpers."""

from __future__ import annotations

import subprocess
from typing import Any

from syndicateclaw.errors import MigrationError


class AlembicMigrationRunner:
    """Alembic-based migration runner."""

    def __init__(self, database_url: str) -> None:
        """
        Initialize the migration runner.

        Args:
            database_url: PostgreSQL connection URL
        """
        self._database_url = database_url

    async def upgrade(self, revision: str = "head") -> None:
        """
        Apply migrations up to the specified revision.

        Args:
            revision: Target revision (default "head")

        Raises:
            MigrationError: If migration fails
        """
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "upgrade",
                    revision,
                    "--sql",
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise MigrationError(f"Migration failed: {result.stderr}")

        except Exception as e:
            raise MigrationError(f"Migration error: {e}") from e

    async def downgrade(self, revision: str = "-1") -> None:
        """
        Revert migrations down to the specified revision.

        Args:
            revision: Target revision (default "-1" for previous)

        Raises:
            MigrationError: If downgrade fails
        """
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "downgrade",
                    revision,
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise MigrationError(f"Downgrade failed: {result.stderr}")

        except Exception as e:
            raise MigrationError(f"Downgrade error: {e}") from e

    async def current(self) -> str | None:
        """
        Get the current migration revision.

        Returns:
            The current revision string or None if not stamped.

        Raises:
            MigrationError: If command fails
        """
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "current",
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=True,
            )

            output = result.stdout.strip()
            if not output:
                return None

            return output.split()[0] if output else None

        except Exception as e:
            raise MigrationError(f"Current revision check failed: {e}") from e

    async def history(self) -> list[str]:
        """
        Get the list of all migration revisions.

        Returns:
            List of revision strings.

        Raises:
            MigrationError: If command fails
        """
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "history",
                    "--verbose=0",
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=True,
            )

            lines = result.stdout.strip().split("\n")
            return [line.split()[0] for line in lines if line.strip()]

        except Exception as e:
            raise MigrationError(f"History check failed: {e}") from e

    async def stamp(self, revision: str) -> None:
        """
        Set the current revision without running migrations.

        Args:
            revision: The revision to stamp

        Raises:
            MigrationError: If stamp fails
        """
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "stamp",
                    revision,
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise MigrationError(f"Stamp failed: {result.stderr}")

        except Exception as e:
            raise MigrationError(f"Stamp error: {e}") from e

    async def check(self) -> tuple[bool, str | None]:
        """
        Check if migrations are up to date.

        Returns:
            Tuple of (is_current, head_revision)

        Raises:
            MigrationError: If check fails
        """
        try:
            current = await self.current()

            # Get head revision
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "alembic",
                    "heads",
                ],
                env={"SYNDICATECLAW_DATABASE_URL": self._database_url},
                capture_output=True,
                text=True,
                check=True,
            )

            head = result.stdout.strip().split()[0] if result.stdout.strip() else None

            return current == head, head

        except Exception as e:
            raise MigrationError(f"Check failed: {e}") from e


async def Migrate(database_url: str, revision: str = "head") -> None:
    """
    Run database migrations.

    Args:
        database_url: PostgreSQL connection URL
        revision: Target revision (default "head")

    Raises:
        MigrationError: If migration fails

    This is the main entry point for migration running.
    """
    runner = AlembicMigrationRunner(database_url)
    await runner.upgrade(revision)
