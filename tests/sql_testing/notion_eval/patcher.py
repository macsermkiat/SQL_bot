"""Accumulate learnings into patch proposals and apply them to schema knowledge files."""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from collections import defaultdict
from pathlib import Path

import yaml

from tests.sql_testing.notion_eval.ticket_models import Learning, PatchProposal

logger = logging.getLogger(__name__)

_SCHEMA_ROOT = Path(__file__).parent.parent.parent.parent / "schema"
_MIN_SUPPORT = 2
_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_]+$')


def accumulate_patches(
    learnings: list[Learning],
    min_support: int = _MIN_SUPPORT,
) -> list[PatchProposal]:
    """Group learnings by type+detail and propose patches with enough support."""
    groups: dict[str, list[Learning]] = defaultdict(list)
    for learning in learnings:
        key = f"{learning.learning_type}::{learning.detail}"
        groups[key].append(learning)

    proposals: list[PatchProposal] = []
    for key, group in groups.items():
        if len(group) < min_support:
            logger.debug("Skipping patch '%s' — only %d ticket(s)", key[:60], len(group))
            continue

        rep = group[0]
        proposals.append(
            PatchProposal(
                patch_id=str(uuid.uuid4())[:8],
                title=f"[{rep.learning_type}] {rep.detail[:60]}",
                target_file=rep.target_file or "concepts.yaml",
                patch_type=_infer_patch_type(rep),
                content=_build_patch_content(rep, group),
                affected_tickets=[learning.ticket_id for learning in group],
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
    """DEPRECATED: not called by runner. Review proposals.yaml manually, then apply with care.

    Apply unapplied proposals to schema files. Returns list of applied proposals.

    Raises RuntimeError if any patch fails, so the caller can abort auto-PR.
    """
    applied: list[PatchProposal] = []
    failed: list[str] = []

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
            failed.append(proposal.patch_id)
            logger.error("Failed to apply patch '%s': %s", proposal.patch_id, exc)

    if failed:
        raise RuntimeError(
            f"{len(failed)} patch(es) failed to apply: {failed}. "
            "Schema files may be in a partial state — review before committing."
        )

    return applied


def _infer_patch_type(learning: Learning) -> str:
    if learning.target_file == "join_edges.csv":
        return "csv_row"
    if learning.target_file == "sql_corrections.yaml":
        return "yaml_correction"
    return "yaml_entry"


def _build_patch_content(rep: Learning, group: list[Learning]) -> str:
    ticket_refs = ", ".join(learning.ticket_id[:8] for learning in group[:5])
    if rep.target_file == "join_edges.csv":
        return _build_join_csv_row(rep)
    if rep.target_file == "sql_corrections.yaml":
        return _build_correction_yaml(rep, ticket_refs)
    return _build_concept_yaml(rep, ticket_refs)


def _slug(detail: str) -> str:
    """Stable, non-empty ASCII slug from a detail string."""
    raw = detail[:60].lower().replace(" ", "_").replace("'", "")
    cleaned = "".join(c if c.isalnum() or c == "_" else "" for c in raw).strip("_")
    return cleaned or f"patch_{uuid.uuid4().hex[:8]}"


def _validate_identifier(value: str, context: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Unsafe identifier in {context}: {value!r}")


def _build_join_csv_row(learning: Learning) -> str:
    """Build a properly quoted CSV row for join_edges.csv."""
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

    for val, ctx in [(ft, "from_table"), (fc, "from_column"), (tt, "to_table"), (tc, "to_column")]:
        _validate_identifier(val, ctx)

    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL).writerow([
        ft, fc, tt, tc, "=", "high", "universal", "notion_eval", "",
        1, "notion_eval", "universal", "", "", tt, tc, ft, fc,
    ])
    return buf.getvalue().rstrip("\r\n")


def _build_correction_yaml(learning: Learning, ticket_refs: str) -> str:
    """Build a safe YAML correction entry via yaml.safe_dump."""
    key = f"{_slug(learning.detail)}_notion_{uuid.uuid4().hex[:6]}"
    payload = {
        key: {
            "tables": [],
            "wrong": f"(pattern from tickets: {ticket_refs})",
            "right": learning.suggested_fix,
            "reason": f"Auto-extracted from Notion eval. Detail: {learning.detail}",
        }
    }
    return "\n" + yaml.safe_dump(
        payload, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False
    )


def _build_concept_yaml(learning: Learning, ticket_refs: str) -> str:
    """Build a safe YAML concept entry via yaml.safe_dump."""
    key = f"{_slug(learning.detail)}_auto"
    parts = learning.detail.split("'")
    table = parts[1] if len(parts) > 1 else ""
    payload = {
        key: {
            "description": learning.detail,
            "tables": [table] if table else [],
            "suggested_fix": learning.suggested_fix,
            "source": f"notion_eval tickets: {ticket_refs}",
        }
    }
    comment = "# Auto-proposed from Notion eval — TODO: review before merging\n"
    return "\n" + comment + yaml.safe_dump(
        payload, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False
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
