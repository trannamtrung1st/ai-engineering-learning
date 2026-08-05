"""Validate execution-time config against prepared package digests (proposal §16.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.config import compute_output_goal_digest
from top_down_planning.config.context import compute_context_spec_digest_from_config
from top_down_planning.package.loader import ExecutionPackageError, LoadedExecutionPackage
from top_down_planning.persistence.digests import compute_config_contract_digest


def validate_resolved_config_against_package(
    resolved: dict[str, Any],
    package: LoadedExecutionPackage,
    *,
    workspace: Path,
) -> None:
    """Reject semantic config drift before creating prepared execution runs."""

    context = package.manifest.get("context") or {}
    if not isinstance(context, dict):
        return

    checks: list[tuple[str, str, str]] = [
        (
            "config_contract",
            compute_config_contract_digest(resolved),
            str(context.get("config_contract_digest") or ""),
        ),
        (
            "output_goal",
            compute_output_goal_digest(resolved, base_dir=workspace),
            str(context.get("output_goal_digest") or ""),
        ),
        (
            "context_spec",
            compute_context_spec_digest_from_config(resolved, workspace=workspace),
            str(context.get("context_spec_digest") or ""),
        ),
    ]
    for field, actual, expected in checks:
        if not expected:
            continue
        if actual != expected:
            raise ExecutionPackageError(
                f"prepared package {field} digest mismatch: execution config drifted "
                "from the approved planning package"
            )


__all__ = ["validate_resolved_config_against_package"]
