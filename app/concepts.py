"""
Clinical concept library loader.

Loads concept definitions from YAML for use in SQL generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


@dataclass
class Concept:
    """A clinical concept definition."""

    name: str
    description: str
    condition: str | None = None  # SQL WHERE condition
    icd10_codes: list[str] = field(default_factory=list)
    icd9_codes: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)  # Lab test names
    bundle_logic: Literal["same_visit", "same_day", "same_order"] | None = None
    tables: list[str] = field(default_factory=list)  # Relevant tables
    notes: str | None = None


@dataclass
class ConceptLibrary:
    """Collection of clinical concepts."""

    concepts: dict[str, Concept] = field(default_factory=dict)

    def get(self, name: str) -> Concept | None:
        """Get concept by name."""
        return self.concepts.get(name)

    def search(self, query: str) -> list[Concept]:
        """Search concepts by name or description."""
        query_lower = query.lower()
        results = []
        for concept in self.concepts.values():
            if (query_lower in concept.name.lower() or
                query_lower in concept.description.lower()):
                results.append(concept)
        return results


def load_concepts(path: Path) -> ConceptLibrary:
    """
    Load concept library from YAML file.

    Args:
        path: Path to concepts.yaml

    Returns:
        ConceptLibrary with loaded concepts
    """
    library = ConceptLibrary()

    if not path.exists():
        return library

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    for name, definition in data.items():
        if isinstance(definition, dict):
            concept = Concept(
                name=name,
                description=definition.get("description", ""),
                condition=definition.get("condition"),
                icd10_codes=definition.get("icd10_codes", []),
                icd9_codes=definition.get("icd9_codes", []),
                tests=definition.get("tests", []),
                bundle_logic=definition.get("bundle_logic"),
                tables=definition.get("tables", []),
                notes=definition.get("notes"),
            )
            library.concepts[name] = concept

    return library


def save_concepts(library: ConceptLibrary, path: Path) -> None:
    """
    Save concept library to YAML file.

    Args:
        library: ConceptLibrary to save
        path: Output path
    """
    data = {}
    for name, concept in library.concepts.items():
        entry = {"description": concept.description}
        if concept.condition:
            entry["condition"] = concept.condition
        if concept.icd10_codes:
            entry["icd10_codes"] = concept.icd10_codes
        if concept.icd9_codes:
            entry["icd9_codes"] = concept.icd9_codes
        if concept.tests:
            entry["tests"] = concept.tests
        if concept.bundle_logic:
            entry["bundle_logic"] = concept.bundle_logic
        if concept.tables:
            entry["tables"] = concept.tables
        if concept.notes:
            entry["notes"] = concept.notes
        data[name] = entry

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
