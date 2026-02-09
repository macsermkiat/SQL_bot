"""Tests for schema_retriever.py - question-aware table discovery."""

from __future__ import annotations

import pytest

from app.schema_catalog import get_schema_catalog
from app.schema_retriever import SchemaRetriever


@pytest.fixture(scope="module")
def retriever() -> SchemaRetriever:
    """Create a retriever using the real schema catalog."""
    catalog = get_schema_catalog()
    return SchemaRetriever(catalog)


# ------------------------------------------------------------------
# Blood pressure (the motivating example)
# ------------------------------------------------------------------

class TestBloodPressureDiscovery:
    """OVSTPRESS must be found for blood pressure queries."""

    def test_english_blood_pressure(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("How many patients have high blood pressure?")
        assert "OVSTPRESS" in tables

    def test_thai_blood_pressure(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("จำนวนผู้ป่วยที่มีความดันโลหิตสูง")
        assert "OVSTPRESS" in tables

    def test_short_thai_pressure(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ข้อมูลความดัน")
        assert "OVSTPRESS" in tables

    def test_hypertension(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("hypertension statistics")
        assert "OVSTPRESS" in tables


# ------------------------------------------------------------------
# Other tables that were previously missed
# ------------------------------------------------------------------

class TestOtherMissedTables:
    """Tables beyond the priority list should be found by concept."""

    def test_appointment_oapp(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("How many appointments were scheduled?")
        assert "OAPP" in tables

    def test_dispensing_motp(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("drug dispensing records")
        assert "MOTP" in tables

    def test_radiology_rdoexm(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("radiology exams xray")
        assert "RDOEXM" in tables

    def test_allergy_ptallergy(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("patient drug allergy")
        assert "PTALLERGY" in tables

    def test_emergency_cner(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("emergency room visits")
        assert "CNER" in tables

    def test_billing_arpt(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("billing charges revenue")
        assert "ARPT" in tables

    def test_icu_booking(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ICU bed booking")
        assert "IPTBOOKBEDICU" in tables

    def test_delivery_dlvst(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("delivery birth records")
        assert "DLVST" in tables

    def test_pregnancy_ancvst(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("pregnancy antenatal care visits")
        assert "ANCVST" in tables

    def test_blood_transfusion(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("blood transfusion orders")
        assert "BDVST" in tables

    def test_occupation(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("patient occupation distribution")
        assert "OCCPTN" in tables

    def test_nationality(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("patient nationality distribution")
        assert "NTNLTY" in tables


# ------------------------------------------------------------------
# Thai language queries
# ------------------------------------------------------------------

class TestThaiQueries:
    """Thai questions should find the right tables."""

    def test_thai_allergy(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ข้อมูลการแพ้ยาของผู้ป่วย")
        assert "PTALLERGY" in tables

    def test_thai_prescription(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("จำนวนใบสั่งยาในปีที่แล้ว")
        assert "PRSC" in tables

    def test_thai_emergency(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ผู้ป่วยฉุกเฉิน")
        assert "CNER" in tables

    def test_thai_delivery(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ข้อมูลการคลอด")
        assert "DLVST" in tables

    def test_thai_lab(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("ผลตรวจทางห้องปฏิบัติการ")
        assert "LVSTEXM" in tables or "LVST" in tables


# ------------------------------------------------------------------
# Priority tables always present
# ------------------------------------------------------------------

class TestPriorityTablesStillWork:
    """Priority tables should still rank highly for common queries."""

    def test_diagnosis_query(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("diabetes diagnosis count")
        assert "PTDIAG" in tables
        assert "ICD10" in tables

    def test_opd_visit(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("OPD visit count by clinic")
        assert "OVST" in tables

    def test_lab_results(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("lab test results")
        assert "LABEXM" in tables


# ------------------------------------------------------------------
# Table directory
# ------------------------------------------------------------------

class TestTableDirectory:
    """The table directory should list all tables."""

    def test_directory_contains_all_tables(
        self, retriever: SchemaRetriever
    ) -> None:
        directory = retriever.build_table_directory()
        # Check a few tables from different parts of the alphabet
        assert "OVSTPRESS" in directory
        assert "OVST" in directory
        assert "ANCVST" in directory
        assert "WARD" in directory

    def test_directory_has_thai_comments(
        self, retriever: SchemaRetriever
    ) -> None:
        directory = retriever.build_table_directory()
        assert "ความดันโลหิต" in directory

    def test_mark_detailed_tables(
        self, retriever: SchemaRetriever
    ) -> None:
        directory = retriever.build_table_directory()
        marked = retriever.mark_detailed_tables(
            directory, {"OVST", "OVSTPRESS"}
        )
        assert "OVST [DETAILED]:" in marked
        assert "OVSTPRESS [DETAILED]:" in marked
        # Non-detailed tables should not be marked
        assert "ANCVST [DETAILED]" not in marked


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_question(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("")
        assert tables == []

    def test_nonsense_question(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("xyzzy foobar baz")
        # Should return empty or very few tables
        assert len(tables) <= 3

    def test_top_k_respected(self, retriever: SchemaRetriever) -> None:
        tables = retriever.retrieve("patient data", top_k=5)
        assert len(tables) <= 5
