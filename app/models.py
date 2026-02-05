"""
Pydantic models for request/response schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Request model for login."""

    email: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class UserInfo(BaseModel):
    """Authenticated user information."""

    email: str
    name: str
    department: str
    role: Literal["super_user", "standard_user"]


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(default=None)


class SQLGenerationResponse(BaseModel):
    """Structured response from LLM for SQL generation."""

    needs_clarification: bool = Field(
        default=False,
        description="Whether clarification is needed before generating SQL",
    )
    clarification_question: str | None = Field(
        default=None,
        description="Question to ask user if clarification needed",
    )
    clarified_question: str = Field(
        default="",
        description="Restatement of the question with resolved ambiguity",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made in interpreting the question",
    )
    concepts_used: list[str] = Field(
        default_factory=list,
        description="Clinical concepts used (e.g., diabetes_icd10)",
    )
    sql: str = Field(
        default="",
        description="Generated SQL query",
    )
    validation_checks: list[str] = Field(
        default_factory=list,
        description="Sanity checks to run on results",
    )
    answer_plan: str = Field(
        default="",
        description="How to format the answer from results",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Confidence level in the generated SQL",
    )


class QueryResult(BaseModel):
    """Result of executing a SQL query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    execution_time_ms: float


class SanityCheckResult(BaseModel):
    """Result of a sanity check."""

    check_name: str
    passed: bool
    message: str


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    session_id: str
    answer: str
    sql: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    concepts_used: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    sanity_checks: list[SanityCheckResult] = Field(default_factory=list)
    query_result: QueryResult | None = None
    error: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None


class Message(BaseModel):
    """A single message in chat history."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """Chat session with history."""

    session_id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    def add_message(self, role: Literal["user", "assistant"], content: str, **metadata: Any) -> Message:
        """Add a message to the session."""
        msg = Message(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        self.last_activity = datetime.now()
        return msg
