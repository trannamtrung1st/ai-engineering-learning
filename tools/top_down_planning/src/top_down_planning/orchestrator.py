"""Top-down planning orchestration loop."""

from __future__ import annotations

import asyncio
import copy
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from top_down_planning.agent_context import (
    AgentContextConfig,
    resolve_phase_agent_context,
    resolve_phase_model,
    validate_agent_context_paths,
)
from top_down_planning.completeness import (
    compute_final_status,
    count_by_status,
    has_child_limit_blocked_leaves,
    is_plan_complete,
    leaf_actionable_count,
    limit_reached,
    reopen_eligible_child_limit_blocked,
)
from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient, SessionResult
from top_down_planning.errors import (
    CursorEnvironmentError,
    CursorSessionError,
    PlanningToolError,
    ResumeError,
    UserInterrupted,
    ValidationError,
)
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint, load_markdown_input, build_source_metadata
from top_down_planning.model_config import resolve_embed_threshold, resolve_model
from top_down_planning.models import (
    AgentResponse,
    FinalStatus,
    GenerationConfig,
    PlanItem,
    PlanningLimits,
    PlanningReport,
    RenderConfig,
    RenderStage,
    ReviewConfig,
    ReviewStatus,
    RunActiveStatus,
    RunState,
    WholePlanContextMode,
)
from top_down_planning.persistence import (
    ensure_resume_compatible,
    describe_resume_limit_changes,
    resolve_resume_limits,
    iteration_context_path,
    iteration_prefix,
    iteration_transaction_path,
    iterations_dir,
    load_plan,
    load_render_state,
    load_run_state,
    mark_last_success,
    new_run_state,
    plan_path,
    record_history,
    save_plan,
    save_run_state,
    update_final_status,
    update_review_status,
    write_json,
)
from top_down_planning.plan_tool import (
    PlanToolError,
    build_session_env,
    load_transaction,
    reset_transaction,
    resolve_plan_tool_command,
)
from top_down_planning.recovery import (
    backup_canonical_plan,
    is_plan_run_state_desynced,
    recover_plan_from_iterations,
    restore_canonical_plan,
)
from top_down_planning.review_flow import ReviewFlowDeps, run_post_decomposition_flow
from top_down_planning.render_flow import RenderFlowDeps, existing_published_artifacts, render_from_confirmed_plan
from top_down_planning.render_preconditions import validate_render_only_preconditions
from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import ensure_plan_overview_artifact, prepare_batch_context
from top_down_planning.prompts import build_planning_prompt
from top_down_planning.scheduler import (
    initialize_root_plan,
    select_concurrent_batches,
    wave_batch_budget,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.stream_events import StreamEmitter
from top_down_planning.validator import validate_wave_responses


@dataclass
class RunConfig:
    input_path: Path
    output_goal: LoadedOutputGoal
    output_dir: Path
    workspace_root: Path
    limits: PlanningLimits
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    render_only: bool = False
    force_rerender: bool = False
    goal_overridden: bool = False
    resume: bool = False
    stream_json: bool = False
    no_color: bool = False
    model: str | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    audit_iterations: bool = True
    embed_threshold: int | None = None
    stop_hint: LoadedStopHint | None = None
    notify: bool = True
    agent_context: AgentContextConfig | None = None
    review: ReviewConfig = field(default_factory=ReviewConfig)


@dataclass(frozen=True)
class _BatchSpec:
    iteration: int
    batch_index: int
    items: list[PlanItem]
    selected_ids: list[str]


@dataclass
class _BatchSessionResult:
    spec: _BatchSpec
    result: SessionResult
    context_mode: WholePlanContextMode | None = None


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.renderer = ConsoleRenderer(no_color=config.no_color)
        self.stream = StreamEmitter(enabled=config.stream_json)
        self._client: CursorClient | None = None
        self._artifacts: list[str] = []
        self._embed_threshold = resolve_embed_threshold(config.embed_threshold)
        self._agent_pid_lock = threading.Lock()
        self._validate_config_agent_context()

    def _validate_config_agent_context(self) -> None:
        if self.config.agent_context is None:
            return
        workspace = self.config.workspace_root.resolve()
        phases = (
            ("rendering", "review")
            if self.config.render_only
            else ("planning", "rendering", "review")
        )
        for phase in phases:
            resolved = resolve_phase_agent_context(
                phase,  # type: ignore[arg-type]
                self.config.agent_context,
            )
            if resolved.skills or resolved.rules:
                validate_agent_context_paths(
                    workspace,
                    resolved,
                    label=f"{phase} agent_context",
                )

    def _resolved_agent_context(self, *, phase: str):
        resolved = resolve_phase_agent_context(
            phase,  # type: ignore[arg-type]
            self.config.agent_context,
        )
        if not resolved.skills and not resolved.rules:
            return None
        return resolved

    def _resolve_session_model(self, *, phase: str) -> str | None:
        return resolve_phase_model(
            phase,  # type: ignore[arg-type]
            resolve_model(self.config.model),
            self.config.agent_context,
        )

    @property
    def client(self) -> CursorClient:
        if self._client is None:
            self._client = CursorClient(
                agent_bin=self.config.agent_bin,
                model=resolve_model(self.config.model),
                no_color=self.config.no_color,
                skip_probe=self.config.skip_probe,
                parse_error_threshold=self.config.limits.parse_error_threshold,
            )
        return self._client

    async def run(self) -> PlanningReport:
        output_dir = self.config.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.config.render_only:
            return await self._run_render_only(output_dir)

        loaded = load_markdown_input(self.config.input_path)

        loaded_goal = self.config.output_goal
        loaded_stop_hint = self.config.stop_hint
        goal_digest = loaded_goal.digest
        stop_hint_digest = loaded_stop_hint.digest if loaded_stop_hint else None

        existing_plan, existing_run = ensure_resume_compatible(
            output_dir,
            input_digest=loaded.digest,
            output_goal_digest=goal_digest,
            stop_hint_digest=stop_hint_digest,
            limits=self.config.limits,
            generation=self.config.generation,
            resume=self.config.resume,
        )

        if existing_plan is not None and existing_run is not None:
            plan = existing_plan
            run_state = existing_run
            if _any_agent_alive(run_state.agent_pids):
                alive = [pid for pid in run_state.agent_pids if _pid_alive(pid)]
                raise PlanningToolError(
                    "Cannot resume while Cursor agent is still running "
                    f"(pids={alive}). Stop them manually, then retry."
                )
            if is_plan_run_state_desynced(plan, run_state):
                if not self.config.audit_iterations:
                    raise ResumeError(
                        "plan.yaml appears reset but run-state shows prior progress "
                        f"(iteration={run_state.iteration}). "
                        "Recovery requires iteration audit files; restore plan.yaml "
                        "manually or re-run without disabling audit."
                    )
                recovered = recover_plan_from_iterations(output_dir, plan)
                if recovered is None or is_plan_run_state_desynced(recovered, run_state):
                    raise ResumeError(
                        "plan.yaml appears reset but run-state shows prior progress "
                        f"(iteration={run_state.iteration}). "
                        "Automatic recovery from iteration audit files failed."
                    )
                plan = recovered
                save_plan(output_dir, plan)
                self.renderer.info(
                    f"Recovered plan state from iteration audit files "
                    f"({len(plan.plan)} items)"
                )
            resolved_limits = resolve_resume_limits(
                run_state.limits,
                self.config.limits,
            )
            stored_limits = run_state.limits
            if resolved_limits != stored_limits:
                changes = describe_resume_limit_changes(
                    stored_limits,
                    resolved_limits,
                )
                run_state.limits = resolved_limits
                self.renderer.info(f"Updated resume limits ({changes})")
            if (
                resolved_limits.max_children_per_expansion
                > stored_limits.max_children_per_expansion
            ):
                plan, reopened = reopen_eligible_child_limit_blocked(
                    plan,
                    max_children_per_expansion=resolved_limits.max_children_per_expansion,
                )
                if reopened:
                    self.renderer.info(
                        "Reopened child-limit blocked nodes "
                        f"({', '.join(reopened)})"
                    )
                    if (
                        plan.result.status == FinalStatus.INCOMPLETE_BLOCKED
                        and not has_child_limit_blocked_leaves(plan)
                    ):
                        update_final_status(plan, FinalStatus.PLANNING, None)
                        if plan.result.review_status == ReviewStatus.BLOCKED:
                            update_review_status(plan, ReviewStatus.PENDING)
                    save_plan(output_dir, plan)
            if (
                plan.result.status == FinalStatus.INCOMPLETE_LIMIT_REACHED
                and not limit_reached(
                    iteration=run_state.iteration,
                    plan=plan,
                    limits=run_state.limits,
                )
            ):
                update_final_status(plan, FinalStatus.PLANNING, None)
                save_plan(output_dir, plan)
            run_state.agent_pids = []
            run_state.active_status = RunActiveStatus.RUNNING
            save_run_state(output_dir, run_state)
            self.renderer.info(f"Resuming planning in {output_dir}")
        else:
            source = build_source_metadata(
                input_file=str(loaded.path),
                input_digest=loaded.digest,
                loaded_goal=loaded_goal,
                loaded_stop_hint=loaded_stop_hint,
            )
            plan = initialize_root_plan(source=source)
            run_state = new_run_state(
                input_file=str(loaded.path),
                output_goal=loaded_goal.source_label,
                input_digest=loaded.digest,
                output_goal_digest=goal_digest,
                stop_hint_digest=stop_hint_digest,
                limits=self.config.limits,
                generation=self.config.generation,
            )
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)

        self.stream.emit(
            "planning.started",
            input=str(loaded.path),
            concurrent_batches=self.config.generation.concurrent_batches,
            batch_strategy=self.config.generation.batch_strategy.value,
        )

        try:
            plan, run_state = await self._planning_loop(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
            )
        except (CursorEnvironmentError, UserInterrupted):
            run_state.active_status = RunActiveStatus.PAUSED
            run_state.agent_pids = []
            save_run_state(output_dir, run_state)
            save_plan(output_dir, plan)
            raise
        except PlanningToolError as exc:
            run_state.active_status = RunActiveStatus.FAILED
            run_state.last_error = str(exc)
            update_final_status(plan, FinalStatus.FAILED, str(exc))
            save_run_state(output_dir, run_state)
            save_plan(output_dir, plan)
            raise

        counts = count_by_status(plan)
        report = PlanningReport(
            status=plan.result.status,
            review_status=plan.result.review_status,
            items=len(plan.plan),
            actionable_items=leaf_actionable_count(plan),
            blocked_items=counts["blocked"],
            out_of_scope_items=counts["out_of_scope"],
            iterations=run_state.iteration,
            output_dir=str(output_dir),
            artifacts=self._artifacts,
            summary=plan.result.summary,
        )
        self.stream.emit(
            "planning.completed",
            status=plan.result.status.value,
            items=report.items,
            actionable_items=report.actionable_items,
            artifacts=report.artifacts,
        )
        return report

    async def _planning_loop(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
    ):
        plan, run_state = await self._decomposition_loop(
            loaded=loaded,
            plan=plan,
            run_state=run_state,
            output_dir=output_dir,
        )

        plan, run_state, should_render = await run_post_decomposition_flow(
            self._review_flow_deps(loaded=loaded, output_dir=output_dir),
            plan=plan,
            run_state=run_state,
        )

        if should_render:
            existing = existing_published_artifacts(
                self.config.workspace_root,
                run_state,
                load_render_state(output_dir),
            )
            if existing and not self.config.force_rerender:
                self._artifacts = existing
                self.stream.emit("render.skipped", artifacts=existing)
            else:
                render_result = await render_from_confirmed_plan(
                    self._render_flow_deps(loaded=loaded, output_dir=output_dir),
                    plan=plan,
                    run_state=run_state,
                    force_rerender=self.config.force_rerender,
                )
                self._artifacts = render_result.artifacts
        return plan, run_state

    async def _decomposition_loop(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
    ):
        limits = run_state.limits

        while True:
            if is_plan_complete(plan):
                break
            if limit_reached(iteration=run_state.iteration, plan=plan, limits=limits):
                status = compute_final_status(plan, limit_reached=True)
                update_final_status(
                    plan,
                    status,
                    "Planning stopped because a configured safety limit was reached.",
                )
                run_state.active_status = RunActiveStatus.COMPLETED
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state

            remaining_iterations = limits.max_iterations - run_state.iteration
            wave_size = wave_batch_budget(
                self.config.generation,
                remaining_iterations=remaining_iterations,
            )
            batch_groups = select_concurrent_batches(
                plan,
                self.config.generation,
                max_batches=wave_size,
                output_dir=output_dir,
            )
            if not batch_groups:
                break

            base_iteration = run_state.iteration
            specs = [
                _BatchSpec(
                    iteration=base_iteration + batch_index + 1,
                    batch_index=batch_index,
                    items=batch_items,
                    selected_ids=[item.id for item in batch_items],
                )
                for batch_index, batch_items in enumerate(batch_groups)
            ]
            plan = await self._run_planning_wave(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                specs=specs,
            )

        status = compute_final_status(plan)
        summary = (
            "Planning decomposition completed."
            if status == FinalStatus.COMPLETE
            else "Planning finished with remaining incomplete items."
        )
        update_final_status(plan, status, summary)
        run_state.active_status = RunActiveStatus.COMPLETED
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state

    def _review_flow_deps(
        self,
        *,
        loaded: LoadedInput,
        output_dir: Path,
    ) -> ReviewFlowDeps:
        async def _resume_decomposition_only(plan, run_state):
            return await self._decomposition_loop(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
            )

        return ReviewFlowDeps(
            workspace_root=self.config.workspace_root,
            output_dir=output_dir,
            loaded=loaded,
            output_goal=self.config.output_goal,
            stop_hint=self.config.stop_hint,
            embed_threshold=self._embed_threshold,
            review=self.config.review,
            client=self.client,
            renderer=self.renderer,
            stream=self.stream,
            audit=self.config.audit_iterations,
            resolve_review_context=lambda: self._resolved_agent_context(phase="review"),
            resolve_review_model=lambda: self._resolve_session_model(phase="review"),
            run_planning_loop=_resume_decomposition_only,
        )

    def _render_flow_deps(
        self,
        *,
        loaded: LoadedInput | None,
        output_dir: Path,
    ) -> RenderFlowDeps:
        return RenderFlowDeps(
            workspace_root=self.config.workspace_root,
            output_dir=output_dir,
            loaded=loaded,
            output_goal=self.config.output_goal,
            embed_threshold=self._embed_threshold,
            render=self.config.render,
            client=self.client,
            renderer=self.renderer,
            stream=self.stream,
            audit=self.config.audit_iterations,
            resolve_render_context=lambda: self._resolved_agent_context(phase="rendering"),
            resolve_render_model=lambda: self._resolve_session_model(phase="rendering"),
            resolve_review_context=lambda: self._resolved_agent_context(phase="review"),
            resolve_review_model=lambda: self._resolve_session_model(phase="review"),
            session_timeout_seconds=self.config.limits.session_timeout_seconds,
        )

    async def _run_render_only(self, output_dir: Path) -> PlanningReport:
        self.stream.emit("render.only.started", output=str(output_dir))
        plan, _plan_digest = validate_render_only_preconditions(
            output_dir,
            output_goal=self.config.output_goal,
            goal_overridden=self.config.goal_overridden,
        )
        run_state = load_run_state(output_dir)
        if run_state is None:
            raise PlanningToolError("Render-only requires existing run-state.json")

        loaded: LoadedInput | None = None
        if self.config.input_path.is_file():
            loaded = load_markdown_input(self.config.input_path)
        elif plan.source.input_file:
            candidate = Path(plan.source.input_file)
            if candidate.is_file():
                loaded = load_markdown_input(candidate)

        render_result = await render_from_confirmed_plan(
            self._render_flow_deps(loaded=loaded, output_dir=output_dir),
            plan=plan,
            run_state=run_state,
            force_rerender=self.config.force_rerender,
            render_only=True,
        )
        self._artifacts = render_result.artifacts

        counts = count_by_status(plan)
        return PlanningReport(
            status=plan.result.status,
            review_status=plan.result.review_status,
            items=len(plan.plan),
            actionable_items=leaf_actionable_count(plan),
            blocked_items=counts["blocked"],
            out_of_scope_items=counts["out_of_scope"],
            iterations=run_state.iteration,
            output_dir=str(output_dir),
            artifacts=self._artifacts,
            summary=plan.result.summary,
        )

    async def _run_planning_wave(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
        specs: list[_BatchSpec],
    ):
        limits = run_state.limits
        plan_snapshot = copy.deepcopy(plan)
        plan_digest = compute_plan_digest(plan_snapshot)
        wave_size = len(specs)
        iteration_numbers = [spec.iteration for spec in specs]

        overview_path = ensure_plan_overview_artifact(
            output_dir,
            plan_snapshot,
            plan_digest,
        )
        self.stream.emit(
            "generation.batch.context_prepared",
            plan_digest=plan_digest,
            plan_overview=str(overview_path),
            wave_size=wave_size,
        )

        self.stream.emit(
            "wave.started",
            wave_size=wave_size,
            iterations=iteration_numbers,
            plan_digest=plan_digest,
        )
        for spec in specs:
            self.stream.emit(
                "generation.batch.started",
                iteration=spec.iteration,
                batch_index=spec.batch_index,
                batch_count=wave_size,
                selected_items=spec.selected_ids,
                plan_digest=plan_digest,
            )
            self.stream.emit(
                "iteration.started",
                iteration=spec.iteration,
                batch_index=spec.batch_index,
                batch_count=wave_size,
                selected_items=spec.selected_ids,
            )
            self.renderer.rule(
                "PLAN "
                f"iteration={spec.iteration} "
                f"batch={spec.batch_index + 1}/{wave_size} "
                f"items={','.join(spec.selected_ids)}"
            )

        validation_feedback: list[str] | None = None
        applied = False
        for attempt in range(1, limits.max_retries + 1):
            run_state.retry_count = attempt - 1
            run_state.agent_pids = []
            save_run_state(output_dir, run_state)

            try:
                session_results = await self._run_batch_sessions(
                    loaded=loaded,
                    plan=plan_snapshot,
                    run_state=run_state,
                    output_dir=output_dir,
                    specs=specs,
                    attempt=attempt,
                    validation_feedback=validation_feedback,
                    plan_digest=plan_digest,
                )
            except UserInterrupted:
                run_state.agent_pids = []
                save_run_state(output_dir, run_state)
                raise
            except CursorEnvironmentError:
                raise
            except CursorSessionError as exc:
                run_state.agent_pids = []
                run_state.last_error = str(exc)
                save_run_state(output_dir, run_state)
                if attempt >= limits.max_retries:
                    raise PlanningToolError(
                        f"Planning wave failed after {limits.max_retries} attempts: {exc}"
                    ) from exc
                self.stream.emit(
                    "wave.retrying",
                    wave_size=wave_size,
                    iterations=iteration_numbers,
                    attempt=attempt + 1,
                    reason=str(exc),
                )
                continue

            run_state.agent_pids = []
            parsed_batches: list[tuple[_BatchSpec, AgentResponse]] = []
            parse_failed = False
            for session_result in session_results:
                spec = session_result.spec
                prefix = Path(iteration_prefix(output_dir, spec.iteration))
                transaction_path = iteration_transaction_path(output_dir, spec.iteration)
                response_path = prefix.with_name(prefix.name + "-response.json")
                validation_path = prefix.with_name(prefix.name + "-validation.json")
                try:
                    response = load_transaction(transaction_path)
                except PlanToolError as exc:
                    parse_failed = True
                    validation_feedback = [str(exc)]
                    self.stream.emit(
                        "validation.failed",
                        iteration=spec.iteration,
                        batch_index=spec.batch_index,
                        batch_count=wave_size,
                        errors=validation_feedback,
                    )
                    if self.config.audit_iterations:
                        write_json(
                            response_path,
                            {
                                "error": str(exc),
                                "assistant_tail": session_result.result.assistant_text[-8000:],
                            },
                        )
                        write_json(validation_path, {"errors": validation_feedback})
                    if attempt >= limits.max_retries:
                        raise PlanningToolError(
                            f"Failed to load planning transaction after {limits.max_retries} attempts"
                        ) from exc
                    self.stream.emit(
                        "wave.retrying",
                        wave_size=wave_size,
                        iterations=iteration_numbers,
                        attempt=attempt + 1,
                        reason=str(exc),
                    )
                    break
                parsed_batches.append((spec, response))

            if parse_failed:
                continue

            wave_pairs = [
                (spec.selected_ids, response)
                for spec, response in parsed_batches
            ]
            errors = validate_wave_responses(
                plan_snapshot,
                wave_pairs,
                limits=limits,
                plan_digest=plan_digest,
            )
            if errors:
                validation_feedback = errors
                self.stream.emit(
                    "generation.wave.validated",
                    success=False,
                    plan_digest=plan_digest,
                    errors=errors,
                )
                for spec, response in parsed_batches:
                    self.stream.emit(
                        "validation.failed",
                        iteration=spec.iteration,
                        batch_index=spec.batch_index,
                        batch_count=wave_size,
                        errors=errors,
                    )
                    if self.config.audit_iterations:
                        prefix = Path(iteration_prefix(output_dir, spec.iteration))
                        response_path = prefix.with_name(prefix.name + "-response.json")
                        validation_path = prefix.with_name(prefix.name + "-validation.json")
                        write_json(response_path, response.model_dump(mode="json"))
                        write_json(validation_path, {"errors": errors})
                if attempt >= limits.max_retries:
                    raise ValidationError(errors)
                self.stream.emit(
                    "wave.retrying",
                    wave_size=wave_size,
                    iterations=iteration_numbers,
                    attempt=attempt + 1,
                )
                continue

            self.stream.emit(
                "generation.wave.validated",
                success=True,
                plan_digest=plan_digest,
            )

            for spec, response in parsed_batches:
                plan = apply_response(plan, response)
                self._emit_operation_events(response)

            if self.config.audit_iterations:
                for spec, response in parsed_batches:
                    prefix = Path(iteration_prefix(output_dir, spec.iteration))
                    response_path = prefix.with_name(prefix.name + "-response.json")
                    validation_path = prefix.with_name(prefix.name + "-validation.json")
                    write_json(response_path, response.model_dump(mode="json"))
                    write_json(validation_path, {"errors": []})

            run_state.iteration = specs[-1].iteration
            save_plan(output_dir, plan)
            mark_last_success(output_dir, run_state)
            record_history(
                output_dir,
                run_state,
                event="wave_applied",
                wave_size=wave_size,
                iterations=iteration_numbers,
                attempt=attempt,
            )
            for spec in specs:
                context_mode = next(
                    (
                        session.context_mode
                        for session in session_results
                        if session.spec.iteration == spec.iteration
                    ),
                    None,
                )
                record_history(
                    output_dir,
                    run_state,
                    event="iteration_applied",
                    iteration=spec.iteration,
                    batch_index=spec.batch_index,
                    batch_count=wave_size,
                    selected_items=spec.selected_ids,
                    attempt=attempt,
                )
                self.stream.emit(
                    "generation.batch.completed",
                    iteration=spec.iteration,
                    batch_index=spec.batch_index,
                    batch_count=wave_size,
                    selected_items=spec.selected_ids,
                    plan_digest=plan_digest,
                    context_mode=context_mode.value if context_mode else None,
                )
                self.stream.emit(
                    "iteration.completed",
                    iteration=spec.iteration,
                    batch_index=spec.batch_index,
                    batch_count=wave_size,
                    selected_items=spec.selected_ids,
                )

            self.stream.emit(
                "generation.wave.applied",
                plan_digest=plan_digest,
                wave_size=wave_size,
                iterations=iteration_numbers,
            )
            self.stream.emit(
                "wave.completed",
                wave_size=wave_size,
                iterations=iteration_numbers,
            )
            applied = True
            break

        if not applied:
            raise PlanningToolError(
                f"Planning wave {iteration_numbers} failed after {limits.max_retries} attempts"
            )

        return plan

    async def _run_batch_sessions(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
        specs: list[_BatchSpec],
        attempt: int,
        validation_feedback: list[str] | None,
        plan_digest: str,
    ) -> list[_BatchSessionResult]:
        await self.client.ensure_ready()
        batch_count = len(specs)
        tasks = [
            asyncio.create_task(
                self._execute_batch_session(
                    loaded=loaded,
                    plan=plan,
                    run_state=run_state,
                    output_dir=output_dir,
                    spec=spec,
                    batch_count=batch_count,
                    attempt=attempt,
                    validation_feedback=validation_feedback,
                    plan_digest=plan_digest,
                )
            )
            for spec in specs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                await _cancel_tasks(tasks)
                raise result
        return results  # type: ignore[return-value]

    async def _execute_batch_session(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
        spec: _BatchSpec,
        batch_count: int,
        attempt: int,
        validation_feedback: list[str] | None,
        plan_digest: str,
    ) -> _BatchSessionResult:
        limits = run_state.limits
        generation = self.config.generation
        plan_tool_command = resolve_plan_tool_command()

        prepared = prepare_batch_context(
            plan=plan,
            selected_items=spec.items,
            plan_digest=plan_digest,
            output_dir=output_dir,
            whole_plan_context=generation.whole_plan_context,
            max_context_characters=generation.max_context_characters,
        )

        context_path = iteration_context_path(output_dir, spec.iteration)
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(prepared.batch_context_markdown, encoding="utf-8")

        prompt = build_planning_prompt(
            loaded_input=loaded,
            workspace=self.config.workspace_root,
            output_goal=self.config.output_goal,
            plan=plan,
            selected_items=spec.items,
            embed_threshold=self._embed_threshold,
            max_children_per_expansion=limits.max_children_per_expansion,
            stop_hint=self.config.stop_hint,
            validation_feedback=validation_feedback,
            plan_tool_command=plan_tool_command,
            agent_context=self._resolved_agent_context(phase="planning"),
            plan_digest=plan_digest,
            batch_context_markdown=prepared.batch_context_markdown,
            context_mode=prepared.context_mode,
        )
        prefix = Path(iteration_prefix(output_dir, spec.iteration))
        prompt_path = prefix.with_name(prefix.name + "-request-prompt.md")
        events_path = prefix.with_name(prefix.name + "-agent.ndjson")
        log_path = prefix.with_name(prefix.name + "-agent.log")
        transaction_path = iteration_transaction_path(output_dir, spec.iteration)
        canonical_plan_file = plan_path(output_dir)

        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        reset_transaction(transaction_path)
        if self.config.audit_iterations:
            request_payload: dict[str, object] = {
                "iteration": spec.iteration,
                "batch_index": spec.batch_index,
                "batch_count": batch_count,
                "attempt": attempt,
                "selected_items": spec.selected_ids,
                "transaction_path": str(transaction_path),
                "plan_digest": plan_digest,
                "batch_context_artifact": context_path.name,
                "context_mode": prepared.context_mode.value,
            }
            if prepared.plan_overview_relative:
                request_payload["plan_overview_artifact"] = (
                    f"context/{Path(prepared.plan_overview_relative).name}"
                    if "plan-overview" in prepared.plan_overview_relative
                    else prepared.plan_overview_relative
                )
            write_json(
                prefix.with_name(prefix.name + "-request.json"),
                request_payload,
            )

        session_env = build_session_env(
            transaction_path=transaction_path,
            selected_ids=spec.selected_ids,
            plan_file=canonical_plan_file,
            plan_digest=plan_digest,
            plan_tool_command=plan_tool_command,
        )
        min_plan_items = len(plan.plan)
        plan_backup = backup_canonical_plan(
            output_dir,
            suffix=f"{spec.iteration:03d}",
        )

        def on_started(pid: int) -> None:
            self._add_agent_pid(output_dir, run_state, pid)

        try:
            result = await self.client.run_session(
                workspace=self.config.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=limits.session_timeout_seconds,
                events_path=events_path if self.config.audit_iterations else None,
                log_path=log_path if self.config.audit_iterations else None,
                renderer=ConsoleRenderer.with_file_logging(
                    self.renderer,
                    log_path,
                )
                if self.config.audit_iterations
                else self.renderer,
                on_agent_started=on_started,
                session_mode="agent",
                extra_env=session_env,
                model=self._resolve_session_model(phase="planning"),
            )
        finally:
            if restore_canonical_plan(
                output_dir, plan_backup, min_items=min_plan_items
            ):
                self.renderer.warning(
                    "Restored plan.yaml after planning session modified canonical state"
                )
        return _BatchSessionResult(
            spec=spec,
            result=result,
            context_mode=prepared.context_mode,
        )

    def _emit_operation_events(self, response: AgentResponse) -> None:
        for operation in response.operations:
            if operation.type == "expand":
                self.stream.emit(
                    "item.expanded",
                    item_id=operation.node_id,
                    children_count=len(operation.children),
                )
            elif operation.type == "mark_actionable":
                self.stream.emit(
                    "item.actionable",
                    item_id=operation.node_id,
                )
            elif operation.type == "mark_blocked":
                self.stream.emit(
                    "item.blocked",
                    item_id=operation.node_id,
                )
            elif operation.type == "mark_out_of_scope":
                self.stream.emit(
                    "item.out_of_scope",
                    item_id=operation.node_id,
                )

    def _add_agent_pid(self, output_dir: Path, run_state: RunState, pid: int) -> None:
        with self._agent_pid_lock:
            if pid not in run_state.agent_pids:
                run_state.agent_pids.append(pid)
            run_state.agent_pid = None
            save_run_state(output_dir, run_state)


def _any_agent_alive(pids: list[int]) -> bool:
    return any(_pid_alive(pid) for pid in pids)


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
