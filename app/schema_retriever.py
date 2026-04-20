"""
Schema Retriever - Question-aware table discovery.

Solves the problem of the LLM not knowing about tables outside the
hardcoded priority list. Searches ALL table names, comments, column
names, and column comments to find tables relevant to a user question.

Uses:
- Substring matching for Thai text (no word segmentation needed)
- Token matching for English text
- IDF weighting so common terms (e.g. "data") don't dominate
- English-Thai bridging for cross-language discovery
- Table name decomposition (OVSTPRESS -> "pressure", "visit")
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from app.schema_catalog import SchemaCatalog

# ---------------------------------------------------------------------------
# Table-name component expansions
#
# HIS tables encode meaning in abbreviated names. Expanding these into
# searchable English words lets us match "blood pressure" -> OVSTPRESS.
# ---------------------------------------------------------------------------
_TABLE_COMPONENT_EXPANSIONS: dict[str, list[str]] = {
    "ovst": ["outpatient", "visit", "opd"],
    "ipt": ["inpatient", "admission", "admit", "ipd"],
    "pt": ["patient"],
    "prsc": ["prescription", "prescribe", "drug", "order"],
    "lvst": ["lab", "laboratory", "visit"],
    "labexm": ["lab", "laboratory", "exam", "test"],
    "lab": ["lab", "laboratory"],
    "dct": ["doctor", "physician"],
    "anc": ["antenatal", "pregnancy", "prenatal", "anc"],
    "dlv": ["delivery", "birth", "labor", "obstetric"],
    "bd": ["blood", "transfusion", "blood bank"],
    "cner": ["emergency", "er", "accident", "trauma"],
    "icu": ["intensive", "critical", "icu"],
    "med": ["medicine", "medication", "drug", "pharmaceutical"],
    "ward": ["ward", "bed", "room"],
    "diag": ["diagnosis", "diagnose", "disease"],
    "oprt": ["operation", "surgery", "procedure", "surgical"],
    "press": ["pressure", "blood pressure", "vital", "bp"],
    "allergy": ["allergy", "allergic", "adverse", "adr"],
    "arpt": ["billing", "charge", "payment", "fee", "income", "revenue"],
    "oapp": ["appointment", "schedule", "booking"],
    "rapp": ["appointment", "referral"],
    "rdo": ["radiology", "xray", "imaging", "ct", "mri"],
    "motp": ["dispensing", "dispense", "issue"],
    "ispm": ["equipment", "instrument", "device", "sterilization"],
    "isp": ["equipment", "instrument", "device"],
    "incpt": ["income", "charge", "billing"],
    "incgrp": ["income", "charge", "group"],
    "dch": ["discharge"],
    "adm": ["admission", "admit", "transfer"],
    "sum": ["summary"],
    "infant": ["infant", "baby", "newborn", "neonatal"],
    "mother": ["mother", "maternal"],
    "organism": ["organism", "bacteria", "culture", "microbiology"],
    "spcm": ["specimen", "sample"],
    "sale": ["price", "cost", "sale"],
    "gnr": ["generic", "generic name"],
    "lbl": ["label", "sticker"],
    "symptom": ["symptom"],
    "clinictype": ["clinic", "type"],
    "masterorder": ["order", "charge", "item"],
    "mastersale": ["price", "charge", "cost"],
    "changwat": ["province", "location", "address"],
    "ntnlty": ["nationality"],
    "occptn": ["occupation", "job"],
    "pttype": ["insurance", "coverage", "right", "benefit"],
    "pttypegrp": ["insurance", "group"],
    "pttypeext": ["insurance", "extended"],
    "diagtype": ["diagnosis", "type", "priority"],
    "erdch": ["emergency", "discharge"],
    "erzone": ["emergency", "zone", "triage"],
    # Previously missing expansions (caused retriever misses)
    "cliniclct": ["clinic", "location", "room", "department"],
    "emrgncy": ["emergency", "urgency", "triage"],
    "lct": ["location", "department", "unit"],
    "spclty": ["specialty", "department", "division"],
    "claim": ["claim", "insurance", "payer"],
    "incprvlg": ["income", "privilege", "billing", "insurance"],
    "wardicu": ["ward", "icu", "intensive"],
    "lcttype": ["location", "type"],
    "strengthunit": ["strength", "unit", "dose"],
    "volumeunit": ["volume", "unit", "dose"],
}

# ---------------------------------------------------------------------------
# English <-> Thai clinical term bridge
#
# When a user asks in English, we also search Thai comments, and vice versa.
# This is NOT a complete dictionary -- just high-value clinical terms.
# ---------------------------------------------------------------------------
_CLINICAL_TERM_BRIDGE: dict[str, list[str]] = {
    # English -> Thai search terms
    "blood pressure": ["ความดัน", "ความดันโลหิต"],
    "pressure": ["ความดัน"],
    "hypertension": ["ความดัน", "ความดันโลหิต"],
    "vital sign": ["ความดัน", "ชีพจร", "อุณหภูมิ"],
    "diabetes": ["เบาหวาน"],
    "allergy": ["แพ้", "การแพ้"],
    "drug allergy": ["แพ้ยา"],
    "prescription": ["สั่งยา", "ใบสั่งยา"],
    "drug": ["ยา", "เวชภัณฑ์"],
    "medicine": ["ยา", "เวชภัณฑ์"],
    "lab": ["ห้องปฏิบัติการ", "ตรวจ"],
    "laboratory": ["ห้องปฏิบัติการ"],
    "surgery": ["ผ่าตัด"],
    "operation": ["ผ่าตัด"],
    "pregnancy": ["ครรภ์", "ตั้งครรภ์", "ฝากครรภ์"],
    "delivery": ["คลอด"],
    "birth": ["คลอด", "เกิด"],
    "emergency": ["ฉุกเฉิน", "อุบัติเหตุ"],
    "accident": ["อุบัติเหตุ"],
    "diagnosis": ["วินิจฉัย", "โรค"],
    "disease": ["โรค"],
    "appointment": ["นัด"],
    "ward": ["ตึก", "หอผู้ป่วย"],
    "inpatient": ["ผู้ป่วยใน"],
    "outpatient": ["ผู้ป่วยนอก"],
    "radiology": ["รังสี"],
    "xray": ["รังสี"],
    "x-ray": ["รังสี"],
    "imaging": ["รังสี"],
    "temperature": ["อุณหภูมิ"],
    "pulse": ["ชีพจร"],
    "heart rate": ["ชีพจร"],
    "weight": ["น้ำหนัก"],
    "height": ["ส่วนสูง"],
    "bmi": ["ดัชนีมวลกาย"],
    "insurance": ["สิทธิ", "สิทธิการรักษา"],
    "billing": ["ค่ารักษา", "ลูกหนี้"],
    "charge": ["ค่ารักษา"],
    "fee": ["ค่ารักษา"],
    "vaccine": ["วัคซีน"],
    "immunization": ["วัคซีน"],
    "referral": ["ส่งต่อ"],
    "transfer": ["ย้าย", "รับย้าย"],
    "discharge": ["จำหน่าย"],
    "admit": ["รับไว้"],
    "icu": ["ไอซียู", "จองเตียง"],
    "blood": ["เลือด"],
    "transfusion": ["เลือด"],
    "specimen": ["สิ่งส่งตรวจ"],
    "bacteria": ["แบคทีเรีย"],
    "culture": ["แบคทีเรีย", "เชื้อ"],
    "antimicrobial": ["ยา"],
    "generic": ["สามัญ", "ชื่อสามัญ"],
    "dispensing": ["จ่ายยา"],
    "dispense": ["จ่ายยา"],
    "equipment": ["เครื่องมือ", "เครื่อง"],
    "sterilization": ["เครื่อง"],
    "province": ["จังหวัด"],
    "nationality": ["สัญชาติ"],
    "occupation": ["อาชีพ"],
    "price": ["ราคา"],
    "cost": ["ราคา", "ค่ารักษา"],
    "clinic": ["คลินิก", "ห้องตรวจ"],
    "doctor": ["แพทย์"],
    "physician": ["แพทย์"],
    "procedure": ["หัตถการ"],
    "mortality": ["เสียชีวิต", "ตาย"],
    "death": ["เสียชีวิต", "ตาย"],
    "readmission": ["รับซ้ำ"],
    "gender": ["เพศ"],
    "sex": ["เพศ"],
    "age": ["อายุ"],
    "bed": ["เตียง"],
    "booking": ["จอง"],
    "reserve": ["จอง"],
}


class SchemaRetriever:
    """Finds tables relevant to a user question by searching schema metadata.

    How it works:
    1. At init, builds a "search document" per table from:
       - Table name (decomposed into meaningful English words)
       - Table comment (Thai)
       - All column names
       - All column comments (Thai)
    2. On retrieve(), tokenizes the question (Thai segments + English words),
       adds cross-language bridging terms, then scores each table by how many
       tokens match its document, weighted by IDF.
    3. Returns the top-k most relevant table names.
    """

    def __init__(self, catalog: SchemaCatalog) -> None:
        self._catalog = catalog
        self._table_docs: dict[str, str] = self._build_search_docs()
        self._doc_count = len(self._table_docs)

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _build_search_docs(self) -> dict[str, str]:
        """Build a searchable text blob for every table."""
        docs: dict[str, str] = {}

        for table_name, table in self._catalog.tables.items():
            parts: list[str] = [
                table_name.lower(),
                table.comment or "",
            ]

            # Expand table-name components into English words
            name_lower = table_name.lower()
            for abbrev, expansions in _TABLE_COMPONENT_EXPANSIONS.items():
                if abbrev in name_lower:
                    parts.extend(expansions)

            # Add all column names and their Thai comments
            for col in table.columns.values():
                parts.append(col.name.lower())
                if col.comment:
                    parts.append(col.comment)

            docs[table_name] = " ".join(parts)

        return docs

    # ------------------------------------------------------------------
    # Thai stopwords (appear in almost every table comment)
    # ------------------------------------------------------------------
    _THAI_STOPWORDS: frozenset[str] = frozenset([
        "ข้อมูล", "ทะเบียน", "แฟ้มข้อมูล", "รายการ", "หลัก",
        "ของ", "ที่", "การ", "ใน", "และ",
    ])

    # ------------------------------------------------------------------
    # Tokenization
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize_question(question: str) -> list[str]:
        """Extract search tokens from a user question.

        For English: words + prefix stems (handles plurals, -ing, -ed).
        For Thai: full segments + character n-grams (length 3-12) so
        substrings like "ความดัน" are extracted from long Thai text.
        """
        tokens: set[str] = set()

        # English words with prefix-based stem variants
        for word in re.findall(r"[a-zA-Z]{2,}", question):
            lower = word.lower()
            tokens.add(lower)
            # Add shorter prefixes to handle plurals/tenses:
            # "appointments" -> "appointment", "appointmen"
            if len(lower) > 4:
                tokens.add(lower[:-1])
            if len(lower) > 5:
                tokens.add(lower[:-2])

        # Thai segments + n-grams
        for seg in re.findall(r"[\u0E00-\u0E7F]{2,}", question):
            tokens.add(seg)
            # Generate substrings of length 3-12 code points.
            # This lets "จำนวนผู้ป่วยที่มีความดันโลหิตสูง" produce
            # "ความดัน", "ความดันโล", "โลหิต", etc.
            for n in range(3, min(len(seg) + 1, 13)):
                for i in range(len(seg) - n + 1):
                    tokens.add(seg[i : i + n])

        return list(tokens)

    @staticmethod
    def _expand_with_bridge(tokens: list[str]) -> list[str]:
        """Add cross-language terms via the clinical term bridge.

        If the user says "blood pressure", we also search for Thai terms
        like "ความดัน" and "ความดันโลหิต".
        """
        extra: set[str] = set()

        # Check single tokens and token pairs against the bridge
        token_set = {t.lower() for t in tokens}

        for eng_phrase, thai_terms in _CLINICAL_TERM_BRIDGE.items():
            eng_words = eng_phrase.lower().split()
            # Match if ALL words in the English phrase appear in tokens
            if all(w in token_set for w in eng_words):
                extra.update(thai_terms)

        return list(set(tokens) | extra)

    # ------------------------------------------------------------------
    # IDF scoring
    # ------------------------------------------------------------------

    def _compute_idf(self, token: str) -> float:
        """IDF weight: rarer tokens across table documents score higher."""
        doc_freq = sum(1 for doc in self._table_docs.values() if token in doc)
        if doc_freq == 0:
            return 0.0
        return math.log(self._doc_count / doc_freq) + 1.0

    # ------------------------------------------------------------------
    # Reverse matching (table metadata found in question)
    # ------------------------------------------------------------------

    def _reverse_match_scores(
        self, question: str
    ) -> dict[str, float]:
        """Score tables by checking if their metadata appears IN the question.

        This is the complement of forward matching: instead of searching
        for question tokens in table docs, we search for table metadata
        (comments, column names) in the question text.

        Critical for Thai: the user's question may contain a Thai phrase
        like "ความดันโลหิตสูง" while the table comment is "ความดันโลหิต".
        Forward matching (token in doc) fails because the full question
        segment is longer, but reverse matching (comment in question) works.
        """
        scores: dict[str, float] = defaultdict(float)
        question_lower = question.lower()

        for table_name, table in self._catalog.tables.items():
            # Check table comment in question
            if table.comment:
                comment = table.comment
                # Strip common prefixes that appear everywhere
                for prefix in self._THAI_STOPWORDS:
                    if comment.startswith(prefix):
                        comment = comment[len(prefix) :]
                        break
                comment = comment.strip()
                if len(comment) >= 3 and comment in question:
                    scores[table_name] += 10.0

            # Check table name components in question
            name_lower = table_name.lower()
            # Split on transitions (e.g., OVSTPRESS -> ovst, press)
            for abbrev, expansions in _TABLE_COMPONENT_EXPANSIONS.items():
                if abbrev in name_lower:
                    for exp in expansions:
                        if exp in question_lower:
                            scores[table_name] += 3.0

            # Check column names in question (e.g., "bps" for blood
            # pressure systolic)
            for col in table.columns.values():
                col_lower = col.name.lower()
                if len(col_lower) >= 3 and col_lower in question_lower:
                    scores[table_name] += 2.0

        return dict(scores)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, question: str, top_k: int = 15) -> list[str]:
        """Find tables most relevant to the user's question.

        Uses three complementary strategies:
        1. Forward matching: question tokens found in table search docs
        2. Reverse matching: table metadata found in question text
        3. Cross-language bridging: English <-> Thai term expansion

        Args:
            question: User's natural language question
            top_k: Maximum number of tables to return

        Returns:
            Table names sorted by relevance score (descending).
        """
        raw_tokens = self._tokenize_question(question)
        if not raw_tokens:
            return []

        tokens = self._expand_with_bridge(raw_tokens)

        scores: dict[str, float] = defaultdict(float)

        # --- Forward matching: tokens from question in table docs ---
        for token in tokens:
            idf = self._compute_idf(token)
            if idf == 0.0:
                continue

            for table_name, doc in self._table_docs.items():
                if token not in doc:
                    continue

                # Base score weighted by IDF
                scores[table_name] += idf

                # Bonus: match in table name itself (strongest signal)
                if token in table_name.lower():
                    scores[table_name] += idf * 2.0

                # Bonus: match in table comment (strong signal)
                table_comment = (
                    self._catalog.tables[table_name].comment or ""
                )
                if token in table_comment:
                    scores[table_name] += idf * 1.5

        # --- Reverse matching: table metadata in question ---
        reverse_scores = self._reverse_match_scores(question)
        for table_name, rev_score in reverse_scores.items():
            scores[table_name] += rev_score

        sorted_tables = sorted(
            scores.items(), key=lambda x: x[1], reverse=True
        )
        return [name for name, _score in sorted_tables[:top_k]]

    # ------------------------------------------------------------------
    # Table directory (compact listing for LLM context)
    # ------------------------------------------------------------------

    @staticmethod
    def _col_type_abbrev(data_type: str) -> str:
        """Compact type abbreviation for a column."""
        dt = (data_type or "").lower()
        if "varchar" in dt or "text" in dt or "char" in dt:
            return "t"
        if "numeric" in dt or "int" in dt or "decimal" in dt:
            return "n"
        if "timestamp" in dt or "date" in dt:
            return "d"
        if "bool" in dt:
            return "b"
        return ""

    def _pick_key_columns(self, table_name: str) -> str:
        """Pick up to 7 key columns for a directory entry.

        Priority order:
        1. Universal keys (hn, an, vn) present in table
        2. PK columns
        3. FK columns (up to 3)
        4. Date columns (vstdate, indate, outdate, etc.)
        5. Important domain columns (name, code, status)
        """
        table = self._catalog.tables.get(table_name)
        if not table or not table.columns:
            return ""

        universal: list[str] = []
        pks: list[str] = []
        fks: list[str] = []
        dates: list[str] = []
        others: list[str] = []

        for col_name, col in table.columns.items():
            abbr = self._col_type_abbrev(col.data_type)
            entry = f"{col_name}:{abbr}" if abbr else col_name

            lower = col_name.lower()
            # Universal keys first
            if lower in ("hn", "an", "vn"):
                universal.append(entry)
            elif col.is_pk:
                pks.append(entry)
            elif col.is_fk:
                fks.append(entry)
            elif abbr == "d" or "date" in lower:
                dates.append(entry)
            elif lower in ("name", "name_en", "abbrname", "icd10", "icd9cm",
                           "labexm", "meditem", "tradename", "status"):
                others.append(entry)

        # Assemble: universal + PKs + FKs (max 3) + dates (max 2) + others
        picked = universal + pks + fks[:3] + dates[:2] + others
        return ",".join(picked[:7])

    def build_table_directory(self) -> str:
        """Build an enhanced directory of ALL tables for LLM context.

        Each entry shows the table description plus key columns (PK/FK/
        universal keys/date columns) so the LLM can write JOINs and basic
        queries even for tables without full DETAILED column info.
        """
        lines = [
            "## TABLE DIRECTORY (All Available Tables)",
            "",
            "Every table with key columns. [DETAILED] = full column info below.",
            "Non-detailed tables: use listed key columns + universal keys (hn/vn/an).",
            "",
        ]

        for table_name in sorted(self._catalog.tables.keys()):
            table = self._catalog.tables[table_name]
            comment = table.comment or ""
            col_count = table.column_count or len(table.columns)
            key_cols = self._pick_key_columns(table_name)
            col_part = f" | {key_cols}" if key_cols else ""
            lines.append(
                f"- {table_name}: {comment}{col_part} [{col_count}c]"
            )

        return "\n".join(lines)

    def mark_detailed_tables(
        self, directory: str, detailed_tables: set[str]
    ) -> str:
        """Add [DETAILED] markers to tables that have full column info."""
        result_lines: list[str] = []
        for line in directory.split("\n"):
            marked = False
            for table_name in detailed_tables:
                # Match "- TABLE_NAME:" at start of line
                prefix = f"- {table_name}:"
                if line.startswith(prefix):
                    line = line.replace(prefix, f"- {table_name} [DETAILED]:")
                    marked = True
                    break
            result_lines.append(line)
        return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_cached_retriever: SchemaRetriever | None = None


def get_schema_retriever(catalog: SchemaCatalog) -> SchemaRetriever:
    """Get or create the global SchemaRetriever instance."""
    global _cached_retriever
    if _cached_retriever is None:
        _cached_retriever = SchemaRetriever(catalog)
    return _cached_retriever


def reset_schema_retriever() -> None:
    """Reset the cached retriever (e.g. after schema reload)."""
    global _cached_retriever
    _cached_retriever = None
