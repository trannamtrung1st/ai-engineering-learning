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
        and str(child_run.get("outcome") or "") == "accepted"
    )


def continue_child_sub_tdp(
    child_store: FileRunStore,
    child_run_id: str,
    *,
    create_provider: ProviderFactory,
    workspace: Path,
    observability: Any | None = None,
) -> dict[str, Any]:
    child_run = child_store.load_run(child_run_id)
    if _child_run_terminal(child_run):
        return child_run

    child_config = child_store.load_resolved_config(child_run_id)
    _ = workspace  # workspace is applied via provider factory / run record

    if str(child_run.get("status") or "") == "paused":
        resume_plan = prepare_resume(child_store, child_run_id, child_config)
        apply_resume_plan_atomically(
            child_store,
            resume_plan,
            resolved_config=child_config,
        )

    from top_down_planning.orchestrator.engine import RunEngine
    from top_down_planning.notifications import wrap_run_store

    store_for_engine = child_store
    if observability is not None:
        store_for_engine = wrap_run_store(child_store, observability=observability)

    engine = RunEngine(
        store_for_engine,
        create_provider=create_provider,
        observability=observability,
    )
    result = engine.continue_run(child_run_id, until="completed")
    child_run = child_store.load_run(child_run_id)
    if not result.ok and str(child_run.get("status") or "") == "paused":
        return child_run
    if str(child_run.get("phase") or "") == OUTPUT_VALIDATED:
        if _child_run_terminal(child_run):
            return child_run
        raise RuntimeError(
            f"child Sub-TDP run {child_run_id} reached output_validated "
            f"without outcome=accepted (outcome={child_run.get('outcome')!r})"
        )
    if not result.ok:
        raise RuntimeError(
            f"child Sub-TDP run {child_run_id} did not complete: {result.reason}"
        )
    return child_run


__all__ = ["ProviderFactory", "continue_child_sub_tdp"]
