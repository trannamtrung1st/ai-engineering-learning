"""Snapshot collection diagnostics (proposal §14)."""

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
    """Relative-path unauthorized mutation message (proposal §14)."""

    from top_down_planning.config.context_digests import short_path_for_observability

    preview = unauthorized_paths[:20]
    lines = "\n".join(f"- {short_path_for_observability(path)}" for path in preview)
    suffix = ""
    if len(unauthorized_paths) > 20:
        suffix = f"\n(+{len(unauthorized_paths) - 20} more)"
    return (
        "production completion cannot rebase context snapshot:\n"
        f"unauthorized workspace changes detected:\n{lines}{suffix}"
    )


__all__ = [
    "SnapshotDiagnostics",
    "binding_payload_size_bytes",
    "format_unauthorized_mutation_message",
]
