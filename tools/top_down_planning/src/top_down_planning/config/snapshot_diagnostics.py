"""Snapshot collection diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SnapshotDiagnostics:
    """Counts observed during a single materialization pass (no second traversal)."""

    included_files: int
    excluded_files: int
    pruned_directories: int
    policy_version: str
    binding_size_bytes: int = 0

    def summary_lines(self) -> list[str]:
        size_kb = max(1, (self.binding_size_bytes + 1023) // 1024) if self.binding_size_bytes else 0
        size_label = f"{size_kb} KB" if self.binding_size_bytes else "0 KB"
        return [
            f"Snapshot: {self.included_files} included files",
            f"Excluded: {self.excluded_files} discovered files",
            f"Pruned: {self.pruned_directories} directories",
            f"Policy: {self.policy_version}",
            f"Binding size: {size_label}",
        ]

    def format_summary(self) -> str:
        return "\n".join(self.summary_lines())

    def to_event_fields(self) -> dict[str, Any]:
        return {
            "included_files": self.included_files,
            "excluded_files": self.excluded_files,
            "pruned_directories": self.pruned_directories,
            "policy_version": self.policy_version,
            "binding_size_bytes": self.binding_size_bytes,
            "summary": self.format_summary(),
        }


def binding_payload_size_bytes(binding: dict[str, Any]) -> int:
    """Deterministic UTF-8 size of the canonical binding JSON."""

    return len(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def format_unauthorized_mutation_message(unauthorized_paths: list[str]) -> str:
    """Unauthorized snapshot drift message for production completion."""

    from top_down_planning.config.context_digests import short_path_for_observability

    preview = unauthorized_paths[:20]
    lines = "\n".join(f"- {short_path_for_observability(path)}" for path in preview)
    suffix = ""
    if len(unauthorized_paths) > 20:
        suffix = f"\n(+{len(unauthorized_paths) - 20} more)"
    return (
        "production completion cannot rebase context snapshot:\n"
        f"unauthorized snapshot-bound changes detected:\n{lines}{suffix}"
    )


def format_apply_snapshot_evidence_message(
    unauthorized_paths: list[str],
    *,
    production_revision: int,
) -> str:
    """Apply-time message when a batch omits snapshot-bound output evidence."""

    from top_down_planning.config.context_digests import short_path_for_observability

    lines = "\n".join(
        f"- {short_path_for_observability(path)}" for path in unauthorized_paths
    )
    return (
        "production apply did not account for all changed snapshot-bound paths:\n"
        f"{lines}\n\n"
        "Add every listed workspace path to this batch's outputs and retry with "
        f"production_revision={production_revision}."
    )


def format_apply_context_mutation_message(
    unauthorized_paths: list[str],
    *,
    production_revision: int,
    evidence_gap_paths: list[str] | None = None,
) -> str:
    """Apply-time message for non-output-authorizable snapshot drift."""

    from top_down_planning.config.context_digests import short_path_for_observability

    lines = "\n".join(
        f"- {short_path_for_observability(path)}" for path in unauthorized_paths
    )
    message = (
        "production apply detected unauthorized snapshot-bound context changes:\n"
        f"{lines}\n\n"
        "Skills, guidance, and similar binding keys cannot be authorized through "
        "production outputs. Revert or reconcile the underlying context change "
        f"before retrying with production_revision={production_revision}."
    )
    if evidence_gap_paths:
        gap_lines = "\n".join(
            f"- {short_path_for_observability(path)}" for path in evidence_gap_paths
        )
        message = (
            f"{message}\n\n"
            "Also missing output evidence for these workspace paths:\n"
            f"{gap_lines}"
        )
    return message


__all__ = [
    "SnapshotDiagnostics",
    "binding_payload_size_bytes",
    "format_apply_context_mutation_message",
    "format_apply_snapshot_evidence_message",
    "format_unauthorized_mutation_message",
]
