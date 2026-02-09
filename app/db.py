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
                timeout=30.0,  # Connection acquisition timeout
                max_waiting=20,  # Max queued requests
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": 10,  # TCP connection timeout
                },
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

    def explain_query(self, sql: str, timeout_ms: int = 5000) -> tuple[bool, str | None]:
        """
        Validate SQL query using EXPLAIN (dry-run without executing).

        This catches runtime errors like:
        - Missing columns
        - Type mismatches
        - Invalid table references
        - Syntax errors specific to PostgreSQL

        Args:
            sql: SQL query to validate
            timeout_ms: Timeout in milliseconds (default 5s)

        Returns:
            Tuple of (is_valid, error_message)
            - (True, None) if query is valid
            - (False, error_message) if query has errors
        """
        try:
            with self.connection() as conn:
                # Set statement timeout for EXPLAIN
                timeout_seconds = timeout_ms / 1000
                conn.execute(f"SET statement_timeout = '{int(timeout_seconds * 1000)}ms'")

                # Run EXPLAIN (doesn't execute, just validates and plans)
                conn.execute(f"EXPLAIN {sql}")

            return (True, None)
        except Exception as e:
            # Extract useful error message
            error_str = str(e)
            # Clean up the error message (remove connection details, etc.)
            if "DETAIL:" in error_str:
                # Include DETAIL as it often has helpful context
                error_str = error_str.split("CONTEXT:")[0].strip()
            return (False, error_str)

    def test_connection(self) -> bool:
        """Test database connectivity."""
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool:
            try:
                # Close with timeout to prevent hanging at shutdown
                self._pool.close(timeout=2.0)
            except Exception:
                # Ignore errors during shutdown (e.g., threading finalization)
                pass
            finally:
                self._pool = None


# Global database instance
_db: Database | None = None


def get_db() -> Database:
    """Get global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
