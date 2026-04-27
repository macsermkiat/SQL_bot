"""Tests for learned SQL correction review workflow."""

from __future__ import annotations

from app.learning_store import LearningStore


def _record_repeated_pattern(store: LearningStore) -> str:
    fixed_sql = 'SELECT COUNT(*) FROM "KCMH_HIS"."OVST"'
    for _ in range(3):
        store.record_pattern(
            question="How many OPD visits?",
            error_stage="validation",
            error_summary="Unknown column: fake_col",
            failed_sql='SELECT fake_col FROM "KCMH_HIS"."OVST"',
            fixed_sql=fixed_sql,
        )

    pattern = store.retrieve_relevant(
        "How many OPD visits?",
        sql=fixed_sql,
        max_patterns=1,
    )[0]
    return store._graduation_entry_id(pattern)


def test_raw_patterns_are_retry_only_until_reviewed(tmp_path) -> None:
    store = LearningStore(
        store_path=tmp_path / "learned_patterns.jsonl",
        corrections_path=tmp_path / "sql_corrections.yaml",
    )
    _record_repeated_pattern(store)

    prompt_section = store.build_prompt_section(
        "How many OPD visits?",
        sql='SELECT COUNT(*) FROM "KCMH_HIS"."OVST"',
    )

    assert "LEARNED FROM PAST MISTAKES" in prompt_section
    assert store.graduate_patterns(min_hits=3) == []
    assert not (tmp_path / "sql_corrections.yaml").exists()


def test_reviewed_patterns_can_graduate_to_yaml(tmp_path) -> None:
    store = LearningStore(
        store_path=tmp_path / "learned_patterns.jsonl",
        corrections_path=tmp_path / "sql_corrections.yaml",
    )
    reviewed_id = _record_repeated_pattern(store)

    graduated = store.graduate_patterns(
        min_hits=3,
        reviewed_ids={reviewed_id},
    )

    assert [g["id"] for g in graduated] == [reviewed_id]
    assert (tmp_path / "sql_corrections.yaml").exists()
