"""
Chat orchestrator - main flow for handling user questions.

Flow:
1. Generate SQL via LLM
2. If needs_clarification → return question
3. Validate SQL with guard
4. If guard fails → retry once with error context
5. Execute query with timeout
6. Run sanity checks
7. Format response with answer, SQL, assumptions, confidence
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schema_catalog import SchemaCatalog, get_schema_catalog
from app.db import CancellableQuery, QueryCancelledError, get_db
from app.llm import get_llm_client
from app.models import ChatRequest, ChatResponse, QueryResult, SanityCheckResult, TokenUsage
from app.staged_query import (
    MAX_MATERIALIZE_ROWS,
    STAGE_TIMEOUT_MS,
    StageResult,
    StagedExecutor,
    analyze_dependencies,
    find_leaf_ctes,
    parse_ctes,
    rebuild_query,
)
from app.sql_optimizer import (
    _PRE_EXEC_MAX_ROWS,
    _PRE_EXEC_TIMEOUT_MS,
    is_large_table_scan,
    optimize_query,
)
from app.query_complexity import analyze_query_complexity, format_complexity_warning
from app.session import get_session_manager
from app.sql_gen import get_sql_generator
from app.sql_guard import SQLGuardError, validate_sql
from app.query_logger import AttemptLog, create_log_task
from app.learning_store import get_learning_store
from app.validators import run_sanity_checks

logger = logging.getLogger(__name__)


def _suppress_small_cells(
    rows: list[list[Any]],
    columns: list[str],
    count_columns: list[str],
    minimum_count: int = 5,
) -> tuple[list[list[Any]], int]:
    """Remove rows containing count values below the privacy threshold."""
    count_indexes = [
        index for index, column in enumerate(columns)
        if column in count_columns
    ]
    if not count_indexes:
        return rows, 0

    filtered_rows = [
        row for row in rows
        if not any(
            isinstance(row[index], (int, float))
            and not isinstance(row[index], bool)
            and row[index] < minimum_count
            for index in count_indexes
        )
    ]
    return filtered_rows, len(rows) - len(filtered_rows)


class ChatOrchestrator:
    """Orchestrates the chat flow for SQL generation and execution."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._catalog: SchemaCatalog | None = None

    @property
    def catalog(self) -> SchemaCatalog | None:
        """Lazy load schema catalog."""
        if self._catalog is None:
            self._catalog = get_schema_catalog()
        return self._catalog

    async def handle_message(
        self,
        request: ChatRequest,
        user_email: str | None = None,
    ) -> ChatResponse:
        """
        Handle a user message and return a response.

        Args:
            request: Chat request with message and optional session_id

        Returns:
            ChatResponse with answer, SQL, and metadata
        """
        session_manager = get_session_manager()
        session = session_manager.get_or_create_session(
            request.session_id,
            owner_email=user_email,
        )

        # Add user message to session
        session.add_message("user", request.message)

        try:
            response = await self._process_question(
                question=request.message,
                session_id=session.session_id,
                user_email=user_email,
            )
        except Exception as e:
            logger.exception("Error processing question")
            response = ChatResponse(
                session_id=session.session_id,
                answer="I encountered an error processing your question. Please try rephrasing it.",
                error=str(e),
            )

        # Add assistant response to session
        session.add_message("assistant", response.answer, sql=response.sql)

        return response

    async def _process_question(
        self,
        question: str,
        session_id: str,
        user_email: str | None = None,
    ) -> ChatResponse:
        """
        Process a user question through the full pipeline.

        Args:
            question: User's analytical question
            session_id: Session ID for context

        Returns:
            ChatResponse with answer and metadata
        """
        session_manager = get_session_manager()
        generator = get_sql_generator()

        # Get conversation history for context
        history = session_manager.get_conversation_history(
            session_id,
            max_messages=6,
            owner_email=user_email,
        )

        # Token accumulator across all LLM calls
        total_usage = TokenUsage()

        def _accumulate(usage: TokenUsage) -> None:
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.total_tokens += usage.total_tokens

        # Step 1: Generate SQL via LLM
        gen_response, gen_usage = generator.generate(question, conversation_history=history)
        _accumulate(gen_usage)

        # Step 2: Check if clarification needed
        if gen_response.needs_clarification:
            return ChatResponse(
                session_id=session_id,
                answer=gen_response.clarification_question or "Could you please clarify your question?",
                needs_clarification=True,
                clarification_question=gen_response.clarification_question,
                assumptions=gen_response.assumptions,
                confidence=gen_response.confidence,
                token_usage=total_usage,
            )

        sql = gen_response.sql
        if not sql:
            return ChatResponse(
                session_id=session_id,
                answer="I couldn't generate a SQL query for your question. Could you rephrase it?",
                error="No SQL generated",
                confidence="low",
            )

        # Step 3: Validate SQL with guard
        validation = validate_sql(
            sql=sql,
            catalog=self.catalog,
            max_rows=self._settings.sql_max_rows,
            strict_catalog_check=True,  # Fail on unknown tables/columns
        )

        # Step 4: If guard fails, try to regenerate once
        if not validation.valid:
            logger.warning(f"SQL validation failed: {validation.error}")

            # Try to fix by asking LLM to regenerate
            retry_response, retry_usage = await self._retry_with_error(
                question=question,
                failed_sql=sql,
                error=validation.error or "Unknown error",
                history=history,
            )
            if retry_usage:
                _accumulate(retry_usage)

            if retry_response:
                # Validate the retry (also with strict checking)
                retry_validation = validate_sql(
                    sql=retry_response.sql,
                    catalog=self.catalog,
                    max_rows=self._settings.sql_max_rows,
                    strict_catalog_check=True,
                )

                if retry_validation.valid:
                    sql = retry_response.sql
                    gen_response = retry_response
                else:
                    return ChatResponse(
                        session_id=session_id,
                        answer=f"I couldn't generate a safe SQL query. Error: {validation.error}",
                        sql=sql,
                        error=validation.error,
                        assumptions=gen_response.assumptions,
                        confidence="low",
                    )
            else:
                return ChatResponse(
                    session_id=session_id,
                    answer=f"I couldn't generate a safe SQL query. Error: {validation.error}",
                    sql=sql,
                    error=validation.error,
                    assumptions=gen_response.assumptions,
                    confidence="low",
                )

        # Step 5: Analyze query complexity
        complexity = analyze_query_complexity(sql)
        logger.info(f"Query complexity: {complexity.level} (~{complexity.estimated_seconds}s)")

        # Add complexity warning to assumptions if high/critical
        complexity_warning = None
        if complexity.level in ("HIGH", "CRITICAL"):
            complexity_warning = format_complexity_warning(complexity)
            logger.info(f"Complex query detected: {complexity_warning}")

        # Step 6: Runtime validation with EXPLAIN (dry-run)
        db = get_db()
        is_valid_runtime, explain_error = db.explain_query(
            sql=sql,
            timeout_ms=5000,  # 5 second timeout for EXPLAIN
        )

        if not is_valid_runtime:
            logger.warning(f"SQL EXPLAIN validation failed: {explain_error}")

            # Try to fix by asking LLM to regenerate with runtime error
            retry_response, retry_usage = await self._retry_with_error(
                question=question,
                failed_sql=sql,
                error=explain_error or "Runtime validation failed",
                history=history,
            )
            if retry_usage:
                _accumulate(retry_usage)

            if retry_response:
                # Validate the retry with both sql_guard and EXPLAIN
                retry_validation = validate_sql(
                    sql=retry_response.sql,
                    catalog=self.catalog,
                    max_rows=self._settings.sql_max_rows,
                    strict_catalog_check=True,
                )

                if retry_validation.valid:
                    # Check runtime validity too
                    is_valid_retry, retry_explain_error = db.explain_query(
                        sql=retry_response.sql,
                        timeout_ms=5000,
                    )

                    if is_valid_retry:
                        sql = retry_response.sql
                        gen_response = retry_response
                    else:
                        return ChatResponse(
                            session_id=session_id,
                            answer=f"I couldn't execute the query. Error: {retry_explain_error}",
                            sql=retry_response.sql,
                            error=retry_explain_error,
                            assumptions=retry_response.assumptions,
                            confidence="low",
                        )
                else:
                    return ChatResponse(
                        session_id=session_id,
                        answer=f"I couldn't execute the query. Error: {explain_error}",
                        sql=sql,
                        error=explain_error,
                        assumptions=gen_response.assumptions,
                        confidence="low",
                    )
            else:
                return ChatResponse(
                    session_id=session_id,
                    answer=f"I couldn't execute the query. Error: {explain_error}",
                    sql=sql,
                    error=explain_error,
                    assumptions=gen_response.assumptions,
                    confidence="low",
                )

        # Step 7: Optimize query (flatten CTE fences + pre-execute small CTEs)
        optimized = optimize_query(sql)
        if optimized:
            logger.info("SQL optimizer: flattened leaf CTEs")
            sql = optimized

        sql = self._pre_execute_small_ctes(sql, db)

        # Step 8: Execute query (with retry on errors)
        # Use complexity-based timeout, capped at max (0 = no timeout)
        if self._settings.sql_statement_timeout_ms == 0:
            execution_timeout = 0
        else:
            base = max(complexity.suggested_timeout_ms, self._settings.sql_statement_timeout_ms)
            execution_timeout = (
                min(base, self._settings.sql_max_timeout_ms)
                if self._settings.sql_max_timeout_ms > 0
                else base
            )
        logger.info(f"Executing with timeout: {execution_timeout}ms (complexity={complexity.level})")

        result: QueryResult | None = None
        try:
            result = db.execute_query(
                sql=sql,
                timeout_ms=execution_timeout,
                max_rows=self._settings.sql_max_rows,
            )
        except Exception as e:
            logger.warning(f"Database execution error: {e}")

            error_str = str(e)
            is_timeout = "timeout" in error_str.lower() or "canceling statement" in error_str.lower()
            is_runtime_error = any(x in error_str.lower() for x in [
                "syntax error", "does not exist", "type", "invalid", "division by zero",
                "out of range", "cannot cast", "ambiguous"
            ])

            # --- Staged execution fallback for timeouts ---
            if is_timeout:
                try:
                    staged = StagedExecutor(db)
                    if staged.can_decompose(sql):
                        logger.info("Attempting staged query execution after timeout")
                        staged_result = await asyncio.to_thread(
                            staged.execute_staged,
                            sql,
                            execution_timeout,
                            self._settings.sql_max_rows,
                        )
                        if staged_result is not None:
                            result = staged_result.query_result
                            logger.info(
                                "Staged execution succeeded: %d stages, %.0fms staging",
                                staged_result.stages_executed,
                                staged_result.total_stage_time_ms,
                            )
                except Exception as staged_e:
                    logger.warning(f"Staged execution failed: {staged_e}")

            # --- LLM retry if staged didn't resolve it ---
            if result is None and (is_timeout or is_runtime_error):
                retry_response, retry_usage = await self._retry_with_error(
                    question=question,
                    failed_sql=sql,
                    error=f"Query execution failed: {error_str}",
                    history=history,
                )
                if retry_usage:
                    _accumulate(retry_usage)

                if retry_response:
                    retry_validation = validate_sql(
                        sql=retry_response.sql,
                        catalog=self.catalog,
                        max_rows=self._settings.sql_max_rows,
                        strict_catalog_check=True,
                    )

                    if retry_validation.valid:
                        is_valid_retry, retry_explain_error = db.explain_query(
                            sql=retry_response.sql,
                            timeout_ms=5000,
                        )

                        if is_valid_retry:
                            try:
                                result = db.execute_query(
                                    sql=retry_response.sql,
                                    timeout_ms=execution_timeout,
                                    max_rows=self._settings.sql_max_rows,
                                )
                                sql = retry_response.sql
                                gen_response = retry_response
                                logger.info("Retry execution succeeded")
                            except Exception as retry_e:
                                logger.exception("Retry execution also failed")
                                return ChatResponse(
                                    session_id=session_id,
                                    answer=f"I couldn't execute the query. Error: {retry_e}",
                                    sql=retry_response.sql,
                                    error=str(retry_e),
                                    assumptions=retry_response.assumptions,
                                    confidence="low",
                                )
                        else:
                            return ChatResponse(
                                session_id=session_id,
                                answer=f"I couldn't execute the query. Error: {retry_explain_error}",
                                sql=retry_response.sql,
                                error=retry_explain_error,
                                assumptions=retry_response.assumptions,
                                confidence="low",
                            )
                    else:
                        return ChatResponse(
                            session_id=session_id,
                            answer=f"I couldn't execute the query. Error: {error_str}",
                            sql=sql,
                            error=error_str,
                            assumptions=gen_response.assumptions,
                            confidence="low",
                        )

            # Non-retryable error or all retries failed
            if result is None:
                return ChatResponse(
                    session_id=session_id,
                    answer=f"I couldn't execute the query. Error: {e}",
                    sql=sql,
                    error=str(e),
                    assumptions=gen_response.assumptions,
                    concepts_used=gen_response.concepts_used,
                    confidence="low",
                )

        # Step 8a: Zero-result retry with extended thinking
        if result is not None and result.row_count == 0:
            logger.info("Zero-result retry: query returned 0 rows, retrying with extended thinking")
            zero_errors = [{
                "sql": sql,
                "error": (
                    "Query returned 0 rows. The query executed successfully "
                    "but found no matching data. Try different tables, "
                    "columns, or filter conditions."
                ),
                "stage": "zero_results",
            }]
            retry_gen, retry_usage = self._retry_with_accumulated_errors(
                question, zero_errors, history,
            )
            if retry_usage:
                _accumulate(retry_usage)

            if retry_gen and retry_gen.sql:
                retry_val = validate_sql(
                    sql=retry_gen.sql, catalog=self.catalog,
                    max_rows=self._settings.sql_max_rows,
                    strict_catalog_check=True,
                )
                if retry_val.valid:
                    is_valid_retry, _ = db.explain_query(
                        sql=retry_gen.sql, timeout_ms=5000,
                    )
                    if is_valid_retry:
                        try:
                            retry_result = db.execute_query(
                                sql=retry_gen.sql,
                                timeout_ms=execution_timeout,
                                max_rows=self._settings.sql_max_rows,
                            )
                            if retry_result.row_count > 0:
                                result = retry_result
                                sql = retry_gen.sql
                                gen_response = retry_gen
                                logger.info("Zero-result retry succeeded with %d rows", result.row_count)
                        except Exception as retry_e:
                            logger.warning("Zero-result retry execution failed: %s", retry_e)

        # Step 8b: Run sanity checks
        sanity_results = run_sanity_checks(result, gen_response.validation_checks)

        # Check if any critical sanity check failed
        failed_checks = [c for c in sanity_results if not c.passed]
        if failed_checks:
            logger.warning(f"Sanity checks failed: {[c.message for c in failed_checks]}")

        # Step 9: Format answer
        answer, fmt_usage = await self._format_answer(
            question=question,
            sql=sql,
            result=result,
            assumptions=gen_response.assumptions,
            concepts_used=gen_response.concepts_used,
            failed_checks=failed_checks,
        )
        _accumulate(fmt_usage)

        # Add complexity warning if query was complex
        if complexity_warning:
            answer = f"{complexity_warning}\n\n{answer}"

        return ChatResponse(
            session_id=session_id,
            answer=answer,
            sql=sql,
            assumptions=gen_response.assumptions,
            concepts_used=gen_response.concepts_used,
            confidence=gen_response.confidence,
            sanity_checks=sanity_results,
            query_result=result,
            token_usage=total_usage,
        )

    def _pre_execute_small_ctes(self, sql: str, db: Any) -> str:
        """Pre-execute small leaf CTEs and materialize as VALUES.

        Runs BEFORE the main execution to give PostgreSQL better
        optimization hints (known-size VALUES vs opaque CTE scans).
        Only targets small reference table lookups (LABEXM, ICD10, etc.).
        """
        parsed = parse_ctes(sql)
        if not parsed:
            return sql

        ctes, final_query = parsed
        deps = analyze_dependencies(ctes)
        leaves = find_leaf_ctes(deps)

        if not leaves:
            return sql

        materialized: dict[str, StageResult] = {}

        for leaf_name in leaves:
            cte = next(c for c in ctes if c.name == leaf_name)

            # Skip CTEs that scan known large tables
            if is_large_table_scan(cte.body):
                continue

            try:
                result = db.execute_query(
                    sql=cte.body,
                    timeout_ms=_PRE_EXEC_TIMEOUT_MS,
                    max_rows=_PRE_EXEC_MAX_ROWS + 1,
                )
                if result.row_count <= _PRE_EXEC_MAX_ROWS:
                    materialized[leaf_name] = StageResult(
                        name=leaf_name,
                        columns=tuple(result.columns),
                        rows=tuple(tuple(r) for r in result.rows),
                        row_count=result.row_count,
                        execution_time_ms=0,
                    )
                    logger.info(
                        "Pre-executed CTE %s: %d rows (materialized as VALUES)",
                        leaf_name, result.row_count,
                    )
            except Exception as exc:
                logger.debug("Pre-execution of CTE %s failed: %s", leaf_name, exc)
                continue

        if not materialized:
            return sql

        rebuilt = rebuild_query(ctes, materialized, final_query)
        logger.info(
            "Pre-executed %d/%d leaf CTEs as VALUES",
            len(materialized), len(leaves),
        )
        return rebuilt

    def _retry_with_error_impl(
        self,
        question: str,
        failed_sql: str,
        error: str,
        history: list[dict[str, str]],
    ) -> tuple[Any, TokenUsage | None]:
        """Retry SQL generation with error context (sync).

        Returns:
            Tuple of (SQLGenerationResponse or None, TokenUsage or None)
        """
        generator = get_sql_generator()

        available_tables = ""
        if self.catalog:
            table_list = sorted(self.catalog.tables.keys())
            available_tables = f"\n\nAvailable tables: {', '.join(table_list)}"

            if "Unknown table" in error:
                available_tables += "\n\nPlease use ONLY these exact table names."

            if "Unknown column" in error or "does not exist" in error:
                for table_name in table_list:
                    if table_name.lower() in failed_sql.lower():
                        table = self.catalog.tables[table_name]
                        cols = list(table.columns.keys())
                        if cols:
                            available_tables += (
                                f"\n\nVerified columns in {table_name}: "
                                f"{', '.join(cols)}"
                            )
                available_tables += (
                    "\n\nCRITICAL: Use ONLY the verified column names above. "
                    "Do NOT invent or guess column names."
                )

        is_timeout = (
            "timeout" in error.lower()
            or "canceling statement" in error.lower()
        )

        fix_guidance = (
            "Remember: no PHI columns in SELECT, no SELECT *, "
            "and non-aggregate queries need LIMIT."
        )

        if is_timeout:
            fix_guidance = (
                "The query timed out. You MUST apply these optimizations:\n"
                "1. NEVER scan the same large table twice - combine into ONE CTE "
                "with CASE WHEN or EXTRACT(YEAR) for period classification\n"
                "2. Pre-filter reference tables (LABEXM, ICD10, etc.) in a small "
                "CTE FIRST, then INNER JOIN to large tables\n"
                "3. Use EXISTS instead of JOIN when counting DISTINCT patients\n"
                "4. Add date filters as the FIRST condition on large tables "
                "(LVST, OVST, IPT, PRSC)\n"
                "5. Combine UNION queries into a single query with CASE WHEN "
                "when possible\n"
                "6. For numeric text columns (lab results): apply date filter "
                "BEFORE regex/CAST operations\n"
                "7. Reduce the number of CTEs - merge CTEs that scan the same table"
            )

        # Inject learned patterns from past mistakes (only during retries)
        learned_section = ""
        try:
            store = get_learning_store()
            learned_section = store.build_prompt_section(question, sql=failed_sql)
        except Exception:
            pass  # non-critical

        error_context = history + [
            {
                "role": "assistant",
                "content": (
                    f"I generated this SQL but it failed:\n"
                    f"```sql\n{failed_sql}\n```\n"
                    f"Error: {error}{available_tables}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Please fix the SQL. {fix_guidance}\n\n"
                    f"{learned_section}"
                    f"Original question: {question}"
                ),
            },
        ]

        try:
            response, usage = generator.generate(
                question, conversation_history=error_context,
            )
            return response, usage
        except Exception:
            logger.exception("Retry failed")
            return None, None

    async def _retry_with_error(
        self,
        question: str,
        failed_sql: str,
        error: str,
        history: list[dict[str, str]],
    ) -> tuple[Any, TokenUsage | None]:
        """Retry SQL generation with error context."""
        return self._retry_with_error_impl(
            question, failed_sql, error, history,
        )

    def _build_verified_columns_info(
        self,
        accumulated_errors: list[dict[str, str]],
    ) -> str:
        """Build verified columns info for tables referenced in failed SQL."""
        if not self.catalog:
            return "No schema catalog available."

        tables_referenced: set[str] = set()
        for err in accumulated_errors:
            sql_text = err.get("sql", "")
            for table_name in self.catalog.tables:
                if table_name.lower() in sql_text.lower():
                    tables_referenced.add(table_name)

        if not tables_referenced:
            return "No tables identified in failed SQL."

        lines: list[str] = []
        for table_name in sorted(tables_referenced):
            table = self.catalog.tables.get(table_name)
            if not table:
                continue
            cols = list(table.columns.keys())
            if cols:
                lines.append(f"**{table_name}**: {', '.join(cols)}")

        return "\n".join(lines) if lines else "No column info available."

    def _build_fix_guidance(
        self,
        accumulated_errors: list[dict[str, str]],
    ) -> str:
        """Build fix guidance based on error patterns."""
        has_timeout = any(
            "timeout" in e.get("error", "").lower()
            or "canceling statement" in e.get("error", "").lower()
            for e in accumulated_errors
        )
        has_column_error = any(
            "does not exist" in e.get("error", "").lower()
            for e in accumulated_errors
        )

        parts = [
            "No PHI columns in SELECT. No SELECT *. "
            "Non-aggregate queries need LIMIT.",
        ]

        if has_timeout:
            parts.append(
                "TIMEOUT FIX: "
                "1) Never scan same large table twice. "
                "2) Pre-filter reference tables in CTE FIRST. "
                "3) Use EXISTS for DISTINCT counts. "
                "4) Date filters as FIRST condition. "
                "5) Combine UNION into CASE WHEN. "
                "6) Reduce CTEs."
            )

        if has_column_error:
            parts.append(
                "COLUMN ERROR: You used column names that DO NOT EXIST. "
                "Check the VERIFIED COLUMNS list and use ONLY those exact names. "
                "Do NOT guess or invent column names."
            )

        has_zero_results = any(
            "zero rows" in e.get("error", "").lower()
            or "returned 0 rows" in e.get("error", "").lower()
            for e in accumulated_errors
        )
        if has_zero_results:
            parts.append(
                "ZERO RESULTS FIX: The query returned 0 rows. Try a DIFFERENT approach:\n"
                "1) Use different tables (e.g. IPTSUMOPRT instead of PTOPRT for icd9cm)\n"
                "2) Check date column names (vstdate vs lvstdate vs indate)\n"
                "3) Broaden filter values (LIKE '%%keyword%%' instead of exact match)\n"
                "4) Verify join conditions - a wrong join can silently filter out all rows\n"
                "5) Check if the column you're filtering on is actually populated"
            )

        return "\n\n".join(parts)

    def _retry_with_accumulated_errors(
        self,
        question: str,
        accumulated_errors: list[dict[str, str]],
        history: list[dict[str, str]],
    ) -> tuple[Any, TokenUsage | None]:
        """Retry SQL generation with all accumulated errors and extended thinking.

        Returns:
            Tuple of (SQLGenerationResponse or None, TokenUsage or None)
        """
        generator = get_sql_generator()

        error_history = list(history)

        for i, err in enumerate(accumulated_errors, 1):
            error_history.append({
                "role": "assistant",
                "content": (
                    f"Attempt {i} SQL (FAILED at {err.get('stage', 'unknown')}):\n"
                    f"```sql\n{err.get('sql', '')}\n```\n"
                    f"Error: {err.get('error', 'Unknown')}"
                ),
            })

        columns_info = self._build_verified_columns_info(accumulated_errors)
        fix_guidance = self._build_fix_guidance(accumulated_errors)

        # Inject learned patterns from past mistakes (only during retries)
        learned_section = ""
        try:
            store = get_learning_store()
            last_sql = accumulated_errors[-1].get("sql", "") if accumulated_errors else ""
            learned_section = store.build_prompt_section(question, sql=last_sql)
        except Exception:
            pass  # non-critical

        error_history.append({
            "role": "user",
            "content": (
                f"Fix the SQL for this question: {question}\n\n"
                f"{fix_guidance}\n\n"
                f"{learned_section}"
                f"## VERIFIED COLUMNS (CRITICAL - USE ONLY THESE)\n"
                f"{columns_info}\n\n"
                f"DO NOT invent column names. If a column is not listed above, "
                f"it DOES NOT EXIST in the database."
            ),
        })

        try:
            response, usage = generator.generate(
                question,
                conversation_history=error_history,
                extended_thinking=True,
            )
            return response, usage
        except Exception:
            logger.exception("Retry with accumulated errors failed")
            return None, None

    def _format_answer_impl(
        self,
        question: str,
        sql: str,
        result: QueryResult,
        assumptions: list[str],
        concepts_used: list[str],
        failed_checks: list[SanityCheckResult],
    ) -> tuple[str, TokenUsage]:
        """Format the final answer from query results (sync).

        Returns:
            Tuple of (answer text, TokenUsage)
        """
        llm = get_llm_client()

        result_data = {
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
        }

        answer, usage = llm.format_answer(
            question=question,
            _sql=sql,
            result_data=result_data,
            assumptions=assumptions,
            concepts_used=concepts_used,
        )

        if failed_checks:
            warnings = "\n\n**Note**: Some data validation checks raised concerns:\n"
            for check in failed_checks:
                warnings += f"- {check.message}\n"
            answer += warnings

        if result.truncated:
            answer += f"\n\n*Note: Results were limited to {result.row_count} rows.*"

        return answer, usage

    async def _format_answer(
        self,
        question: str,
        sql: str,
        result: QueryResult,
        assumptions: list[str],
        concepts_used: list[str],
        failed_checks: list[SanityCheckResult],
    ) -> tuple[str, TokenUsage]:
        """Format the final answer from query results."""
        return self._format_answer_impl(
            question, sql, result, assumptions, concepts_used, failed_checks,
        )


    # ------------------------------------------------------------------
    # Streaming interface
    # ------------------------------------------------------------------

    async def handle_message_streaming(
        self,
        request: ChatRequest,
        cancellable: CancellableQuery,
        user_email: str | None = None,
        user_role: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Handle a message with streaming progress events."""
        session_manager = get_session_manager()
        session = session_manager.get_or_create_session(
            request.session_id,
            owner_email=user_email,
        )
        session.add_message("user", request.message)

        try:
            async for event in self._process_question_streaming(
                question=request.message,
                session_id=session.session_id,
                cancellable=cancellable,
                user_email=user_email,
                user_role=user_role,
            ):
                if event.get("event") == "complete" and "data" in event:
                    data = event["data"]
                    session.add_message(
                        "assistant",
                        data.get("answer", ""),
                        sql=data.get("sql"),
                    )
                yield event
        except QueryCancelledError:
            session.add_message("assistant", "Query cancelled by user")
            yield {"event": "cancelled", "message": "Query cancelled by user"}
        except Exception as e:
            logger.exception("Error in streaming pipeline")
            session.add_message("assistant", "An error occurred processing your question.")
            yield {
                "event": "error",
                "step": "unknown",
                "message": "An error occurred processing your question. Please try again.",
            }

    async def _emit_countdown(
        self,
        error_str: str,
        sql: str,
        cancellable: CancellableQuery,
        countdown_secs: int = 3,
    ) -> AsyncGenerator[dict, None]:
        """Yield auto-fix countdown events (3s -> 0) before retry."""
        yield {
            "event": "auto_fix_countdown",
            "data": {
                "error_message": error_str,
                "failed_sql": sql,
                "seconds_remaining": countdown_secs,
            },
        }
        for sec in range(countdown_secs - 1, -1, -1):
            await asyncio.sleep(1)
            cancellable.check_cancelled()
            yield {
                "event": "auto_fix_countdown",
                "data": {"seconds_remaining": sec},
            }

    async def _process_question_streaming(
        self,
        question: str,
        session_id: str,
        cancellable: CancellableQuery,
        user_email: str | None = None,
        user_role: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Process a question with up to 5 auto-fix retries and streaming progress.

        Each attempt runs: generate SQL -> validate -> EXPLAIN -> optimize -> execute.
        On failure at any stage, the error is accumulated and the next attempt
        starts with a new progress bar in the UI.
        """
        MAX_RETRIES = 5
        total_attempts = MAX_RETRIES + 1
        query_group_id = uuid.uuid4()

        session_manager = get_session_manager()
        generator = get_sql_generator()
        history = session_manager.get_conversation_history(
            session_id,
            max_messages=6,
            owner_email=user_email,
        )

        def _progress(step: str, message: str, pct: int) -> dict:
            return {"event": "progress", "step": step,
                    "message": message, "progress": pct}

        def _complete(resp: ChatResponse) -> dict:
            return {"event": "complete", "data": resp.model_dump()}

        def _fail(answer: str, **kw: Any) -> dict:
            kw.setdefault("token_usage", total_usage)
            return _complete(ChatResponse(
                session_id=session_id, answer=answer, **kw,
            ))

        # Token accumulator across all LLM calls
        total_usage = TokenUsage()

        def _accumulate(usage: TokenUsage | None) -> None:
            if usage is None:
                return
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.total_tokens += usage.total_tokens

        def _log(attempt: int, stage: str, **kwargs: Any) -> None:
            """Fire-and-forget log of one attempt."""
            create_log_task(AttemptLog(
                query_group_id=query_group_id,
                attempt_number=attempt,
                session_id=session_id,
                question=question,
                attempt_stage=stage,
                user_email=user_email,
                user_role=user_role,
                generated_sql=kwargs.get("generated_sql"),
                assumptions=kwargs.get("assumptions"),
                concepts_used=kwargs.get("concepts_used"),
                confidence=kwargs.get("confidence"),
                guard_valid=kwargs.get("guard_valid"),
                guard_error=kwargs.get("guard_error"),
                explain_valid=kwargs.get("explain_valid"),
                explain_error=kwargs.get("explain_error"),
                execution_time_ms=kwargs.get("execution_time_ms"),
                row_count=kwargs.get("row_count"),
                result_truncated=kwargs.get("result_truncated"),
                error_message=kwargs.get("error_message"),
                answer=kwargs.get("answer"),
                sanity_checks=kwargs.get("sanity_checks"),
                input_tokens=total_usage.input_tokens,
                output_tokens=total_usage.output_tokens,
                total_tokens=total_usage.total_tokens,
            ))

        accumulated_errors: list[dict[str, str]] = []
        sql: str | None = None
        gen: Any = None
        result: QueryResult | None = None
        complexity: Any = None
        complexity_warning: str | None = None
        zero_result_retried = False

        for attempt in range(total_attempts):
            is_retry = attempt > 0
            attempt_label = f" (attempt {attempt + 1}/{total_attempts})" if is_retry else ""

            # --- On retry: show countdown then signal new attempt ---
            if is_retry:
                last_err = accumulated_errors[-1]
                async for evt in self._emit_countdown(
                    last_err.get("error", "Unknown error"),
                    last_err.get("sql", ""),
                    cancellable,
                ):
                    yield evt

                yield {
                    "event": "auto_fix_new_attempt",
                    "data": {
                        "attempt": attempt + 1,
                        "max_attempts": total_attempts,
                        "error_message": last_err.get("error", "Unknown error"),
                        "failed_sql": last_err.get("sql", ""),
                    },
                }

            # --- Step 1: Generate SQL ---
            yield _progress(
                "generating_sql",
                f"Generating SQL{attempt_label}...",
                10,
            )
            cancellable.check_cancelled()

            if is_retry:
                gen, gen_usage = await asyncio.to_thread(
                    self._retry_with_accumulated_errors,
                    question, accumulated_errors, history,
                )
                _accumulate(gen_usage)
                if not gen or not gen.sql:
                    accumulated_errors.append({
                        "sql": accumulated_errors[-1].get("sql", "") if accumulated_errors else "",
                        "error": "Auto-fix failed to generate corrected SQL",
                        "stage": "generation",
                    })
                    _log(attempt, "generation", error_message="Auto-fix failed to generate corrected SQL")
                    continue
            else:
                gen, gen_usage = await asyncio.to_thread(generator.generate, question, history)
                _accumulate(gen_usage)

            # Clarification / no SQL - not retryable
            if gen.needs_clarification:
                _log(attempt, "clarification",
                     assumptions=gen.assumptions, confidence=gen.confidence,
                     error_message=gen.clarification_question)
                yield _fail(
                    gen.clarification_question or "Could you please clarify?",
                    needs_clarification=True,
                    clarification_question=gen.clarification_question,
                    assumptions=gen.assumptions, confidence=gen.confidence,
                    token_usage=total_usage,
                )
                return

            sql = gen.sql
            if not sql:
                _log(attempt, "generation", error_message="No SQL generated")
                yield _fail(
                    "I couldn't generate a SQL query. Could you rephrase?",
                    error="No SQL generated", confidence="low",
                )
                return

            # --- Step 2: Validate SQL with guard ---
            yield _progress("validating", f"Validating query safety{attempt_label}...", 30)
            cancellable.check_cancelled()
            val = validate_sql(
                sql=sql, catalog=self.catalog,
                max_rows=self._settings.sql_max_rows,
                strict_catalog_check=True,
            )

            if not val.valid:
                accumulated_errors.append({
                    "sql": sql,
                    "error": val.error or "Unknown validation error",
                    "stage": "validation",
                })
                _log(attempt, "validation",
                     generated_sql=sql, guard_valid=False,
                     guard_error=val.error,
                     assumptions=gen.assumptions, concepts_used=gen.concepts_used,
                     confidence=gen.confidence,
                     error_message=val.error)
                continue

            # --- Step 3: EXPLAIN validation (dry-run) ---
            yield _progress("explaining", f"Checking query plan{attempt_label}...", 45)
            cancellable.check_cancelled()
            is_valid, explain_err = await asyncio.to_thread(
                cancellable.explain, sql, 5000,
            )

            if not is_valid:
                accumulated_errors.append({
                    "sql": sql,
                    "error": explain_err or "Runtime validation failed",
                    "stage": "explain",
                })
                _log(attempt, "explain",
                     generated_sql=sql, guard_valid=True,
                     explain_valid=False, explain_error=explain_err,
                     assumptions=gen.assumptions, concepts_used=gen.concepts_used,
                     confidence=gen.confidence,
                     error_message=explain_err)
                continue

            # --- Step 4: Complexity analysis ---
            complexity = analyze_query_complexity(sql)
            complexity_warning = (
                format_complexity_warning(complexity)
                if complexity.level in ("HIGH", "CRITICAL") else None
            )

            # --- Step 5: Optimize query ---
            yield _progress("optimizing", f"Optimizing query{attempt_label}...", 55)
            optimized = optimize_query(sql)
            if optimized:
                logger.info("SQL optimizer: flattened leaf CTEs")
                sql = optimized

            db = get_db()
            sql = await asyncio.to_thread(
                self._pre_execute_small_ctes, sql, db,
            )

            # --- Step 6: Execute query ---
            if self._settings.sql_statement_timeout_ms == 0:
                exec_timeout = 0
            else:
                base = max(
                    complexity.suggested_timeout_ms,
                    self._settings.sql_statement_timeout_ms,
                )
                exec_timeout = (
                    min(base, self._settings.sql_max_timeout_ms)
                    if self._settings.sql_max_timeout_ms > 0
                    else base
                )
            logger.info(
                "Executing with timeout: %dms (complexity=%s, attempt=%d/%d)",
                exec_timeout, complexity.level, attempt + 1, total_attempts,
            )
            yield _progress(
                "executing",
                f"Running query{attempt_label} ({complexity.level} complexity)...",
                60,
            )

            result = None
            try:
                result = await asyncio.to_thread(
                    cancellable.execute, sql, None,
                    exec_timeout, self._settings.sql_max_rows,
                )
            except QueryCancelledError:
                raise
            except Exception as exec_err:
                error_str = str(exec_err)
                is_timeout = (
                    "timeout" in error_str.lower()
                    or "canceling statement" in error_str.lower()
                )
                is_runtime_error = any(
                    x in error_str.lower() for x in [
                        "syntax error", "does not exist", "type", "invalid",
                        "division by zero", "out of range", "cannot cast",
                        "ambiguous",
                    ]
                )

                # Staged execution fallback for timeouts
                if is_timeout:
                    try:
                        staged = StagedExecutor(get_db())
                        if staged.can_decompose(sql):
                            yield _progress(
                                "staged_execution",
                                "Retrying with staged execution...",
                                65,
                            )
                            staged_result = await asyncio.to_thread(
                                staged.execute_staged,
                                sql, exec_timeout,
                                self._settings.sql_max_rows,
                                STAGE_TIMEOUT_MS, MAX_MATERIALIZE_ROWS,
                                cancellable,
                            )
                            if staged_result is not None:
                                result = staged_result.query_result
                                logger.info(
                                    "Staged execution succeeded: %d stages, %.0fms",
                                    staged_result.stages_executed,
                                    staged_result.total_stage_time_ms,
                                )
                    except QueryCancelledError:
                        raise
                    except Exception as staged_e:
                        logger.warning("Staged execution failed: %s", staged_e)

                if result is None and (is_timeout or is_runtime_error):
                    accumulated_errors.append({
                        "sql": sql,
                        "error": f"Query execution failed: {error_str}",
                        "stage": "execution",
                    })
                    _log(attempt, "execution",
                         generated_sql=sql, guard_valid=True, explain_valid=True,
                         assumptions=gen.assumptions, concepts_used=gen.concepts_used,
                         confidence=gen.confidence,
                         error_message=f"Query execution failed: {error_str}")
                    continue

                # Non-retryable error
                if result is None:
                    _log(attempt, "terminal_error",
                         generated_sql=sql, guard_valid=True, explain_valid=True,
                         assumptions=gen.assumptions, concepts_used=gen.concepts_used,
                         confidence=gen.confidence,
                         error_message=error_str)
                    yield _fail(
                        f"I couldn't execute the query. Error: {exec_err}",
                        sql=sql, error=error_str,
                        assumptions=gen.assumptions,
                        concepts_used=gen.concepts_used, confidence="low",
                    )
                    return

            # Execution succeeded — check for zero results before breaking
            if (
                result is not None
                and result.row_count == 0
                and not zero_result_retried
            ):
                zero_result_retried = True
                zero_err = (
                    "Query returned 0 rows. The query executed successfully "
                    "but found no matching data. Try different tables, "
                    "columns, or filter conditions."
                )
                accumulated_errors.append({
                    "sql": sql,
                    "error": zero_err,
                    "stage": "zero_results",
                })
                _log(attempt, "zero_results",
                     generated_sql=sql, guard_valid=True, explain_valid=True,
                     execution_time_ms=result.execution_time_ms,
                     row_count=0, result_truncated=False,
                     assumptions=gen.assumptions, concepts_used=gen.concepts_used,
                     confidence=gen.confidence,
                     error_message=zero_err)
                logger.info("Zero-result retry: query returned 0 rows, retrying with extended thinking")
                continue

            break
        else:
            # All attempts exhausted
            last_err = accumulated_errors[-1] if accumulated_errors else {
                "error": "Unknown error", "sql": "",
            }
            _log(attempt, "exhausted",
                 generated_sql=last_err.get("sql"),
                 assumptions=gen.assumptions if gen else None,
                 concepts_used=gen.concepts_used if gen else None,
                 error_message=last_err.get("error"))
            yield _fail(
                f"I couldn't process the query after {total_attempts} attempts. "
                f"Last error: {last_err.get('error', 'Unknown')}",
                sql=last_err.get("sql", ""),
                error=last_err.get("error"),
                assumptions=gen.assumptions if gen else [],
                concepts_used=gen.concepts_used if gen else [],
                confidence="low",
            )
            return

        # --- Post-loop: capture learning from retries ---
        if accumulated_errors and sql and result is not None:
            try:
                store = get_learning_store()
                # Record each error that was overcome
                for err in accumulated_errors:
                    store.record_pattern(
                        question=question,
                        error_stage=err.get("stage", "unknown"),
                        error_summary=err.get("error", "")[:300],
                        failed_sql=err.get("sql", ""),
                        fixed_sql=sql,
                    )
            except Exception as learn_err:
                logger.debug("Learning capture failed (non-critical): %s", learn_err)

        # --- Post-loop: sanity checks, format answer ---
        assumptions = list(gen.assumptions)
        filtered_rows, suppressed_count = _suppress_small_cells(
            result.rows, result.columns, val.count_columns,
        )
        if suppressed_count:
            result = result.model_copy(update={
                "rows": filtered_rows,
                "row_count": len(filtered_rows),
            })
            assumptions.append(
                "Rows with counts below 5 were suppressed for privacy (k-anonymity)."
            )

        yield _progress("sanity_check", "Validating results...", 80)
        sanity_results = run_sanity_checks(result, gen.validation_checks)
        failed_checks = [c for c in sanity_results if not c.passed]

        yield _progress("formatting", "Preparing your answer...", 90)
        cancellable.check_cancelled()
        answer, fmt_usage = await asyncio.to_thread(
            self._format_answer_impl, question, sql, result,
            assumptions, gen.concepts_used, failed_checks,
        )
        _accumulate(fmt_usage)

        if complexity_warning:
            answer = f"{complexity_warning}\n\n{answer}"

        response = ChatResponse(
            session_id=session_id, answer=answer, sql=sql,
            assumptions=assumptions, concepts_used=gen.concepts_used,
            confidence=gen.confidence, sanity_checks=sanity_results,
            query_result=result, token_usage=total_usage,
        )
        _log(attempt, "success",
             generated_sql=sql, guard_valid=True, explain_valid=True,
             execution_time_ms=result.execution_time_ms if result else None,
             row_count=result.row_count if result else None,
             result_truncated=result.truncated if result else None,
             assumptions=assumptions, concepts_used=gen.concepts_used,
             confidence=gen.confidence, answer=answer,
             sanity_checks=[c.model_dump() for c in sanity_results])
        yield _complete(response)


# Global orchestrator instance
_orchestrator: ChatOrchestrator | None = None


def get_orchestrator() -> ChatOrchestrator:
    """Get global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ChatOrchestrator()
    return _orchestrator
