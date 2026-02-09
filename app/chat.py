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

import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schema_catalog import SchemaCatalog, get_schema_catalog
from app.db import get_db
from app.llm import get_llm_client
from app.models import ChatRequest, ChatResponse, QueryResult, SanityCheckResult
from app.query_complexity import analyze_query_complexity, format_complexity_warning
from app.session import get_session_manager
from app.sql_gen import get_sql_generator
from app.sql_guard import SQLGuardError, validate_sql
from app.validators import run_sanity_checks

logger = logging.getLogger(__name__)


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

    async def handle_message(self, request: ChatRequest) -> ChatResponse:
        """
        Handle a user message and return a response.

        Args:
            request: Chat request with message and optional session_id

        Returns:
            ChatResponse with answer, SQL, and metadata
        """
        session_manager = get_session_manager()
        session = session_manager.get_or_create_session(request.session_id)

        # Add user message to session
        session.add_message("user", request.message)

        try:
            response = await self._process_question(
                question=request.message,
                session_id=session.session_id,
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
        history = session_manager.get_conversation_history(session_id, max_messages=6)

        # Step 1: Generate SQL via LLM
        gen_response = generator.generate(question, conversation_history=history)

        # Step 2: Check if clarification needed
        if gen_response.needs_clarification:
            return ChatResponse(
                session_id=session_id,
                answer=gen_response.clarification_question or "Could you please clarify your question?",
                needs_clarification=True,
                clarification_question=gen_response.clarification_question,
                assumptions=gen_response.assumptions,
                confidence=gen_response.confidence,
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
            retry_response = await self._retry_with_error(
                question=question,
                failed_sql=sql,
                error=validation.error or "Unknown error",
                history=history,
            )

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
            logger.warning(f"Complex query detected: {complexity_warning}")

        # Step 6: Runtime validation with EXPLAIN (dry-run)
        db = get_db()
        is_valid_runtime, explain_error = db.explain_query(
            sql=sql,
            timeout_ms=5000,  # 5 second timeout for EXPLAIN
        )

        if not is_valid_runtime:
            logger.warning(f"SQL EXPLAIN validation failed: {explain_error}")

            # Try to fix by asking LLM to regenerate with runtime error
            retry_response = await self._retry_with_error(
                question=question,
                failed_sql=sql,
                error=explain_error or "Runtime validation failed",
                history=history,
            )

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

        # Step 7: Execute query (with retry on errors)
        # Use complexity-based timeout (may be higher than default for complex queries)
        execution_timeout = max(
            complexity.suggested_timeout_ms,
            self._settings.sql_statement_timeout_ms
        )
        logger.info(f"Executing with timeout: {execution_timeout}ms")

        try:
            result = db.execute_query(
                sql=sql,
                timeout_ms=execution_timeout,
                max_rows=self._settings.sql_max_rows,
            )
        except Exception as e:
            logger.warning(f"Database execution error: {e}")

            # Determine if error is retryable
            error_str = str(e)
            is_timeout = "timeout" in error_str.lower() or "canceling statement" in error_str.lower()
            is_runtime_error = any(x in error_str.lower() for x in [
                "syntax error", "does not exist", "type", "invalid", "division by zero",
                "out of range", "cannot cast", "ambiguous"
            ])

            # Try to fix by asking LLM to regenerate with execution error
            if is_timeout or is_runtime_error:
                retry_response = await self._retry_with_error(
                    question=question,
                    failed_sql=sql,
                    error=f"Query execution failed: {error_str}",
                    history=history,
                )

                if retry_response:
                    # Validate the retry
                    retry_validation = validate_sql(
                        sql=retry_response.sql,
                        catalog=self.catalog,
                        max_rows=self._settings.sql_max_rows,
                        strict_catalog_check=True,
                    )

                    if retry_validation.valid:
                        # Check EXPLAIN validity
                        is_valid_retry, retry_explain_error = db.explain_query(
                            sql=retry_response.sql,
                            timeout_ms=5000,
                        )

                        if is_valid_retry:
                            # Try executing the retry
                            try:
                                result = db.execute_query(
                                    sql=retry_response.sql,
                                    timeout_ms=self._settings.sql_statement_timeout_ms,
                                    max_rows=self._settings.sql_max_rows,
                                )
                                # Success! Use the retry response
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

            # Non-retryable error or retry failed - return error to user
            return ChatResponse(
                session_id=session_id,
                answer=f"I couldn't execute the query. Error: {e}",
                sql=sql,
                error=str(e),
                assumptions=gen_response.assumptions,
                concepts_used=gen_response.concepts_used,
                confidence="low",
            )

        # Step 8: Run sanity checks
        sanity_results = run_sanity_checks(result, gen_response.validation_checks)

        # Check if any critical sanity check failed
        failed_checks = [c for c in sanity_results if not c.passed]
        if failed_checks:
            logger.warning(f"Sanity checks failed: {[c.message for c in failed_checks]}")

        # Step 9: Format answer
        answer = await self._format_answer(
            question=question,
            sql=sql,
            result=result,
            assumptions=gen_response.assumptions,
            concepts_used=gen_response.concepts_used,
            failed_checks=failed_checks,
        )

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
        )

    async def _retry_with_error(
        self,
        question: str,
        failed_sql: str,
        error: str,
        history: list[dict[str, str]],
    ) -> Any:
        """
        Retry SQL generation with error context.

        Args:
            question: Original question
            failed_sql: SQL that failed validation
            error: Error message
            history: Conversation history

        Returns:
            New SQLGenerationResponse or None
        """
        generator = get_sql_generator()

        # Build helpful context about available tables/columns
        available_tables = ""
        if self.catalog:
            table_list = sorted(self.catalog.tables.keys())
            available_tables = f"\n\nAvailable tables: {', '.join(table_list)}"

            # If error mentions unknown table, show similar tables
            if "Unknown table" in error:
                available_tables += "\n\nPlease use ONLY these exact table names."

            # If error mentions unknown column, show columns for mentioned tables
            if "Unknown column" in error:
                # Extract table names from the failed SQL
                for table_name in table_list:
                    if table_name.lower() in failed_sql.lower():
                        table = self.catalog.tables[table_name]
                        cols = list(table.columns.keys())
                        if cols:
                            available_tables += f"\n\nVerified columns in {table_name}: {', '.join(cols)}"

        # Determine error type and provide specific guidance
        is_timeout = "timeout" in error.lower() or "canceling statement" in error.lower()

        fix_guidance = "Remember: no PHI columns in SELECT, no SELECT *, and non-aggregate queries need LIMIT."

        if is_timeout:
            fix_guidance = """The query timed out. Apply these optimizations:
1. Use CTEs to filter large tables (PTDIAG, OVST, IPT) BEFORE joining
2. Pre-filter reference tables (MEDITEMDIS, ICD9CM, ICD10, LABEXM) in CTEs
3. Use EXISTS instead of JOIN when counting DISTINCT
4. Add date filters early (EXTRACT(YEAR FROM date_col) = year)
5. Filter by indexed columns first (hn, an, vn, labexm, meditem)

Example pattern:
WITH filtered_set AS (
    SELECT key_column FROM table WHERE <conditions> AND <date_filter>
)
SELECT COUNT(DISTINCT x) FROM main_table
WHERE EXISTS (SELECT 1 FROM filtered_set WHERE key = main_table.key)"""

        # Add error context to history
        error_context = history + [
            {
                "role": "assistant",
                "content": f"I generated this SQL but it failed:\n```sql\n{failed_sql}\n```\nError: {error}{available_tables}",
            },
            {
                "role": "user",
                "content": f"Please fix the SQL. {fix_guidance}\n\nOriginal question: {question}",
            },
        ]

        try:
            return generator.generate(question, conversation_history=error_context)
        except Exception as e:
            logger.exception("Retry failed")
            return None

    async def _format_answer(
        self,
        question: str,
        sql: str,
        result: QueryResult,
        assumptions: list[str],
        concepts_used: list[str],
        failed_checks: list[SanityCheckResult],
    ) -> str:
        """
        Format the final answer from query results.

        Args:
            question: Original question
            sql: Executed SQL
            result: Query result
            assumptions: Assumptions made
            concepts_used: Concepts used
            failed_checks: Failed sanity checks

        Returns:
            Formatted answer string
        """
        llm = get_llm_client()

        result_data = {
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
        }

        answer = llm.format_answer(
            question=question,
            _sql=sql,
            result_data=result_data,
            assumptions=assumptions,
            concepts_used=concepts_used,
        )

        # Add warnings if sanity checks failed
        if failed_checks:
            warnings = "\n\n⚠️ **Note**: Some data validation checks raised concerns:\n"
            for check in failed_checks:
                warnings += f"- {check.message}\n"
            answer += warnings

        # Add truncation warning
        if result.truncated:
            answer += f"\n\n*Note: Results were limited to {result.row_count} rows.*"

        return answer


# Global orchestrator instance
_orchestrator: ChatOrchestrator | None = None


def get_orchestrator() -> ChatOrchestrator:
    """Get global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ChatOrchestrator()
    return _orchestrator
