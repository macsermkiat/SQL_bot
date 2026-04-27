"""Structural SQL comparison using sqlglot.

Normalises Oracle/SQL-Server gold SQL and PostgreSQL-generated SQL to
a common canonical form, then computes set-level diffs on tables, joins,
and filter predicates.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

try:
    import sqlglot
    import sqlglot.expressions as exp
    _SQLGLOT_AVAILABLE = True
except ImportError:
    _SQLGLOT_AVAILABLE = False

from tests.sql_testing.notion_eval.ticket_models import SqlDiffResult

logger = logging.getLogger(__name__)

_SCHEMA_PREFIXES = re.compile(
    r"\b(?:CUH|ddc_internal|KCMH_HIS|cleaned_ddc_internal)\.",
    re.IGNORECASE,
)

_DIALECT_MAP = {
    "oracle": "oracle",
    "sqlserver": "tsql",
    "postgresql": "postgres",
}


def _strip_schema(sql: str) -> str:
    return _SCHEMA_PREFIXES.sub("", sql)


@dataclass
class _SqlStructure:
    tables: set[str] = field(default_factory=set)
    joins: list[tuple[str, str]] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    aggregates: list[str] = field(default_factory=list)
    parse_error: str | None = None


def _extract_tables(tree: "exp.Expression") -> set[str]:
    tables: set[str] = set()
    for node in tree.walk():
        if isinstance(node, exp.Table):
            name = node.name
            if name:
                tables.add(name.upper())
    return tables


def _extract_joins(tree: "exp.Expression") -> list[tuple[str, str]]:
    joins: list[tuple[str, str]] = []
    for node in tree.walk():
        if isinstance(node, exp.Join):
            on_clause = node.args.get("on")
            if on_clause:
                cols = [
                    c.sql(dialect="postgres").upper()
                    for c in on_clause.walk()
                    if isinstance(c, exp.Column)
                ]
                if len(cols) >= 2:
                    joins.append((cols[0], cols[1]))
    return joins


def _extract_filters(tree: "exp.Expression") -> list[str]:
    filters: list[str] = []
    for node in tree.walk():
        if isinstance(node, (exp.Where, exp.Having)):
            for child in node.walk():
                if isinstance(
                    child,
                    (exp.EQ, exp.Like, exp.In, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.Between),
                ):
                    filters.append(child.sql(dialect="postgres").upper())
    return filters


def _extract_aggregates(tree: "exp.Expression") -> list[str]:
    aggs: list[str] = []
    for node in tree.walk():
        if isinstance(node, (exp.Count, exp.Sum, exp.Avg, exp.Max, exp.Min)):
            aggs.append(node.sql(dialect="postgres").upper())
    return aggs


def _parse_sql(sql: str, dialect: str) -> _SqlStructure:
    if not _SQLGLOT_AVAILABLE:
        return _SqlStructure(parse_error="sqlglot not installed")

    clean = _strip_schema(sql)
    structure = _SqlStructure()

    try:
        trees = sqlglot.parse(clean, dialect=_DIALECT_MAP.get(dialect, "postgres"))
    except Exception as exc:
        structure.parse_error = str(exc)
        return structure

    for tree in trees:
        if tree is None:
            continue
        structure.tables |= _extract_tables(tree)
        structure.joins.extend(_extract_joins(tree))
        structure.filters.extend(_extract_filters(tree))
        structure.aggregates.extend(_extract_aggregates(tree))

    return structure


def _recall(gold: list | set, gen: list | set) -> float:
    gold_set = set(gold) if not isinstance(gold, set) else gold
    gen_set = set(gen) if not isinstance(gen, set) else gen
    if not gold_set:
        return 1.0
    return len(gold_set & gen_set) / len(gold_set)


def _precision(gold: list | set, gen: list | set) -> float:
    gold_set = set(gold) if not isinstance(gold, set) else gold
    gen_set = set(gen) if not isinstance(gen, set) else gen
    if not gen_set:
        return 1.0
    return len(gold_set & gen_set) / len(gen_set)


def diff_sql(
    ticket_id: str,
    gold_sql: str,
    gen_sql: str,
    gold_dialect: str = "oracle",
) -> SqlDiffResult:
    """Compare gold SQL against generated SQL, returning a scored diff."""
    gold_struct = _parse_sql(gold_sql, gold_dialect)
    gen_struct = _parse_sql(gen_sql, "postgresql")

    if gold_struct.parse_error:
        logger.warning("Gold SQL parse error for %s: %s", ticket_id, gold_struct.parse_error)

    table_recall = _recall(gold_struct.tables, gen_struct.tables)
    table_precision = _precision(gold_struct.tables, gen_struct.tables)
    join_recall = _recall(
        {f"{a}={b}" for a, b in gold_struct.joins},
        {f"{a}={b}" for a, b in gen_struct.joins},
    )
    filter_recall = _recall(gold_struct.filters, gen_struct.filters)
    agg_recall = _recall(gold_struct.aggregates, gen_struct.aggregates)

    overall = (
        0.40 * table_recall
        + 0.30 * join_recall
        + 0.20 * filter_recall
        + 0.10 * agg_recall
    )

    missing_tables = gold_struct.tables - gen_struct.tables
    extra_tables = gen_struct.tables - gold_struct.tables
    gold_join_strs = {f"{a}={b}" for a, b in gold_struct.joins}
    gen_join_strs = {f"{a}={b}" for a, b in gen_struct.joins}
    missing_join_strs = gold_join_strs - gen_join_strs
    missing_joins: list[tuple[str, str]] = [
        tuple(s.split("=", 1)) for s in missing_join_strs  # type: ignore[misc]
    ]
    missing_filters = list(set(gold_struct.filters) - set(gen_struct.filters))

    return SqlDiffResult(
        ticket_id=ticket_id,
        gold_tables=gold_struct.tables,
        gen_tables=gen_struct.tables,
        gold_joins=gold_struct.joins,
        gen_joins=gen_struct.joins,
        gold_filters=gold_struct.filters,
        gen_filters=gen_struct.filters,
        gold_aggregates=gold_struct.aggregates,
        gen_aggregates=gen_struct.aggregates,
        table_precision=table_precision,
        table_recall=table_recall,
        join_recall=join_recall,
        filter_recall=filter_recall,
        aggregate_recall=agg_recall,
        overall_score=overall,
        missing_tables=missing_tables,
        extra_tables=extra_tables,
        missing_joins=missing_joins,
        missing_filters=missing_filters,
        parse_error=gold_struct.parse_error,
    )
