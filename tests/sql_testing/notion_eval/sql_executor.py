"""Execute gold and generated SQL against the live DB and compare results.

Requires DB connectivity (VPN + SSH tunnel on user's machine).
Gold SQL is transpiled from Oracle/SQL Server to PostgreSQL via sqlglot
before execution. Both SQLs pass through sql_guard before being wrapped
in SELECT COUNT(*) FROM (...) to get true result-set sizes.
"""

from __future__ import annotations

import logging
import re
import time

try:
    import sqlglot
    _SQLGLOT_AVAILABLE = True
except ImportError:
    _SQLGLOT_AVAILABLE = False

from tests.sql_testing.notion_eval.ticket_models import ExecutionResult, TicketData

logger = logging.getLogger(__name__)

_DIALECT_MAP = {
    "oracle": "oracle",
    "sqlserver": "tsql",
    "postgresql": "postgres",
}

_SCHEMA_PREFIXES = re.compile(
    r"\b(?:CUH|ddc_internal|KCMH_HIS|cleaned_ddc_internal)\.",
    re.IGNORECASE,
)

_ORACLE_HINTS = re.compile(r"/\*\+.*?\*/", re.DOTALL)
_ORACLE_ROWNUM = re.compile(r"\bAND\s+ROWNUM\s*<=?\s*\d+", re.IGNORECASE)


def _strip_schema(sql: str) -> str:
    return _SCHEMA_PREFIXES.sub("", sql)


def _transpile_to_postgres(sql: str, dialect: str) -> tuple[str, str | None]:
    """Transpile gold SQL to PostgreSQL. Returns (pg_sql, error_or_None)."""
    if not _SQLGLOT_AVAILABLE:
        return sql, "sqlglot not installed"

    clean = _strip_schema(sql)
    clean = _ORACLE_HINTS.sub("", clean)
    clean = _ORACLE_ROWNUM.sub("", clean)

    read_dialect = _DIALECT_MAP.get(dialect, "oracle")
    try:
        statements = sqlglot.transpile(clean, read=read_dialect, write="postgres", pretty=False)
        if not statements:
            return clean, "transpile produced no output"
        return statements[0], None
    except Exception as exc:
        logger.warning("Transpile failed (%s → postgres): %s", dialect, exc)
        return clean, str(exc)


def _guard_sql(sql: str, label: str) -> str | None:
    """Run sql through app.sql_guard. Returns error string or None if safe."""
    try:
        from app.sql_guard import validate_sql
        result = validate_sql(sql)
        if not result.is_valid:
            return f"guard_blocked: {result.error}"
        return None
    except ImportError:
        # Fallback when running outside app context: minimal SELECT/WITH check
        stripped = sql.strip().upper().lstrip("(")
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            return f"guard_blocked: not a SELECT/CTE statement"
        return None
    except Exception as exc:
        return f"guard_error: {exc}"


def _wrap_count(sql: str) -> str:
    """Wrap any SELECT in COUNT(*) to get true result-set size."""
    stripped = sql.strip().rstrip(";")
    return f"SELECT COUNT(*) AS _total FROM ({stripped}) AS _subq"


def _run_count(db: object, sql: str, timeout_ms: int) -> tuple[int | None, str | None, float]:
    """Validate, wrap in COUNT(*), execute. Returns (count, error, exec_ms)."""
    guard_err = _guard_sql(sql, "sql")
    if guard_err:
        return None, guard_err, 0.0

    count_sql = _wrap_count(sql)
    t0 = time.monotonic()
    try:
        result = db.execute_query(count_sql, timeout_ms=timeout_ms, max_rows=1)  # type: ignore[attr-defined]
        exec_ms = (time.monotonic() - t0) * 1000
        count = int(result.rows[0][0]) if result.rows else 0
        return count, None, exec_ms
    except Exception as exc:
        exec_ms = (time.monotonic() - t0) * 1000
        return None, str(exc), exec_ms


def execute_both(
    ticket: TicketData,
    gen_sql: str,
    timeout_ms: int = 30_000,
) -> ExecutionResult:
    """Run generated SQL and transpiled gold SQL against the live DB.

    Both are guarded (sql_guard) then wrapped in SELECT COUNT(*) FROM (...)
    so the comparison is true result-set size.

    Requires `app.db` to be reachable (VPN + correct DATABASE_URL in .env).
    """
    from app.db import get_db
    db = get_db()

    label = ticket.ticket_number or ticket.id[:8]

    gen_row_count, gen_error, gen_exec_ms = _run_count(db, gen_sql, timeout_ms)
    if gen_error:
        logger.warning("gen SQL failed for %s: %s", label, gen_error)
    else:
        logger.debug("gen SQL OK: %d rows in %.0fms", gen_row_count, gen_exec_ms)

    gold_pg_sql, transpile_error = _transpile_to_postgres(ticket.gold_sql, ticket.gold_sql_dialect)
    if transpile_error:
        logger.warning("Transpile warning for %s: %s", label, transpile_error)

    gold_row_count, gold_error, gold_exec_ms = _run_count(db, gold_pg_sql, timeout_ms)
    if gold_error:
        logger.warning("gold SQL failed for %s: %s", label, gold_error)
    else:
        logger.debug("gold SQL OK: %d rows in %.0fms", gold_row_count, gold_exec_ms)

    exec_result = ExecutionResult(
        ticket_id=ticket.id,
        gen_row_count=gen_row_count,
        gen_error=gen_error,
        gen_exec_time_ms=gen_exec_ms,
        gold_row_count=gold_row_count,
        gold_error=gold_error,
        gold_exec_time_ms=gold_exec_ms,
        gold_sql_transpiled=gold_pg_sql,
    )

    logger.info(
        "%s | gen=%s  gold=%s  match=%s",
        label,
        f"{gen_row_count} rows" if gen_error is None else f"ERR({gen_error[:40]})",
        f"{gold_row_count} rows" if gold_error is None else f"ERR({gold_error[:40]})",
        exec_result.rowcount_match,
    )
    return exec_result
