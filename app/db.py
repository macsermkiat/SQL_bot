"""
Database connection pool with safety features.

- Per-query statement timeout
- Row limit enforcement
- Connection pooling via psycopg
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.models import QueryResult


class Database:
    """Database connection manager with safety features."""

    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None

    def _get_pool(self) -> ConnectionPool:
        """Get or create connection pool."""
        if self._pool is None:
            settings = get_settings()
            self._pool = ConnectionPool(
                settings.db_url,
                min_size=1,
                max_size=10,
                kwargs={"row_factory": dict_row},
            )
        return self._pool

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        """Get a connection from the pool."""
        pool = self._get_pool()
        with pool.connection() as conn:
            yield conn

    def execute_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
    ) -> QueryResult:
        """
        Execute a read-only query with safety limits.

        Args:
            sql: SQL query to execute
            params: Query parameters
            timeout_ms: Statement timeout (default from settings)
            max_rows: Max rows to fetch (default from settings)

        Returns:
            QueryResult with columns, rows, timing
        """
        settings = get_settings()
        timeout_ms = timeout_ms or settings.sql_statement_timeout_ms
        max_rows = max_rows or settings.sql_max_rows

        start_time = time.perf_counter()

        with self.connection() as conn:
            # Set statement timeout for this query
            conn.execute(f"SET statement_timeout = {timeout_ms}")

            with conn.cursor() as cur:
                # If no params, escape % to avoid psycopg interpreting them as placeholders
                # (e.g., LIKE '%dilantin%' has '%d' which looks like a format specifier)
                if not params:
                    escaped_sql = sql.replace("%", "%%")
                    cur.execute(escaped_sql)
                else:
                    cur.execute(sql, params)

                # Fetch max_rows + 1 to detect truncation
                rows_raw = cur.fetchmany(max_rows + 1)
                truncated = len(rows_raw) > max_rows
                if truncated:
                    rows_raw = rows_raw[:max_rows]

                # Get column names
                columns = [desc.name for desc in cur.description] if cur.description else []

                # Convert dict rows to lists
                rows = [list(row.values()) for row in rows_raw]

        execution_time = (time.perf_counter() - start_time) * 1000

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution_time_ms=round(execution_time, 2),
        )

    def test_connection(self) -> bool:
        """Test database connectivity."""
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None


# Global database instance
_db: Database | None = None


def get_db() -> Database:
    """Get global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
