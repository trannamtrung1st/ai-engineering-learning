"""Top-down planning orchestration loop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
    UserInterrupted,
    ValidationError,
)
from top_down_planning.input_loader import LoadedInput, digest_output_goal, load_markdown_input
from top_down_planning.model_config import resolve_model
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
    load_plan,
    load_run_state,
    mark_last_success,
    new_run_state,
    record_history,
    save_plan,
    save_run_state,
    update_final_status,
    write_json,
)
from top_down_planning.prompts import build_planning_prompt
from top_down_planning.renderer import write_plan_markdown
from top_down_planning.response_parser import parse_agent_response
from top_down_planning.scheduler import initialize_root_plan, select_batch
from top_down_planning.state_updates import apply_response
from top_down_planning.stream_events import StreamEmitter
from top_down_planning.validator import validate_response


@dataclass
class RunConfig:
    input_path: Path
    output_goal: str
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


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.renderer = ConsoleRenderer(no_color=config.no_color)
        self.stream = StreamEmitter(enabled=config.stream_json)
        self._client: CursorClient | None = None

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
        goal_digest = digest_output_goal(self.config.output_goal)
        output_dir = self.config.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        existing_plan, existing_run = ensure_resume_compatible(
            output_dir,
            input_digest=loaded.digest,
            output_goal_digest=goal_digest,
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
            run_state.agent_pid = None
            run_state.active_status = RunActiveStatus.RUNNING
            save_run_state(output_dir, run_state)
            self.renderer.info(f"Resuming planning in {output_dir}")
        else:
            plan = initialize_root_plan(
                input_file=str(loaded.path),
                output_goal=self.config.output_goal,
                input_digest=loaded.digest,
                output_goal_digest=goal_digest,
            )
            run_state = new_run_state(
                input_file=str(loaded.path),
                output_goal=self.config.output_goal,
                input_digest=loaded.digest,
                output_goal_digest=goal_digest,
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
            save_run_state(output_dir, run_state)
            save_plan(output_dir, plan)
            write_plan_markdown(output_dir, plan)
            raise
        except PlanningToolError as exc:
            run_state.active_status = RunActiveStatus.FAILED
            run_state.last_error = str(exc)
            update_final_status(plan, FinalStatus.FAILED, str(exc))
            save_run_state(output_dir, run_state)
            save_plan(output_dir, plan)
            write_plan_markdown(output_dir, plan)
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
            summary=plan.result.summary,
        )
        self.stream.emit(
            "planning.completed",
            status=plan.result.status.value,
            items=report.items,
            actionable_items=report.actionable_items,
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
                write_plan_markdown(output_dir, plan)
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
                    input_text=loaded.text,
                    output_goal=self.config.output_goal,
                    plan=plan,
                    selected_items=batch,
                    validation_feedback=validation_feedback,
                )
                prefix = Path(iteration_prefix(output_dir, iteration))
                prompt_path = prefix.with_name(prefix.name + "-request-prompt.md")
                response_path = prefix.with_name(prefix.name + "-response.json")
                validation_path = prefix.with_name(prefix.name + "-validation.json")
                events_path = prefix.with_name(prefix.name + "-agent.ndjson")
                log_path = prefix.with_name(prefix.name + "-agent.log")

                if self.config.audit_iterations:
                    prompt_path.parent.mkdir(parents=True, exist_ok=True)
                    prompt_path.write_text(prompt, encoding="utf-8")
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
            write_plan_markdown(output_dir, plan)

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
        write_plan_markdown(output_dir, plan)
        return plan, run_state


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
