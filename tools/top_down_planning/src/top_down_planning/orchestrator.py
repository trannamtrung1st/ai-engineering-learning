"""Top-down planning orchestration loop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    ResponseParseError,
    ResumeError,
    UserInterrupted,
    ValidationError,
)
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint, load_markdown_input, build_source_metadata
from top_down_planning.model_config import resolve_embed_threshold, resolve_model
from top_down_planning.models import (
    FinalStatus,
    PlanningLimits,
    PlanningReport,
    RunActiveStatus,
    RunState,
)
from top_down_planning.persistence import (
    ensure_resume_compatible,
    iteration_prefix,
    iterations_dir,
    load_run_state,
    mark_last_success,
    new_run_state,
    plan_path,
    record_history,
    save_plan,
    save_run_state,
    update_final_status,
    write_json,
)
from top_down_planning.recovery import (
    backup_canonical_plan,
    is_plan_run_state_desynced,
    recover_plan_from_iterations,
    restore_canonical_plan,
)
from top_down_planning.artifact_writer import (
    discover_written_artifacts,
    snapshot_deliverable_files,
    write_render_artifacts,
)
from top_down_planning.fallback_artifact import write_fallback_artifact
from top_down_planning.prompts import build_final_render_prompt, build_planning_prompt
from top_down_planning.response_parser import parse_agent_response
from top_down_planning.scheduler import initialize_root_plan, select_batch
from top_down_planning.state_updates import apply_response
from top_down_planning.stream_events import StreamEmitter
from top_down_planning.validator import validate_response


@dataclass
class RunConfig:
    input_path: Path
    output_goal: LoadedOutputGoal
    output_dir: Path
    workspace_root: Path
    limits: PlanningLimits
    resume: bool = False
    stream_json: bool = False
    no_color: bool = False
    model: str | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    audit_iterations: bool = True
    embed_threshold: int | None = None
    stop_hint: LoadedStopHint | None = None


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.renderer = ConsoleRenderer(no_color=config.no_color)
        self.stream = StreamEmitter(enabled=config.stream_json)
        self._client: CursorClient | None = None
        self._artifacts: list[str] = []
        self._embed_threshold = resolve_embed_threshold(config.embed_threshold)

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
        loaded = load_markdown_input(self.config.input_path)
        loaded_goal = self.config.output_goal
        loaded_stop_hint = self.config.stop_hint
        goal_digest = loaded_goal.digest
        stop_hint_digest = loaded_stop_hint.digest if loaded_stop_hint else None
        output_dir = self.config.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        existing_plan, existing_run = ensure_resume_compatible(
            output_dir,
            input_digest=loaded.digest,
            output_goal_digest=goal_digest,
            stop_hint_digest=stop_hint_digest,
            limits=self.config.limits,
            resume=self.config.resume,
        )

        if existing_plan is not None and existing_run is not None:
            plan = existing_plan
            run_state = existing_run
            if run_state.agent_pid and _pid_alive(run_state.agent_pid):
                raise PlanningToolError(
                    "Cannot resume while Cursor agent is still running "
                    f"(pid={run_state.agent_pid}). Stop it manually, then retry."
                )
            if is_plan_run_state_desynced(plan, run_state):
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
            run_state.agent_pid = None
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
            )
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)

        self.stream.emit("planning.started", input=str(loaded.path))

        try:
            plan, run_state = await self._planning_loop(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
            )
        except (CursorEnvironmentError, UserInterrupted):
            run_state.active_status = RunActiveStatus.PAUSED
            run_state.agent_pid = None
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
        limits = self.config.limits

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

            batch = select_batch(plan, limits)
            if not batch:
                break

            run_state.iteration += 1
            iteration = run_state.iteration
            selected_ids = [item.id for item in batch]
            self.stream.emit(
                "iteration.started",
                iteration=iteration,
                selected_items=selected_ids,
            )
            self.renderer.rule(
                f"PLAN iteration={iteration} items={','.join(selected_ids)}"
            )

            validation_feedback: list[str] | None = None
            applied = False
            for attempt in range(1, limits.max_retries + 1):
                run_state.retry_count = attempt - 1
                prompt = build_planning_prompt(
                    loaded_input=loaded,
                    workspace=self.config.workspace_root,
                    output_goal=self.config.output_goal,
                    plan=plan,
                    selected_items=batch,
                    embed_threshold=self._embed_threshold,
                    stop_hint=self.config.stop_hint,
                    validation_feedback=validation_feedback,
                )
                prefix = Path(iteration_prefix(output_dir, iteration))
                prompt_path = prefix.with_name(prefix.name + "-request-prompt.md")
                response_path = prefix.with_name(prefix.name + "-response.json")
                validation_path = prefix.with_name(prefix.name + "-validation.json")
                events_path = prefix.with_name(prefix.name + "-agent.ndjson")
                log_path = prefix.with_name(prefix.name + "-agent.log")

                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text(prompt, encoding="utf-8")
                if self.config.audit_iterations:
                    write_json(
                        prefix.with_name(prefix.name + "-request.json"),
                        {
                            "iteration": iteration,
                            "attempt": attempt,
                            "selected_items": selected_ids,
                        },
                    )

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
                        on_agent_started=lambda pid: _persist_agent_pid(
                            output_dir, run_state, pid
                        ),
                    )
                except UserInterrupted:
                    run_state.agent_pid = None
                    save_run_state(output_dir, run_state)
                    raise
                except CursorEnvironmentError:
                    raise
                except CursorSessionError as exc:
                    run_state.last_error = str(exc)
                    save_run_state(output_dir, run_state)
                    if attempt >= limits.max_retries:
                        raise PlanningToolError(
                            f"Agent session failed after {limits.max_retries} attempts: {exc}"
                        ) from exc
                    self.stream.emit(
                        "iteration.retrying",
                        iteration=iteration,
                        attempt=attempt + 1,
                        reason=str(exc),
                    )
                    continue

                run_state.agent_pid = None

                try:
                    response = parse_agent_response(result.assistant_text)
                except ResponseParseError as exc:
                    validation_feedback = [str(exc)]
                    self.stream.emit(
                        "validation.failed",
                        iteration=iteration,
                        errors=validation_feedback,
                    )
                    if self.config.audit_iterations:
                        write_json(response_path, {"raw": result.assistant_text[-8000:]})
                        write_json(validation_path, {"errors": validation_feedback})
                    if attempt >= limits.max_retries:
                        raise PlanningToolError(
                            f"Failed to parse agent response after {limits.max_retries} attempts"
                        ) from exc
                    self.stream.emit(
                        "iteration.retrying",
                        iteration=iteration,
                        attempt=attempt + 1,
                    )
                    continue

                errors = validate_response(
                    plan,
                    response,
                    selected_ids=selected_ids,
                    limits=limits,
                )
                if errors:
                    validation_feedback = errors
                    self.stream.emit(
                        "validation.failed",
                        iteration=iteration,
                        errors=errors,
                    )
                    if self.config.audit_iterations:
                        write_json(
                            response_path,
                            response.model_dump(mode="json"),
                        )
                        write_json(validation_path, {"errors": errors})
                    if attempt >= limits.max_retries:
                        raise ValidationError(errors)
                    self.stream.emit(
                        "iteration.retrying",
                        iteration=iteration,
                        attempt=attempt + 1,
                    )
                    continue

                plan = apply_response(plan, response)
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

                if self.config.audit_iterations:
                    write_json(response_path, response.model_dump(mode="json"))
                    write_json(validation_path, {"errors": []})

                save_plan(output_dir, plan)
                mark_last_success(output_dir, run_state)
                record_history(
                    output_dir,
                    run_state,
                    event="iteration_applied",
                    selected_items=selected_ids,
                    attempt=attempt,
                )
                applied = True
                break

            if not applied:
                raise PlanningToolError(
                    f"Iteration {iteration} failed after {limits.max_retries} attempts"
                )

            save_plan(output_dir, plan)

        status = compute_final_status(plan)
        summary = (
            "Planning completed successfully."
            if status == FinalStatus.COMPLETE
            else "Planning finished with remaining incomplete items."
        )
        update_final_status(plan, status, summary)
        run_state.active_status = RunActiveStatus.COMPLETED
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        if status == FinalStatus.COMPLETE:
            existing = _existing_generated_artifacts(output_dir, run_state)
            if existing:
                self._artifacts = existing
                self.stream.emit("render.skipped", artifacts=existing)
            else:
                self._artifacts = await self._run_final_render(
                    loaded=loaded,
                    plan=plan,
                    output_dir=output_dir,
                    run_state=run_state,
                )
        return plan, run_state

    async def _run_final_render(
        self,
        *,
        loaded: LoadedInput,
        plan,
        output_dir: Path,
        run_state: RunState,
    ) -> list[str]:
        canonical_plan_file = plan_path(output_dir)
        limits = self.config.limits
        validation_feedback: list[str] | None = None
        audit_dir = iterations_dir(output_dir)

        self.stream.emit("render.started")
        self.renderer.rule("RENDER deliverables according to output goal")

        for attempt in range(1, limits.max_retries + 1):
            before_snapshot = snapshot_deliverable_files(output_dir)
            prompt = build_final_render_prompt(
                loaded_input=loaded,
                plan_file=canonical_plan_file,
                output_dir=output_dir,
                workspace=self.config.workspace_root,
                output_goal=self.config.output_goal,
                plan=plan,
                embed_threshold=self._embed_threshold,
            )
            if validation_feedback:
                prompt += (
                    "\n\n## Validation feedback from previous attempt\n"
                    + "\n".join(f"- {error}" for error in validation_feedback)
                    + "\n\nFix every issue and write deliverable files under the output directory.\n"
                )

            prompt_path = audit_dir / "render-request-prompt.md"
            response_path = audit_dir / "render-response.json"
            events_path = audit_dir / "render-agent.ndjson"
            log_path = audit_dir / "render-agent.log"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt, encoding="utf-8")
            plan_backup = backup_canonical_plan(output_dir)
            min_plan_items = len(plan.plan)

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
                    on_agent_started=lambda pid: _persist_agent_pid(
                        output_dir, run_state, pid
                    ),
                    session_mode="agent",
                )
            except UserInterrupted:
                run_state.agent_pid = None
                save_run_state(output_dir, run_state)
                raise
            except CursorEnvironmentError:
                raise
            except CursorSessionError as exc:
                run_state.last_error = str(exc)
                save_run_state(output_dir, run_state)
                if attempt >= limits.max_retries:
                    self.renderer.warning(
                        "Final render failed; writing deterministic fallback artifact."
                    )
                    fallback = write_fallback_artifact(output_dir, plan)
                    paths = _persist_render_result(output_dir, run_state, [fallback])
                    save_run_state(output_dir, run_state)
                    self.stream.emit("render.fallback", reason=str(exc))
                    return paths
                self.stream.emit(
                    "render.retrying",
                    attempt=attempt + 1,
                    reason=str(exc),
                )
                continue
            finally:
                if restore_canonical_plan(
                    output_dir, plan_backup, min_items=min_plan_items
                ):
                    self.renderer.warning(
                        "Restored plan.yaml after render modified canonical state"
                    )

            run_state.agent_pid = None

            written = discover_written_artifacts(output_dir, before_snapshot)
            if not written:
                validation_feedback = [
                    "No deliverable files were written under the output directory."
                ]
                if self.config.audit_iterations:
                    write_json(
                        response_path,
                        {"raw": result.assistant_text[-8000:]},
                    )
                if attempt >= limits.max_retries:
                    self.renderer.warning(
                        "Final render produced no deliverables; "
                        "writing deterministic fallback artifact."
                    )
                    fallback = write_fallback_artifact(output_dir, plan)
                    paths = _persist_render_result(output_dir, run_state, [fallback])
                    save_run_state(output_dir, run_state)
                    self.stream.emit(
                        "render.fallback",
                        reason="no deliverables written",
                    )
                    return paths
                self.stream.emit(
                    "render.retrying",
                    attempt=attempt + 1,
                    reason=validation_feedback[0],
                )
                continue

            if self.config.audit_iterations:
                write_json(
                    response_path,
                    {
                        "artifacts": [
                            path.relative_to(output_dir).as_posix() for path in written
                        ],
                    },
                )

            artifact_paths = _persist_render_result(output_dir, run_state, written)
            record_history(
                output_dir,
                run_state,
                event="render_applied",
                attempt=attempt,
                artifacts=artifact_paths,
            )
            save_run_state(output_dir, run_state)
            self.stream.emit("render.completed", artifacts=artifact_paths)
            return artifact_paths

        fallback = write_fallback_artifact(output_dir, plan)
        paths = _persist_render_result(output_dir, run_state, [fallback])
        save_run_state(output_dir, run_state)
        self.stream.emit("render.fallback", reason="exhausted retries")
        return paths


def _persist_render_result(
    output_dir: Path,
    run_state: RunState,
    written: list[Path],
) -> list[str]:
    relative = [path.relative_to(output_dir).as_posix() for path in written]
    run_state.generated_artifacts = relative
    return [str(output_dir / name) for name in relative]


def _existing_generated_artifacts(
    output_dir: Path,
    run_state: RunState,
) -> list[str] | None:
    if not run_state.generated_artifacts:
        return None
    absolute: list[str] = []
    for relative in run_state.generated_artifacts:
        path = output_dir / relative
        if not path.is_file():
            return None
        absolute.append(str(path))
    return absolute


def _persist_agent_pid(output_dir: Path, run_state: RunState, pid: int) -> None:
    run_state.agent_pid = pid
    save_run_state(output_dir, run_state)


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
