"""Top-down planning orchestration loop."""

from __future__ import annotations

import copy
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from top_down_planning.agent_context import (
    AgentContextConfig,
    PhaseName,
    resolve_phase_agent_context,
    resolve_phase_model,
    validate_agent_context_paths,
)
from top_down_planning.completeness import (
    compute_final_status,
    count_by_status,
    is_plan_complete,
    leaf_actionable_count,
    limit_reached,
)
from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
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
    ProcessedBatchRecord,
    PlanningLimits,
    PlanningReport,
    RenderConfig,
    RenderStage,
    ReviewConfig,
    ReviewFinding,
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
from top_down_planning.render_flow import RenderFlowDeps, existing_deliverable_artifacts, render_from_confirmed_plan
from top_down_planning.render_preconditions import validate_render_only_preconditions
from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import (
    ensure_plan_overview_artifact,
    prepare_batch_context,
)
from top_down_planning.prompts import build_amend_prompt, build_planning_prompt
from top_down_planning.scheduler import (
    amendable_items,
    expandable_items,
    initialize_root_plan,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.stream_events import StreamEmitter
from top_down_planning.validator import (
    validate_amend_wave_responses,
    validate_wave_responses,
)


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
                phase,
                self.config.agent_context,
            )
            if resolved.skills or resolved.rules:
                validate_agent_context_paths(
                    workspace,
                    resolved,
                    label=f"{phase} agent_context",
                )

    def _resolved_agent_context(self, *, phase: PhaseName):
        resolved = resolve_phase_agent_context(
            phase,
            self.config.agent_context,
        )
        if not resolved.skills and not resolved.rules:
            return None
        return resolved

    def _resolve_session_model(self, *, phase: PhaseName) -> str | None:
        return resolve_phase_model(
            phase,
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
            render=self.config.render,
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
                plan.result.status == FinalStatus.INCOMPLETE_LIMIT_REACHED
                and not limit_reached(
                    iteration=run_state.iteration,
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
                render=self.config.render,
            )
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)

        self.stream.emit(
            "planning.started",
            input=str(loaded.path),
        )

        try:
            plan, run_state = await self._planning_loop(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
            )
        except (CursorEnvironmentError, UserInterrupted):
            persisted_run = load_run_state(output_dir)
            if persisted_run is not None:
                run_state = persisted_run
            run_state.active_status = RunActiveStatus.PAUSED
            run_state.agent_pids = []
            save_run_state(output_dir, run_state)
            # Do not save `plan` here: it is the snapshot from before
            # `_planning_loop` and would overwrite iterations already persisted to
            # plan.yaml. In-flight agent sessions restore canonical plan.yaml in
            # their finally blocks when an iteration is interrupted.
            raise
        except PlanningToolError as exc:
            run_state.active_status = RunActiveStatus.FAILED
            run_state.last_error = str(exc)
            persisted_plan = load_plan(output_dir)
            if persisted_plan is not None:
                plan = persisted_plan
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
            render_state = load_render_state(output_dir)
            existing = existing_deliverable_artifacts(
                self.config.workspace_root,
                run_state,
                render_state,
                output_dir=output_dir,
                artifact_ignore_patterns=self.config.render.artifact_ignore_patterns,
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
            if limit_reached(iteration=run_state.iteration, limits=limits):
                status = compute_final_status(plan, limit_reached=True)
                update_final_status(
                    plan,
                    status,
                    "Planning stopped because max_iterations was reached.",
                )
                run_state.active_status = RunActiveStatus.COMPLETED
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state

            eligible = expandable_items(plan)
            if not eligible:
                break

            plan = await self._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=eligible,
                session_kind="planning",
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

    async def _amend_loop(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
        amend_node_ids: list[str],
        review_findings: list[ReviewFinding],
    ):
        limits = run_state.limits
        pending = list(dict.fromkeys(amend_node_ids))

        while pending:
            if limit_reached(iteration=run_state.iteration, limits=limits):
                status = compute_final_status(plan, limit_reached=True)
                update_final_status(
                    plan,
                    status,
                    "Amendment stopped because max_iterations was reached.",
                )
                run_state.active_status = RunActiveStatus.COMPLETED
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state

            eligible = amendable_items(plan, pending)
            if not eligible:
                break

            plan = await self._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=eligible,
                session_kind="amend",
                review_findings=review_findings,
            )
            if run_state.processed_batches:
                processed_ids = set(run_state.processed_batches[-1].selected_items)
                pending = [node_id for node_id in pending if node_id not in processed_ids]

        if pending:
            raise PlanningToolError(
                "Amendment did not reach all queued items: "
                + ", ".join(pending)
            )

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

        async def _resume_amend_only(
            plan,
            run_state,
            *,
            amend_node_ids: list[str],
            review_findings: list[ReviewFinding],
        ):
            return await self._amend_loop(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                amend_node_ids=amend_node_ids,
                review_findings=review_findings,
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
            run_amend_loop=_resume_amend_only,
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

        render_state = load_render_state(output_dir)
        existing = existing_deliverable_artifacts(
            self.config.workspace_root,
            run_state,
            render_state,
            output_dir=output_dir,
            artifact_ignore_patterns=self.config.render.artifact_ignore_patterns,
        )
        if existing and not self.config.force_rerender:
            self._artifacts = existing
            self.stream.emit("render.skipped", artifacts=existing)
            plan_counts = count_by_status(plan)
            return PlanningReport(
                status=plan.result.status,
                review_status=plan.result.review_status,
                items=len(plan.plan),
                actionable_items=leaf_actionable_count(plan),
                blocked_items=plan_counts["blocked"],
                out_of_scope_items=plan_counts["out_of_scope"],
                iterations=run_state.iteration,
                output_dir=str(output_dir),
                artifacts=self._artifacts,
                summary=plan.result.summary,
            )

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

    async def _run_planning_iteration(
        self,
        *,
        loaded: LoadedInput,
        plan,
        run_state: RunState,
        output_dir: Path,
        eligible_items: list[PlanItem],
        session_kind: str = "planning",
        review_findings: list[ReviewFinding] | None = None,
    ):
        limits = run_state.limits
        iteration = run_state.iteration + 1
        plan_snapshot = copy.deepcopy(plan)
        plan_digest = compute_plan_digest(plan_snapshot)
        eligible_ids = [item.id for item in eligible_items]

        overview_path = ensure_plan_overview_artifact(
            output_dir,
            plan_snapshot,
            plan_digest,
        )
        self.stream.emit(
            "generation.batch.context_prepared",
            plan_digest=plan_digest,
            plan_overview=str(overview_path),
        )
        self.stream.emit(
            "iteration.started",
            iteration=iteration,
            eligible_items=eligible_ids,
        )
        self.renderer.rule(
            f"{'AMEND' if session_kind == 'amend' else 'PLAN'} "
            f"iteration={iteration} eligible={','.join(eligible_ids)}"
        )

        generation = self.config.generation
        plan_tool_command = resolve_plan_tool_command()
        prepared = prepare_batch_context(
            plan=plan_snapshot,
            selected_items=[],
            plan_digest=plan_digest,
            output_dir=output_dir,
            whole_plan_context=generation.whole_plan_context,
            include_cross_item_updates=session_kind == "planning",
        )

        context_path = iteration_context_path(output_dir, iteration)
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(prepared.batch_context_markdown, encoding="utf-8")

        prompt = (
            build_amend_prompt(
                loaded_input=loaded,
                workspace=self.config.workspace_root,
                output_goal=self.config.output_goal,
                plan=plan_snapshot,
                eligible_items=eligible_items,
                processed_batches=run_state.processed_batches,
                review_findings=review_findings or [],
                embed_threshold=self._embed_threshold,
                validation_feedback=None,
                plan_tool_command=plan_tool_command,
                agent_context=self._resolved_agent_context(phase="planning"),
                plan_digest=plan_digest,
                batch_context_markdown=prepared.batch_context_markdown,
                context_mode=prepared.context_mode,
            )
            if session_kind == "amend"
            else build_planning_prompt(
                loaded_input=loaded,
                workspace=self.config.workspace_root,
                output_goal=self.config.output_goal,
                plan=plan_snapshot,
                eligible_items=eligible_items,
                processed_batches=run_state.processed_batches,
                embed_threshold=self._embed_threshold,
                stop_hint=self.config.stop_hint,
                validation_feedback=None,
                plan_tool_command=plan_tool_command,
                agent_context=self._resolved_agent_context(phase="planning"),
                plan_digest=plan_digest,
                batch_context_markdown=prepared.batch_context_markdown,
                context_mode=prepared.context_mode,
            )
        )

        prefix = Path(iteration_prefix(output_dir, iteration))
        prompt_suffix = (
            "-amend-request-prompt.md" if session_kind == "amend" else "-request-prompt.md"
        )
        prompt_path = prefix.with_name(prefix.name + prompt_suffix)
        events_path = prefix.with_name(prefix.name + "-agent.ndjson")
        log_path = prefix.with_name(prefix.name + "-agent.log")
        transaction_path = iteration_transaction_path(output_dir, iteration)
        canonical_plan_file = plan_path(output_dir)

        validation_feedback: list[str] | None = None
        applied = False
        context_mode = prepared.context_mode
        for attempt in range(1, limits.max_retries + 1):
            run_state.retry_count = attempt - 1
            run_state.agent_pids = []
            save_run_state(output_dir, run_state)

            current_prompt = prompt
            if validation_feedback:
                if session_kind == "amend":
                    current_prompt = build_amend_prompt(
                        loaded_input=loaded,
                        workspace=self.config.workspace_root,
                        output_goal=self.config.output_goal,
                        plan=plan_snapshot,
                        eligible_items=eligible_items,
                        processed_batches=run_state.processed_batches,
                        review_findings=review_findings or [],
                        embed_threshold=self._embed_threshold,
                        validation_feedback=validation_feedback,
                        plan_tool_command=plan_tool_command,
                        agent_context=self._resolved_agent_context(phase="planning"),
                        plan_digest=plan_digest,
                        batch_context_markdown=prepared.batch_context_markdown,
                        context_mode=prepared.context_mode,
                    )
                else:
                    current_prompt = build_planning_prompt(
                        loaded_input=loaded,
                        workspace=self.config.workspace_root,
                        output_goal=self.config.output_goal,
                        plan=plan_snapshot,
                        eligible_items=eligible_items,
                        processed_batches=run_state.processed_batches,
                        embed_threshold=self._embed_threshold,
                        stop_hint=self.config.stop_hint,
                        validation_feedback=validation_feedback,
                        plan_tool_command=plan_tool_command,
                        agent_context=self._resolved_agent_context(phase="planning"),
                        plan_digest=plan_digest,
                        batch_context_markdown=prepared.batch_context_markdown,
                        context_mode=prepared.context_mode,
                    )

            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(current_prompt, encoding="utf-8")
            reset_transaction(transaction_path)
            if self.config.audit_iterations:
                write_json(
                    prefix.with_name(prefix.name + "-request.json"),
                    {
                        "iteration": iteration,
                        "attempt": attempt,
                        "eligible_items": eligible_ids,
                        "transaction_path": str(transaction_path),
                        "plan_digest": plan_digest,
                        "batch_context_artifact": context_path.name,
                        "context_mode": prepared.context_mode.value,
                        "session_kind": session_kind,
                    },
                )

            session_env = build_session_env(
                transaction_path=transaction_path,
                eligible_ids=eligible_ids,
                plan_file=canonical_plan_file,
                plan_digest=plan_digest,
                plan_tool_command=plan_tool_command,
            )
            min_plan_items = len(plan.plan)
            plan_backup = backup_canonical_plan(
                output_dir,
                suffix=f"{iteration:03d}",
            )

            def on_started(pid: int) -> None:
                self._add_agent_pid(output_dir, run_state, pid)

            try:
                session_result = await self.client.run_session(
                    workspace=self.config.workspace_root,
                    prompt=current_prompt,
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
            except UserInterrupted:
                run_state.agent_pids = []
                save_plan(output_dir, plan)
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
                        f"Planning iteration failed after {limits.max_retries} attempts: {exc}"
                    ) from exc
                self.stream.emit(
                    "iteration.retrying",
                    iteration=iteration,
                    attempt=attempt + 1,
                    reason=str(exc),
                )
                continue
            finally:
                if restore_canonical_plan(
                    output_dir, plan_backup, min_items=min_plan_items
                ):
                    self.renderer.warn(
                        "Restored plan.yaml after planning session modified canonical state"
                    )

            run_state.agent_pids = []
            response_path = prefix.with_name(prefix.name + "-response.json")
            validation_path = prefix.with_name(prefix.name + "-validation.json")
            try:
                response = load_transaction(transaction_path)
            except PlanToolError as exc:
                validation_feedback = [str(exc)]
                self.stream.emit(
                    "validation.failed",
                    iteration=iteration,
                    errors=validation_feedback,
                )
                if self.config.audit_iterations:
                    write_json(
                        response_path,
                        {
                            "error": str(exc),
                            "assistant_tail": session_result.assistant_text[-8000:],
                        },
                    )
                    write_json(validation_path, {"errors": validation_feedback})
                if attempt >= limits.max_retries:
                    raise PlanningToolError(
                        f"Failed to load planning transaction after {limits.max_retries} attempts"
                    ) from exc
                self.stream.emit(
                    "iteration.retrying",
                    iteration=iteration,
                    attempt=attempt + 1,
                    reason=str(exc),
                )
                continue

            selected_ids = list(response.selected_items)
            errors = (
                validate_amend_wave_responses(
                    plan_snapshot,
                    [(selected_ids, response)],
                    plan_digest=plan_digest,
                    output_goal_text=self.config.output_goal.text,
                )
                if session_kind == "amend"
                else validate_wave_responses(
                    plan_snapshot,
                    [(selected_ids, response)],
                    plan_digest=plan_digest,
                    output_goal_text=self.config.output_goal.text,
                )
            )
            if errors:
                validation_feedback = errors
                self.stream.emit(
                    "generation.batch.validated",
                    success=False,
                    plan_digest=plan_digest,
                    errors=errors,
                )
                self.stream.emit(
                    "validation.failed",
                    iteration=iteration,
                    errors=errors,
                )
                if self.config.audit_iterations:
                    write_json(response_path, response.model_dump(mode="json"))
                    write_json(validation_path, {"errors": errors})
                if attempt >= limits.max_retries:
                    raise ValidationError(errors)
                self.stream.emit(
                    "iteration.retrying",
                    iteration=iteration,
                    attempt=attempt + 1,
                )
                continue

            self.stream.emit(
                "generation.batch.validated",
                success=True,
                plan_digest=plan_digest,
            )
            plan = apply_response(plan, response)
            self._emit_operation_events(response)
            plan_digest_after = compute_plan_digest(plan)

            if self.config.audit_iterations:
                write_json(response_path, response.model_dump(mode="json"))
                write_json(validation_path, {"errors": []})

            run_state.iteration = iteration
            run_state.processed_batches.append(
                ProcessedBatchRecord(
                    iteration=iteration,
                    selected_items=selected_ids,
                    purpose=response.batch_purpose,
                    plan_digest_before=plan_digest,
                    plan_digest_after=plan_digest_after,
                    result="completed",
                )
            )
            save_plan(output_dir, plan)
            mark_last_success(output_dir, run_state)
            record_history(
                output_dir,
                run_state,
                event="iteration_applied",
                iteration=iteration,
                selected_items=selected_ids,
                batch_purpose=response.batch_purpose,
                attempt=attempt,
            )
            self.stream.emit(
                "generation.batch.completed",
                iteration=iteration,
                selected_items=selected_ids,
                plan_digest=plan_digest_after,
                context_mode=context_mode.value,
            )
            self.stream.emit(
                "iteration.completed",
                iteration=iteration,
                selected_items=selected_ids,
            )
            applied = True
            break

        if not applied:
            raise PlanningToolError(
                f"Planning iteration {iteration} failed after {limits.max_retries} attempts"
            )

        return plan

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
            elif operation.type == "revise_actionable":
                self.stream.emit(
                    "item.revised",
                    item_id=operation.node_id,
                )
        for update in response.updates:
            self.stream.emit(
                "item.updated",
                item_id=update.node_id,
            )

    def _add_agent_pid(self, output_dir: Path, run_state: RunState, pid: int) -> None:
        with self._agent_pid_lock:
            if pid not in run_state.agent_pids:
                run_state.agent_pids.append(pid)
            save_run_state(output_dir, run_state)


def _any_agent_alive(pids: list[int]) -> bool:
    return any(_pid_alive(pid) for pid in pids)


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
