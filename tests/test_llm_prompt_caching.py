"""Tests for stable-prefix system prompt caching."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.llm import LLMClient


def test_system_prompt_has_byte_identical_cached_prefix():
    client = object.__new__(LLMClient)
    concepts = "UNIQUE_CONCEPTS_MARKER"

    first = client._build_system_prompt("UNIQUE_SCHEMA_ONE", concepts)
    second = client._build_system_prompt("UNIQUE_SCHEMA_TWO", concepts)

    assert first[0]["text"].encode("utf-8") == second[0]["text"].encode("utf-8")
    assert first[0]["cache_control"] == {"type": "ephemeral"}
    assert first[0]["type"] == "text"
    assert concepts in first[0]["text"]
    assert "UNIQUE_SCHEMA_ONE" not in first[0]["text"]
    assert "UNIQUE_SCHEMA_TWO" not in second[0]["text"]


def test_volatile_block_contains_schema_and_current_date():
    client = object.__new__(LLMClient)
    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")

    blocks = client._build_system_prompt(
        "UNIQUE_SCHEMA_MARKER",
        "UNIQUE_CONCEPTS_MARKER",
    )

    assert len(blocks) == 2
    assert blocks[1]["type"] == "text"
    assert "cache_control" not in blocks[1]
    assert "## TABLE SCHEMA" in blocks[1]["text"]
    assert "UNIQUE_SCHEMA_MARKER" in blocks[1]["text"]
    assert today in blocks[1]["text"]
    assert today not in blocks[0]["text"]
