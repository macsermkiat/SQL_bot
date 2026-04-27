"""Accumulate learnings into patch proposals and apply them to schema knowledge files."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from pathlib import Path

from tests.sql_testing.notion_eval.ticket_models import Learning, PatchProposal

logger = logging.getLogger(__name__)

_SCHEMA_ROOT = Path(__file__).parent.parent.parent.parent / "schema"
_MIN_SUPPORT = 2


def accumulate_patches(
    learnings: list[Learning],
    min_support: int = _MIN_SUPPORT,
) -> list[PatchProposal]:
    """Group learnings by type+detail and propose patches for those with enough support."""
    groups: dict[str, list[Learning]] = defaultdict(list)
    for l in learnings:
        key = f"{l.learning_type}::{l.detail[:80]}"
        groups[key].append(l)

    proposals: list[PatchProposal] = []
    for key, group in groups.items():
        if len(group) < min_support:
            logger.debug("Skipping patch '%s' — only %d ticket(s)", key, len(group))
            continue

        rep = group[0]
        proposals.append(
            PatchProposal(
                patch_id=str(uuid.uuid4())[:8],
                title=f"[{rep.learning_type}] {rep.detail[:60]}",
                target_file=rep.target_file or "concepts.yaml",
                patch_type=_infer_patch_type(rep),
                content=_build_patch_content(rep, group),
                affected_tickets=[l.ticket_id for l in group],
                support_count=len(group),
            )
        )

    proposals.sort(key=lambda p: p.support_count, reverse=True)
    logger.info("Generated %d patch proposal(s) from %d learnings", len(proposals), len(learnings))
    return proposals


def apply_patches(
    proposals: list[PatchProposal],
    schema_root: Path = _SCHEMA_ROOT,
    dry_run: bool = False,
) -> list[PatchProposal]:
    """Apply unapplied proposals to schema files. Returns list of applied proposals."""
    applied: list[PatchProposal] = []

    for proposal in proposals:
        if proposal.applied:
            continue

        target = schema_root / proposal.target_file
        try:
            if proposal.patch_type == "csv_row":
                _apply_csv_row(target, proposal.content, dry_run)
            else:
                _apply_yaml_entry(target, proposal.content, dry_run)

            proposal.applied = not dry_run
            applied.append(proposal)
            logger.info(
                "%sApplied patch '%s' to %s (support=%d)",
                "[DRY-RUN] " if dry_run else "",
                proposal.patch_id,
                proposal.target_file,
                proposal.support_count,
            )
        except Exception as exc:
            logger.error("Failed to apply patch '%s': %s", proposal.patch_id, exc)

    return applied


def _infer_patch_type(learning: Learning) -> str:
    if learning.target_file == "join_edges.csv":
        return "csv_row"
    if learning.target_file == "sql_corrections.yaml":
        return "yaml_correction"
    return "yaml_entry"


def _build_patch_content(rep: Learning, group: list[Learning]) -> str:
    ticket_refs = ", ".join(l.ticket_id[:8] for l in group[:5])
    if rep.target_file == "join_edges.csv":
        return _build_join_csv_row(rep)
    if rep.target_file == "sql_corrections.yaml":
        return _build_correction_yaml(rep, ticket_refs)
    return _build_concept_yaml(rep, ticket_refs)


def _build_join_csv_row(learning: Learning) -> str:
    parts = learning.detail.split("'")
    left_full = parts[1] if len(parts) > 1 else "UNKNOWN.col"
    right_full = parts[3] if len(parts) > 3 else "UNKNOWN.col"

    def split_col(s: str) -> tuple[str, str]:
        if "." in s:
            tbl, col = s.rsplit(".", 1)
            return tbl.upper(), col.lower()
        return s.upper(), "hn"

    ft, fc = split_col(left_full)
    tt, tc = split_col(right_full)
    return (
        f"{ft},{fc},{tt},{tc},=,high,universal,notion_eval,,1,"
        f"notion_eval,universal,,,{tt},{tc},{ft},{fc}"
    )


def _build_correction_yaml(learning: Learning, ticket_refs: str) -> str:
    slug = learning.detail[:40].lower().replace(" ", "_").replace("'", "")
    slug = "".join(c if c.isalnum() or c == "_" else "" for c in slug)
    return (
        f"\n{slug}_notion_{ticket_refs[:8]}:\n"
        f"  tables: []\n"
        f"  wrong: |\n"
        f"    (pattern from tickets: {ticket_refs})\n"
        f"  right: |\n"
        f"    {learning.suggested_fix}\n"
        f"  reason: |\n"
        f"    Auto-extracted from Notion eval. Detail: {learning.detail}\n"
    )


def _build_concept_yaml(learning: Learning, ticket_refs: str) -> str:
    slug = learning.detail[:40].lower().replace(" ", "_").replace("'", "")
    slug = "".join(c if c.isalnum() or c == "_" else "" for c in slug)
    table = ""
    parts = learning.detail.split("'")
    if len(parts) > 1:
        table = parts[1]
    return (
        f"\n# Auto-proposed from Notion eval (tickets: {ticket_refs})\n"
        f"# TODO: review and complete this entry\n"
        f"{slug}_auto:\n"
        f"  description: |\n"
        f"    {learning.detail}\n"
        f"  tables:\n"
        f"    - \"{table}\"\n"
        f"  suggested_fix: |\n"
        f"    {learning.suggested_fix}\n"
    )


def _apply_yaml_entry(target: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        logger.info("[DRY-RUN] Would append to %s:\n%s", target, content[:200])
        return
    with open(target, "a", encoding="utf-8") as f:
        f.write(content)


def _apply_csv_row(target: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        logger.info("[DRY-RUN] Would append CSV row to %s:\n%s", target, content)
        return
    with open(target, "a", encoding="utf-8", newline="") as f:
        f.write("\n" + content)
