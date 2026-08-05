"""Continue prepared child runs through production and output review."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core_tools.provider import Provider

from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Provider]


def _child_run_terminal(child_run: dict[str, Any]) -> bool:
    return (
        str(child_run.get("status") or "") == "completed"
        and str(child_run.get("phase") or "") == OUTPUT_VALIDATED
    )


def continue_child_sub_tdp(
    child_store: FileRunStore,
    child_run_id: str,
    *,
    create_provider: ProviderFactory,
    workspace: Path,
) -> dict[str, Any]:
    child_run = child_store.load_run(child_run_id)
    if _child_run_terminal(child_run):
        return child_run

    child_config = child_store.load_resolved_config(child_run_id)
    resolved_workspace = workspace.resolve()

    if str(child_run.get("status") or "") == "paused":
        resume_plan = prepare_resume(child_store, child_run_id, child_config)
        apply_resume_plan_atomically(
            child_store,
            resume_plan,
            resolved_config=child_config,
        )

    from top_down_planning.orchestrator.engine import RunEngine

    engine = RunEngine(child_store, create_provider=create_provider)
    result = engine.continue_run(child_run_id, until="completed")
    child_run = child_store.load_run(child_run_id)
    if not result.ok and str(child_run.get("status") or "") == "paused":
        return child_run
    if str(child_run.get("phase") or "") == OUTPUT_VALIDATED:
        return child_run
    if not result.ok:
        raise RuntimeError(
            f"child Sub-TDP run {child_run_id} did not complete: {result.reason}"
        )
    return child_run


__all__ = ["ProviderFactory", "continue_child_sub_tdp"]
