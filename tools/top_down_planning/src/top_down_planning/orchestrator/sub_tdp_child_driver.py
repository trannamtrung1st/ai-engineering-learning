"""Continue prepared child runs through production and output review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core_tools.provider import Provider

from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.package.lineage import load_canonical_child_delivery
from top_down_planning.package.loader import ExecutionPackageError
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Provider]


@dataclass(frozen=True)
class PreparedChildResult:
    """Structured outcome of driving a prepared child Sub-TDP run."""

    run: dict[str, Any]
    ok: bool
    cancelled: bool
    status: str
    outcome: str | None
    reason: str | None = None
    phase: str | None = None

    @classmethod
    def from_run(
        cls,
        run: dict[str, Any],
        *,
        ok: bool,
        cancelled: bool = False,
        reason: str | None = None,
    ) -> PreparedChildResult:
        return cls(
            run=run,
            ok=ok,
            cancelled=cancelled,
            status=str(run.get("status") or ""),
            outcome=(
                str(run["outcome"])
                if run.get("outcome") is not None
                else None
            ),
            reason=reason,
            phase=str(run.get("phase") or "") or None,
        )


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
) -> PreparedChildResult:
    snapshot = child_store.load_canonical_snapshot(child_run_id)
    child_run = snapshot.run
    if _child_run_terminal(child_run):
        try:
            snapshot = load_canonical_child_delivery(
                child_store,
                child_run_id,
                verify_evidence=True,
            )
        except ValueError as exc:
            raise ExecutionPackageError(
                f"terminal child delivery invalid: {exc}",
                code="sub_tdp_lineage_mismatch",
            ) from exc
        return PreparedChildResult.from_run(snapshot.run, ok=True)

    child_config = snapshot.resolved_config
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
    cancelled = getattr(result, "cancelled", False) is True
    if cancelled:
        return PreparedChildResult.from_run(
            child_run,
            ok=False,
            cancelled=True,
            reason=getattr(result, "reason", None) or "cancelled by user",
        )
    if not result.ok and str(child_run.get("status") or "") == "paused":
        reason = getattr(result, "reason", None)
        stop = child_run.get("stop")
        child_cancelled = (
            cancelled
            or (
                isinstance(stop, dict)
                and str(stop.get("code") or "") == "user_cancelled"
            )
        )
        return PreparedChildResult.from_run(
            child_run,
            ok=False,
            cancelled=child_cancelled,
            reason=reason if isinstance(reason, str) else None,
        )
    if str(child_run.get("phase") or "") == OUTPUT_VALIDATED:
        if _child_run_terminal(child_run):
            return PreparedChildResult.from_run(child_run, ok=True)
        return PreparedChildResult.from_run(
            child_run,
            ok=False,
            cancelled=False,
            reason=(
                f"child Sub-TDP run {child_run_id} reached output_validated "
                f"without outcome=accepted (outcome={child_run.get('outcome')!r})"
            ),
        )
    if not result.ok:
        return PreparedChildResult.from_run(
            child_run,
            ok=False,
            cancelled=False,
            reason=(
                getattr(result, "reason", None)
                or f"child Sub-TDP run {child_run_id} did not complete"
            ),
        )
    return PreparedChildResult.from_run(child_run, ok=_child_run_terminal(child_run))


__all__ = ["PreparedChildResult", "ProviderFactory", "continue_child_sub_tdp"]
