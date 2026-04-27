"""
Self-learning store for SQL error patterns.

Two-tier system:
1. JSONL inbox (out/learned_patterns.jsonl) - raw patterns captured automatically
2. YAML reference (schema/sql_corrections.yaml) - curated, proven corrections

Flow:
- Query fails -> retry succeeds -> pattern recorded in JSONL (automatic)
- Patterns with hit_count >= threshold -> graduated to YAML (manual or auto)
- YAML corrections loaded into LLM prompt alongside schema context (always)
- JSONL patterns injected only during retries (on-demand)

Usage:
    # Graduate proven patterns to YAML
    python -m app.learning_store graduate
    python -m app.learning_store graduate --min-hits 2

    # Show current stats
    python -m app.learning_store stats

    # Prune old JSONL patterns
    python -m app.learning_store prune
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_STORE_PATH = Path(__file__).parent.parent / "out" / "learned_patterns.jsonl"
_DEFAULT_CORRECTIONS_PATH = Path(__file__).parent.parent / "schema" / "sql_corrections.yaml"
_MAX_PATTERNS_IN_PROMPT = 5
_MAX_PATTERN_AGE_DAYS = 180
_MIN_RELEVANCE_SCORE = 0.15
_GRADUATION_MIN_HITS = 3


# ---------------------------------------------------------------
# Tier 2: YAML corrections (curated reference, always in prompt)
# ---------------------------------------------------------------

@dataclass(frozen=True)
class SQLCorrection:
    """A curated SQL correction from the YAML reference."""

    id: str
    tables: list[str]
    wrong: str
    right: str
    reason: str


def load_corrections(path: Path | None = None) -> list[SQLCorrection]:
    """Load curated corrections from YAML file."""
    corrections_path = path or _DEFAULT_CORRECTIONS_PATH
    if not corrections_path.exists():
        return []

    try:
        with open(corrections_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.warning("Could not load sql_corrections.yaml: %s", e)
        return []

    if not data or not isinstance(data, dict):
        return []

    corrections: list[SQLCorrection] = []
    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        corrections.append(SQLCorrection(
            id=key,
            tables=val.get("tables", []),
            wrong=val.get("wrong", ""),
            right=val.get("right", ""),
            reason=val.get("reason", ""),
        ))

    logger.info("Loaded %d SQL corrections from %s", len(corrections), corrections_path)
    return corrections


def build_corrections_context(
    corrections: list[SQLCorrection],
    tables_in_query: set[str] | None = None,
) -> str:
    """Build prompt section from YAML corrections.

    If tables_in_query is provided, only include corrections for those tables.
    Otherwise includes all corrections.
    """
    if not corrections:
        return ""

    relevant = corrections
    if tables_in_query:
        upper_tables = {t.upper() for t in tables_in_query}
        relevant = [
            c for c in corrections
            if any(t.upper() in upper_tables for t in c.tables)
        ]

    if not relevant:
        return ""

    lines = [
        "### SQL Corrections (from past mistakes)",
        "",
    ]
    for c in relevant:
        tables_str = ", ".join(c.tables)
        lines.append(f"- **{tables_str}**: {c.reason}")
        lines.append(f"  - Wrong: `{c.wrong}`")
        lines.append(f"  - Right: `{c.right}`")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------
# Tier 1: JSONL inbox (raw patterns, used during retries only)
# ---------------------------------------------------------------

@dataclass(frozen=True)
class LearnedPattern:
    """A single error->fix pattern learned from a failed-then-succeeded query."""

    question_keywords: list[str]
    error_stage: str
    error_summary: str
    failed_sql_fragment: str
    fixed_sql_fragment: str
    lesson: str
    tables: list[str] = field(default_factory=list)
    hit_count: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    graduated: bool = False


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase keywords from text, filtering noise."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "of", "in", "to", "for", "with", "on", "at", "from", "by",
        "as", "into", "through", "and", "or", "but", "not", "no",
        "if", "then", "else", "when", "where", "how", "what", "which",
        "who", "that", "this", "it", "its", "my", "your", "our",
        "select", "from", "where", "join", "inner", "left", "right",
        "on", "and", "or", "as", "null", "true", "false",
    }
    words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()))
    return words - stop_words


def _extract_tables(sql: str) -> list[str]:
    """Extract table names from SQL (KCMH_HIS.TABLE pattern)."""
    matches = re.findall(r'"KCMH_HIS"\."(\w+)"', sql, re.IGNORECASE)
    return sorted(set(matches))


def _compute_relevance(
    query_keywords: set[str],
    query_tables: set[str],
    pattern: LearnedPattern,
) -> float:
    """Score how relevant a stored pattern is to the current query."""
    pattern_keywords = set(pattern.question_keywords) | set(
        w.lower() for w in pattern.tables
    )
    if not pattern_keywords:
        return 0.0

    keyword_overlap = query_keywords & pattern_keywords
    keyword_score = len(keyword_overlap) / max(len(pattern_keywords), 1)

    table_overlap = query_tables & {t.upper() for t in pattern.tables}
    table_score = len(table_overlap) / max(len(query_tables), 1) if query_tables else 0.0

    score = 0.4 * keyword_score + 0.6 * table_score

    if pattern.hit_count >= 3:
        score *= 1.3
    elif pattern.hit_count >= 2:
        score *= 1.1

    return min(score, 1.0)


def _generate_lesson(
    error_stage: str,
    error_summary: str,
) -> str:
    """Generate a concise lesson from the error."""
    if "does not exist" in error_summary.lower():
        return f"Column/table error: {error_summary}. Use the corrected names."
    if "timeout" in error_summary.lower() or "canceling" in error_summary.lower():
        return "Query timed out. Optimize with CTEs, date filters, and EXISTS."
    if "zero" in error_stage or "0 rows" in error_summary.lower():
        return "Query returned no results. Check table choice, join conditions, and filters."
    if "validation" in error_stage:
        return f"SQL guard rejected: {error_summary}"
    return f"Error at {error_stage}: {error_summary}"


def _truncate_sql(sql: str, max_chars: int = 500) -> str:
    """Truncate SQL to key fragment for storage efficiency."""
    sql = sql.strip()
    if len(sql) <= max_chars:
        return sql
    return sql[:max_chars] + "..."


class LearningStore:
    """Two-tier learning store: JSONL inbox + YAML reference."""

    def __init__(
        self,
        store_path: Path | None = None,
        corrections_path: Path | None = None,
    ) -> None:
        self._path = store_path or _DEFAULT_STORE_PATH
        self._corrections_path = corrections_path or _DEFAULT_CORRECTIONS_PATH
        self._patterns: list[LearnedPattern] = []
        self._corrections: list[SQLCorrection] | None = None
        self._lock = threading.Lock()
        self._loaded = False

    # --- YAML corrections (Tier 2) ---

    @property
    def corrections(self) -> list[SQLCorrection]:
        """Lazy-load curated corrections from YAML."""
        if self._corrections is None:
            self._corrections = load_corrections(self._corrections_path)
        return self._corrections

    def build_corrections_for_prompt(
        self,
        tables_in_query: set[str] | None = None,
    ) -> str:
        """Build corrections prompt section filtered by tables in the query."""
        return build_corrections_context(self.corrections, tables_in_query)

    # --- JSONL patterns (Tier 1) ---

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._patterns = self._load_from_disk()
            self._loaded = True

    def _load_from_disk(self) -> list[LearnedPattern]:
        if not self._path.exists():
            return []

        patterns: list[LearnedPattern] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        patterns.append(LearnedPattern(**data))
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug("Skipping malformed pattern: %s", e)
        except OSError as e:
            logger.warning("Could not load learning store: %s", e)

        logger.info("Loaded %d learned patterns from %s", len(patterns), self._path)
        return patterns

    def _save_to_disk(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for p in self._patterns:
                    f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
            tmp.replace(self._path)
        except OSError as e:
            logger.warning("Could not save learning store: %s", e)

    def record_pattern(
        self,
        question: str,
        error_stage: str,
        error_summary: str,
        failed_sql: str,
        fixed_sql: str,
    ) -> None:
        """Record a new error->fix pattern (or increment hit_count of existing)."""
        self._ensure_loaded()

        tables = _extract_tables(fixed_sql)
        keywords = sorted(_extract_keywords(question))
        failed_frag = _truncate_sql(failed_sql)
        fixed_frag = _truncate_sql(fixed_sql)
        lesson = _generate_lesson(error_stage, error_summary)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            existing = self._find_similar(tables, error_stage, error_summary)
            if existing is not None:
                old = self._patterns[existing]
                self._patterns[existing] = LearnedPattern(
                    question_keywords=sorted(set(old.question_keywords) | set(keywords)),
                    error_stage=error_stage,
                    error_summary=error_summary,
                    failed_sql_fragment=failed_frag,
                    fixed_sql_fragment=fixed_frag,
                    lesson=lesson,
                    tables=tables,
                    hit_count=old.hit_count + 1,
                    created_at=old.created_at,
                    last_seen_at=now,
                    graduated=old.graduated,
                )
            else:
                self._patterns.append(LearnedPattern(
                    question_keywords=keywords,
                    error_stage=error_stage,
                    error_summary=error_summary,
                    failed_sql_fragment=failed_frag,
                    fixed_sql_fragment=fixed_frag,
                    lesson=lesson,
                    tables=tables,
                    hit_count=1,
                    created_at=now,
                    last_seen_at=now,
                ))

            self._save_to_disk()

        logger.info(
            "Learned pattern: stage=%s tables=%s (total: %d)",
            error_stage, tables, len(self._patterns),
        )

    def _find_similar(
        self,
        tables: list[str],
        error_stage: str,
        error_summary: str,
    ) -> int | None:
        table_set = set(t.upper() for t in tables)
        error_key = error_summary.lower()[:80]

        for i, p in enumerate(self._patterns):
            if p.error_stage != error_stage:
                continue
            p_tables = set(t.upper() for t in p.tables)
            if table_set == p_tables and error_key in p.error_summary.lower():
                return i
        return None

    def retrieve_relevant(
        self,
        question: str,
        sql: str | None = None,
        max_patterns: int = _MAX_PATTERNS_IN_PROMPT,
    ) -> list[LearnedPattern]:
        """Retrieve JSONL patterns relevant to the current question/SQL.

        Used only during retries (not on first attempt).
        """
        self._ensure_loaded()

        if not self._patterns:
            return []

        query_keywords = _extract_keywords(question)
        query_tables: set[str] = set()
        if sql:
            query_tables = {t.upper() for t in _extract_tables(sql)}

        scored: list[tuple[float, LearnedPattern]] = []
        for pattern in self._patterns:
            if pattern.graduated:
                continue  # already in YAML, skip
            score = _compute_relevance(query_keywords, query_tables, pattern)
            if score >= _MIN_RELEVANCE_SCORE:
                scored.append((score, pattern))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_patterns]]

    def build_prompt_section(
        self,
        question: str,
        sql: str | None = None,
    ) -> str:
        """Build retry prompt section from JSONL patterns.

        Only used during retries, not on first attempt.
        """
        patterns = self.retrieve_relevant(question, sql)
        if not patterns:
            return ""

        lines = [
            "## LEARNED FROM PAST MISTAKES (DO NOT REPEAT THESE ERRORS)",
            "",
        ]

        for i, p in enumerate(patterns, 1):
            lines.append(f"**Mistake {i}** (seen {p.hit_count}x, tables: {', '.join(p.tables)})")
            lines.append(f"- Error: {p.error_summary}")
            lines.append(f"- Lesson: {p.lesson}")
            if p.failed_sql_fragment and p.fixed_sql_fragment:
                lines.append(f"- Wrong: `{p.failed_sql_fragment[:200]}`")
                lines.append(f"- Fixed: `{p.fixed_sql_fragment[:200]}`")
            lines.append("")

        return "\n".join(lines)

    # --- Graduation: JSONL -> YAML ---

    @staticmethod
    def _graduation_entry_id(pattern: LearnedPattern) -> str:
        """Stable review ID used before a learned pattern can enter YAML."""
        table_slug = "_".join(t.lower() for t in pattern.tables[:3])
        error_slug = re.sub(
            r"[^a-z0-9]+",
            "_",
            pattern.error_summary.lower()[:40],
        ).strip("_")
        return f"{table_slug}_{error_slug}"

    def graduate_patterns(
        self,
        min_hits: int = _GRADUATION_MIN_HITS,
        reviewed_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Graduate proven JSONL patterns into YAML corrections file.

        Graduation is intentionally manual: a pattern must meet the hit
        threshold AND its stable review ID must be provided in
        ``reviewed_ids``. This keeps production-specific or unlucky
        one-off fixes from becoming global prompt rules.

        Returns list of graduated entries.
        """
        self._ensure_loaded()

        reviewed = set(reviewed_ids or [])
        if not reviewed:
            return []

        candidates = [
            p for p in self._patterns
            if (
                p.hit_count >= min_hits
                and not p.graduated
                and self._graduation_entry_id(p) in reviewed
            )
        ]

        if not candidates:
            return []

        # Load existing YAML
        existing_yaml: dict[str, Any] = {}
        if self._corrections_path.exists():
            try:
                with open(self._corrections_path, encoding="utf-8") as f:
                    existing_yaml = yaml.safe_load(f) or {}
            except Exception:
                existing_yaml = {}

        graduated: list[dict[str, Any]] = []
        for p in candidates:
            entry_id = self._graduation_entry_id(p)

            # Avoid duplicates
            if entry_id in existing_yaml:
                continue

            entry = {
                "tables": p.tables,
                "wrong": p.failed_sql_fragment[:200],
                "right": p.fixed_sql_fragment[:200],
                "reason": p.lesson,
            }
            existing_yaml[entry_id] = entry
            graduated.append({"id": entry_id, **entry})

        if graduated:
            # Write updated YAML
            self._corrections_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._corrections_path, "w", encoding="utf-8") as f:
                f.write(
                    "# SQL Corrections - Learned patterns from past query failures\n"
                    "# Auto-graduated from out/learned_patterns.jsonl\n"
                    "# Review and edit as needed.\n\n"
                )
                yaml.dump(
                    existing_yaml, f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            # Mark as graduated in JSONL
            with self._lock:
                for i, p in enumerate(self._patterns):
                    if (
                        p.hit_count >= min_hits
                        and not p.graduated
                        and self._graduation_entry_id(p) in reviewed
                    ):
                        self._patterns[i] = LearnedPattern(
                            **{**asdict(p), "graduated": True},
                        )
                self._save_to_disk()

            # Reload corrections cache
            self._corrections = None

        return graduated

    @property
    def pattern_count(self) -> int:
        self._ensure_loaded()
        return len(self._patterns)

    def prune_old(self, max_age_days: int = _MAX_PATTERN_AGE_DAYS) -> int:
        """Remove patterns older than max_age_days. Returns count removed."""
        self._ensure_loaded()
        now = datetime.now(timezone.utc)
        original_count = len(self._patterns)

        with self._lock:
            self._patterns = [
                p for p in self._patterns
                if (now - datetime.fromisoformat(p.last_seen_at)).days <= max_age_days
            ]
            removed = original_count - len(self._patterns)
            if removed > 0:
                self._save_to_disk()
                logger.info("Pruned %d old patterns", removed)

        return removed

    def stats(self) -> dict[str, Any]:
        """Return stats about the learning store."""
        self._ensure_loaded()
        return {
            "jsonl_total": len(self._patterns),
            "jsonl_ungraduated": sum(1 for p in self._patterns if not p.graduated),
            "jsonl_graduated": sum(1 for p in self._patterns if p.graduated),
            "yaml_corrections": len(self.corrections),
            "ready_to_graduate": sum(
                1 for p in self._patterns
                if p.hit_count >= _GRADUATION_MIN_HITS and not p.graduated
            ),
        }


# Global instance
_store: LearningStore | None = None


def get_learning_store() -> LearningStore:
    """Get global learning store instance."""
    global _store
    if _store is None:
        _store = LearningStore()
    return _store


def reset_learning_store() -> None:
    """Reset the global store (for testing)."""
    global _store
    _store = None


# ---------------------------------------------------------------
# CLI: python -m app.learning_store <command>
# ---------------------------------------------------------------

def _cli() -> None:
    import sys

    commands = {
        "graduate": "Promote proven JSONL patterns to YAML",
        "stats": "Show learning store statistics",
        "prune": "Remove old patterns from JSONL",
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python -m app.learning_store <command>")
        print("\nCommands:")
        for cmd, desc in commands.items():
            print(f"  {cmd:12s} {desc}")
        sys.exit(1)

    store = get_learning_store()
    cmd = sys.argv[1]

    if cmd == "stats":
        s = store.stats()
        print(f"JSONL patterns:     {s['jsonl_total']}")
        print(f"  Ungraduated:      {s['jsonl_ungraduated']}")
        print(f"  Graduated:        {s['jsonl_graduated']}")
        print(f"  Ready to promote: {s['ready_to_graduate']}")
        print(f"YAML corrections:   {s['yaml_corrections']}")

    elif cmd == "graduate":
        min_hits = _GRADUATION_MIN_HITS
        if "--min-hits" in sys.argv:
            idx = sys.argv.index("--min-hits")
            min_hits = int(sys.argv[idx + 1])

        reviewed_ids: set[str] = set()
        for i, arg in enumerate(sys.argv):
            if arg == "--reviewed-id" and i + 1 < len(sys.argv):
                reviewed_ids.add(sys.argv[i + 1])

        graduated = store.graduate_patterns(
            min_hits=min_hits,
            reviewed_ids=reviewed_ids,
        )
        if graduated:
            print(f"Graduated {len(graduated)} patterns to sql_corrections.yaml:")
            for g in graduated:
                print(f"  - {g['id']}: {g['reason']}")
        elif not reviewed_ids:
            print(
                "No patterns graduated. Review candidates first, then pass "
                "--reviewed-id <id> for each approved correction."
            )
        else:
            print("No patterns ready for graduation "
                  f"(need >= {min_hits} hits, not already graduated)")

    elif cmd == "prune":
        max_days = _MAX_PATTERN_AGE_DAYS
        if "--max-days" in sys.argv:
            idx = sys.argv.index("--max-days")
            max_days = int(sys.argv[idx + 1])

        removed = store.prune_old(max_age_days=max_days)
        print(f"Pruned {removed} patterns older than {max_days} days")


if __name__ == "__main__":
    _cli()
