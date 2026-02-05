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

from app.catalog import Catalog, load_catalog
from app.config import get_settings
from app.db import get_db
from app.llm import get_llm_client
from app.models import ChatRequest, ChatResponse, QueryResult, SanityCheckResult
from app.session import get_session_manager
from app.sql_gen import get_sql_generator
from app.sql_guard import SQLGuardError, validate_sql
from app.validators import run_sanity_checks

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    """Orchestrates the chat flow for SQL generation and execution."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._catalog: Catalog | None = None

    @property
    def catalog(self) -> Catalog | None:
        """Lazy load catalog."""
        if self._catalog is None:
            catalog_path = self._settings.catalog_path
            if catalog_path.exists():
                self._catalog = load_catalog(catalog_path)
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

        # Step 5: Execute query
        try:
            db = get_db()
            result = db.execute_query(
                sql=sql,
                timeout_ms=self._settings.sql_statement_timeout_ms,
                max_rows=self._settings.sql_max_rows,
            )
        except Exception as e:
            logger.exception("Database execution error")
            return ChatResponse(
                session_id=session_id,
                answer=f"I couldn't execute the query. Error: {e}",
                sql=sql,
                error=str(e),
                assumptions=gen_response.assumptions,
                concepts_used=gen_response.concepts_used,
                confidence="low",
            )

        # Step 6: Run sanity checks
        sanity_results = run_sanity_checks(result, gen_response.validation_checks)

        # Check if any critical sanity check failed
        failed_checks = [c for c in sanity_results if not c.passed]
        if failed_checks:
            logger.warning(f"Sanity checks failed: {[c.message for c in failed_checks]}")

        # Step 7: Format answer
        answer = await self._format_answer(
            question=question,
            sql=sql,
            result=result,
            assumptions=gen_response.assumptions,
            concepts_used=gen_response.concepts_used,
            failed_checks=failed_checks,
        )

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

        # Add error context to history
        error_context = history + [
            {
                "role": "assistant",
                "content": f"I generated this SQL but it failed validation:\n```sql\n{failed_sql}\n```\nError: {error}{available_tables}",
            },
            {
                "role": "user",
                "content": f"Please fix the SQL using ONLY the tables and columns listed above. Remember: no PHI columns in SELECT, no SELECT *, and non-aggregate queries need LIMIT. Original question: {question}",
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
            sql=sql,
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
